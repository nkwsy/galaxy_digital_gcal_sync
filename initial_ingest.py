"""One-shot initial ingest -- run once after `./bootstrap.sh` to populate
SQLite before launching the web viewer.

Stubs the gcal module so this doesn't trigger a Google OAuth flow; only
the SQLite store is touched. Safe to re-run; ingest is idempotent.
"""
from __future__ import annotations

import sys
import types

from dotenv import load_dotenv

load_dotenv()

# Block gcal's import-time OAuth side effect; we don't need calendar here.
_fake = types.ModuleType("gcal")
_fake.service = None
_fake.get_calendars = lambda s: []
_fake.update_calendar_events = lambda *a, **k: None
sys.modules["gcal"] = _fake

from loguru import logger

import db
import get_connected as gc
import sync


def main() -> None:
    api = gc.GalaxyAPI()
    db.init()
    logger.info("ingesting /responses ...")
    n_r = sync.sync_responses(api)
    print(f"  {n_r} responses")
    logger.info("ingesting /hours ...")
    n_h = sync.sync_hours(api)
    print(f"  {n_h} hours")
    logger.info("marking historical no-shows ...")
    with db.connect() as conn:
        conn.execute("BEGIN")
        n_ns = sync.mark_no_shows(conn)
        conn.execute("COMMIT")
    print(f"  {n_ns} no-show history rows backfilled")
    print("done. now run: python run_web.py")


if __name__ == "__main__":
    main()
