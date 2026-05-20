"""SQLite store for Galaxy Digital sync state.

Single source of truth for:
  - users / needs / shifts (descriptive data)
  - signups (one row per /responses record, keyed by response_id)
  - hours  (one row per /hours record, keyed by hour id, with derived
           `classification` from checkin.classify_hour)
  - status_history (append-only log of (response_id, status, observed_at)
                    so repeat-offender queries are cheap)
  - scan_state (key/value bookkeeping for cursors and last-run timestamps)

Why SQLite: the previous JSON file was a full rewrite each refresh; for the
digest, webpage, and offender tracking we need point-in-time queries, joins,
and per-shift aggregates -- all painful against a flat JSON list.

Designed to be the bottom layer with no upward dependencies: sync.py drives
ingest from the API, digest.py and web.py read views.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterable, Iterator

import pytz

import checkin

DB_PATH = os.getenv("GALAXY_DB_PATH", "galaxy_sync.sqlite3")
CHICAGO = pytz.timezone("America/Chicago")


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    fname         TEXT,
    lname         TEXT,
    email         TEXT,
    phone         TEXT,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS needs (
    id            TEXT PRIMARY KEY,
    title         TEXT,
    agency_name   TEXT,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS shifts (
    id            TEXT PRIMARY KEY,
    need_id       TEXT,
    start_ts      TEXT,
    end_ts        TEXT,
    duration_min  REAL,
    slots         INTEGER,
    FOREIGN KEY (need_id) REFERENCES needs(id)
);
CREATE INDEX IF NOT EXISTS idx_shifts_start ON shifts(start_ts);

CREATE TABLE IF NOT EXISTS signups (
    id              TEXT PRIMARY KEY,           -- response_id
    user_id         TEXT NOT NULL,
    shift_id        TEXT NOT NULL,
    need_id         TEXT,
    response_status TEXT,
    created_at      TEXT,
    updated_at      TEXT,
    FOREIGN KEY (user_id)  REFERENCES users(id),
    FOREIGN KEY (shift_id) REFERENCES shifts(id)
);
CREATE INDEX IF NOT EXISTS idx_signups_shift ON signups(shift_id);
CREATE INDEX IF NOT EXISTS idx_signups_user  ON signups(user_id);

CREATE TABLE IF NOT EXISTS hours (
    id              TEXT PRIMARY KEY,
    response_id     TEXT,
    user_id         TEXT,
    need_id         TEXT,
    source          TEXT,
    raw_status      TEXT,
    classification  TEXT,                       -- checked_in|checked_out|manager_entered
    date_start      TEXT,
    date_end        TEXT,
    created_at      TEXT,
    updated_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_hours_response ON hours(response_id);
CREATE INDEX IF NOT EXISTS idx_hours_user_day ON hours(user_id, date_start);

CREATE TABLE IF NOT EXISTS status_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    response_id   TEXT NOT NULL,
    shift_id      TEXT,
    user_id       TEXT,
    status        TEXT NOT NULL,
    observed_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_resp   ON status_history(response_id);
CREATE INDEX IF NOT EXISTS idx_history_user   ON status_history(user_id, status);

CREATE TABLE IF NOT EXISTS scan_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


@contextmanager
def connect(path: str = DB_PATH) -> Iterator[sqlite3.Connection]:
    """Yield a connection with foreign keys enabled and Row factory set.

    Caller is responsible for committing; the context manager closes the
    connection on exit.
    """
    conn = sqlite3.connect(path, isolation_level=None)  # autocommit; we use BEGIN explicitly
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    try:
        yield conn
    finally:
        conn.close()


def init(path: str = DB_PATH) -> None:
    """Create tables if they don't exist. Idempotent."""
    with connect(path) as conn:
        conn.executescript(SCHEMA)


# ---------- scan_state -----------------------------------------------------

def get_state(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM scan_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO scan_state(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


# ---------- ingest helpers -------------------------------------------------

def upsert_user(conn: sqlite3.Connection, u: dict) -> None:
    conn.execute(
        """INSERT INTO users(id,fname,lname,email,phone,updated_at)
           VALUES(:id,:fname,:lname,:email,:phone,:updated_at)
           ON CONFLICT(id) DO UPDATE SET
             fname=excluded.fname, lname=excluded.lname,
             email=excluded.email, phone=excluded.phone,
             updated_at=excluded.updated_at
        """,
        {
            "id": str(u["id"]),
            "fname": u.get("user_fname"),
            "lname": u.get("user_lname"),
            "email": u.get("user_email"),
            "phone": u.get("user_phone") or u.get("user_phone_cell"),
            "updated_at": u.get("updated_at"),
        },
    )


def upsert_need(conn: sqlite3.Connection, n: dict, agency_name: str | None = None) -> None:
    """Upsert a need. `agency_name` is taken explicitly because the /responses
    payload exposes the agency at the response level, while /needs exposes it
    nested under `agency`. Caller passes whichever it has; we never overwrite
    a non-null value with NULL.
    """
    if not n:
        return
    if not agency_name and isinstance(n.get("agency"), dict):
        agency_name = (n.get("agency") or {}).get("agency_name")
    conn.execute(
        """INSERT INTO needs(id,title,agency_name,updated_at)
           VALUES(:id,:title,:agency,:updated_at)
           ON CONFLICT(id) DO UPDATE SET
             title=excluded.title,
             agency_name=COALESCE(excluded.agency_name, needs.agency_name),
             updated_at=excluded.updated_at
        """,
        {
            "id": str(n["id"]),
            "title": n.get("need_title"),
            "agency": agency_name,
            "updated_at": n.get("updated_at"),
        },
    )


def upsert_shift(conn: sqlite3.Connection, s: dict, need_id: str | None) -> None:
    conn.execute(
        """INSERT INTO shifts(id,need_id,start_ts,end_ts,duration_min,slots)
           VALUES(:id,:need_id,:start,:end,:duration,:slots)
           ON CONFLICT(id) DO UPDATE SET
             need_id=excluded.need_id,
             start_ts=excluded.start_ts,
             end_ts=excluded.end_ts,
             duration_min=excluded.duration_min,
             slots=excluded.slots
        """,
        {
            "id": str(s["id"]),
            "need_id": str(need_id) if need_id else None,
            "start": s.get("start"),
            "end": s.get("end"),
            "duration": float(s["duration"]) if s.get("duration") else None,
            "slots": int(s["slots"]) if s.get("slots") else None,
        },
    )


def ingest_response(conn: sqlite3.Connection, r: dict) -> None:
    """One /responses record -> users + needs + shifts + signups upserts."""
    user = r.get("user") or {}
    need = r.get("need") or {}
    shift = r.get("shift") or {}
    if not (user and shift):
        return
    upsert_user(conn, user)
    agency_name = None
    agency = r.get("agency") or {}
    if isinstance(agency, dict):
        agency_name = agency.get("agency_name")
    upsert_need(conn, need, agency_name=agency_name)
    upsert_shift(conn, shift, need.get("id"))
    conn.execute(
        """INSERT INTO signups(id,user_id,shift_id,need_id,response_status,created_at,updated_at)
           VALUES(:id,:uid,:sid,:nid,:status,:created,:updated)
           ON CONFLICT(id) DO UPDATE SET
             user_id=excluded.user_id,
             shift_id=excluded.shift_id,
             need_id=excluded.need_id,
             response_status=excluded.response_status,
             updated_at=excluded.updated_at
        """,
        {
            "id": str(r["id"]),
            "uid": str(user["id"]),
            "sid": str(shift["id"]),
            "nid": str(need["id"]) if need else None,
            "status": r.get("response_status"),
            "created": r.get("created_at") or r.get("response_date_added"),
            "updated": r.get("updated_at") or r.get("response_date_updated"),
        },
    )


def ingest_hour(conn: sqlite3.Connection, h: dict) -> None:
    """One /hours record -> hours upsert + status_history append (if changed)."""
    user = h.get("user") or {}
    need = h.get("need") or {}
    if user:
        upsert_user(conn, user)
    if need:
        upsert_need(conn, need)

    sig = checkin.HourSignal.from_api(h)
    classification = checkin.classify_hour(sig)

    conn.execute(
        """INSERT INTO hours(id,response_id,user_id,need_id,source,raw_status,
                              classification,date_start,date_end,created_at,updated_at)
           VALUES(:id,:rid,:uid,:nid,:src,:rstat,:cls,:ds,:de,:c,:u)
           ON CONFLICT(id) DO UPDATE SET
             source=excluded.source,
             raw_status=excluded.raw_status,
             classification=excluded.classification,
             date_start=excluded.date_start,
             date_end=excluded.date_end,
             updated_at=excluded.updated_at
        """,
        {
            "id": str(h["id"]),
            "rid": sig.response_id,
            "uid": sig.user_id,
            "nid": str(need["id"]) if need else None,
            "src": sig.source,
            "rstat": sig.status,
            "cls": classification,
            "ds": sig.date_start,
            "de": sig.date_end,
            "c": h.get("created_at"),
            "u": h.get("updated_at"),
        },
    )


def record_status(conn: sqlite3.Connection, response_id: str, shift_id: str | None,
                  user_id: str | None, status: str) -> None:
    """Append to status_history if this status differs from the most recent one
    for the same response. Idempotent and cheap.
    """
    row = conn.execute(
        "SELECT status FROM status_history WHERE response_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (response_id,),
    ).fetchone()
    if row and row["status"] == status:
        return
    conn.execute(
        "INSERT INTO status_history(response_id,shift_id,user_id,status,observed_at) "
        "VALUES(?,?,?,?,?)",
        (response_id, shift_id, user_id, status, datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")),
    )


# ---------- query helpers --------------------------------------------------

def shifts_for_day(conn: sqlite3.Connection, day: datetime | None = None) -> list[sqlite3.Row]:
    """Shifts whose start falls on the given local day (default: today CT)."""
    day = (day or datetime.now(CHICAGO)).astimezone(CHICAGO)
    start = day.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    end = (day + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    return conn.execute(
        """SELECT s.*, n.title, n.agency_name
           FROM shifts s LEFT JOIN needs n ON n.id = s.need_id
           WHERE s.start_ts >= ? AND s.start_ts < ?
           ORDER BY s.start_ts
        """,
        (start, end),
    ).fetchall()


def signups_for_shift(conn: sqlite3.Connection, shift_id: str) -> list[sqlite3.Row]:
    """Return (signup x user x latest_hour) join for one shift."""
    return conn.execute(
        """SELECT
              sg.id            AS response_id,
              u.id             AS user_id,
              u.fname, u.lname, u.email,
              h.classification, h.source, h.date_start, h.date_end,
              h.updated_at     AS hour_updated_at
           FROM signups sg
           JOIN users u ON u.id = sg.user_id
           LEFT JOIN hours h ON h.response_id = sg.id
           WHERE sg.shift_id = ?
           ORDER BY u.lname, u.fname
        """,
        (shift_id,),
    ).fetchall()


def repeat_offenders(conn: sqlite3.Connection, days: int = 30, min_count: int = 2) -> list[sqlite3.Row]:
    """Top users by NO_SHOW count in the last N days."""
    cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)).isoformat(timespec="seconds")
    return conn.execute(
        """SELECT
              u.id, u.fname, u.lname, u.email,
              COUNT(*) AS no_shows
           FROM status_history h
           JOIN users u ON u.id = h.user_id
           WHERE h.status = ? AND h.observed_at >= ?
           GROUP BY u.id
           HAVING no_shows >= ?
           ORDER BY no_shows DESC, u.lname
        """,
        (checkin.NO_SHOW, cutoff, min_count),
    ).fetchall()
