"""Local FastAPI webapp for real-time check-in visibility.

Reads from the SQLite store (db.py). The sync loop in run_cal_update.py
writes to that same DB, so this app is purely a viewer -- no Galaxy API
calls from web request paths.

Pages:
  /                 today's shifts + live status (SSE-driven)
  /shift/{id}       drill-down for one shift
  /offenders        repeat no-shows (configurable window)
  /digest           today's digest (HTML format)
  /api/today.json   machine-readable view of /
  /events           Server-Sent Events stream pushing today's HTML
                    fragment whenever the underlying SQLite state changes.

Live updates: the page no longer meta-refreshes. Instead it opens an
EventSource against /events; the server polls the DB every SSE_POLL_SECS
(default 5s) and only sends a frame when the (response_id, status,
checkin_time, checkout_time) fingerprint of today's roster changes.
Heartbeat comments are sent in between so proxies / browsers don't
idle-close the connection.

Auth: single shared password via env WEB_PASSWORD (HTTP Basic). If unset,
the app refuses to start to avoid accidentally exposing PII to the LAN.

Run: uvicorn web:app --host 0.0.0.0 --port ${WEB_PORT:-8765}
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Annotated, AsyncIterator

import pytz
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

import checkin
import db
import digest as digest_mod

CHICAGO = pytz.timezone("America/Chicago")

WEB_PASSWORD = os.getenv("WEB_PASSWORD")
WEB_USERNAME = os.getenv("WEB_USERNAME", "volunteer")
# How often the SSE endpoint re-queries SQLite to look for changes. Keep
# this small (1-5s) -- the work is one indexed query plus a hash; the
# stream only emits when the fingerprint actually changes.
SSE_POLL_SECS = float(os.getenv("WEB_SSE_POLL_SECS", "5"))
SSE_HEARTBEAT_SECS = float(os.getenv("WEB_SSE_HEARTBEAT_SECS", "20"))

@asynccontextmanager
async def _lifespan(app):
    """Create the SQLite schema on first launch so the viewer doesn't 500
    when the operator hits / before run_cal_update.py has done its first
    ingest. The tables will be empty until then -- but empty is renderable.

    Uses the modern lifespan API rather than the deprecated on_event hook.
    """
    db.init()
    yield


app = FastAPI(title="Galaxy Digital live status", lifespan=_lifespan)
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
tr.checked-in { background: #fffbe6; }   /* 🟡 at the kiosk now */
tr.checked-out { background: #f1faf2; }  /* 🟢 done for the day */
.empty { color: #888; font-style: italic; }
"""


SSE_CLIENT_JS = """
<script>
// Open a Server-Sent Events stream and patch the shifts container in
// place when the server tells us the roster changed. Falls back to a
// 60s page reload if SSE isn't supported (very old browsers).
(function(){
  if (typeof EventSource === 'undefined') {
    setTimeout(function(){ location.reload(); }, 60000);
    return;
  }
  var es = new EventSource('/events');
  es.addEventListener('today', function(ev){
    var c = document.getElementById('shifts-container');
    if (c) c.innerHTML = ev.data;
    var stamp = document.getElementById('updated-at');
    if (stamp) stamp.textContent = new Date().toLocaleTimeString();
  });
  es.onerror = function(){
    // EventSource auto-reconnects with backoff -- nothing to do here,
    // but log it so misconfiguration shows up in devtools.
    console.warn('SSE stream dropped; browser will retry.');
  };
})();
</script>
"""


def _layout(title: str, body: str, live: bool = False) -> str:
    """Wrap `body` in the site chrome. If `live` is true, embed the SSE
    client JS that swaps #shifts-container in place when /events fires.
    """
    live_script = SSE_CLIENT_JS if live else ""
    stamp = datetime.now(CHICAGO).strftime("%H:%M:%S")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
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
<p class="meta">{('Live: updated <span id="updated-at">' + stamp + '</span>' if live else 'generated ' + datetime.now(CHICAGO).strftime('%Y-%m-%d %H:%M %Z'))}</p>
{live_script}
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


def _render_today_body(conn) -> tuple[str, str]:
    """Build the shifts fragment for today and a fingerprint over it.

    Returning the fingerprint alongside the HTML lets the SSE loop decide
    whether to push without having to diff strings -- the fingerprint
    covers the only things that actually affect what's displayed.
    """
    shifts = db.shifts_for_day(conn)
    rendered = []
    fp_inputs: list[str] = []
    for s in shifts:
        sgs = db.signups_for_shift(conn, s["id"])
        people = [_row_for_signup(r, s["end_ts"]) for r in sgs]
        counts: dict[str, int] = {}
        for p in people:
            counts[p["status"]] = counts.get(p["status"], 0) + 1
            fp_inputs.append(
                f"{s['id']}|{p['name']}|{p['status']}|{p['check_in'] or ''}|{p['check_out'] or ''}"
            )
        rendered.append({"shift": s, "people": people, "counts": counts})

    if not rendered:
        body = "<p class='empty'>No shifts scheduled today.</p>"
        return body, hashlib.sha1(b"empty").hexdigest()

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

    body_html = "\n".join(parts)
    fp = hashlib.sha1("\n".join(sorted(fp_inputs)).encode()).hexdigest()
    return body_html, fp


@app.get("/", response_class=HTMLResponse)
def today(_: Annotated[HTTPBasicCredentials, Depends(_require_auth)]):
    with db.connect() as conn:
        body, _fp = _render_today_body(conn)
    # The body is wrapped in a container the SSE handler can target.
    wrapped = f'<div id="shifts-container">{body}</div>'
    return HTMLResponse(_layout("Today", wrapped, live=True))


@app.get("/events")
async def events_stream(_: Annotated[HTTPBasicCredentials, Depends(_require_auth)]):
    """Server-Sent Events: push the today fragment when its fingerprint
    changes; emit a `: heartbeat` comment otherwise so the connection
    stays warm through proxies.

    Each event uses the SSE field `event: today` so the browser client
    can dispatch it to one handler regardless of how many event types we
    add later.
    """

    async def gen() -> AsyncIterator[str]:
        last_fp: str | None = None
        last_heartbeat = asyncio.get_event_loop().time()

        # Push an immediate snapshot so the client can drop the initial
        # SSR'd body if it wants to without waiting for a real change.
        with db.connect() as conn:
            body, fp = _render_today_body(conn)
        last_fp = fp
        yield _sse("today", body)

        while True:
            await asyncio.sleep(SSE_POLL_SECS)
            with db.connect() as conn:
                body, fp = _render_today_body(conn)
            now = asyncio.get_event_loop().time()
            if fp != last_fp:
                last_fp = fp
                last_heartbeat = now
                yield _sse("today", body)
            elif now - last_heartbeat >= SSE_HEARTBEAT_SECS:
                last_heartbeat = now
                # Comment-only SSE frame; keeps NAT / proxies from idle-killing.
                yield ": heartbeat\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # nginx: don't buffer the stream
        },
    )


def _sse(event: str, data: str) -> str:
    """Format a single SSE frame. `data:` lines split on newline per spec."""
    lines = "\n".join(f"data: {ln}" for ln in data.splitlines() or [""])
    return f"event: {event}\n{lines}\n\n"


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
                 '<th>Status</th><th>In</th><th>Out</th><th>Action</th></tr></thead><tbody>')
    # Build a {name -> response_id} lookup so we can attach action buttons.
    # signups_for_shift is already in DB-sort order.
    rid_lookup = {f"{r['fname']} {r['lname']}".strip(): r['response_id']
                  for r in sgs}
    for p in people:
        rid = rid_lookup.get(p['name'], '')
        parts.append(f"<tr><td>{p['emoji']}</td><td>{p['name']}</td><td>{p['email']}</td>"
                     f"<td>{p['status']}</td><td>{p['check_in'] or ''}</td>"
                     f"<td>{p['check_out'] or ''}</td>"
                     f"<td>{_render_action_buttons(rid, p['status'], shift_id)}</td></tr>")
    parts.append('</tbody></table>')
    parts.append("<p class='meta' style='font-size:0.85em'>"
                 "Buttons write status locally and propagate to Google "
                 "Calendar within ~60s. They do NOT update Galaxy Digital -- "
                 "back-fill there separately if needed.</p>")
    parts.append('<h3>Recent status changes</h3>')
    if hist:
        parts.append('<table><thead><tr><th>When (UTC)</th><th>Status</th></tr></thead><tbody>')
        for h in hist:
            parts.append(f"<tr><td>{h['observed_at']}</td><td>{h['status']}</td></tr>")
        parts.append('</tbody></table>')
    else:
        parts.append("<p class='empty'>No recorded status changes.</p>")
    parts.append('<p><a href="/">&laquo; back to today</a></p>')
    return HTMLResponse(_layout(s["title"] or "Shift", "\n".join(parts), live=False))


# ---------- manual check-in actions ---------------------------------------
#
# Why local-only: a POST to Galaxy Digital /hours would write hour_source =
# "/api/..." which our classifier resolves to MANAGER_ENTERED (purple). The
# UI would then bounce 🟡 -> 🟣 on the next sync, which is confusing. Use
# the same kiosk-source convention simulate_checkin.py uses so the calendar
# and webpage agree on the visual state; document the Galaxy-side gap.

def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write_manual_status(response_id: str, action: str) -> str:
    """Apply a manual check-in/check-out/clear to local SQLite.

    Returns the resulting status string for logging / UX.
    Raises HTTPException(404) if response_id is unknown.
    """
    db.init()
    with db.connect() as conn:
        sg = conn.execute(
            "SELECT sg.user_id, sg.shift_id, sg.need_id "
            "FROM signups sg WHERE sg.id = ?",
            (response_id,),
        ).fetchone()
        if not sg:
            raise HTTPException(404, f"unknown response_id {response_id!r}")

        # Synthesize the same hour_source strings simulate_checkin.py uses so
        # checkin.classify_hour resolves them to CHECKED_IN / CHECKED_OUT.
        if action == "clear":
            conn.execute("BEGIN")
            conn.execute(
                "DELETE FROM hours WHERE response_id = ? AND id LIKE 'web-%'",
                (response_id,),
            )
            conn.execute(
                "DELETE FROM scan_state WHERE key = ?",
                (f"gcal_fp:{sg['shift_id']}",),
            )
            conn.execute("COMMIT")
            return checkin.SIGNED_UP

        if action == "checkin":
            source = "Added at: /kiosk/storeCheckin/ by web ui"
            status = checkin.CHECKED_IN
        elif action == "checkout":
            source = ("Added at: /kiosk/storeCheckin/ by web ui "
                      "Updated at: /kiosk/storeCheckout/ by web ui")
            status = checkin.CHECKED_OUT
        else:
            raise HTTPException(400, f"unknown action {action!r}")

        existing = conn.execute(
            "SELECT id FROM hours WHERE response_id = ? AND id LIKE 'web-%' LIMIT 1",
            (response_id,),
        ).fetchone()
        now = _now_iso()
        conn.execute("BEGIN")
        if existing:
            conn.execute(
                "UPDATE hours SET source=?, classification=?, updated_at=? "
                "WHERE id=?",
                (source, status, now, existing["id"]),
            )
        else:
            hid = f"web-{uuid.uuid4().hex[:10]}"
            db.ingest_hour(conn, {
                "id": hid,
                "hour_response_id": response_id,
                "user": {"id": sg["user_id"]},
                "need": {"id": sg["need_id"]},
                "hour_source": source,
                "hour_status": "approved",
                "hour_date_start": now,
                "hour_date_end": now,
                "created_at": now,
                "updated_at": now,
            })
        # Append to status_history (idempotent) so /offenders + digest see it.
        db.record_status(
            conn, response_id=response_id, shift_id=sg["shift_id"],
            user_id=sg["user_id"], status=status,
        )
        # Invalidate the per-shift gcal fingerprint so the next scan tick
        # pushes the update instead of skipping it as unchanged.
        conn.execute(
            "DELETE FROM scan_state WHERE key = ?",
            (f"gcal_fp:{sg['shift_id']}",),
        )
        conn.execute("COMMIT")
        return status


def _render_action_buttons(response_id: str, current_status: str,
                            shift_id: str) -> str:
    """Two/three inline POST forms next to a volunteer row.

    Each button posts to /action/<verb> with response_id; on success it
    redirects back to /shift/<shift_id>, so the page reflects the new
    state immediately (the SSE channel will also pick it up within ~5s).
    """
    if not response_id:
        return ""
    forms = []
    def _btn(action: str, label: str) -> str:
        # `formaction` makes one form support multiple submit destinations,
        # but plain forms work fine and are easier to read.
        return (f'<form method="post" action="/action/{action}" '
                f'style="display:inline; margin:0 2px">'
                f'<input type="hidden" name="response_id" value="{response_id}">'
                f'<input type="hidden" name="shift_id"    value="{shift_id}">'
                f'<button type="submit">{label}</button></form>')
    if current_status == checkin.CHECKED_IN:
        forms.append(_btn("checkout", "Mark out"))
        forms.append(_btn("clear", "Undo"))
    elif current_status == checkin.CHECKED_OUT:
        forms.append(_btn("clear", "Undo"))
    elif current_status in (checkin.SIGNED_UP, checkin.NO_SHOW):
        forms.append(_btn("checkin", "Mark in"))
        forms.append(_btn("checkout", "Mark out"))
    else:
        forms.append(_btn("clear", "Undo"))
    return "".join(forms)


@app.post("/action/checkin")
def action_checkin(
    _: Annotated[HTTPBasicCredentials, Depends(_require_auth)],
    response_id: Annotated[str, Form()],
    shift_id: Annotated[str, Form()],
):
    _write_manual_status(response_id, "checkin")
    return RedirectResponse(f"/shift/{shift_id}", status_code=303)


@app.post("/action/checkout")
def action_checkout(
    _: Annotated[HTTPBasicCredentials, Depends(_require_auth)],
    response_id: Annotated[str, Form()],
    shift_id: Annotated[str, Form()],
):
    _write_manual_status(response_id, "checkout")
    return RedirectResponse(f"/shift/{shift_id}", status_code=303)


@app.post("/action/clear")
def action_clear(
    _: Annotated[HTTPBasicCredentials, Depends(_require_auth)],
    response_id: Annotated[str, Form()],
    shift_id: Annotated[str, Form()],
):
    _write_manual_status(response_id, "clear")
    return RedirectResponse(f"/shift/{shift_id}", status_code=303)


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
    return HTMLResponse(_layout("Repeat no-shows", "\n".join(parts), live=False))


@app.get("/digest", response_class=HTMLResponse)
def view_digest(_: Annotated[HTTPBasicCredentials, Depends(_require_auth)], days: int = 1):
    data = digest_mod.collect(days_back=days)
    html = digest_mod.render_html(data)
    return HTMLResponse(_layout("Digest preview", html, live=False))


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
