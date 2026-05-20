"""One-shot visible push to a test calendar so a human can eyeball the
rendering. Leaves the event in place; rerun with --delete <event_id> to
clean up afterwards.

Usage:
    GCAL_TEST_CALENDAR_ID="<id>" python demo_gcal_push.py
    GCAL_TEST_CALENDAR_ID="<id>" python demo_gcal_push.py --delete <event_id>
"""
from __future__ import annotations

import argparse
import os
import uuid
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

import checkin
import gcal

CAL = os.getenv("GCAL_TEST_CALENDAR_ID") or os.getenv("CALENDAR_ID")


def push(svc):
    event_id = f"demoshift{uuid.uuid4().hex}"
    # Slot the event for tomorrow at 2 PM CT so it's findable in the
    # week view without polluting "today".
    start = (datetime.now() + timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)
    shift = {
        "id": event_id,
        "title": "Kayak River Clean Up - Wild Mile (demo)",
        "slots_filled": 4,
        "slots": 6,
        "start_time": start,
        "end_time": start + timedelta(hours=2),
        "users": [
            {"id": "u1", "response_id": "r1", "user_fname": "Alice",
             "user_lname": "Demo", "user_email": "alice@example.test",
             "checkin_status": checkin.CHECKED_IN},     # 🟡 at kiosk now
            {"id": "u2", "response_id": "r2", "user_fname": "Bob",
             "user_lname": "Demo", "user_email": "bob@example.test",
             "checkin_status": checkin.CHECKED_OUT},    # 🟢 wrapped
            {"id": "u3", "response_id": "r3", "user_fname": "Carol",
             "user_lname": "Demo", "user_email": "carol@example.test",
             "checkin_status": checkin.SIGNED_UP},      # 🔘 pending
            {"id": "u4", "response_id": "r4", "user_fname": "Dave",
             "user_lname": "Demo", "user_email": "dave@example.test",
             "checkin_status": checkin.NO_SHOW},        # 🔴 missed
        ],
    }
    gcal.update_calendar_events([shift], svc, calendar_id=CAL, add_attendees=False)
    got = svc.events().get(calendarId=CAL, eventId=event_id).execute()
    print(f"\n✓ created event id: {event_id}")
    print(f"✓ summary:  {got['summary']}")
    print(f"✓ when:     {got['start']['dateTime']} → {got['end']['dateTime']}")
    print(f"✓ link:     {got.get('htmlLink')}")
    print()
    print("Description posted:")
    print(got.get("description", "(no description)"))
    print()
    print(f"To clean up:  python demo_gcal_push.py --delete {event_id}")


def delete(svc, event_id: str):
    svc.events().delete(calendarId=CAL, eventId=event_id).execute()
    print(f"deleted {event_id}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--delete", metavar="EVENT_ID", help="delete an event id and exit")
    args = p.parse_args()
    if not CAL:
        raise SystemExit("set GCAL_TEST_CALENDAR_ID (or CALENDAR_ID) first")
    svc = gcal.get_service()
    if args.delete:
        delete(svc, args.delete)
    else:
        push(svc)


if __name__ == "__main__":
    main()
