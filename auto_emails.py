"""Background scan that fires email templates on configured triggers.

Called from run_cal_update.py once per main-loop tick. For each template
where auto_trigger is set and is_active=1:

  1. Find signups that match the trigger's condition + time window.
  2. Filter out (template_id, response_id) pairs we've already sent to
     (using emails.already_sent).
  3. Fire them off; the send log dedupes future runs automatically.

This module never raises -- a misconfigured SMTP or bad template
shouldn't crash the sync loop. Failures land in email_sends.error.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytz
from loguru import logger

import checkin
import db
import emails

CHICAGO = pytz.timezone("America/Chicago")


def qualifying_signups(conn, trigger: str) -> list[str]:
    """Return response_ids that should receive a template with the given
    auto_trigger right now. Window logic is per-trigger.
    """
    now_ct = datetime.now(CHICAGO).strftime("%Y-%m-%d %H:%M:%S")

    if trigger == "no_show_24h":
        # Shift ended >= 24h ago AND <= 7d ago. No hour row. Not cancelled.
        end_window_start = (datetime.now(CHICAGO) - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        end_window_end   = (datetime.now(CHICAGO) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        rows = conn.execute(
            """SELECT sg.id FROM signups sg
               JOIN shifts s ON s.id = sg.shift_id
               LEFT JOIN hours h ON h.response_id = sg.id
               WHERE s.end_ts BETWEEN ? AND ?
                 AND h.id IS NULL
                 AND (sg.response_status IS NULL OR sg.response_status='active')
            """,
            (end_window_start, end_window_end),
        ).fetchall()
        return [r["id"] for r in rows]

    if trigger == "no_show_2h":
        end_window_start = (datetime.now(CHICAGO) - timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
        end_window_end   = (datetime.now(CHICAGO) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        rows = conn.execute(
            """SELECT sg.id FROM signups sg
               JOIN shifts s ON s.id = sg.shift_id
               LEFT JOIN hours h ON h.response_id = sg.id
               WHERE s.end_ts BETWEEN ? AND ?
                 AND h.id IS NULL
                 AND (sg.response_status IS NULL OR sg.response_status='active')
            """,
            (end_window_start, end_window_end),
        ).fetchall()
        return [r["id"] for r in rows]

    if trigger == "reminder_24h_before":
        # Shift starts ~22-26h from now. Volunteer is still signed_up
        # (no hour row yet, not cancelled).
        start_window_start = (datetime.now(CHICAGO) + timedelta(hours=22)).strftime("%Y-%m-%d %H:%M:%S")
        start_window_end   = (datetime.now(CHICAGO) + timedelta(hours=26)).strftime("%Y-%m-%d %H:%M:%S")
        rows = conn.execute(
            """SELECT sg.id FROM signups sg
               JOIN shifts s ON s.id = sg.shift_id
               LEFT JOIN hours h ON h.response_id = sg.id
               WHERE s.start_ts BETWEEN ? AND ?
                 AND h.id IS NULL
                 AND (sg.response_status IS NULL OR sg.response_status='active')
            """,
            (start_window_start, start_window_end),
        ).fetchall()
        return [r["id"] for r in rows]

    if trigger == "thanks_after_checkout":
        # Shift ended within last 6h AND classification = checked_out.
        end_window_start = (datetime.now(CHICAGO) - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
        rows = conn.execute(
            """SELECT sg.id FROM signups sg
               JOIN shifts s ON s.id = sg.shift_id
               LEFT JOIN hours h ON h.response_id = sg.id
               WHERE s.end_ts BETWEEN ? AND ?
                 AND h.classification = ?
            """,
            (end_window_start, now_ct, checkin.CHECKED_OUT),
        ).fetchall()
        return [r["id"] for r in rows]

    return []


def process(conn) -> dict:
    """Walk every active template with an auto_trigger, fire qualifying
    signups, return a summary dict for logging.
    """
    tmpls = conn.execute(
        "SELECT id, name, auto_trigger FROM email_templates "
        "WHERE is_active=1 AND auto_trigger IS NOT NULL AND auto_trigger != ''"
    ).fetchall()
    summary = {"templates_evaluated": len(tmpls), "sent": 0, "skipped": 0, "errors": 0}
    for t in tmpls:
        rids = qualifying_signups(conn, t["auto_trigger"])
        for rid in rids:
            if emails.already_sent(conn, t["id"], rid):
                summary["skipped"] += 1
                continue
            r = emails.send_template(conn, t["id"], rid,
                                     triggered_by=f"auto:{t['auto_trigger']}")
            if r["ok"]:
                summary["sent"] += 1
            else:
                summary["errors"] += 1
                logger.warning(f"auto-send {t['name']!r}->{rid} failed: {r['error']}")
    return summary
