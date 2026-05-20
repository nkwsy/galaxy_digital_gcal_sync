"""One-shot push of upcoming shifts to a test calendar.

Pulls /needs, /responses, and /hours from Galaxy Digital into SQLite,
then pushes the next N days of shifts (default 14) to whichever calendar
id is in GCAL_TEST_CALENDAR_ID -- so production stays untouched.

Why not just call api.update_responses()? That pushes the entire all-
time shift list (~1465 events for this org), which is overkill for a
verification run and chews through Google Calendar quota.

Usage:
    GCAL_TEST_CALENDAR_ID="<id>" python push_to_demo.py [--days 14]
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

import checkin  # noqa: E402
import db  # noqa: E402
import gcal  # noqa: E402
import get_connected as gc  # noqa: E402
import sync  # noqa: E402


def upcoming_shifts(conn, days: int) -> list[dict]:
    """Build shift dicts for the next `days` days in the shape gcal expects."""
    horizon = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    now_ct = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        """SELECT s.id, s.start_ts, s.end_ts, s.duration_min, s.slots,
                  s.need_id, n.title, n.location
           FROM shifts s LEFT JOIN needs n ON n.id = s.need_id
           WHERE s.start_ts >= ? AND s.start_ts < ?
           ORDER BY s.start_ts
        """,
        (now_ct, horizon),
    ).fetchall()

    out = []
    for s in rows:
        users = []
        for sg in db.signups_for_shift(conn, s["id"]):
            users.append({
                "id": sg["user_id"],
                "response_id": sg["response_id"],
                "user_fname": sg["fname"],
                "user_lname": sg["lname"],
                "user_email": sg["email"],
                "checkin_status": sg["classification"] or checkin.SIGNED_UP,
            })
        out.append({
            "id": s["id"],
            "start_time": datetime.strptime(s["start_ts"], "%Y-%m-%d %H:%M:%S"),
            "end_time": datetime.strptime(s["end_ts"], "%Y-%m-%d %H:%M:%S"),
            "need_id": s["need_id"],
            "duration": s["duration_min"],
            "slots": s["slots"],
            "title": s["title"] or "(no title)",
            "location": s["location"],
            "users": users,
            "slots_filled": len(users),
        })
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=14,
                   help="how many days of upcoming shifts to push (default 14)")
    args = p.parse_args()

    demo_cal = os.getenv("GCAL_TEST_CALENDAR_ID")
    if not demo_cal:
        print("Set GCAL_TEST_CALENDAR_ID before running (won't touch production).",
              file=sys.stderr)
        return 1
    print(f"-> using calendar id: ...{demo_cal[-30:]}")

    api = gc.GalaxyAPI()
    print("\n[1/3] sync_responses (incl. sync_needs + mark_no_shows) ...")
    n_resp = sync.sync_responses(api)
    print(f"     {n_resp} responses ingested")

    print("\n[2/3] sync_hours (24h) ...")
    n_hours = sync.sync_hours(api)
    print(f"     {n_hours} hours ingested")

    with db.connect() as conn:
        shifts = upcoming_shifts(conn, args.days)
    print(f"\n[3/3] pushing {len(shifts)} shifts (next {args.days}d) to gcal ...")
    if not shifts:
        print("     nothing to push.")
        return 0

    svc = gcal.get_service()
    gcal.update_calendar_events(shifts, svc, calendar_id=demo_cal, add_attendees=False)

    print(f"\n=== summary ===")
    for s in shifts:
        loc = s["location"] or "(no location)"
        statuses = {}
        for u in s["users"]:
            st = u["checkin_status"]
            statuses[st] = statuses.get(st, 0) + 1
        status_bar = " ".join(f"{checkin.STATUS_EMOJI[k]}{v}"
                              for k, v in statuses.items()
                              if k in checkin.STATUS_EMOJI)
        print(f"  {s['start_time'].strftime('%Y-%m-%d %H:%M')}  "
              f"({s['slots_filled']}/{s['slots']})  {s['title']}")
        print(f"      @ {loc}   [{status_bar}]")
    print("\nOpen Google Calendar -> RangersTest to verify.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
