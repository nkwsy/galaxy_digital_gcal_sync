"""Ingest pipeline: Galaxy Digital API -> SQLite (db.py).

Two entry points:
  - sync_responses(api): paginated full refresh of /responses (cheap; once per
    REFRESH_INTERVAL_S in the main loop).
  - sync_hours(api, since): incremental scan of /hours updated since the given
    timestamp, then derive per-signup status and append to status_history.

A status snapshot is also taken on the SIGNED_UP / NO_SHOW path so the
repeat-offender table works without anyone ever check-in/check-outing.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

import pytz
from loguru import logger

import checkin
import db

CHICAGO = pytz.timezone("America/Chicago")
WATCH_WINDOW_H = 20  # how far around now to compute live statuses


def sync_responses(api) -> int:
    """Pull all /responses and upsert into the store.

    Returns the count of records ingested. We do a full sweep rather than
    cursor-since because new responses for upcoming shifts can appear at any
    historical position, and the volume is small enough (~8k rows total).
    """
    db.init()
    rows = api.get_data_from_api("responses") or []
    with db.connect() as conn:
        conn.execute("BEGIN")
        for r in rows:
            db.ingest_response(conn, r)
        db.set_state(conn, "last_responses_sync_at", datetime.utcnow().isoformat(timespec="seconds"))
        conn.execute("COMMIT")
    logger.info(f"sync_responses ingested {len(rows)} rows")
    return len(rows)


def sync_hours(api, since: datetime | None = None) -> int:
    """Pull /hours updated since `since` (default: 24h ago) and upsert.

    Also touches status_history for any (response_id) we see so the digest's
    repeat-offender section sees check-in/checkout activity even outside of
    the active watch window.
    """
    db.init()
    if since is None:
        since = datetime.now(CHICAGO) - timedelta(hours=24)
    since_str = since.astimezone(CHICAGO).strftime("%Y-%m-%d %H:%M")
    rows = api.get_data_from_api("hours", {"since_updated": since_str}) or []
    with db.connect() as conn:
        conn.execute("BEGIN")
        for h in rows:
            db.ingest_hour(conn, h)
            sig = checkin.HourSignal.from_api(h)
            cls = checkin.classify_hour(sig)
            if sig.response_id:
                # Look up the shift_id for status_history denormalization
                sid_row = conn.execute(
                    "SELECT shift_id FROM signups WHERE id = ?", (sig.response_id,)
                ).fetchone()
                db.record_status(
                    conn,
                    response_id=sig.response_id,
                    shift_id=sid_row["shift_id"] if sid_row else None,
                    user_id=sig.user_id,
                    status=cls,
                )
        db.set_state(conn, "last_hours_sync_at", datetime.utcnow().isoformat(timespec="seconds"))
        conn.execute("COMMIT")
    logger.info(f"sync_hours ingested {len(rows)} rows since {since_str}")
    return len(rows)


def mark_no_shows(conn) -> int:
    """Sweep for shifts whose end has passed and write NO_SHOW status_history
    entries for any signup that never produced an hours row.

    `observed_at` is set to the shift's actual end time (UTC-naive ISO) so
    repeat-offender windows over the last N days reflect actual behavior, not
    when the backfill happened to run.

    Idempotent: any (response_id) whose last history entry is already NO_SHOW
    is skipped.
    """
    now_ct = datetime.now(CHICAGO).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        """SELECT sg.id AS response_id, sg.shift_id, sg.user_id, s.end_ts
           FROM signups sg
           JOIN shifts s ON s.id = sg.shift_id
           LEFT JOIN hours h ON h.response_id = sg.id
           WHERE s.end_ts < ?
             AND h.id IS NULL
             AND (sg.response_status IS NULL OR sg.response_status = 'active')
        """,
        (now_ct,),
    ).fetchall()
    written = 0
    for r in rows:
        before = conn.execute(
            "SELECT status FROM status_history WHERE response_id = ? ORDER BY id DESC LIMIT 1",
            (r["response_id"],),
        ).fetchone()
        if before and before["status"] == checkin.NO_SHOW:
            continue
        # Translate the shift end (assumed America/Chicago) to an ISO timestamp
        # so date math elsewhere stays consistent. We keep it naive-UTC-ish to
        # match db.record_status's convention.
        try:
            local_end = CHICAGO.localize(datetime.strptime(r["end_ts"], "%Y-%m-%d %H:%M:%S"))
            observed_at = local_end.astimezone(pytz.UTC).replace(tzinfo=None).isoformat(timespec="seconds")
        except (ValueError, TypeError):
            observed_at = datetime.utcnow().isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO status_history(response_id,shift_id,user_id,status,observed_at) "
            "VALUES(?,?,?,?,?)",
            (r["response_id"], r["shift_id"], r["user_id"], checkin.NO_SHOW, observed_at),
        )
        written += 1
    return written


def current_status_for_signup(conn, response_id: str, user_id: str, shift_end: str | None) -> str:
    """Resolve the live status for one signup, with the no-show / signed-up
    distinction made from the shift end-time.
    """
    row = conn.execute(
        "SELECT classification FROM hours WHERE response_id = ? "
        "ORDER BY updated_at DESC LIMIT 1",
        (response_id,),
    ).fetchone()
    if row and row["classification"]:
        return row["classification"]
    # No hour row. signed_up vs no_show by clock.
    return checkin.status_for(response_id, user_id, shift_end, hour_index={})
