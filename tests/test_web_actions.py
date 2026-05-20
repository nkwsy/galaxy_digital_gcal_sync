"""Tests for the manual check-in / check-out / clear action endpoints.

Drives the FastAPI app via TestClient. Each test seeds a single shift +
two signups, hits one of the /action/* endpoints, and asserts that:

  - the redirect goes back to /shift/{id}
  - hours row got created with the right hour_source convention
  - status_history got an entry
  - the per-shift gcal fingerprint got nuked (so the next scan will push)
"""
from __future__ import annotations

import pytest


pytest.importorskip("httpx", reason="TestClient needs httpx")


@pytest.fixture
def client(monkeypatch, tmp_db_path):
    monkeypatch.setenv("WEB_PASSWORD", "testpw")
    # Reload web so the env var is picked up
    import importlib
    import web
    importlib.reload(web)
    from fastapi.testclient import TestClient
    return TestClient(web.app), web


def _seed(conn):
    import db
    db.init()
    today = conn.execute("SELECT date('now','localtime') AS d").fetchone()["d"]
    db.ingest_response(conn, {
        "id": "r_a",
        "agency": {"id": "1", "agency_name": "Test"},
        "shift": {"id": "s_x", "start": f"{today} 10:00:00",
                  "end": f"{today} 12:00:00", "duration": "2", "slots": "4"},
        "need": {"id": "n", "need_title": "Test Need"},
        "user": {"id": "u_a", "user_fname": "Ann", "user_lname": "Alpha",
                 "user_email": "a@x.test"},
        "response_status": "active",
    })
    # Pre-seed a gcal fingerprint so we can prove the action nukes it.
    db.set_state(conn, "gcal_fp:s_x", "stale_fingerprint")


def test_action_checkin_writes_local_hour(client):
    c, web_mod = client
    import db, checkin
    with db.connect() as conn:
        _seed(conn)

    r = c.post("/action/checkin",
               data={"response_id": "r_a", "shift_id": "s_x"},
               auth=("volunteer", "testpw"),
               follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/shift/s_x"

    with db.connect() as conn:
        h = conn.execute("SELECT classification, source FROM hours "
                         "WHERE response_id='r_a'").fetchone()
        assert h is not None, "no hour row created"
        assert h["classification"] == checkin.CHECKED_IN
        assert "/kiosk/storeCheckin/" in h["source"]
        assert "/kiosk/storeCheckout/" not in h["source"]

        hist = conn.execute("SELECT status FROM status_history "
                            "WHERE response_id='r_a'").fetchall()
        assert any(h["status"] == checkin.CHECKED_IN for h in hist)

        fp = db.get_state(conn, "gcal_fp:s_x")
        assert fp is None, "fingerprint should have been invalidated"


def test_action_checkout_then_clear(client):
    c, _ = client
    import db, checkin
    with db.connect() as conn:
        _seed(conn)

    c.post("/action/checkin",  data={"response_id": "r_a", "shift_id": "s_x"},
           auth=("volunteer", "testpw"), follow_redirects=False)
    c.post("/action/checkout", data={"response_id": "r_a", "shift_id": "s_x"},
           auth=("volunteer", "testpw"), follow_redirects=False)

    with db.connect() as conn:
        h = conn.execute("SELECT classification, source FROM hours "
                         "WHERE response_id='r_a'").fetchone()
        assert h["classification"] == checkin.CHECKED_OUT
        assert "/kiosk/storeCheckout/" in h["source"]

    # clear -> hour row gone, fingerprint invalidated again
    c.post("/action/clear", data={"response_id": "r_a", "shift_id": "s_x"},
           auth=("volunteer", "testpw"), follow_redirects=False)

    with db.connect() as conn:
        h = conn.execute("SELECT id FROM hours "
                         "WHERE response_id='r_a' AND id LIKE 'web-%'").fetchone()
        assert h is None, "clear should delete the web-* hours row"


def test_action_unknown_response_id_404(client):
    c, _ = client
    r = c.post("/action/checkin",
               data={"response_id": "does_not_exist", "shift_id": "x"},
               auth=("volunteer", "testpw"), follow_redirects=False)
    assert r.status_code == 404


def test_action_requires_auth(client):
    c, _ = client
    r = c.post("/action/checkin",
               data={"response_id": "r_a", "shift_id": "s_x"},
               follow_redirects=False)
    assert r.status_code == 401


def test_shift_detail_renders_action_buttons(client):
    c, web_mod = client
    import db
    with db.connect() as conn:
        _seed(conn)
    r = c.get("/shift/s_x", auth=("volunteer", "testpw"))
    assert r.status_code == 200
    assert "Mark in" in r.text or "Mark out" in r.text
    # The response_id should be in the form payloads
    assert 'value="r_a"' in r.text
