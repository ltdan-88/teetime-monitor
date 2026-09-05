"""SQLite-backed persistence for scraped tee sheets and confirmed bookings.

Not just a cache — this is the only record of the past that will ever exist, since pc
caddie itself hides past tee sheets and there's no way to look them up again later.
Deliberately SQLite from the start rather than a flat JSON cache (contrast with the
original docs/spec-v1.md) — Phase 5 analytics needs history to accumulate across
scrapes, and every scrape is logged as its own row rather than overwritten, so "today's
schedule" is just the latest scrape per slot and the full table is what analytics later
reads from.

Two tables:
- `scrapes` — what the tee sheet looked like, logged every time it's scraped.
- `confirmed_bookings` — what *you* actually played (see ConfirmedBooking in
  models.py). Revised 2026-09-05: populated automatically each scrape from pc caddie's
  own "My Reservations" page (scraper.scrape_my_reservations), not primarily by hand —
  the TUI's `c` keybinding remains as a fallback for the same-day-booking timing gap
  described in ROADMAP.md Phase 1, not the main path. Kept as its own table because it
  answers a different question than scraped player-name matching can reliably answer on
  its own (most players show as anonymized "Member (H.H)", not by name).

NOT YET IMPLEMENTED — schema and functions sketched below per ROADMAP.md Phase 1.
"""

import sqlite3
from pathlib import Path

from .models import ConfirmedBooking, Schedule

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

CREATE TABLE IF NOT EXISTS confirmed_bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course TEXT NOT NULL,
    date TEXT NOT NULL,        -- YYYY-MM-DD
    time TEXT,                 -- HH:MM, or NULL for "confirmed not playing"
    holes INTEGER,             -- 9 or 18, if noted
    source TEXT NOT NULL,      -- "my_reservations" (automatic) or "manual" (TUI `c`)
    confirmed_at TEXT NOT NULL -- ISO 8601 timestamp
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


def save_confirmed_booking(booking: ConfirmedBooking, path: Path = DEFAULT_DB_PATH) -> None:
    """Record a confirmed booking (or a confirmed "not playing"). Never overwrite."""
    raise NotImplementedError("storage.py is a stub — see ROADMAP.md Phase 1")


def load_confirmed_booking(course: str, date: str, path: Path = DEFAULT_DB_PATH) -> ConfirmedBooking | None:
    """Return the confirmed booking for a course/date, or None if never confirmed."""
    raise NotImplementedError("storage.py is a stub — see ROADMAP.md Phase 1")
