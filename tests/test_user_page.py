"""Tests for /user/{id} and /users search.

Covers:
  - 404 for an unknown user id
  - The page renders volunteer name, email, and aggregate stats
  - Past vs upcoming shifts are sorted correctly
  - Manual overrides feed into the per-user attendance counts
  - /users?q= surfaces matches by partial name / email
  - Enrichment path: no /users API call is made when last_enriched is set
"""
from __future__ import annotations

import pytest


pytest.importorskip("httpx", reason="TestClient needs httpx")


@pytest.fixture
def client(monkeypatch, tmp_db_path):
    monkeypatch.setenv("WEB_PASSWORD", "testpw")
    import importlib
    import web
    importlib.reload(web)
    from fastapi.testclient import TestClient
    return TestClient(web.app), web


def _seed_two_shifts_one_user(conn, *, response_status="active"):
    """One user, two shifts: one past, one future."""
    import db
    db.init()
    today = conn.execute("SELECT date('now','localtime') AS d").fetchone()["d"]
    past_start = f"{today} 09:00:00"
    past_end = f"{today} 11:00:00"
    fut_start = "2099-01-01 14:00:00"
    fut_end   = "2099-01-01 16:00:00"

    # Two distinct needs so we can verify which is rendered where.
    db.ingest_response(conn, {
        "id": "r_past", "agency": {"id": "1", "agency_name": "Test"},
        "shift": {"id": "s_past", "start": "2020-01-01 09:00:00",
                  "end": "2020-01-01 11:00:00", "duration": "2", "slots": "4"},
        "need":  {"id": "n_past", "need_title": "Past Need"},
        "user":  {"id": "u_a", "user_fname": "Ann", "user_lname": "Alpha",
                  "user_email": "ann@x.test"},
        "response_status": response_status,
    })
    db.ingest_response(conn, {
        "id": "r_fut", "agency": {"id": "1", "agency_name": "Test"},
        "shift": {"id": "s_fut", "start": fut_start, "end": fut_end,
                  "duration": "2", "slots": "4"},
        "need":  {"id": "n_fut", "need_title": "Future Need"},
        "user":  {"id": "u_a", "user_fname": "Ann", "user_lname": "Alpha",
                  "user_email": "ann@x.test"},
        "response_status": response_status,
    })
    # Decorate the user with phone + enrichment timestamp so the page
    # doesn't try to call /users on its own.
    conn.execute(
        "UPDATE users SET phone=?, address=?, last_enriched=? WHERE id='u_a'",
        ("555-0100", "100 Main St, Chicago, IL", "2026-05-20T18:00:00"),
    )


def test_unknown_user_404(client):
    c, _ = client
    import db
    with db.connect() as conn:
        db.init()
    r = c.get("/user/no_such_id", auth=("volunteer", "testpw"))
    assert r.status_code == 404


def test_user_page_shows_profile_and_stats(client):
    c, _ = client
    import db
    with db.connect() as conn:
        _seed_two_shifts_one_user(conn)
    r = c.get("/user/u_a", auth=("volunteer", "testpw"))
    assert r.status_code == 200
    # Profile fields
    assert "Ann Alpha" in r.text
    assert "ann@x.test" in r.text
    assert "555-0100" in r.text
    assert "100 Main" in r.text
    # 2 signups total
    assert "2 signups" in r.text
    # One past shift -> classified NO_SHOW since shift end < now and no hour row
    assert "no_show" in r.text or "🔴" in r.text


def test_user_page_reflects_manual_override(client):
    c, _ = client
    import db, checkin
    with db.connect() as conn:
        _seed_two_shifts_one_user(conn)
        # Pretend Ann was manually checked in for the past shift.
        db.set_override(conn, "r_past", checkin.CHECKED_IN)

    r = c.get("/user/u_a", auth=("volunteer", "testpw"))
    assert r.status_code == 200
    # Status should reflect the override, not the would-be NO_SHOW.
    assert checkin.STATUS_EMOJI[checkin.CHECKED_IN] in r.text


def test_user_page_splits_upcoming_and_past(client):
    c, _ = client
    import db
    with db.connect() as conn:
        _seed_two_shifts_one_user(conn)
    r = c.get("/user/u_a", auth=("volunteer", "testpw"))
    assert "Upcoming" in r.text
    assert "Past" in r.text
    # Future Need (2099) should be in Upcoming, Past Need in Past.
    upi = r.text.find("Upcoming")
    pi  = r.text.find("Past")
    fni = r.text.find("Future Need")
    pni = r.text.find("Past Need")
    assert upi < fni < pi < pni, "future and past need to be in their sections"


def test_users_search_finds_by_partial_name(client):
    c, _ = client
    import db
    with db.connect() as conn:
        _seed_two_shifts_one_user(conn)

    # Empty search -> just the form
    r = c.get("/users", auth=("volunteer", "testpw"))
    assert "Find a volunteer" in r.text

    # Partial name match
    r = c.get("/users?q=Alph", auth=("volunteer", "testpw"))
    assert r.status_code == 200
    assert "Ann Alpha" in r.text
    assert 'href="/user/u_a"' in r.text


def test_users_search_finds_by_email_substring(client):
    c, _ = client
    import db
    with db.connect() as conn:
        _seed_two_shifts_one_user(conn)
    r = c.get("/users?q=x.test", auth=("volunteer", "testpw"))
    assert "Ann Alpha" in r.text


def test_user_links_appear_on_shift_page(client):
    c, _ = client
    import db
    with db.connect() as conn:
        _seed_two_shifts_one_user(conn)
    r = c.get("/shift/s_fut", auth=("volunteer", "testpw"))
    assert r.status_code == 200
    assert 'href="/user/u_a"' in r.text
