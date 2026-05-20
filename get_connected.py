import requests
import os
import hashlib
from dotenv import load_dotenv
import json
import gcal
from datetime import datetime, timedelta
import time
import pytz
from loguru import logger
import checkin
import db
import sync

# Note: the legacy `model.py` (pydantic v1 schemas) is no longer imported.
# All ingestion now goes through db.py / sync.py which work directly on raw
# dicts -- removing the pydantic v1 dep lets us use modern Python + FastAPI
# without resolver conflicts.

logger.add("debug.log", format="{time} {level} {message}", level='ERROR', retention="1 week", rotation="10 MB")
load_dotenv()

class GalaxyAPI:

    def __init__(self):
        self.api_key = os.getenv('API_KEY')
        self.email = os.getenv('EMAIL')
        self.password = os.getenv('PASSWORD')
        self.calendar_id = os.getenv('CALENDAR_ID')
        self.url = 'https://api.galaxydigital.com/api/'
        self.api_user_id: str | None = None      # filled by login()
        self.token = self.login()
        self.shifts = {}
        self.login_responce = None
    def login(self):
        login_url = 'https://api.galaxydigital.com/api/users/login'
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }
        data = {
            'key': f'{self.api_key}',
            'user_email': f'{self.email}',
            'user_password': f'{self.password}',
        }
        response = requests.post(login_url, headers=headers, json=data)
        if response.status_code == 200:
            resp = response.json()
            self.login_responce = resp['data']
            # Capture the authenticated user's id so post_hours/etc. can be
            # attributed correctly in Galaxy's audit log, and so any future
            # parsing of hour_source for "by user <id>" knows whose writes
            # to treat as ours.
            user = resp['data'].get('user') or {}
            self.api_user_id = str(user.get('id')) if user.get('id') else None
            return resp['data']['token']
        else:
            response.raise_for_status()

    def get_data_from_api(self, url_path, additional_params=None):
        all_data = []
        records = 0
        page_return = 150
        query = {
            'per_page': 150,
            'show_inactive': 'No',
        }

        # Merge additional parameters if provided
        if additional_params:
            query.update(additional_params)

        relogin_attempts = 0
        while True:
            if records != 0:
                query['since_id'] = all_data[-1]['id']
                logger.debug(f"Since ID: {query['since_id']}")

            headers = {
                'Accept': 'application/json',
                'Authorization': f"Bearer {self.token}",
            }
            response = requests.get(f"{self.url}{url_path}", headers=headers, json=query)

            if response.status_code == 200:
                data = response.json()
                all_data.extend(data.get('data'))
                records += len(data.get('data'))
                page_return = len(data.get('data'))
                if page_return != 150:
                    logger.debug(f"Fin Page: {page_return}, Records: {records}")
                    return all_data
            elif response.status_code == 401 and relogin_attempts == 0:
                # Token expired mid-paginate. Re-login once and retry the
                # current page (without bumping records, so the same
                # since_id is used). Avoids a hard fail after long runs.
                logger.warning("401 on /%s -- re-authenticating once", url_path)
                self.token = self.login()
                relogin_attempts += 1
                continue
            else:
                response.raise_for_status()

    def get_needs(self):
        url_path = 'needs'
        data = self.get_data_from_api(url_path)

        return data['data']

    # -------- /hours write methods (used by manual web check-in path) -------
    #
    # We intentionally only call these from web.py's button handlers. The
    # background sync loop never POSTs -- it only reads. That keeps Galaxy
    # Digital authoritative for everything except deliberate operator clicks.

    def _hours_request(self, method: str, path: str, body: dict) -> dict:
        """One-shot /hours write with a single re-login on 401."""
        for attempt in range(2):
            headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Authorization': f"Bearer {self.token}",
            }
            r = requests.request(method, f"{self.url}{path}", headers=headers, json=body, timeout=15)
            if r.status_code == 401 and attempt == 0:
                logger.warning(f"{method} /{path} -> 401, re-authenticating once")
                self.token = self.login()
                continue
            r.raise_for_status()
            return r.json() if r.text else {}
        raise RuntimeError("unreachable")

    def post_hours(self, response_id: str, hour_start: datetime,
                   hour_hours: float, hour_status: str = 'pending') -> dict:
        """POST a new /hours record. Returns Galaxy's response dict.

        Required by the API: hour_start (datetime), hour_hours (decimal),
        hour_status (enum). response_id ties this to a specific signup --
        without it Galaxy returns 403 'User has not responded to that need'.
        """
        return self._hours_request("POST", "hours", {
            "response_id": str(response_id),
            "hour_start":  hour_start.strftime("%Y-%m-%d %H:%M:%S"),
            "hour_hours":  f"{hour_hours:.2f}",
            "hour_status": hour_status,
        })

    def update_hours(self, hour_id: str, hour_hours: float,
                     hour_status: str = 'entered') -> dict:
        """PUT an existing /hours record. Used for the checkout transition:
        we re-set hour_hours to the actual elapsed time and flip status
        from 'pending' to 'entered'.
        """
        return self._hours_request("PUT", f"hours/{hour_id}", {
            "hour_hours":  f"{hour_hours:.2f}",
            "hour_status": hour_status,
        })

    def delete_hours(self, hour_id: str) -> None:
        """Soft-DELETE an /hours record. Used when an operator clicks 'Undo'."""
        # 204 No Content; nothing to parse.
        for attempt in range(2):
            headers = {
                'Accept': 'application/json',
                'Authorization': f"Bearer {self.token}",
            }
            r = requests.delete(f"{self.url}hours/{hour_id}", headers=headers, timeout=15)
            if r.status_code == 401 and attempt == 0:
                self.token = self.login()
                continue
            if r.status_code in (204, 200, 404):
                # 404 == already gone, treat as success for idempotency.
                return
            r.raise_for_status()

    def transform_responses(self, responses):
        shifts_dict = {}
        for response in responses:
            shift_id = response["shift"]["id"]
            user = dict(response["user"])  # copy so we don't mutate the raw payload
            # Carry the response_id on the user so hour_response_id can match
            # back to this exact (user, shift) pair without ambiguity.
            user["response_id"] = response.get("id")
            logger.debug(f'response: {response}')
            if shift_id in shifts_dict:
                shifts_dict[shift_id]["users"].append(user)
            else:
                shift = response["shift"]
                shift["start_time"] = datetime.strptime(f"{shift['start']}", "%Y-%m-%d %H:%M:%S")
                shift["end_time"] = datetime.strptime(f"{shift['end']}", "%Y-%m-%d %H:%M:%S")
                need = response["need"]
                shift["need_id"] = need["id"]
                shift["duration"] = shift["duration"]
                shift["title"] = need["need_title"]
                shift["users"] = [user]
                shifts_dict[shift_id] = shift
            shifts_dict[shift_id]["slots_filled"] = len(shifts_dict[shift_id]["users"])
        return list(shifts_dict.values())

    def update_responses(self):
        """Full refresh: pull /responses into SQLite, then push the resulting
        per-shift roster to Google Calendar.

        The JSON file is still written as a debug snapshot so the legacy
        diagnostics keep working, but SQLite is authoritative.
        """
        sync.sync_responses(self)

        # Build the shift roster from SQLite for gcal. Same dict shape the
        # gcal layer already expects (start_time / end_time / users / etc).
        # We also fingerprint each shift here so the 2h refresh only pushes
        # the ones whose displayed content actually changed -- otherwise we
        # would UPDATE every event in the calendar (~1500 for this org)
        # every refresh, which works but is noisy and chews quota.
        tr: list[dict] = []
        with db.connect() as conn:
            shifts = conn.execute(
                """SELECT s.id, s.start_ts, s.end_ts, s.duration_min, s.slots,
                          s.need_id, n.title, n.location
                   FROM shifts s LEFT JOIN needs n ON n.id = s.need_id
                """,
            ).fetchall()
            for s in shifts:
                signups = db.signups_for_shift(conn, s["id"])
                users = []
                for sg in signups:
                    users.append({
                        "id": sg["user_id"],
                        "response_id": sg["response_id"],
                        "user_fname": sg["fname"],
                        "user_lname": sg["lname"],
                        "user_email": sg["email"],
                        "checkin_status": sg["classification"] or checkin.SIGNED_UP,
                    })
                # Fingerprint = (slot count, location, user statuses).
                fp_input = "|".join([
                    str(s["slots"] or ""),
                    s["location"] or "",
                    ",".join(sorted(f"{u['response_id']}:{u['checkin_status']}" for u in users)),
                ])
                fp = hashlib.sha1(fp_input.encode()).hexdigest()
                key = f"gcal_fp:{s['id']}"
                prev_fp = db.get_state(conn, key)
                if prev_fp == fp:
                    continue
                db.set_state(conn, key, fp)
                tr.append({
                    "id": s["id"],
                    "start_time": datetime.strptime(s["start_ts"], "%Y-%m-%d %H:%M:%S"),
                    "end_time": datetime.strptime(s["end_ts"], "%Y-%m-%d %H:%M:%S"),
                    "need_id": s["need_id"],
                    "duration": s["duration_min"],
                    "slots": s["slots"],
                    "title": s["title"],
                    "location": s["location"],
                    "users": users,
                    "slots_filled": len(users),
                })

        with open("transformed_responses.json", "w") as f:
            json.dump(tr, f, default=str)
        if not tr:
            logger.debug("update_responses: nothing changed since last push")
            return
        logger.info(f"update_responses: pushing {len(tr)} changed shift(s) to gcal")
        svc = gcal.get_service()
        gcal.get_calendars(svc)
        gcal.update_calendar_events(tr, svc, calendar_id=self.calendar_id, add_attendees=False)
        logger.debug("updated_responses complete")

    def user_checkin_update(self):
        """Incremental scan: pull /hours since cutoff, ingest into SQLite,
        then push the per-shift delta to Google Calendar.

        Returns the list of shift dicts that actually changed since the last
        scan -- only those get sent to gcal (avoids rate-limit hammering).
        """
        shifts_to_update: list[dict] = []
        tz = pytz.timezone("America/Chicago")
        current_time = datetime.now(tz)
        since = current_time - timedelta(hours=24)

        try:
            sync.sync_hours(self, since=since)

            with db.connect() as conn:
                # Find shifts in the live-tracking window and rebuild their roster.
                window_start = (current_time - timedelta(hours=20)).strftime("%Y-%m-%d %H:%M:%S")
                window_end = (current_time + timedelta(hours=20)).strftime("%Y-%m-%d %H:%M:%S")
                shifts = conn.execute(
                    """SELECT s.id, s.start_ts, s.end_ts, s.duration_min, s.slots,
                              s.need_id, n.title, n.location
                       FROM shifts s LEFT JOIN needs n ON n.id = s.need_id
                       WHERE s.start_ts BETWEEN ? AND ?
                    """,
                    (window_start, window_end),
                ).fetchall()

                # Also write any newly-detected no_shows to history (idempotent).
                conn.execute("BEGIN")
                _ = sync.mark_no_shows(conn)
                conn.execute("COMMIT")

                for s in shifts:
                    users = []
                    for sg in db.signups_for_shift(conn, s["id"]):
                        status = sync.current_status_for_signup(
                            conn, sg["response_id"], sg["user_id"], s["end_ts"],
                        )
                        # Append to status_history if this is a transition.
                        db.record_status(
                            conn,
                            response_id=sg["response_id"],
                            shift_id=s["id"],
                            user_id=sg["user_id"],
                            status=status,
                        )
                        users.append({
                            "id": sg["user_id"],
                            "response_id": sg["response_id"],
                            "user_fname": sg["fname"],
                            "user_lname": sg["lname"],
                            "user_email": sg["email"],
                            "checkin_status": status,
                        })
                    # Fingerprint = sorted (response_id,status) pairs for the
                    # shift. If unchanged since the last gcal push, skip --
                    # this is what keeps us from spamming the Google Calendar
                    # API every 60s for shifts that haven't moved.
                    fp_input = ",".join(sorted(f"{u['response_id']}:{u['checkin_status']}" for u in users))
                    fp = hashlib.sha1(fp_input.encode()).hexdigest()
                    key = f"gcal_fp:{s['id']}"
                    prev_fp = db.get_state(conn, key)
                    if prev_fp == fp:
                        continue
                    db.set_state(conn, key, fp)
                    shifts_to_update.append({
                        "id": s["id"],
                        "start_time": datetime.strptime(s["start_ts"], "%Y-%m-%d %H:%M:%S"),
                        "end_time": datetime.strptime(s["end_ts"], "%Y-%m-%d %H:%M:%S"),
                        "need_id": s["need_id"],
                        "duration": s["duration_min"],
                        "slots": s["slots"],
                        "title": s["title"],
                        "location": s["location"],
                        "users": users,
                        "slots_filled": len(users),
                    })

            if len(shifts_to_update) > 0:
                logger.debug(f"Updating {len(shifts_to_update)} shifts")
                logger.debug(f"shifts_to_update: {shifts_to_update}")
                
                # Convert string datetime values to datetime objects before passing to gcal
                for shift in shifts_to_update:
                    if isinstance(shift['start_time'], str):
                        shift['start_time'] = datetime.strptime(shift['start_time'], '%Y-%m-%d %H:%M:%S')
                    if isinstance(shift['end_time'], str):
                        shift['end_time'] = datetime.strptime(shift['end_time'], '%Y-%m-%d %H:%M:%S')
                
                svc = gcal.get_service()
                gcal.get_calendars(svc)
                gcal.update_calendar_events(shifts_to_update, svc, calendar_id=self.calendar_id, add_attendees=False)
        except Exception as e:
            # Log with traceback. The previous bare message silently swallowed
            # a KeyError("location") for half a release, which made the
            # scan-loop appear functional while pushing zero shifts.
            logger.exception(f"Error updating checkin shifts: {e}")
        return shifts_to_update
    
    def get_next_shift(self):
        """Seconds until the next upcoming shift starts. inf if none."""
        tz = pytz.timezone('America/Chicago')
        now_ct = datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')
        with db.connect() as conn:
            row = conn.execute(
                "SELECT start_ts FROM shifts WHERE start_ts > ? ORDER BY start_ts ASC LIMIT 1",
                (now_ct,),
            ).fetchone()
        if not row:
            return float('inf')
        start = tz.localize(datetime.strptime(row['start_ts'], '%Y-%m-%d %H:%M:%S'))
        return (start - datetime.now(tz)).total_seconds()

    def get_last_shift(self):
        """Seconds since the most recent shift ENDED. inf if none."""
        tz = pytz.timezone('America/Chicago')
        now_ct = datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')
        with db.connect() as conn:
            row = conn.execute(
                "SELECT end_ts FROM shifts WHERE end_ts < ? ORDER BY end_ts DESC LIMIT 1",
                (now_ct,),
            ).fetchone()
        if not row:
            return float('inf')
        end = tz.localize(datetime.strptime(row['end_ts'], '%Y-%m-%d %H:%M:%S'))
        return (datetime.now(tz) - end).total_seconds()
            

    def get_user_list(self, api_key, offset=0, limit=50):
        url = 'https://volunteerapi.com/agencies'
        headers = {
            'Authorization': f'{api_key}',
        }
        params = {
            'key': api_key,
            'offset': offset,
            'limit': limit,
        }
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            return response.json() 
        else:
            response.raise_for_status()  

    # transform_objects() lived here previously to coerce raw dicts into
    # pydantic v1 ModelClass instances. Nothing called it in the active
    # codebase, so it has been removed along with the `import model` to
    # let us run on modern Python without pydantic v1's resolver headaches.
# #TODO: sync with internal mongoDB
# api_key = os.getenv('API_KEY')
# email = os.getenv('EMAIL')
# password = os.getenv('PASSWORD')
# calendar_id = os.getenv('CALENDAR_ID')

# url = 'https://api.galaxydigital.com/api/'


# shifts = {}
# def login(api_key, email, password):
#     login_url = 'https://api.galaxydigital.com/api/users/login'
#     headers = {
#         'Accept': 'application/json',
#         'Content-Type': 'application/json',
#     }
#     data = {
#         'key': f'{api_key}',
#         'user_email': f'{email}',
#         'user_password': f'{password}',
#     }
#     response = requests.post(login_url, headers=headers, json=data)
#     if response.status_code == 200:
#         resp = response.json()
#         return resp['data']['token']  # If the response was successful, no Exception will be raised
#     else:
#         response.raise_for_status()  # Raises stored HTTPError, if one occurred.

# token = login(api_key, email, password)
# print(token)
# def get_data_from_api(url_path):
#     all_data = []
#     records = 0
#     page_return = 150
#     headers = {
#     'Accept': 'application/json',
#     'Authorization': f'Bearer {token}',
#     }
#     query = {
#         'per_page': 150,
#         'show_inactive': 'No',
#     }
#     while True:
#         if records != 0:
#             query['since_id'] = all_data[-1]['id']
#             logger.debug(f"Since ID: {query['since_id']}")
#         response = requests.get(f"{url}{url_path}", headers=headers,json=query)
#         if response.status_code == 200:
#             data = response.json()
#             all_data.extend(data.get('data'))  # If the response was successful, no Exception will be raised
#             records += len(data.get('data'))
#             page_return = len(data.get('data'))
#             logger.debug(f"Page: {page_return}, Records: {records}")
#             logger.info(f"Data: {data.get('data')}")
#             if page_return != 150:
#                 logger.debug(f"Fin Page: {page_return}, Records: {records}")
#                 # logger.debug(f"Data: {data}")
#                 return all_data
#         else:
#             response.raise_for_status()  # Raises stored HTTPError, if one occurred.

# def get_needs():
#     url_path = 'needs'
#     data = get_data_from_api(url_path)
#     return data['data']


# def transform_responses(responses):
#     shifts_dict = {}
#     for response in responses:
#         shift_id = response["shift"]["id"]
#         user = response["user"]
#         logger.debug(f'response: {response}')
#         print(response)
#         if shift_id in shifts_dict:
#             shifts_dict[shift_id]["users"].append(user)
#         else:
#             shift = response["shift"]
#             shift["start_time"] = datetime.strptime(f"{shift['start']}", "%Y-%m-%d %H:%M:%S")
#             shift["end_time"] = datetime.strptime(f"{shift['end']}", "%Y-%m-%d %H:%M:%S")
#             need = response["need"]
#             shift["need_id"] = need["id"]
#             shift["duration"] = shift["duration"]
#             shift["title"] = need["need_title"]
#             shift["users"] = [user]
#             shifts_dict[shift_id] = shift

#         shifts_dict[shift_id]["slots_filled"] = len(shifts_dict[shift_id]["users"])
#     # return shifts_dict
#     print(shifts_dict)
#     return list(shifts_dict.values())

# def update_responses():
#     data = get_data_from_api('responses')
#     tr = transform_responses(data)
#     gcal.get_calendars(gcal.service)
#     gcal.update_calendar_events(tr, gcal.service, calendar_id=calendar_id)

# def get_user_list(api_key, offset=0, limit=50):
#     # url = 'https://api.galaxydigital.com/agencies'
#     url = 'https://volunteerapi.com/agencies'
#     headers = {
#         'Authorization': f'{api_key}',
#     }

#     response = requests.get(url, headers=headers)

#     params = {
#         'key': api_key,
#         'offset': offset,
#         'limit': limit,
#     }
    
#     response = requests.get(url, headers=headers)
    
#     if response.status_code == 200:
#         return response.json() 
#     else:
#         response.raise_for_status()  

