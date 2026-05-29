"""Daily/weekly digest email of who signed up, who showed up, and who didn't.

Reads from SQLite (db.py). No Galaxy Digital API calls -- sync.py is
responsible for keeping the store fresh, the digest just renders.

Config via environment (all optional unless you actually want to send mail):
  DIGEST_EMAIL_TO       comma-separated recipients (required to actually send)
  DIGEST_EMAIL_FROM     default: same as SMTP_USER
  DIGEST_SUBJECT_PREFIX default: 'Galaxy Digital'
  DIGEST_LOOKBACK_DAYS  default: 1 (one-day digest = "today")
  DIGEST_REPEAT_WINDOW  days for repeat-offender section (default 30)
  DIGEST_REPEAT_MIN     min no-shows to appear in repeat list (default 2)
  SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / SMTP_TLS  (TLS default 'yes')

Render-only mode: digest.render_html() returns a string for the webpage to
embed or for `python -m digest --dry-run` to print.
"""
from __future__ import annotations

import argparse
import os
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Iterable

import pytz

import checkin
import db

CHICAGO = pytz.timezone("America/Chicago")


def _fmt_time(s: str | None) -> str:
    """'2026-05-20 13:00:00' -> '1:00 PM'. Returns '—' if unparseable."""
    if not s:
        return "—"
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").strftime("%-I:%M %p")
    except (ValueError, TypeError):
        return s


def _checkin_time_from_source(row) -> str:
    """The actual kiosk Checkin happens at hour.created_at when source is kiosk;
    fall back to date_start otherwise.
    """
    src = (row["source"] or "").lower() if "source" in row.keys() else ""
    if "/kiosk/storecheckin/" in src:
        return _fmt_time(row["date_start"])
    return _fmt_time(row["date_start"])


def _checkout_time(row) -> str | None:
    src = (row["source"] or "").lower() if "source" in row.keys() else ""
    if "/kiosk/storecheckout/" in src:
        # Kiosk-out time isn't broken out in the API; date_end is the best we have.
        return _fmt_time(row["date_end"])
    return None


def collect(days_back: int = 1, end: datetime | None = None) -> dict:
    """Gather data for the digest. Returns a render-ready dict.

    `end` is the inclusive last day; default is "now". When set, the
    window becomes [end - days_back .. end + 1 day) -- so you can
    re-render historical digests for any past week.
    """
    # Always normalize end_marker to end-of-its-day. Otherwise a digest
    # generated at, say, 8 AM excludes the rest of today's shifts -- which
    # is the wrong story for "today's report".
    if end is None:
        now = datetime.now(CHICAGO)
        end_marker = now.replace(hour=23, minute=59, second=59, microsecond=0)
    else:
        end_marker = end.replace(hour=23, minute=59, second=59, microsecond=0)
        now = end_marker
    start = (end_marker - timedelta(days=days_back)).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    end_ts = end_marker.strftime("%Y-%m-%d %H:%M:%S")
    start_ts = start.strftime("%Y-%m-%d %H:%M:%S")

    repeat_window = int(os.getenv("DIGEST_REPEAT_WINDOW", "30"))
    repeat_min = int(os.getenv("DIGEST_REPEAT_MIN", "2"))

    with db.connect() as conn:
        shifts = conn.execute(
            """SELECT s.id, s.start_ts, s.end_ts, s.slots,
                      n.title, n.agency_name
               FROM shifts s LEFT JOIN needs n ON n.id = s.need_id
               WHERE s.start_ts >= ? AND s.start_ts < ?
               ORDER BY s.start_ts
            """,
            (start_ts, end_ts),
        ).fetchall()

        out_shifts = []
        totals = {k: 0 for k in (checkin.SIGNED_UP, checkin.CHECKED_IN,
                                  checkin.CHECKED_OUT, checkin.MANAGER_ENTERED,
                                  checkin.NO_SHOW, checkin.CANCELLED)}
        # Resolve each signup's status through sync.current_status_for_signup
        # so CANCELLED, manual overrides, and time-based no_show are all
        # handled the same way the web UI uses them. Avoids subtle drift
        # between what the digest shows and what's on the live page.
        import sync as sync_mod
        for s in shifts:
            rows = db.signups_for_shift(conn, s["id"])
            people = []
            counts = {k: 0 for k in totals}
            for r in rows:
                status = sync_mod.current_status_for_signup(
                    conn, r["response_id"], r["user_id"], s["end_ts"],
                )
                counts[status] = counts.get(status, 0) + 1
                totals[status] = totals.get(status, 0) + 1
                people.append({
                    "user_id": r["user_id"],
                    "name": f"{r['fname'] or ''} {r['lname'] or ''}".strip(),
                    "email": r["email"] or "",
                    "status": status,
                    "emoji": checkin.STATUS_EMOJI.get(status, "🔘"),
                    "checkin_time": _checkin_time_from_source(r) if status in (checkin.CHECKED_IN, checkin.CHECKED_OUT, checkin.MANAGER_ENTERED) else None,
                    "checkout_time": _checkout_time(r) if status == checkin.CHECKED_OUT else None,
                })
            out_shifts.append({
                "id": s["id"],
                "title": s["title"] or "(no title)",
                "agency": s["agency_name"] or "",
                "start": _fmt_time(s["start_ts"]),
                "end": _fmt_time(s["end_ts"]),
                "date": (s["start_ts"] or "")[:10],
                "slots": s["slots"],
                "counts": counts,
                "people": people,
            })

        offenders = db.repeat_offenders(conn, days=repeat_window, min_count=repeat_min)

    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M %Z"),
        "lookback_days": days_back,
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date": now.strftime("%Y-%m-%d"),
        "totals": totals,
        "shifts": out_shifts,
        "repeat_window_days": repeat_window,
        "repeat_offenders": [
            {
                "user_id": r["id"],
                "name": f"{r['fname'] or ''} {r['lname'] or ''}".strip(),
                "email": r["email"] or "",
                "no_shows": r["no_shows"],
            }
            for r in offenders
        ],
    }


def _user_link(user_id: str | None, name: str, base_url: str) -> str:
    """Wrap a volunteer name in an absolute <a href> when WEB_PUBLIC_URL
    is configured, plain text otherwise. The digest goes to email clients
    that can't resolve a bare /user/{id} path, so we need the full URL.
    """
    if not user_id or not base_url:
        return name
    return f'<a href="{base_url.rstrip("/")}/user/{user_id}">{name}</a>'


CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       color: #222; max-width: 820px; margin: 1em auto; padding: 0 1em; }
h1, h2 { color: #2a4d69; }
.summary { background: #f4f6f9; padding: 0.75em 1em; border-radius: 6px;
           display: flex; gap: 1.4em; flex-wrap: wrap; }
.summary span { font-size: 0.95em; }
.shift { border: 1px solid #e2e4e8; border-radius: 6px; margin: 1em 0; padding: 0.8em 1em; }
.shift h3 { margin: 0 0 0.25em 0; }
.meta { color: #666; font-size: 0.9em; margin-bottom: 0.5em; }
table { width: 100%; border-collapse: collapse; font-size: 0.93em; }
th, td { padding: 4px 8px; text-align: left; border-bottom: 1px solid #eee; }
.no-show { background: #fff2f2; }
.offenders th, .offenders td { padding: 4px 12px; }
"""


def render_html(data: dict) -> str:
    t = data["totals"]
    # WEB_PUBLIC_URL is what the digest uses to link names back to the
    # live viewer. Without it (default), names render as plain text -- a
    # localhost link would 404 for whoever opens the email.
    base_url = (os.getenv("WEB_PUBLIC_URL") or "").strip().rstrip("/")
    parts = [f"<style>{CSS}</style>"]
    parts.append(f"<h1>Volunteer digest · {data['start_date']} → {data['end_date']}</h1>")
    parts.append(f"<p class='meta'>Generated {data['generated_at']}</p>")
    parts.append("<div class='summary'>")
    for k in (checkin.SIGNED_UP, checkin.CHECKED_IN, checkin.CHECKED_OUT,
              checkin.MANAGER_ENTERED, checkin.NO_SHOW, checkin.CANCELLED):
        parts.append(f"<span>{checkin.STATUS_EMOJI[k]} <b>{t.get(k,0)}</b> {k.replace('_',' ')}</span>")
    parts.append("</div>")

    if not data["shifts"]:
        parts.append("<p><em>No shifts in this window.</em></p>")
    for s in data["shifts"]:
        c = s["counts"]
        parts.append("<div class='shift'>")
        parts.append(f"<h3>{s['title']}</h3>")
        filled = sum(c.get(k, 0) for k in checkin.FILLED_STATUSES)
        parts.append(f"<div class='meta'>{s['agency']} · {s['date']} {s['start']}–{s['end']} · "
                     f"{filled}/{s['slots']} filled · "
                     f"{checkin.STATUS_EMOJI[checkin.CHECKED_IN]} {c.get(checkin.CHECKED_IN,0)} in · "
                     f"{checkin.STATUS_EMOJI[checkin.CHECKED_OUT]} {c.get(checkin.CHECKED_OUT,0)} done · "
                     f"{checkin.STATUS_EMOJI[checkin.NO_SHOW]} {c.get(checkin.NO_SHOW,0)} no-show · "
                     f"{checkin.STATUS_EMOJI[checkin.CANCELLED]} {c.get(checkin.CANCELLED,0)} cancelled</div>")
        if s["people"]:
            parts.append("<table><thead><tr><th></th><th>Volunteer</th><th>Email</th>"
                         "<th>In</th><th>Out</th></tr></thead><tbody>")
            for p in s["people"]:
                cls = " class='no-show'" if p["status"] == checkin.NO_SHOW else ""
                name_html = _user_link(p.get("user_id"), p["name"], base_url)
                parts.append(f"<tr{cls}><td>{p['emoji']}</td><td>{name_html}</td>"
                             f"<td>{p['email']}</td>"
                             f"<td>{p['checkin_time'] or ''}</td>"
                             f"<td>{p['checkout_time'] or ''}</td></tr>")
            parts.append("</tbody></table>")
        parts.append("</div>")

    parts.append(f"<h2>Repeat no-shows · last {data['repeat_window_days']} days</h2>")
    if data["repeat_offenders"]:
        parts.append("<table class='offenders'><thead><tr><th>Volunteer</th><th>Email</th>"
                     "<th>No-shows</th></tr></thead><tbody>")
        for o in data["repeat_offenders"]:
            name_html = _user_link(o.get("user_id"), o["name"], base_url)
            parts.append(f"<tr><td>{name_html}</td><td>{o['email']}</td><td>{o['no_shows']}</td></tr>")
        parts.append("</tbody></table>")
    else:
        parts.append("<p><em>None.</em></p>")
    return "\n".join(parts)


def render_text(data: dict) -> str:
    """Plain-text fallback for the multipart email."""
    out = [f"Volunteer digest · {data['start_date']} → {data['end_date']}",
           f"Generated {data['generated_at']}", ""]
    t = data["totals"]
    out.append(f"Totals: signed_up={t.get(checkin.SIGNED_UP,0)} "
               f"checked_in={t.get(checkin.CHECKED_IN,0)} "
               f"checked_out={t.get(checkin.CHECKED_OUT,0)} "
               f"manager={t.get(checkin.MANAGER_ENTERED,0)} "
               f"no_show={t.get(checkin.NO_SHOW,0)}")
    out.append("")
    for s in data["shifts"]:
        out.append(f"## {s['title']}  ({s['agency']})")
        out.append(f"   {s['date']} {s['start']}–{s['end']}  ({sum(s['counts'].values())}/{s['slots']})")
        for p in s["people"]:
            extra = []
            if p["checkin_time"]:  extra.append(f"in {p['checkin_time']}")
            if p["checkout_time"]: extra.append(f"out {p['checkout_time']}")
            extra_s = f"  [{', '.join(extra)}]" if extra else ""
            out.append(f"   {p['emoji']} {p['name']:25s} {p['status']:18s} {p['email']}{extra_s}")
        out.append("")
    out.append(f"Repeat no-shows (last {data['repeat_window_days']}d):")
    for o in data["repeat_offenders"]:
        out.append(f"  {o['no_shows']}x  {o['name']:25s} {o['email']}")
    return "\n".join(out)


def send(data: dict, html: str, text: str) -> bool:
    """Send the digest. Returns True on success, False on configuration miss."""
    to = os.getenv("DIGEST_EMAIL_TO", "").strip()
    if not to:
        return False
    host = os.getenv("SMTP_HOST", "").strip()
    if not host:
        return False
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASS", "")
    use_tls = os.getenv("SMTP_TLS", "yes").lower() != "no"
    sender = os.getenv("DIGEST_EMAIL_FROM", user or to)
    prefix = os.getenv("DIGEST_SUBJECT_PREFIX", "Galaxy Digital")

    msg = EmailMessage()
    msg["Subject"] = f"{prefix}: digest {data['start_date']} → {data['end_date']}"
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    if use_tls:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls(context=ssl.create_default_context())
            if user:
                s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context()) as s:
            if user:
                s.login(user, password)
            s.send_message(msg)
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=int(os.getenv("DIGEST_LOOKBACK_DAYS", "1")))
    p.add_argument("--dry-run", action="store_true", help="render to stdout, don't email")
    p.add_argument("--format", choices=("html", "text"), default="text")
    args = p.parse_args()

    data = collect(days_back=args.days)
    html = render_html(data)
    text = render_text(data)
    if args.dry_run or not os.getenv("DIGEST_EMAIL_TO"):
        print(text if args.format == "text" else html)
        return
    ok = send(data, html, text)
    print("sent" if ok else "skipped (no DIGEST_EMAIL_TO or SMTP_HOST)")


if __name__ == "__main__":
    main()
