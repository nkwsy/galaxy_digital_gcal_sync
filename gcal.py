import csv
from loguru import logger
from datetime import datetime
import pytz
import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import time

import checkin


# If modifying these SCOPES, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar']

# OAuth used to run at module import, which made `import gcal` open a browser
# whenever token.json was missing or stale. That meant every smoke test,
# digest preview, and standalone tool had to stub the module out. Now the
# credentials and service are built lazily on first use; importing gcal is
# free.

_service = None
_token_path = os.getenv('GCAL_TOKEN_PATH', 'token.json')
_creds_path = os.getenv('GCAL_CREDS_PATH', 'credentials.json')


def _load_credentials() -> Credentials:
    creds = None
    if os.path.exists(_token_path):
        creds = Credentials.from_authorized_user_file(_token_path)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(_creds_path):
                raise FileNotFoundError(
                    f"No {_token_path} and no {_creds_path} -- cannot open OAuth flow. "
                    "Set GCAL_TOKEN_PATH / GCAL_CREDS_PATH or place these files in cwd."
                )
            flow = InstalledAppFlow.from_client_secrets_file(_creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(_token_path, 'w') as token:
            token.write(creds.to_json())
    return creds


def get_service():
    """Return the cached Calendar v3 service, building it on first call.

    Side effects (OAuth flow / disk write) happen only here, so importing
    this module is free. Callers that previously read `gcal.service`
    directly should switch to `gcal.get_service()`.
    """
    global _service
    if _service is None:
        _service = build('calendar', 'v3', credentials=_load_credentials())
    return _service


class _ServiceProxy:
    """Backwards-compat shim so legacy `gcal.service` reads still work,
    but no OAuth runs until something actually calls a method on it.

    Once nothing references `gcal.service` directly, this proxy and the
    module-level `service` alias can be deleted; callers should use
    get_service() instead.
    """
    def __getattr__(self, item):
        return getattr(get_service(), item)


service = _ServiceProxy()
def convert_to_iso(datetime_str):
    return datetime_str.replace(" ", "T")

def create_attendees_list(users):
    """Build the description block listing signups with status emoji.

    Status comes from checkin.classify_hour() and is one of:
      signed_up | checked_in | checked_out | manager_entered | no_show
    See checkin.py for the rationale -- hour_status/hour_date_end are NOT
    reliable real-time signals; only hour_source is.
    """
    lines = ['Signups:']
    for user in users:
        status = user.get('checkin_status') or checkin.SIGNED_UP
        emoji = checkin.STATUS_EMOJI.get(status, '🔘')
        lines.append(f"{emoji} {user.get('user_fname','')} {user.get('user_lname','')} "
                     f"email: {user.get('user_email','')}")
    return '\n'.join(lines) + '\n'

#Hacky way to change the color of the event, https://lukeboyle.com/blog/posts/google-calendar-api-color-id
def change_color(attendees):
    if int(attendees) < 2:
        return '2'
    else:
        return '10'
    
#TODO: Add attendees to calendar event,
#TODO: Add HTML description to calendar event
#TODO: Add location to calendar event, pull from galaxy digital API
#TODO: Add description to calendar event, pull from galaxy digital API
def update_calendar_events(shifts, service, calendar_id='primary', add_attendees=False):
    events = service.events().list(calendarId=calendar_id, maxResults=2500).execute()
    logger.info(f"Updating calendar {calendar_id}")
    logger.debug(f"Events: {events}")
    RATE_LIMIT_SLEEP = 0.12  # ~8 requests/sec (600/min)
    MAX_RETRIES = 5
    for shift in shifts:
        # Check to see if duration of shift is greater than 24 hours
        if isinstance(shift['end_time'], str):
            end_time = datetime.strptime(shift['end_time'], '%Y-%m-%d %H:%M:%S')
            start_time = datetime.strptime(shift['start_time'], '%Y-%m-%d %H:%M:%S')
            time_delta = end_time - start_time
        else:
            time_delta = shift['end_time'] - shift['start_time']
        if time_delta.days > 1:
            logger.error(f"Shift {shift['id']} is longer than 24 hours, skipping")
            continue
        event_id = shift['id']
        event = {
            'id': event_id,
            'summary': f"{shift['title']} - ({shift['slots_filled']}/{shift['slots']}) ",
            'start': {
                'dateTime': shift['start_time'].isoformat(),
                'timeZone': 'America/Chicago',
            },
            'end': {
                'dateTime': shift['end_time'].isoformat(),
                'timeZone': 'America/Chicago',
            },
            'colorId': change_color(shift['slots_filled']),
        }
        # Get the list of event attendees
        if add_attendees:
            event['attendees'] = [{'email': 'test@urbanriv.org'}]
        else:
            event['description'] = create_attendees_list(shift['users'])
        # Check if event exists
        existing_event = next((e for e in events['items'] if e['id'] == event_id), None)
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if existing_event:
                    logger.info(f"Updating event {event_id}, {event}")
                    service.events().update(calendarId=calendar_id, eventId=event_id, body=event).execute()
                else:
                    logger.info(f"Creating event {event_id}, {event}")
                    service.events().insert(calendarId=calendar_id, body=event).execute()
                break  # Success, exit retry loop
            except HttpError as error:
                if error.resp.status == 409:
                    logger.error(f"Event with this ID already exists. Consider updating it instead.")
                    break
                elif error.resp.status == 403 and 'rateLimitExceeded' in str(error):
                    wait_time = (2 ** attempt)  # Exponential backoff: 2, 4, 8, 16, 32 seconds
                    logger.error(f"Rate limit exceeded. Attempt {attempt}/{MAX_RETRIES}. Waiting {wait_time} seconds before retrying...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Failed to create/update event {event_id}: {error}")
                    break
        time.sleep(RATE_LIMIT_SLEEP)  # Rate limit: sleep between requests
    

#TODO: Get updates from calendar and reflect in galaxy digital i.e. if a user declines a shift, update galaxy digital
def get_calendars(service):
    calendars = service.calendarList().list().execute()
    print(calendars)
    return calendars['items']

