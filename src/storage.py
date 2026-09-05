"""SQLite-backed persistence for scraped tee sheets.

Deliberately SQLite from the start rather than a flat JSON cache (contrast with the
original docs/spec-v1.md) — Phase 5 analytics needs history to accumulate across scrapes,
and every scrape is logged as its own row rather than overwritten, so "today's schedule"
is just the latest scrape per slot and the full table is what analytics later reads from.

NOT YET IMPLEMENTED — schema and functions sketched below per ROADMAP.md Phase 1.
"""

import sqlite3
from pathlib import Path

from .models import Schedule

DEFAULT_DB_PATH = Path("teetime.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS scrapes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course TEXT NOT NULL,
    date TEXT NOT NULL,        -- YYYY-MM-DD
    time TEXT NOT NULL,        -- HH:MM
    booked INTEGER NOT NULL,
    capacity INTEGER NOT NULL,
    players TEXT NOT NULL,     -- JSON-encoded list[str]
    scraped_at TEXT NOT NULL   -- ISO 8601 timestamp
);
"""


def init_db(path: Path = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(SCHEMA)


def save_schedule(schedule: Schedule, path: Path = DEFAULT_DB_PATH) -> None:
    """Append one scrape's slots as new rows (never overwrite — history matters)."""
    raise NotImplementedError("storage.py is a stub — see ROADMAP.md Phase 1")


def load_latest_schedule(course: str, date: str, path: Path = DEFAULT_DB_PATH) -> Schedule | None:
    """Return the most recent scrape's slots for a course/date, or None if never scraped."""
    raise NotImplementedError("storage.py is a stub — see ROADMAP.md Phase 1")
