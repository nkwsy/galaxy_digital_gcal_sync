"""Local FastAPI webapp for real-time check-in visibility.

Reads from the SQLite store (db.py). The sync loop in run_cal_update.py
writes to that same DB, so this app is purely a viewer -- no Galaxy API
calls from web request paths.

Pages:
  /                 today's shifts + live status
  /shift/{id}       drill-down for one shift
  /offenders        repeat no-shows (configurable window)
  /digest           today's digest (HTML format)
  /api/today.json   machine-readable view of /

Auth: single shared password via env WEB_PASSWORD (HTTP Basic). If unset,
the app refuses to start to avoid accidentally exposing PII to the LAN.

Run: uvicorn web:app --host 0.0.0.0 --port ${WEB_PORT:-8765}
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta
from typing import Annotated

import pytz
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

import checkin
import db
import digest as digest_mod

CHICAGO = pytz.timezone("America/Chicago")

WEB_PASSWORD = os.getenv("WEB_PASSWORD")
WEB_USERNAME = os.getenv("WEB_USERNAME", "volunteer")
# How many seconds between auto-refreshes on the live page.
REFRESH_SECS = int(os.getenv("WEB_REFRESH_SECS", "60"))

app = FastAPI(title="Galaxy Digital live status")
security = HTTPBasic(auto_error=False)


def _require_auth(creds: Annotated[HTTPBasicCredentials | None, Depends(security)]):
    if not WEB_PASSWORD:
        # Refuse to serve anything if the operator hasn't set a password --
        # this page lists volunteer emails so it must not be wide-open by
        # default.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WEB_PASSWORD env var must be set before the server will serve requests.",
        )
    if creds is None or not (
        secrets.compare_digest(creds.username, WEB_USERNAME)
        and secrets.compare_digest(creds.password, WEB_PASSWORD)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Auth required",
            headers={"WWW-Authenticate": "Basic"},
        )
    return creds


PAGE_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       color: #1a1a1a; max-width: 980px; margin: 0 auto; padding: 1em; background: #fafbfc; }
header { display: flex; justify-content: space-between; align-items: baseline;
         border-bottom: 1px solid #e2e4e8; padding-bottom: 0.5em; margin-bottom: 1em; }
header h1 { margin: 0; color: #2a4d69; }
nav a { margin-left: 1em; color: #2a4d69; text-decoration: none; }
nav a:hover { text-decoration: underline; }
.meta { color: #777; font-size: 0.9em; }
.shift { background: white; border: 1px solid #e2e4e8; border-radius: 8px;
         margin: 1em 0; padding: 0.9em 1em; }
.shift h3 { margin: 0 0 0.2em 0; }
.shift .meta { margin-bottom: 0.5em; }
.bar { display: flex; gap: 0.6em; flex-wrap: wrap; font-size: 0.9em; margin: 0.3em 0 0.5em; }
.bar span { background: #f0f3f7; padding: 2px 8px; border-radius: 12px; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 5px 8px; text-align: left; border-bottom: 1px solid #f0f0f0; font-size: 0.93em; }
tr.no-show { background: #fff4f4; }
tr.checked-in { background: #f1faf2; }
tr.checked-out { background: #f1f5fa; }
.empty { color: #888; font-style: italic; }
"""


def _layout(title: str, body: str, refresh: bool = False) -> str:
    refresh_tag = f'<meta http-equiv="refresh" content="{REFRESH_SECS}">' if refresh else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8">{refresh_tag}<title>{title}</title>
<style>{PAGE_CSS}</style></head>
<body>
<header>
<h1>Galaxy Digital · live</h1>
<nav>
  <a href="/">Today</a>
  <a href="/offenders">Repeat no-shows</a>
  <a href="/digest">Digest</a>
</nav>
</header>
{body}
<p class="meta">Page auto-refreshes every {REFRESH_SECS}s · generated {datetime.now(CHICAGO).strftime('%Y-%m-%d %H:%M %Z')}</p>
</body></html>"""


def _row_for_signup(sg, shift_end_ts: str | None) -> dict:
    """Resolve display row for one (signup + maybe-hour) pair."""
    status = sg["classification"]
    if not status:
        now_ct = datetime.now(CHICAGO).strftime("%Y-%m-%d %H:%M:%S")
        status = checkin.NO_SHOW if shift_end_ts and shift_end_ts < now_ct else checkin.SIGNED_UP
    src = (sg["source"] or "") if "source" in sg.keys() else ""
    return {
        "name": f"{sg['fname'] or ''} {sg['lname'] or ''}".strip(),
        "email": sg["email"] or "",
        "status": status,
        "emoji": checkin.STATUS_EMOJI.get(status, "🔘"),
        "check_in": sg["date_start"] if "/kiosk/storeCheckin/".lower() in src.lower() else None,
        "check_out": sg["date_end"] if "/kiosk/storeCheckout/".lower() in src.lower() else None,
    }


@app.get("/", response_class=HTMLResponse)
def today(_: Annotated[HTTPBasicCredentials, Depends(_require_auth)]):
    with db.connect() as conn:
        shifts = db.shifts_for_day(conn)
        rendered = []
        for s in shifts:
            sgs = db.signups_for_shift(conn, s["id"])
            people = [_row_for_signup(r, s["end_ts"]) for r in sgs]
            counts: dict[str, int] = {}
            for p in people:
                counts[p["status"]] = counts.get(p["status"], 0) + 1
            rendered.append({"shift": s, "people": people, "counts": counts})

    if not rendered:
        body = "<p class='empty'>No shifts scheduled today.</p>"
        return HTMLResponse(_layout("Today", body, refresh=True))

    parts = ["<h2>Today's shifts</h2>"]
    for blk in rendered:
        s = blk["shift"]
        c = blk["counts"]
        title = s["title"] or "(no title)"
        agency = s["agency_name"] or ""
        start = (s["start_ts"] or "")[11:16]
        end = (s["end_ts"] or "")[11:16]
        parts.append(f'<div class="shift"><h3><a href="/shift/{s["id"]}">{title}</a></h3>')
        parts.append(f'<div class="meta">{agency} · {start}–{end} · '
                     f'{sum(c.values())}/{s["slots"]} filled</div>')
        parts.append('<div class="bar">')
        for k in (checkin.CHECKED_IN, checkin.CHECKED_OUT, checkin.SIGNED_UP,
                  checkin.NO_SHOW, checkin.MANAGER_ENTERED):
            n = c.get(k, 0)
            if n:
                parts.append(f"<span>{checkin.STATUS_EMOJI[k]} {n} {k.replace('_',' ')}</span>")
        parts.append('</div>')
        if blk["people"]:
            parts.append('<table><thead><tr><th></th><th>Volunteer</th><th>Email</th>'
                         '<th>In</th><th>Out</th></tr></thead><tbody>')
            for p in blk["people"]:
                tr_cls = ""
                if p["status"] == checkin.NO_SHOW:    tr_cls = " class='no-show'"
                elif p["status"] == checkin.CHECKED_IN:  tr_cls = " class='checked-in'"
                elif p["status"] == checkin.CHECKED_OUT: tr_cls = " class='checked-out'"
                parts.append(
                    f"<tr{tr_cls}><td>{p['emoji']}</td>"
                    f"<td>{p['name']}</td><td>{p['email']}</td>"
                    f"<td>{(p['check_in'] or '')[11:16]}</td>"
                    f"<td>{(p['check_out'] or '')[11:16]}</td></tr>"
                )
            parts.append('</tbody></table>')
        parts.append('</div>')
    return HTMLResponse(_layout("Today", "\n".join(parts), refresh=True))


@app.get("/shift/{shift_id}", response_class=HTMLResponse)
def shift_detail(shift_id: str,
                 _: Annotated[HTTPBasicCredentials, Depends(_require_auth)]):
    with db.connect() as conn:
        s = conn.execute(
            "SELECT s.*, n.title, n.agency_name FROM shifts s "
            "LEFT JOIN needs n ON n.id = s.need_id WHERE s.id = ?",
            (shift_id,),
        ).fetchone()
        if not s:
            raise HTTPException(404, "shift not found")
        sgs = db.signups_for_shift(conn, shift_id)
        people = [_row_for_signup(r, s["end_ts"]) for r in sgs]
        hist = conn.execute(
            """SELECT status, observed_at FROM status_history
               WHERE shift_id = ? ORDER BY id DESC LIMIT 25""",
            (shift_id,),
        ).fetchall()

    parts = [f'<h2>{s["title"] or "(no title)"}</h2>']
    parts.append(f'<div class="meta">{s["agency_name"] or ""} · '
                 f'{s["start_ts"]} → {s["end_ts"]} · slots={s["slots"]}</div>')
    parts.append('<table><thead><tr><th></th><th>Volunteer</th><th>Email</th>'
                 '<th>Status</th><th>In</th><th>Out</th></tr></thead><tbody>')
    for p in people:
        parts.append(f"<tr><td>{p['emoji']}</td><td>{p['name']}</td><td>{p['email']}</td>"
                     f"<td>{p['status']}</td><td>{p['check_in'] or ''}</td>"
                     f"<td>{p['check_out'] or ''}</td></tr>")
    parts.append('</tbody></table>')
    parts.append('<h3>Recent status changes</h3>')
    if hist:
        parts.append('<table><thead><tr><th>When (UTC)</th><th>Status</th></tr></thead><tbody>')
        for h in hist:
            parts.append(f"<tr><td>{h['observed_at']}</td><td>{h['status']}</td></tr>")
        parts.append('</tbody></table>')
    else:
        parts.append("<p class='empty'>No recorded status changes.</p>")
    parts.append('<p><a href="/">&laquo; back to today</a></p>')
    return HTMLResponse(_layout(s["title"] or "Shift", "\n".join(parts), refresh=True))


@app.get("/offenders", response_class=HTMLResponse)
def offenders(_: Annotated[HTTPBasicCredentials, Depends(_require_auth)],
              days: int = 30, min_count: int = 2):
    with db.connect() as conn:
        rows = db.repeat_offenders(conn, days=days, min_count=min_count)
    parts = [f'<h2>Repeat no-shows · last {days} days (min {min_count})</h2>']
    parts.append('<p class="meta">')
    for d in (7, 30, 90, 365):
        parts.append(f' <a href="/offenders?days={d}&min_count={min_count}">last {d}d</a>')
    parts.append('</p>')
    if not rows:
        parts.append("<p class='empty'>No repeat offenders in this window. 🎉</p>")
    else:
        parts.append('<table><thead><tr><th>Volunteer</th><th>Email</th><th>No-shows</th>'
                     '</tr></thead><tbody>')
        for r in rows:
            parts.append(
                f"<tr><td>{(r['fname'] or '')} {(r['lname'] or '')}</td>"
                f"<td>{r['email'] or ''}</td><td>{r['no_shows']}</td></tr>"
            )
        parts.append('</tbody></table>')
    return HTMLResponse(_layout("Repeat no-shows", "\n".join(parts), refresh=False))


@app.get("/digest", response_class=HTMLResponse)
def view_digest(_: Annotated[HTTPBasicCredentials, Depends(_require_auth)], days: int = 1):
    data = digest_mod.collect(days_back=days)
    html = digest_mod.render_html(data)
    return HTMLResponse(_layout("Digest preview", html, refresh=False))


@app.get("/api/today.json")
def api_today(_: Annotated[HTTPBasicCredentials, Depends(_require_auth)]):
    with db.connect() as conn:
        shifts = db.shifts_for_day(conn)
        out = []
        for s in shifts:
            sgs = db.signups_for_shift(conn, s["id"])
            out.append({
                "id": s["id"],
                "title": s["title"],
                "agency": s["agency_name"],
                "start": s["start_ts"],
                "end": s["end_ts"],
                "slots": s["slots"],
                "people": [_row_for_signup(r, s["end_ts"]) for r in sgs],
            })
    return JSONResponse(out)
