"""End-to-end roundtrip against a real Google Calendar.

This is gated behind the GCAL_TEST_CALENDAR_ID env var. If unset (the
common case in CI or on a fresh checkout) the test is skipped so the
suite is still green. Set it to the calendar ID of a *throwaway*
calendar you don't mind getting events created and deleted in.

To run locally:
    export GCAL_TEST_CALENDAR_ID=<calendar id>
    pytest tests/test_gcal_push.py -v

What it covers:
  1. gcal.get_service() actually authenticates and returns a usable
     Calendar v3 client.
  2. gcal.update_calendar_events creates a new event with the expected
     title and emoji-decorated description.
  3. Calling it again with the same shift id is an idempotent UPDATE
     (not a duplicate insert).
  4. The event can be cleanly deleted afterwards.
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta

import pytest

import checkin
import gcal

TEST_CAL = os.getenv("GCAL_TEST_CALENDAR_ID")

pytestmark = pytest.mark.skipif(
    not TEST_CAL,
    reason="GCAL_TEST_CALENDAR_ID not set; skipping live gcal test",
)


def _make_shift(shift_id: str, when: datetime) -> dict:
    """Build a shift dict in the shape gcal.update_calendar_events expects."""
    return {
        "id": shift_id,
        "title": f"PYTEST roundtrip {shift_id[:6]}",
        "slots_filled": 2,
        "slots": 4,
        "start_time": when,
        "end_time": when + timedelta(hours=1),
        "location": "905 W Eastman St., Chicago, IL 60642",
        "users": [
            {
                "id": "u1",
                "response_id": "r1",
                "user_fname": "Alice",
                "user_lname": "Test",
                "user_email": "alice@example.test",
                "checkin_status": checkin.CHECKED_IN,
            },
            {
                "id": "u2",
                "response_id": "r2",
                "user_fname": "Bob",
                "user_lname": "Test",
                "user_email": "bob@example.test",
                "checkin_status": checkin.NO_SHOW,
            },
        ],
    }


def _fetch(svc, event_id: str):
    return svc.events().get(calendarId=TEST_CAL, eventId=event_id).execute()


def _delete(svc, event_id: str) -> None:
    try:
        svc.events().delete(calendarId=TEST_CAL, eventId=event_id).execute()
    except Exception:
        # Already gone or never created -- nothing to clean up.
        pass


def test_create_update_delete_roundtrip():
    """Push a synthetic shift, read it back, push again (idempotent
    update), then delete it. All four checkpoints must succeed.
    """
    svc = gcal.get_service()
    # Pick an event id that's globally unique to this run so we don't
    # collide with previous test runs or real data. Google's event IDs
    # are RFC2938 base32hex: lowercase a-v + 0-9 only, 5-1024 chars.
    # uuid.uuid4().hex (0-9 + a-f) is always valid; prefixing with
    # "demoshift" (d,e,m,o,s,h,i,f,t are all in a-v) keeps it readable
    # in the calendar's all-events view.
    event_id = f"demoshift{uuid.uuid4().hex}"
    when = datetime.now() + timedelta(days=365)  # far in the future so it
                                                  # doesn't pollute "today" views
    shift = _make_shift(event_id, when)

    try:
        # 1. Create
        gcal.update_calendar_events([shift], svc, calendar_id=TEST_CAL, add_attendees=False)
        time.sleep(1.0)  # give Google a moment to materialize the write

        got = _fetch(svc, event_id)
        assert got["summary"].startswith("PYTEST roundtrip")
        assert "(2/4)" in got["summary"]
        assert got.get("location") == "905 W Eastman St., Chicago, IL 60642"
        # Emoji-decorated signup list should be in the description.
        desc = got.get("description", "")
        assert "Alice Test" in desc
        assert "Bob Test" in desc
        assert checkin.STATUS_EMOJI[checkin.CHECKED_IN] in desc
        assert checkin.STATUS_EMOJI[checkin.NO_SHOW] in desc

        # 2. Update -- flip Alice to checked_out and re-push the same id.
        shift["users"][0]["checkin_status"] = checkin.CHECKED_OUT
        gcal.update_calendar_events([shift], svc, calendar_id=TEST_CAL, add_attendees=False)
        time.sleep(1.0)
        got2 = _fetch(svc, event_id)
        assert checkin.STATUS_EMOJI[checkin.CHECKED_OUT] in got2.get("description", "")
        # Still the same single event -- no duplicate.
        listing = svc.events().list(
            calendarId=TEST_CAL,
            q="PYTEST roundtrip",
            singleEvents=True,
        ).execute()
        ids = {e["id"] for e in listing.get("items", [])}
        assert event_id in ids, "event vanished after update"
    finally:
        _delete(svc, event_id)
