"""Volunteer-name hyperlinks on the Today page and in the digest.

Today page: names should always link to /user/{id} (relative path).
Digest: names link iff WEB_PUBLIC_URL is set (absolute path); without
it the digest falls back to plain text so a bare /user/{id} in an
email client doesn't 404.
"""
from __future__ import annotations

import importlib
import os
import pytest

pytest.importorskip("httpx", reason="TestClient needs httpx")


def _seed_today_shift(conn):
    """One shift dated today + two signups so we can find name links."""
    import db
    db.init()
    today = conn.execute("SELECT date('now','localtime') AS d").fetchone()["d"]
    db.ingest_response(conn, {
        "id": "r1", "agency": {"id": "1", "agency_name": "Test"},
        "shift": {"id": "s1", "start": f"{today} 10:00:00",
                  "end": f"{today} 12:00:00", "duration": "2", "slots": "4"},
        "need": {"id": "n", "need_title": "Today Need"},
        "user": {"id": "u_a", "user_fname": "Ann", "user_lname": "Alpha",
                 "user_email": "ann@x.test"},
        "response_status": "active",
    })
    db.ingest_response(conn, {
        "id": "r2", "agency": {"id": "1", "agency_name": "Test"},
        "shift": {"id": "s1", "start": f"{today} 10:00:00",
                  "end": f"{today} 12:00:00", "duration": "2", "slots": "4"},
        "need": {"id": "n", "need_title": "Today Need"},
        "user": {"id": "u_b", "user_fname": "Bob", "user_lname": "Beta",
                 "user_email": "bob@x.test"},
        "response_status": "active",
    })


def test_today_page_names_link_to_user_detail(monkeypatch, tmp_db_path):
    monkeypatch.setenv("WEB_PASSWORD", "testpw")
    import web
    importlib.reload(web)
    import db
    with db.connect() as conn:
        _seed_today_shift(conn)

    from fastapi.testclient import TestClient
    c = TestClient(web.app)
    r = c.get("/", auth=("volunteer", "testpw"))
    assert r.status_code == 200
    assert 'href="/user/u_a">Ann Alpha</a>' in r.text
    assert 'href="/user/u_b">Bob Beta</a>' in r.text


def test_digest_html_links_names_when_public_url_set(monkeypatch, tmp_db_path):
    monkeypatch.setenv("WEB_PUBLIC_URL", "https://volunteer-status.example.org")
    import digest as digest_mod
    importlib.reload(digest_mod)
    import db
    with db.connect() as conn:
        _seed_today_shift(conn)

    data = digest_mod.collect(days_back=1)
    html = digest_mod.render_html(data)
    assert ('href="https://volunteer-status.example.org/user/u_a">Ann Alpha</a>'
            in html), "expected absolute link to user detail in digest html"


def test_digest_html_plain_text_without_public_url(monkeypatch, tmp_db_path):
    """Sanity: no WEB_PUBLIC_URL -> plain text names (no <a> tags around them)."""
    monkeypatch.delenv("WEB_PUBLIC_URL", raising=False)
    import digest as digest_mod
    importlib.reload(digest_mod)
    import db
    with db.connect() as conn:
        _seed_today_shift(conn)

    data = digest_mod.collect(days_back=1)
    html = digest_mod.render_html(data)
    assert "Ann Alpha" in html
    assert 'href="/user/u_a"' not in html
    assert 'href="https://' not in html or "user/u_a" not in html.split('href="https://', 1)[1]
