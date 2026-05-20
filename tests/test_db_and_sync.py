"""Tests for the SQLite ingest path and no-show backfill.

These are credentials-free: they push hand-rolled API payload dicts into
db.ingest_response / db.ingest_hour and assert on the resulting state.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import checkin
import db
import sync


# ----- fixtures specific to these tests -----------------------------------


def _resp(response_id: str, user_id: str, shift_id: str, *,
          shift_start: str = "2026-05-19 10:00:00",
          shift_end: str = "2026-05-19 12:00:00",
          response_status: str = "active",
          need_id: str = "n1",
          agency_name: str = "Agency Test") -> dict:
    return {
        "id": response_id,
        "agency": {"id": "a1", "agency_name": agency_name},
        "shift": {"id": shift_id, "start": shift_start, "end": shift_end,
                  "duration": "2.00", "slots": "4"},
        "need": {"id": need_id, "need_title": "Need Test"},
        "user": {"id": user_id, "user_fname": "Alice", "user_lname": "T",
                 "user_email": "alice@example.test"},
        "response_status": response_status,
        "created_at": "2026-05-01 09:00:00",
        "updated_at": "2026-05-01 09:00:00",
    }


def _hour(hour_id: str, response_id: str | None, user_id: str, source: str,
          need_id: str = "n1") -> dict:
    return {
        "id": hour_id,
        "hour_response_id": response_id,
        "user": {"id": user_id, "user_fname": "Alice", "user_lname": "T",
                 "user_email": "alice@example.test"},
        "need": {"id": need_id, "need_title": "Need Test"},
        "hour_source": source,
        "hour_status": "approved",
        "hour_date_start": "2026-05-19 10:00:00",
        "hour_date_end":   "2026-05-19 12:00:00",
        "created_at":      "2026-05-19 10:00:00",
        "updated_at":      "2026-05-19 10:05:00",
    }


# ----- tests --------------------------------------------------------------


def test_ingest_response_populates_all_tables(db_conn):
    db.ingest_response(db_conn, _resp("r1", "u1", "s1"))
    counts = {t: db_conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
              for t in ("users", "needs", "shifts", "signups")}
    assert counts == {"users": 1, "needs": 1, "shifts": 1, "signups": 1}

    sg = db_conn.execute("SELECT user_id, shift_id, need_id, response_status FROM signups").fetchone()
    assert sg["user_id"] == "u1"
    assert sg["shift_id"] == "s1"
    assert sg["response_status"] == "active"

    n = db_conn.execute("SELECT agency_name FROM needs").fetchone()
    assert n["agency_name"] == "Agency Test"


def test_agency_name_not_overwritten_by_null(db_conn):
    """The COALESCE in upsert_need must preserve a previously-set agency
    when a later upsert has no agency info.
    """
    db.ingest_response(db_conn, _resp("r1", "u1", "s1", agency_name="First"))
    # Simulate a second upsert with no agency (e.g. a /needs sweep that
    # doesn't carry agency in this code path).
    db.upsert_need(db_conn, {"id": "n1", "need_title": "Updated title"}, agency_name=None)
    n = db_conn.execute("SELECT title, agency_name FROM needs").fetchone()
    assert n["title"] == "Updated title"
    assert n["agency_name"] == "First"


def test_ingest_hour_classifies_via_source(db_conn):
    db.ingest_response(db_conn, _resp("r1", "u1", "s1"))
    db.ingest_hour(db_conn, _hour("h1", "r1", "u1",
        source="Added at: /kiosk/storeCheckin/ by user 1"))
    h = db_conn.execute("SELECT classification, response_id FROM hours").fetchone()
    assert h["classification"] == checkin.CHECKED_IN
    assert h["response_id"] == "r1"


def test_mark_no_shows_writes_history_with_shift_end_time(db_conn):
    """The repeat-offender window relies on observed_at == shift end (not
    backfill wall time), so we can answer 'how many no-shows in the last
    30 days' correctly even after a big bulk backfill.
    """
    # Past shift with no hour row -> should be marked no_show.
    db.ingest_response(db_conn, _resp("r_past", "u_past", "s_past",
        shift_start="2020-01-01 10:00:00", shift_end="2020-01-01 12:00:00"))
    # Future shift with no hour row -> should NOT be marked.
    db.ingest_response(db_conn, _resp("r_future", "u_future", "s_future",
        shift_start="2099-01-01 10:00:00", shift_end="2099-01-01 12:00:00"))

    n = sync.mark_no_shows(db_conn)
    assert n == 1

    rows = db_conn.execute("SELECT response_id, status, observed_at FROM status_history").fetchall()
    assert len(rows) == 1
    assert rows[0]["response_id"] == "r_past"
    assert rows[0]["status"] == checkin.NO_SHOW
    # observed_at should reflect the shift end (2020 ish), not "now".
    assert rows[0]["observed_at"].startswith("2020-01-01")


def test_mark_no_shows_is_idempotent(db_conn):
    db.ingest_response(db_conn, _resp("r1", "u1", "s1",
        shift_start="2020-01-01 10:00:00", shift_end="2020-01-01 12:00:00"))
    sync.mark_no_shows(db_conn)
    sync.mark_no_shows(db_conn)
    n_rows = db_conn.execute("SELECT COUNT(*) AS n FROM status_history").fetchone()["n"]
    assert n_rows == 1, "second invocation must not duplicate"


def test_mark_no_shows_skips_cancellations(db_conn):
    """A signup with response_status='cancelled' must not become a no-show."""
    db.ingest_response(db_conn, _resp("r_cancelled", "u1", "s1",
        shift_start="2020-01-01 10:00:00", shift_end="2020-01-01 12:00:00",
        response_status="cancelled"))
    n = sync.mark_no_shows(db_conn)
    assert n == 0


def test_record_status_dedupes_same_status_in_a_row(db_conn):
    db.record_status(db_conn, response_id="r1", shift_id="s1", user_id="u1",
                     status=checkin.CHECKED_IN)
    db.record_status(db_conn, response_id="r1", shift_id="s1", user_id="u1",
                     status=checkin.CHECKED_IN)
    db.record_status(db_conn, response_id="r1", shift_id="s1", user_id="u1",
                     status=checkin.CHECKED_OUT)
    db.record_status(db_conn, response_id="r1", shift_id="s1", user_id="u1",
                     status=checkin.CHECKED_OUT)
    rows = db_conn.execute("SELECT status FROM status_history ORDER BY id").fetchall()
    assert [r["status"] for r in rows] == [checkin.CHECKED_IN, checkin.CHECKED_OUT]


def test_compose_location_full_address():
    n = {"need_address": "905 W Eastman St.", "need_address2": "",
         "need_city": "Chicago", "need_state": "IL", "need_postal": "60642"}
    assert db.compose_location(n) == "905 W Eastman St., Chicago, IL 60642"


def test_compose_location_with_unit():
    n = {"need_address": "1440 N Kingsbury St", "need_address2": "suite 005",
         "need_city": "Chicago", "need_state": "IL", "need_postal": "60642"}
    assert db.compose_location(n) == "1440 N Kingsbury St, suite 005, Chicago, IL 60642"


def test_compose_location_missing_pieces_skipped():
    n = {"need_address": "Park entrance", "need_address2": None,
         "need_city": "Chicago", "need_state": "", "need_postal": ""}
    assert db.compose_location(n) == "Park entrance, Chicago"


def test_compose_location_none_when_all_empty():
    assert db.compose_location({}) is None
    assert db.compose_location({"need_address": "", "need_city": ""}) is None


def test_upsert_need_writes_location_and_preserves_on_null(db_conn):
    db.upsert_need(db_conn, {
        "id": "n1", "need_title": "Test",
        "need_address": "100 Main", "need_city": "Chicago",
        "need_state": "IL", "need_postal": "60601",
    })
    row = db_conn.execute("SELECT title, location FROM needs WHERE id='n1'").fetchone()
    assert row["location"] == "100 Main, Chicago, IL 60601"

    # Later ingest path (e.g. a /responses sweep) carries no address.
    # The location must survive untouched.
    db.upsert_need(db_conn, {"id": "n1", "need_title": "Updated title"})
    row = db_conn.execute("SELECT title, location FROM needs WHERE id='n1'").fetchone()
    assert row["title"] == "Updated title"
    assert row["location"] == "100 Main, Chicago, IL 60601"


def test_repeat_offenders_respects_window(db_conn):
    # Two users, each with 2 historical no-shows: one inside 30d, one outside.
    db.ingest_response(db_conn, _resp("r_a1", "u_a", "s_a1",
        shift_start="2020-01-01 10:00:00", shift_end="2020-01-01 12:00:00"))
    db.ingest_response(db_conn, _resp("r_a2", "u_a", "s_a2",
        shift_start="2020-01-02 10:00:00", shift_end="2020-01-02 12:00:00"))
    sync.mark_no_shows(db_conn)
    rows = db.repeat_offenders(db_conn, days=30, min_count=2)
    assert rows == [], "old no-shows must fall outside 30d window"
    rows_all = db.repeat_offenders(db_conn, days=9999, min_count=2)
    assert len(rows_all) == 1
    assert rows_all[0]["no_shows"] == 2
