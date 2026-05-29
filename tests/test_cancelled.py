"""Cancelled signups are tracked separately from no-shows.

Galaxy's API hides response_status='inactive' rows by default (the kind
left over when a volunteer un-registers). Our sync now passes
show_inactive=Yes so we see them and the classifier can return CANCELLED
instead of mis-labelling them as NO_SHOW.
"""
from __future__ import annotations

import pytest


def _ingest(conn, *, rid, status, shift_id="s", shift_end_past=True):
    """Helper: drop one signup with a specific response_status."""
    import db
    db.init()
    if shift_end_past:
        start, end = "2020-01-01 10:00:00", "2020-01-01 12:00:00"
    else:
        start, end = "2099-01-01 10:00:00", "2099-01-01 12:00:00"
    db.ingest_response(conn, {
        "id": rid,
        "agency": {"id": "1", "agency_name": "Test"},
        "shift": {"id": shift_id, "start": start, "end": end,
                  "duration": "2", "slots": "4"},
        "need":  {"id": "n", "need_title": "Need"},
        "user":  {"id": f"u_{rid}", "user_fname": "X", "user_lname": "Y",
                  "user_email": f"{rid}@x.test"},
        "response_status": status,
    })


def test_cancelled_signup_resolves_to_cancelled_not_no_show(db_conn):
    """A response_status='inactive' on a past shift must NOT become no_show.
    """
    import checkin, sync
    _ingest(db_conn, rid="r_cancel", status="inactive")
    _ingest(db_conn, rid="r_real_no_show", status="active")

    cancel = sync.current_status_for_signup(db_conn, "r_cancel", "u_r_cancel",
                                            "2020-01-01 12:00:00")
    no_show = sync.current_status_for_signup(db_conn, "r_real_no_show",
                                              "u_r_real_no_show", "2020-01-01 12:00:00")
    assert cancel == checkin.CANCELLED
    assert no_show == checkin.NO_SHOW


def test_mark_no_shows_skips_cancellations(db_conn):
    """The no-show backfill must not add a NO_SHOW history row for an
    inactive signup -- otherwise the offender list and digest counts
    inflate with people who explicitly cancelled.
    """
    import sync
    _ingest(db_conn, rid="r_x", status="inactive")
    n = sync.mark_no_shows(db_conn)
    assert n == 0
    hist = db_conn.execute("SELECT COUNT(*) AS n FROM status_history "
                            "WHERE response_id='r_x'").fetchone()["n"]
    assert hist == 0


def test_manual_override_beats_cancellation(db_conn):
    """If a volunteer cancelled but then physically showed up, the
    operator's 'Mark in' click must override the CANCELLED classification.
    """
    import checkin, db, sync
    _ingest(db_conn, rid="r_late", status="inactive")
    # Operator marks them in -- override fires.
    db.set_override(db_conn, "r_late", checkin.CHECKED_IN)
    s = sync.current_status_for_signup(db_conn, "r_late", "u_r_late",
                                        "2020-01-01 12:00:00")
    assert s == checkin.CHECKED_IN


def test_today_page_filled_count_excludes_cancellations(monkeypatch, tmp_db_path):
    """The 'N/M filled' display on the Today page must not include
    cancelled signups -- a cancellation gives the slot back.
    """
    pytest.importorskip("httpx")
    monkeypatch.setenv("WEB_PASSWORD", "testpw")
    import importlib, web
    importlib.reload(web)
    import db

    today = None
    with db.connect() as conn:
        db.init()
        today = conn.execute("SELECT date('now','localtime') AS d").fetchone()["d"]
        # 1 active + 2 cancelled, slots=4 -> should display "1/4 filled".
        for i, st in enumerate(("active", "inactive", "inactive")):
            db.ingest_response(conn, {
                "id": f"r_{i}", "agency": {"id": "1", "agency_name": "Test"},
                "shift": {"id": "s_today",
                          "start": f"{today} 12:00:00",
                          "end":   f"{today} 14:00:00",
                          "duration": "2", "slots": "4"},
                "need":  {"id": "n", "need_title": "Today"},
                "user":  {"id": f"u_{i}", "user_fname": f"User{i}",
                          "user_lname": "T", "user_email": f"{i}@x.test"},
                "response_status": st,
            })

    from fastapi.testclient import TestClient
    c = TestClient(web.app)
    r = c.get("/", auth=("volunteer", "testpw"))
    assert r.status_code == 200
    assert "1/4 filled" in r.text, \
        f"expected '1/4 filled' (active only), saw: {r.text[r.text.find('filled')-20:r.text.find('filled')+10]!r}"
    # And the bar should show "2 cancelled"
    import checkin
    assert checkin.STATUS_EMOJI[checkin.CANCELLED] in r.text
    assert "2 cancelled" in r.text


def test_build_shift_roster_excludes_cancellations_from_filled(db_conn):
    """Direct unit test of the helper that powers the gcal title.

    Before this fix, a shift with 1 active + 3 cancelled signups produced
    "(4/N filled)" on the calendar -- because get_connected was reading
    hour-row classification directly, which is NULL for cancellations
    and fell back to SIGNED_UP. Now both update_responses and
    user_checkin_update route through sync.build_shift_roster, which
    resolves status via current_status_for_signup -- so CANCELLED is
    detected and slots_filled excludes them.
    """
    import checkin, db, sync
    # 1 active + 3 cancelled on a 4-slot future shift.
    _ingest(db_conn, rid="r_active",   status="active",   shift_id="s_fill",
            shift_end_past=False)
    _ingest(db_conn, rid="r_cancel_1", status="inactive", shift_id="s_fill",
            shift_end_past=False)
    _ingest(db_conn, rid="r_cancel_2", status="inactive", shift_id="s_fill",
            shift_end_past=False)
    _ingest(db_conn, rid="r_cancel_3", status="inactive", shift_id="s_fill",
            shift_end_past=False)

    # ingest_response upserts the same shift row each time, so only one
    # shift exists. Pull it through the same SELECT update_responses uses.
    shift_row = db_conn.execute(
        """SELECT s.id, s.start_ts, s.end_ts, s.duration_min, s.slots,
                  s.need_id, n.title, n.location
           FROM shifts s LEFT JOIN needs n ON n.id = s.need_id
           WHERE s.id = ?""",
        ("s_fill",),
    ).fetchone()
    roster = sync.build_shift_roster(db_conn, shift_row)
    assert roster["slots"] == 4
    assert roster["slots_filled"] == 1, \
        f"expected 1 filled (active only), saw {roster['slots_filled']}"
    statuses = [u["checkin_status"] for u in roster["users"]]
    assert statuses.count(checkin.CANCELLED) == 3
    assert sum(1 for s in statuses if s != checkin.CANCELLED) == 1


def test_filled_statuses_excludes_cancelled():
    """Belt-and-suspenders: the FILLED_STATUSES tuple must not contain
    CANCELLED. If a future refactor changes this, every "X/Y filled"
    display in the codebase will be wrong; the unit test gives loud
    early warning.
    """
    import checkin
    assert checkin.CANCELLED not in checkin.FILLED_STATUSES
    # And no_show *does* still count -- the volunteer ate the slot.
    assert checkin.NO_SHOW in checkin.FILLED_STATUSES
