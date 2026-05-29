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
tr.cancelled { color: #999; background: #f5f5f5; }    /* ⚪ un-registered */
tr.cancelled td { text-decoration: line-through; }
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


def _layout(title: str, body: str, live: bool = False,
            wide: bool = False) -> str:
    """Wrap `body` in the site chrome. If `live` is true, embed the SSE
    client JS that swaps #shifts-container in place when /events fires.

    `wide` disables the page's max-width so the /calendar iframe can use
    the whole viewport instead of being squeezed into the 980px column.
    """
    live_script = SSE_CLIENT_JS if live else ""
    stamp = datetime.now(CHICAGO).strftime("%H:%M:%S")
    body_style = "margin: 0; padding: 0.5em;" if wide else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>{PAGE_CSS}{'body { max-width: none !important; ' + body_style + ' }' if wide else ''}</style></head>
<body>
<header>
<h1>Galaxy Digital · live</h1>
<nav>
  <a href="/">Today</a>
  <a href="/calendar">Calendar</a>
  <a href="/users">Find volunteer</a>
  <a href="/offenders">Repeat no-shows</a>
  <a href="/digest">Digest</a>
</nav>
</header>
{body}
<p class="meta">{('Live: updated <span id="updated-at">' + stamp + '</span>' if live else 'generated ' + datetime.now(CHICAGO).strftime('%Y-%m-%d %H:%M %Z'))}</p>
{live_script}
</body></html>"""


def _row_for_signup(sg, shift_end_ts: str | None, conn=None) -> dict:
    """Resolve display row for one (signup + maybe-hour) pair.

    When `conn` is provided we route status resolution through
    sync.current_status_for_signup so manual overrides + cancellations
    are honored. Falling back to classification-only when no conn is
    handed in keeps the digest's offline rendering simple.
    """
    if conn is not None:
        import sync as sync_mod
        status = sync_mod.current_status_for_signup(
            conn, sg["response_id"], sg["user_id"], shift_end_ts,
        )
    else:
        status = sg["classification"]
        if not status:
            # response_status reflects cancellations even without a conn.
            if (sg["response_status"] if "response_status" in sg.keys() else None) \
                    and sg["response_status"] != "active":
                status = checkin.CANCELLED
            else:
                now_ct = datetime.now(CHICAGO).strftime("%Y-%m-%d %H:%M:%S")
                status = (checkin.NO_SHOW if shift_end_ts and shift_end_ts < now_ct
                          else checkin.SIGNED_UP)
    src = (sg["source"] or "") if "source" in sg.keys() else ""
    return {
        "user_id": sg["user_id"],
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
        people = [_row_for_signup(r, s["end_ts"], conn=conn) for r in sgs]
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
        # Filled count excludes cancellations -- those volunteers gave the
        # slot back. Without this, "14/9 filled" gets rendered for shifts
        # where 8 people have cancelled but Galaxy still has their rows.
        filled = sum(c.get(k, 0) for k in checkin.FILLED_STATUSES)
        parts.append(f'<div class="shift"><h3><a href="/shift/{s["id"]}">{title}</a></h3>')
        parts.append(f'<div class="meta">{agency} · {start}–{end} · '
                     f'{filled}/{s["slots"]} filled</div>')
        parts.append('<div class="bar">')
        for k in (checkin.CHECKED_IN, checkin.CHECKED_OUT, checkin.SIGNED_UP,
                  checkin.NO_SHOW, checkin.MANAGER_ENTERED, checkin.CANCELLED):
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
                elif p["status"] == checkin.CANCELLED:   tr_cls = " class='cancelled'"
                name_html = (f'<a href="/user/{p["user_id"]}">{p["name"]}</a>'
                             if p.get("user_id") else p["name"])
                parts.append(
                    f"<tr{tr_cls}><td>{p['emoji']}</td>"
                    f"<td>{name_html}</td><td>{p['email']}</td>"
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
        people = [_row_for_signup(r, s["end_ts"], conn=conn) for r in sgs]
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
    # Build {name -> (response_id, user_id)} so we can attach buttons +
    # link names through to the user-detail page. signups_for_shift
    # is already in DB-sort order.
    name_lookup = {f"{r['fname']} {r['lname']}".strip(): (r['response_id'], r['user_id'])
                   for r in sgs}
    for p in people:
        rid, uid = name_lookup.get(p['name'], ('', ''))
        name_html = (f'<a href="/user/{uid}">{p["name"]}</a>' if uid
                     else p['name'])
        parts.append(f"<tr><td>{p['emoji']}</td><td>{name_html}</td>"
                     f"<td>{p['email']}</td>"
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


_galaxy_api = None  # cached singleton for web action POSTs


def _get_galaxy_api():
    """Lazily instantiate (and login) a GalaxyAPI for the web process.

    The sync loop has its own client. We avoid sharing because:
      1. Both processes log in with the same creds -- two sessions are fine.
      2. The web process doesn't always need the API; only when an operator
         clicks an action button.
      3. Lazy import dodges the global-import side-effect of get_connected
         (which would otherwise fire on every uvicorn boot, even if no one
         ever clicks an action).
    """
    global _galaxy_api
    if _galaxy_api is None:
        import get_connected as gc  # local import; defers loguru side effects
        _galaxy_api = gc.GalaxyAPI()
    return _galaxy_api


def _push_to_galaxy(action: str, response_id: str, shift_meta: dict,
                    existing_galaxy_hour_id: str | None) -> tuple[str | None, bool, str | None]:
    """Best-effort: replicate the manual action to Galaxy Digital.

    Returns (galaxy_hour_id, ok, error_str). Failures are NEVER raised --
    the local override is the source of truth, so a Galaxy outage must
    not block the UI button.

    Only fires when WEB_CHECKIN_POSTS_TO_GALAXY=yes (default off).
    """
    if os.getenv("WEB_CHECKIN_POSTS_TO_GALAXY", "no").lower() not in ("yes", "1", "true"):
        return existing_galaxy_hour_id, False, None
    try:
        api = _get_galaxy_api()
    except Exception as e:
        return existing_galaxy_hour_id, False, f"login: {e}"

    now = datetime.now()
    duration_h = (shift_meta["duration_min"] or 0) / 60.0 or 1.0
    try:
        if action == "checkin":
            api.post_hours(response_id, hour_start=now,
                           hour_hours=duration_h, hour_status="pending")
            # Galaxy's 201 doesn't include the id; we fish it out via the
            # next GET. Best-effort -- a missing id is non-fatal.
            return None, True, None

        if action == "checkout":
            if not existing_galaxy_hour_id:
                # No previous Galaxy hour to update -- fall back to a fresh
                # POST representing the whole shift as completed.
                api.post_hours(response_id, hour_start=now,
                               hour_hours=duration_h, hour_status="entered")
                return None, True, None
            # Compute elapsed time from when we marked them in. If we don't
            # know, just record the full shift duration.
            api.update_hours(existing_galaxy_hour_id,
                             hour_hours=duration_h, hour_status="entered")
            return existing_galaxy_hour_id, True, None

        if action == "clear":
            if existing_galaxy_hour_id:
                api.delete_hours(existing_galaxy_hour_id)
            return None, True, None

    except Exception as e:
        return existing_galaxy_hour_id, False, str(e)[:240]
    return existing_galaxy_hour_id, False, "unknown action"


def _write_manual_status(response_id: str, action: str) -> str:
    """Apply a manual check-in/check-out/clear.

    Local-first: writes the override row, then best-effort POSTs to
    Galaxy Digital. The override row drives the UI / calendar /
    digest; the Galaxy write only affects reports inside their admin
    panel.

    Returns the resulting status string. Raises 404 for unknown rids.
    """
    db.init()
    with db.connect() as conn:
        sg = conn.execute(
            "SELECT sg.user_id, sg.shift_id, sg.need_id, s.duration_min "
            "FROM signups sg "
            "JOIN shifts s ON s.id = sg.shift_id "
            "WHERE sg.id = ?",
            (response_id,),
        ).fetchone()
        if not sg:
            raise HTTPException(404, f"unknown response_id {response_id!r}")

        prev_override = db.get_override(conn, response_id)
        prev_galaxy_id = prev_override["galaxy_hour_id"] if prev_override else None
        shift_meta = {"duration_min": sg["duration_min"]}

        if action == "clear":
            # Wipe both the local override AND any Galaxy hour we created.
            conn.execute("BEGIN")
            db.clear_override(conn, response_id)
            conn.execute(
                "DELETE FROM scan_state WHERE key = ?",
                (f"gcal_fp:{sg['shift_id']}",),
            )
            conn.execute("COMMIT")
            _push_to_galaxy("clear", response_id, shift_meta, prev_galaxy_id)
            return checkin.SIGNED_UP

        if action == "checkin":
            status = checkin.CHECKED_IN
        elif action == "checkout":
            status = checkin.CHECKED_OUT
        else:
            raise HTTPException(400, f"unknown action {action!r}")

        # 1. Local override (always succeeds).
        conn.execute("BEGIN")
        db.set_override(conn, response_id, status,
                        galaxy_hour_id=prev_galaxy_id,
                        galaxy_post_ok=False)
        db.record_status(conn, response_id=response_id,
                         shift_id=sg["shift_id"], user_id=sg["user_id"],
                         status=status)
        conn.execute(
            "DELETE FROM scan_state WHERE key = ?",
            (f"gcal_fp:{sg['shift_id']}",),
        )
        conn.execute("COMMIT")

        # 2. Best-effort Galaxy POST (no-op if WEB_CHECKIN_POSTS_TO_GALAXY=no).
        galaxy_id, ok, err = _push_to_galaxy(action, response_id, shift_meta, prev_galaxy_id)
        if ok or err:
            with db.connect() as conn:
                db.set_override(conn, response_id, status,
                                galaxy_hour_id=galaxy_id,
                                galaxy_post_ok=ok,
                                galaxy_last_err=err)
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
    elif current_status in (checkin.SIGNED_UP, checkin.NO_SHOW, checkin.CANCELLED):
        # CANCELLED gets the same buttons -- if a volunteer cancelled but
        # then showed up anyway, the operator can still mark them in. The
        # manual override beats the response_status='inactive' classification.
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


@app.get("/users", response_class=HTMLResponse)
def users_search(_: Annotated[HTTPBasicCredentials, Depends(_require_auth)],
                 q: str = ""):
    """Simple name/email search over local users.

    The result table links each row through to /user/{id}. No /users API
    call -- this is purely a lookup over what we've already synced. New
    volunteers show up after the next sync_responses cycle (max 2h).
    """
    q = (q or "").strip()
    parts = ['<h2>Find a volunteer</h2>']
    parts.append(
        '<form method="get" action="/users" style="margin-bottom:1em">'
        f'<input type="text" name="q" value="{q}" placeholder="name or email" '
        'autofocus style="padding:6px;width:60%"> '
        '<button type="submit">Search</button>'
        '</form>'
    )
    if not q:
        return HTMLResponse(_layout("Find volunteer", "\n".join(parts)))

    needle = f"%{q}%"
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT u.id, u.fname, u.lname, u.email,
                      (SELECT COUNT(*) FROM signups sg WHERE sg.user_id=u.id) AS n
               FROM users u
               WHERE u.fname LIKE ? OR u.lname LIKE ? OR u.email LIKE ?
                  OR (u.fname || ' ' || u.lname) LIKE ?
               ORDER BY u.lname, u.fname
               LIMIT 50
            """,
            (needle, needle, needle, needle),
        ).fetchall()
    if not rows:
        parts.append(f"<p class='empty'>No volunteers matching <b>{q}</b>.</p>")
    else:
        parts.append(f"<p class='meta'>{len(rows)} result(s)</p>")
        parts.append('<table><thead><tr><th>Volunteer</th><th>Email</th>'
                     '<th>Signups</th></tr></thead><tbody>')
        for r in rows:
            full = f"{(r['fname'] or '')} {(r['lname'] or '')}".strip() or r['email']
            parts.append(
                f"<tr><td><a href=\"/user/{r['id']}\">{full}</a></td>"
                f"<td>{r['email'] or ''}</td><td>{r['n']}</td></tr>"
            )
        parts.append('</tbody></table>')
    return HTMLResponse(_layout("Find volunteer", "\n".join(parts)))


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
            full = f"{(r['fname'] or '')} {(r['lname'] or '')}".strip()
            parts.append(
                f"<tr><td><a href=\"/user/{r['id']}\">{full}</a></td>"
                f"<td>{r['email'] or ''}</td><td>{r['no_shows']}</td></tr>"
            )
        parts.append('</tbody></table>')
    return HTMLResponse(_layout("Repeat no-shows", "\n".join(parts), live=False))


@app.get("/digest", response_class=HTMLResponse)
def view_digest(_: Annotated[HTTPBasicCredentials, Depends(_require_auth)], days: int = 1):
    data = digest_mod.collect(days_back=days)
    html = digest_mod.render_html(data)
    return HTMLResponse(_layout("Digest preview", html, live=False))


@app.get("/user/{user_id}", response_class=HTMLResponse)
def user_detail(user_id: str,
                _: Annotated[HTTPBasicCredentials, Depends(_require_auth)],
                refresh: int = 0):
    """Profile + history for one volunteer.

    Pulls all signups (past + future) joined with their resolved status,
    aggregates attendance stats, and shows contact info. If the user has
    no `last_enriched` timestamp (we never pulled their full /users record),
    fires a one-shot sync.enrich_user before rendering -- the page then
    cache hits forever until the operator clicks "Refresh from Galaxy".
    """
    db.init()
    # On-demand enrichment (lazy / explicit refresh).
    needs_enrich = False
    with db.connect() as conn:
        u = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not u:
            raise HTTPException(404, f"unknown user_id {user_id!r}")
        needs_enrich = refresh == 1 or not u["last_enriched"]
    if needs_enrich:
        try:
            import sync as sync_mod
            api = _get_galaxy_api()
            sync_mod.enrich_user(api, user_id)
        except Exception:
            # Non-fatal -- render with whatever we have.
            pass
        with db.connect() as conn:
            u = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    with db.connect() as conn:
        rows = conn.execute(
            """SELECT sg.id AS rid, s.id AS sid, s.start_ts, s.end_ts,
                      n.title, n.location, sg.response_status,
                      h.classification, h.source, h.date_start, h.date_end
               FROM signups sg
               JOIN shifts s ON s.id = sg.shift_id
               LEFT JOIN needs n ON n.id = sg.need_id
               LEFT JOIN hours h ON h.response_id = sg.id
               WHERE sg.user_id = ?
               ORDER BY s.start_ts DESC
            """,
            (user_id,),
        ).fetchall()
        # Resolve live status per row through current_status_for_signup so
        # manual overrides are reflected and past shifts get NO_SHOW stamped.
        import sync as sync_mod
        signups = []
        counts = {checkin.SIGNED_UP: 0, checkin.CHECKED_IN: 0,
                  checkin.CHECKED_OUT: 0, checkin.MANAGER_ENTERED: 0,
                  checkin.NO_SHOW: 0}
        for r in rows:
            status = sync_mod.current_status_for_signup(
                conn, r["rid"], user_id, r["end_ts"]
            )
            counts[status] = counts.get(status, 0) + 1
            signups.append({
                "rid": r["rid"], "sid": r["sid"],
                "start": r["start_ts"], "end": r["end_ts"],
                "title": r["title"] or "(no title)",
                "location": r["location"] or "",
                "status": status, "emoji": checkin.STATUS_EMOJI.get(status, "🔘"),
                "response_status": r["response_status"],
                "check_in": (r["date_start"] or "") if "/kiosk/storecheckin/" in (r["source"] or "").lower() else "",
                "check_out": (r["date_end"] or "") if "/kiosk/storecheckout/" in (r["source"] or "").lower() else "",
            })

    # Split into upcoming vs past for readability.
    now_ct = datetime.now(CHICAGO).strftime("%Y-%m-%d %H:%M:%S")
    upcoming = [s for s in signups if (s["start"] or "") >= now_ct]
    past = [s for s in signups if (s["start"] or "") < now_ct]
    total = sum(counts.values())
    attended = counts.get(checkin.CHECKED_OUT, 0) + counts.get(checkin.MANAGER_ENTERED, 0)
    attendance_pct = round(100 * attended / total) if total else 0

    name = f"{u['fname'] or ''} {u['lname'] or ''}".strip() or f"user {user_id}"
    parts = [f'<h2>{name}</h2>']
    parts.append('<div class="meta">')
    if u["email"]:
        parts.append(f'<a href="mailto:{u["email"]}">{u["email"]}</a> · ')
    if u["phone"]:
        parts.append(f'<a href="tel:{u["phone"]}">{u["phone"]}</a> · ')
    if u["address"]:
        addr_q = u["address"].replace(" ", "+")
        parts.append(f'<a target="_blank" href="https://maps.google.com/?q={addr_q}">'
                     f'{u["address"]}</a> · ')
    if u["user_status"]:
        parts.append(f'status: <b>{u["user_status"]}</b> · ')
    parts.append(f'user id {user_id}')
    if u["last_enriched"]:
        parts.append(f' · last enriched {u["last_enriched"][:16]}Z · '
                     f'<a href="/user/{user_id}?refresh=1">refresh from Galaxy</a>')
    else:
        parts.append(f' · <a href="/user/{user_id}?refresh=1">enrich from Galaxy</a>')
    parts.append('</div>')

    # Summary stats card
    parts.append('<div class="summary">')
    parts.append(f'<span>{total} signups · <b>{attendance_pct}%</b> attended</span>')
    for k in (checkin.CHECKED_OUT, checkin.MANAGER_ENTERED, checkin.CHECKED_IN,
              checkin.SIGNED_UP, checkin.NO_SHOW):
        n = counts.get(k, 0)
        if n:
            parts.append(f"<span>{checkin.STATUS_EMOJI[k]} {n} {k.replace('_',' ')}</span>")
    parts.append('</div>')

    def _table(label: str, rows_):
        if not rows_:
            return ""
        out = [f'<h3>{label} ({len(rows_)})</h3>']
        out.append('<table><thead><tr><th></th><th>When</th><th>Need</th>'
                   '<th>Status</th><th>In</th><th>Out</th></tr></thead><tbody>')
        for s in rows_:
            tr_cls = ""
            if s["status"] == checkin.NO_SHOW: tr_cls = " class='no-show'"
            elif s["status"] == checkin.CHECKED_IN: tr_cls = " class='checked-in'"
            elif s["status"] == checkin.CHECKED_OUT: tr_cls = " class='checked-out'"
            out.append(
                f"<tr{tr_cls}><td>{s['emoji']}</td>"
                f"<td>{(s['start'] or '')[:16]}</td>"
                f"<td><a href=\"/shift/{s['sid']}\">{s['title']}</a></td>"
                f"<td>{s['status']}</td>"
                f"<td>{(s['check_in'])[11:16] if s['check_in'] else ''}</td>"
                f"<td>{(s['check_out'])[11:16] if s['check_out'] else ''}</td></tr>"
            )
        out.append('</tbody></table>')
        return "\n".join(out)

    parts.append(_table("Upcoming", upcoming))
    parts.append(_table("Past", past))
    return HTMLResponse(_layout(name, "\n".join(parts), live=False))


@app.get("/calendar", response_class=HTMLResponse)
def view_calendar(_: Annotated[HTTPBasicCredentials, Depends(_require_auth)]):
    """Embed the Google Calendar so the same page can be the operator's
    single source of truth: live status above, calendar grid below.

    Reads CALENDAR_ID from env (falls back to GCAL_TEST_CALENDAR_ID for
    soak-testing setups). If the calendar is private, the iframe will
    show a "permission denied" message inside itself -- that's a
    Google-side concern, fix is to make the calendar public-readable
    OR share with the operator's google account.
    """
    import urllib.parse
    cal_id = (os.getenv("GCAL_TEST_CALENDAR_ID") or os.getenv("CALENDAR_ID") or "").strip()
    if not cal_id:
        body = ("<p class='empty'>No CALENDAR_ID configured in .env -- "
                "nothing to embed.</p>")
        return HTMLResponse(_layout("Calendar", body))
    # Google Calendar's public-embed URL. ctz= sets the displayed timezone.
    src = (
        "https://calendar.google.com/calendar/embed?"
        + urllib.parse.urlencode({
            "src": cal_id,
            "ctz": "America/Chicago",
            "mode": "WEEK",
            "showTitle": "0",
            "showPrint": "0",
            "showCalendars": "0",
            "showTz": "0",
        })
    )
    body = (
        f'<iframe src="{src}" '
        f'style="border:0;width:100%;height:calc(100vh - 130px);" '
        f'frameborder="0" scrolling="no"></iframe>'
        '<p class="meta" style="font-size:0.85em">'
        'If you see a blank or permission-denied frame: '
        "the calendar must be shared with you or made public for the embed "
        "to load. Open it in a new tab to confirm: "
        f'<a href="https://calendar.google.com" target="_blank">calendar.google.com</a>'
        '</p>'
    )
    return HTMLResponse(_layout("Calendar", body, wide=True))


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
                "people": [_row_for_signup(r, s["end_ts"], conn=conn) for r in sgs],
            })
    return JSONResponse(out)
