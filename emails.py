"""Email templates, variable substitution, and SMTP delivery.

This module is the single source of truth for transactional sends:
  - The web "Send email" button calls send_template(template_id, response_id)
  - The auto-trigger scanner in auto_emails.py iterates active templates
    with auto_trigger != NULL and calls the same send_template for each
    qualifying signup.
  - The digest still uses digest.py's own send() helper because its body
    is fully assembled in code; templates are operator-editable.

Variables supported in {{double_braces}}:
  volunteer_first    Ann
  volunteer_last     Alpha
  volunteer_name     Ann Alpha
  volunteer_email    ann@example.com
  shift_title        Kayak River Clean Up - Wild Mile
  shift_date         2026-05-20
  shift_start        2:00 PM
  shift_end          4:00 PM
  shift_when         Wed May 20 · 2:00 PM
  shift_location     905 W Eastman St, Chicago, IL
  agency_name        River Ranger Volunteer Program
  status             no_show, checked_in, checked_out, signed_up, cancelled
  user_page_url      <WEB_PUBLIC_URL>/user/<id>  (blank if no public URL)
  org_name           env WEB_ORG_NAME (default "Urban Rivers")

Unknown variables stay literal -- safer than KeyErroring mid-send.
"""
from __future__ import annotations

import os
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from html import unescape
from typing import Iterable

import pytz

import checkin
import db

CHICAGO = pytz.timezone("America/Chicago")

# Triggers the auto-scanner knows how to evaluate. Adding a new one means
# extending auto_emails.qualifying_signups; keep these in sync.
AUTO_TRIGGERS = (
    ("", "Manual only"),
    ("no_show_24h",          "24h after a no-show"),
    ("no_show_2h",           "2h after a no-show"),
    ("reminder_24h_before",  "24h before shift start (signed_up)"),
    ("thanks_after_checkout","After checkout"),
)


_VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _fmt_time(s: str | None) -> str:
    if not s:
        return ""
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").strftime("%-I:%M %p")
    except (ValueError, TypeError):
        return s


def _fmt_when(start_ts: str | None) -> str:
    if not start_ts:
        return ""
    try:
        d = datetime.strptime(start_ts, "%Y-%m-%d %H:%M:%S")
        return d.strftime("%a %b %-d · %-I:%M %p")
    except (ValueError, TypeError):
        return start_ts


def build_context(conn, response_id: str) -> dict | None:
    """Pull everything a template might reference for one signup.

    Returns None if the response_id is unknown (caller treats as a soft
    skip -- we don't want a stale id to break a bulk auto-send).
    """
    row = conn.execute(
        """SELECT sg.id AS rid, sg.response_status,
                  u.id AS user_id, u.fname, u.lname, u.email,
                  s.id AS shift_id, s.start_ts, s.end_ts,
                  n.title, n.agency_name, n.location,
                  h.classification
           FROM signups sg
           JOIN users u ON u.id = sg.user_id
           JOIN shifts s ON s.id = sg.shift_id
           LEFT JOIN needs n ON n.id = sg.need_id
           LEFT JOIN hours h ON h.response_id = sg.id
           WHERE sg.id = ?
           LIMIT 1
        """,
        (response_id,),
    ).fetchone()
    if not row:
        return None
    import sync as sync_mod
    status = sync_mod.current_status_for_signup(conn, response_id, row["user_id"], row["end_ts"])

    base_url = (os.getenv("WEB_PUBLIC_URL") or "").strip().rstrip("/")
    user_url = f"{base_url}/user/{row['user_id']}" if base_url else ""
    return {
        "volunteer_first": row["fname"] or "",
        "volunteer_last":  row["lname"] or "",
        "volunteer_name":  f"{row['fname'] or ''} {row['lname'] or ''}".strip(),
        "volunteer_email": row["email"] or "",
        "shift_title":     row["title"] or "",
        "shift_date":      (row["start_ts"] or "")[:10],
        "shift_start":     _fmt_time(row["start_ts"]),
        "shift_end":       _fmt_time(row["end_ts"]),
        "shift_when":      _fmt_when(row["start_ts"]),
        "shift_location":  row["location"] or "",
        "agency_name":     row["agency_name"] or "",
        "status":          status,
        "user_page_url":   user_url,
        "org_name":        os.getenv("WEB_ORG_NAME", "the volunteer team"),
    }


def render(text: str, ctx: dict) -> str:
    """Substitute {{var}} placeholders. Unknown vars stay literal."""
    def _sub(m: re.Match) -> str:
        key = m.group(1)
        return str(ctx.get(key, m.group(0)))
    return _VAR_RE.sub(_sub, text)


def html_to_text(html: str) -> str:
    """Cheap HTML-to-plaintext fallback for the multipart message. Good
    enough for short transactional emails -- preserves line breaks and
    strips tags. For richer needs we can swap in html2text later.
    """
    s = re.sub(r"<\s*br\s*/?>", "\n", html, flags=re.I)
    s = re.sub(r"</\s*(p|div|h\d|li)\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = unescape(s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


# ---------- template CRUD --------------------------------------------------

def list_templates(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT id, name, subject, body, auto_trigger, is_active, "
        "       created_at, updated_at FROM email_templates "
        "ORDER BY is_active DESC, name"
    ).fetchall()]


def get_template(conn, tid: int) -> dict | None:
    r = conn.execute(
        "SELECT id, name, subject, body, auto_trigger, is_active "
        "FROM email_templates WHERE id = ?", (tid,)
    ).fetchone()
    return dict(r) if r else None


def save_template(conn, *, name: str, subject: str, body: str,
                  auto_trigger: str | None = None,
                  is_active: int = 1, tid: int | None = None) -> int:
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    if tid:
        conn.execute(
            """UPDATE email_templates
               SET name=?, subject=?, body=?, auto_trigger=?, is_active=?, updated_at=?
               WHERE id=?""",
            (name, subject, body, auto_trigger or None, is_active, now, tid),
        )
        return tid
    cur = conn.execute(
        """INSERT INTO email_templates(name,subject,body,auto_trigger,is_active,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?)""",
        (name, subject, body, auto_trigger or None, is_active, now, now),
    )
    return cur.lastrowid


def delete_template(conn, tid: int) -> None:
    conn.execute("DELETE FROM email_templates WHERE id = ?", (tid,))


# ---------- send -----------------------------------------------------------

def _smtp_send(to_email: str, subject: str, html: str) -> None:
    """Raw SMTP. Honors the existing SMTP_* env vars so digest + manual
    sends + auto sends all use the same config. Google Workspace setup:
        SMTP_HOST=smtp.gmail.com
        SMTP_PORT=587
        SMTP_USER=you@yourdomain.com
        SMTP_PASS=<App password from Google account>
        SMTP_TLS=yes
    """
    host = os.getenv("SMTP_HOST", "").strip()
    if not host:
        raise RuntimeError("SMTP_HOST not configured")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASS", "")
    use_tls = os.getenv("SMTP_TLS", "yes").lower() != "no"
    sender = os.getenv("EMAIL_FROM", user)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email
    msg.set_content(html_to_text(html))
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


def send_template(conn, template_id: int, response_id: str,
                  triggered_by: str = "manual") -> dict:
    """Render the template for the given signup and SMTP it. Logs the
    outcome to email_sends regardless of success so the UI can show
    "last sent X" and the auto-trigger scanner can dedup.

    Returns a dict {ok, error, to, subject}.
    """
    tmpl = get_template(conn, template_id)
    if not tmpl:
        return {"ok": False, "error": "template not found", "to": "", "subject": ""}
    ctx = build_context(conn, response_id)
    if not ctx:
        return {"ok": False, "error": "response_id not found", "to": "", "subject": ""}
    to_email = ctx["volunteer_email"]
    subject_rendered = render(tmpl["subject"], ctx)
    body_rendered = render(tmpl["body"], ctx)

    ok, err = True, None
    if not to_email:
        ok, err = False, "no email on file for volunteer"
    elif os.getenv("EMAIL_DRY_RUN", "").lower() in ("yes", "1", "true"):
        # Operator sanity flag -- render and log without actually
        # contacting the SMTP server. Useful for first-deploy verification.
        ok, err = True, "DRY_RUN"
    else:
        try:
            _smtp_send(to_email, subject_rendered, body_rendered)
        except Exception as e:
            ok, err = False, str(e)[:240]

    conn.execute(
        """INSERT INTO email_sends(template_id,response_id,user_id,to_email,
                                    subject,sent_at,success,error,triggered_by)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            template_id, response_id,
            (conn.execute("SELECT user_id FROM signups WHERE id=?",
                          (response_id,)).fetchone() or {})["user_id"]
                if conn.execute("SELECT 1 FROM signups WHERE id=?",
                                (response_id,)).fetchone() else None,
            to_email, subject_rendered,
            datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"),
            1 if ok else 0, err, triggered_by,
        ),
    )
    return {"ok": ok, "error": err, "to": to_email, "subject": subject_rendered}


def already_sent(conn, template_id: int, response_id: str) -> bool:
    """Has (template, response) ever produced a successful send?

    Used by the auto-scanner to avoid double-firing if it runs multiple
    times in a window when the volunteer's status hasn't changed.
    """
    row = conn.execute(
        "SELECT 1 FROM email_sends WHERE template_id=? AND response_id=? AND success=1 LIMIT 1",
        (template_id, response_id),
    ).fetchone()
    return row is not None


# ---------- starter templates ----------------------------------------------

STARTER_TEMPLATES = (
    {
        "name": "No-show follow-up",
        "auto_trigger": "no_show_24h",
        "subject": "We missed you at {{shift_title}}",
        "body": (
            "<p>Hi {{volunteer_first}},</p>"
            "<p>We didn't see you at <b>{{shift_title}}</b> on "
            "{{shift_when}}. We hope everything is alright! If something "
            "came up, please let us know -- and feel free to grab another "
            "spot whenever you're free.</p>"
            "<p>Thanks,<br>{{org_name}}</p>"
        ),
    },
    {
        "name": "Shift reminder (24h)",
        "auto_trigger": "reminder_24h_before",
        "subject": "Tomorrow: {{shift_title}}",
        "body": (
            "<p>Hi {{volunteer_first}},</p>"
            "<p>This is a friendly reminder that you're signed up for "
            "<b>{{shift_title}}</b> tomorrow, {{shift_when}}"
            "{{shift_location}}.</p>"
            "<p>See you there!<br>{{org_name}}</p>"
        ),
    },
    {
        "name": "Thanks for showing up",
        "auto_trigger": "thanks_after_checkout",
        "subject": "Thanks for joining us at {{shift_title}}",
        "body": (
            "<p>Hi {{volunteer_first}},</p>"
            "<p>Thank you for coming out to <b>{{shift_title}}</b> "
            "earlier today -- we couldn't do this without you.</p>"
            "<p>Hope to see you at another shift soon.<br>{{org_name}}</p>"
        ),
    },
)


def seed_starter_templates(conn) -> int:
    """Idempotently insert the three starter templates if none exist."""
    n = conn.execute("SELECT COUNT(*) AS n FROM email_templates").fetchone()["n"]
    if n > 0:
        return 0
    for t in STARTER_TEMPLATES:
        save_template(conn, name=t["name"], subject=t["subject"], body=t["body"],
                      auto_trigger=t["auto_trigger"], is_active=1)
    return len(STARTER_TEMPLATES)
