"""Tests for the SSE fingerprint + frame formatter.

We don't drive the live async generator here -- that requires a uvicorn
loop and adds flakiness for a logic test. Instead we exercise the two
pieces the streaming endpoint depends on:

  - _render_today_body(conn) -> (html, fp): fingerprint must be stable
    across calls with no DB change, and must move when a displayed value
    changes (status, name, kiosk times, etc.).
  - _sse(event, data): produces a well-formed SSE frame.

If both invariants hold, the live loop's correctness reduces to "yield
when fp changes", which is straightforward.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture
def web_module(monkeypatch):
    """web.py reads WEB_PASSWORD at import; supply one so the module is
    importable even on a fresh process.
    """
    monkeypatch.setenv("WEB_PASSWORD", "irrelevant")
    import importlib
    import web
    importlib.reload(web)
    return web


def _seed_one_today_shift(conn):
    """Insert one shift dated today (Chicago local) with two signups."""
    import db
    today = conn.execute("SELECT date('now','localtime') AS d").fetchone()["d"]
    start = f"{today} 10:00:00"
    end = f"{today} 12:00:00"
    db.ingest_response(conn, {
        "id": "r_a", "agency": {"id": "1", "agency_name": "Test Agency"},
        "shift": {"id": "s_today", "start": start, "end": end, "duration": "2", "slots": "4"},
        "need": {"id": "n", "need_title": "Test Need"},
        "user": {"id": "u_a", "user_fname": "Ann", "user_lname": "Alpha", "user_email": "a@x.test"},
        "response_status": "active",
    })
    db.ingest_response(conn, {
        "id": "r_b", "agency": {"id": "1", "agency_name": "Test Agency"},
        "shift": {"id": "s_today", "start": start, "end": end, "duration": "2", "slots": "4"},
        "need": {"id": "n", "need_title": "Test Need"},
        "user": {"id": "u_b", "user_fname": "Bob", "user_lname": "Beta", "user_email": "b@x.test"},
        "response_status": "active",
    })


def test_render_today_body_fingerprint_stable_across_calls(db_conn, web_module):
    _seed_one_today_shift(db_conn)
    html1, fp1 = web_module._render_today_body(db_conn)
    html2, fp2 = web_module._render_today_body(db_conn)
    assert fp1 == fp2
    assert html1 == html2


def test_render_today_body_fingerprint_changes_when_name_changes(db_conn, web_module):
    _seed_one_today_shift(db_conn)
    _, fp1 = web_module._render_today_body(db_conn)
    db_conn.execute("UPDATE users SET fname = 'Annabel' WHERE id = 'u_a'")
    _, fp2 = web_module._render_today_body(db_conn)
    assert fp1 != fp2


def test_render_today_body_empty_when_no_shifts(db_conn, web_module):
    """Empty days are still renderable -- this was the original 500 bug."""
    html, fp = web_module._render_today_body(db_conn)
    assert "No shifts scheduled today" in html
    assert len(fp) == 40  # sha1 hex


def test_sse_frame_format(web_module):
    frame = web_module._sse("today", "hello\nworld")
    # SSE spec: event line, then one `data:` line per source-line, then blank.
    assert frame == "event: today\ndata: hello\ndata: world\n\n"


def test_sse_frame_empty_data(web_module):
    """Even an empty payload must terminate with the spec-required blank line."""
    frame = web_module._sse("ping", "")
    assert frame == "event: ping\ndata: \n\n"
