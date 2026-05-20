"""Shared pytest fixtures.

Putting these here means individual test files can ask for `db_conn` or
`tmp_db_path` without each one re-wiring the same scaffolding.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make the project root importable so `import db`, `import checkin` etc. work
# when pytest is invoked from any directory.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def tmp_db_path(tmp_path, monkeypatch):
    """Point db.py at a per-test sqlite file."""
    p = tmp_path / "test.sqlite3"
    monkeypatch.setenv("GALAXY_DB_PATH", str(p))
    # db.py reads DB_PATH at import time; force a reload so the new env var
    # is honored.
    import importlib
    import db
    importlib.reload(db)
    return str(p)


@pytest.fixture
def db_conn(tmp_db_path):
    """Yield an initialized connection to a fresh per-test DB."""
    import db
    db.init()
    with db.connect() as conn:
        yield conn
