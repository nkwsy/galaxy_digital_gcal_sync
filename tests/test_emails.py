"""Email templates, rendering, dry-run send, and the auto-trigger
qualifying-signups query.

SMTP is never actually contacted -- EMAIL_DRY_RUN=yes makes send_template
log + skip the network. That keeps the suite hermetic.
"""
from __future__ import annotations

import importlib
import os
import pytest


@pytest.fixture(autouse=True)
def _dry_run(monkeypatch):
    monkeypatch.setenv("EMAIL_DRY_RUN", "yes")


@pytest.fixture
def fresh(tmp_db_path, monkeypatch):
    import emails as emails_mod, sync as sync_mod
    importlib.reload(emails_mod)
    importlib.reload(sync_mod)
    return emails_mod


def _seed(conn, *, shift_end_offset_h=2):
    """One signup, named user, shift ending shift_end_offset_h ago/ahead."""
    import db
    from datetime import datetime, timedelta
    db.init()
    end = datetime.now() + timedelta(hours=shift_end_offset_h)
    start = end - timedelta(hours=2)
    db.ingest_response(conn, {
        "id": "r1", "agency": {"id": "1", "agency_name": "River Rangers"},
        "shift": {"id": "s1",
                  "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                  "end":   end.strftime("%Y-%m-%d %H:%M:%S"),
                  "duration": "120", "slots": "4"},
        "need":  {"id": "n", "need_title": "Kayak River Clean Up"},
        "user":  {"id": "u_a", "user_fname": "Ann", "user_lname": "Alpha",
                  "user_email": "ann@example.test"},
        "response_status": "active",
    })


def test_render_substitutes_known_vars_and_keeps_unknown(fresh):
    out = fresh.render(
        "Hi {{volunteer_first}}, see you at {{shift_title}}. {{NOT_A_VAR}}",
        {"volunteer_first": "Ann", "shift_title": "Kayak"},
    )
    assert out == "Hi Ann, see you at Kayak. {{NOT_A_VAR}}"


def test_save_and_get_template(db_conn, fresh):
    tid = fresh.save_template(
        db_conn, name="t1", subject="Hi {{volunteer_first}}",
        body="<p>Body</p>", auto_trigger="no_show_24h",
    )
    t = fresh.get_template(db_conn, tid)
    assert t["name"] == "t1"
    assert t["auto_trigger"] == "no_show_24h"
    # Update
    fresh.save_template(db_conn, name="t1-updated", subject="X", body="Y", tid=tid)
    assert fresh.get_template(db_conn, tid)["name"] == "t1-updated"


def test_send_template_dry_run_logs_send(db_conn, fresh):
    _seed(db_conn)
    tid = fresh.save_template(
        db_conn, name="hi", subject="Hi {{volunteer_first}}",
        body="<p>Hello {{volunteer_first}} from {{org_name}}</p>",
    )
    result = fresh.send_template(db_conn, tid, "r1", triggered_by="manual")
    assert result["ok"] is True
    assert result["error"] == "DRY_RUN"
    assert result["to"] == "ann@example.test"
    assert result["subject"] == "Hi Ann"
    # Send was logged
    row = db_conn.execute(
        "SELECT to_email, subject, success, triggered_by FROM email_sends "
        "WHERE template_id=? AND response_id=?",
        (tid, "r1"),
    ).fetchone()
    assert row is not None
    assert row["success"] == 1
    assert row["triggered_by"] == "manual"


def test_already_sent_dedup(db_conn, fresh):
    _seed(db_conn)
    tid = fresh.save_template(db_conn, name="x", subject="X", body="Y")
    assert fresh.already_sent(db_conn, tid, "r1") is False
    fresh.send_template(db_conn, tid, "r1")
    assert fresh.already_sent(db_conn, tid, "r1") is True


def test_send_template_missing_email_records_error(db_conn, fresh):
    import db
    db.init()
    db.ingest_response(db_conn, {
        "id": "r_noemail", "agency": {"id": "1", "agency_name": "T"},
        "shift": {"id": "s2", "start": "2026-05-21 10:00:00",
                  "end": "2026-05-21 12:00:00", "duration": "2", "slots": "4"},
        "need":  {"id": "n", "need_title": "T"},
        "user":  {"id": "u_b", "user_fname": "B", "user_lname": "B",
                  "user_email": ""},  # no email on file
        "response_status": "active",
    })
    tid = fresh.save_template(db_conn, name="x", subject="X", body="Y")
    r = fresh.send_template(db_conn, tid, "r_noemail")
    assert r["ok"] is False
    assert "no email" in (r["error"] or "")


def test_auto_emails_qualifying_no_show_24h(db_conn):
    """A shift that ended ~25h ago with no hour row qualifies."""
    import auto_emails
    from datetime import datetime, timedelta
    end = datetime.now() - timedelta(hours=25)
    start = end - timedelta(hours=2)
    import db
    db.init()
    db.ingest_response(db_conn, {
        "id": "r_late_noshow", "agency": {"id": "1", "agency_name": "T"},
        "shift": {"id": "s_late",
                  "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                  "end":   end.strftime("%Y-%m-%d %H:%M:%S"),
                  "duration": "2", "slots": "4"},
        "need":  {"id": "n", "need_title": "T"},
        "user":  {"id": "u_x", "user_fname": "X", "user_lname": "Y",
                  "user_email": "x@x.test"},
        "response_status": "active",
    })
    rids = auto_emails.qualifying_signups(db_conn, "no_show_24h")
    assert "r_late_noshow" in rids


def test_auto_emails_skips_cancellations(db_conn):
    """A cancelled signup must not qualify as no_show -- otherwise we'd
    auto-email people we have no business pestering.
    """
    import auto_emails
    from datetime import datetime, timedelta
    end = datetime.now() - timedelta(hours=25)
    start = end - timedelta(hours=2)
    import db
    db.init()
    db.ingest_response(db_conn, {
        "id": "r_cancel", "agency": {"id": "1", "agency_name": "T"},
        "shift": {"id": "s_c",
                  "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                  "end":   end.strftime("%Y-%m-%d %H:%M:%S"),
                  "duration": "2", "slots": "4"},
        "need":  {"id": "n", "need_title": "T"},
        "user":  {"id": "u_z", "user_fname": "Z", "user_lname": "Z",
                  "user_email": "z@x.test"},
        "response_status": "inactive",
    })
    rids = auto_emails.qualifying_signups(db_conn, "no_show_24h")
    assert "r_cancel" not in rids


def test_auto_emails_process_sends_once(db_conn, fresh):
    """Two ticks of auto_emails.process should fire the template once
    only -- second tick is fully dedup'd.
    """
    import auto_emails, db
    db.init()
    from datetime import datetime, timedelta
    end = datetime.now() - timedelta(hours=25)
    start = end - timedelta(hours=2)
    db.ingest_response(db_conn, {
        "id": "r_one", "agency": {"id": "1", "agency_name": "T"},
        "shift": {"id": "s_one",
                  "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                  "end":   end.strftime("%Y-%m-%d %H:%M:%S"),
                  "duration": "2", "slots": "4"},
        "need":  {"id": "n", "need_title": "T"},
        "user":  {"id": "u_one", "user_fname": "A", "user_lname": "B",
                  "user_email": "a@b.test"},
        "response_status": "active",
    })
    fresh.save_template(db_conn, name="ns24",
                        subject="hello {{volunteer_first}}",
                        body="bye", auto_trigger="no_show_24h")
    s1 = auto_emails.process(db_conn)
    s2 = auto_emails.process(db_conn)
    assert s1["sent"] >= 1
    assert s2["sent"] == 0
    assert s2["skipped"] >= 1


def test_collect_with_end_window(monkeypatch, tmp_db_path):
    """digest.collect(days_back=N, end=...) returns only shifts whose
    start_ts falls inside the [end-N, end+1day) window.
    """
    monkeypatch.delenv("WEB_PUBLIC_URL", raising=False)
    import digest as digest_mod, db
    from datetime import datetime
    importlib.reload(digest_mod)
    db.init()
    with db.connect() as conn:
        db.ingest_response(conn, {
            "id": "r_old", "agency": {"id": "1", "agency_name": "T"},
            "shift": {"id": "s_old", "start": "2025-01-15 10:00:00",
                      "end": "2025-01-15 12:00:00", "duration": "2", "slots": "4"},
            "need":  {"id": "n", "need_title": "Old shift"},
            "user":  {"id": "u_old", "user_fname": "O", "user_lname": "ld",
                      "user_email": "o@x.test"},
            "response_status": "active",
        })
    data = digest_mod.collect(days_back=1, end=datetime(2025, 1, 15))
    titles = [s["title"] for s in data["shifts"]]
    assert "Old shift" in titles
    # End set to today -> the 2025 shift should NOT be in the window.
    data2 = digest_mod.collect(days_back=1)
    assert "Old shift" not in [s["title"] for s in data2["shifts"]]
