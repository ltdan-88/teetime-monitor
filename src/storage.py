"""SQLite-backed persistence for scraped tee sheets and confirmed bookings.

Not just a cache — this is the only record of the past that will ever exist, since pc
caddie itself hides past tee sheets and there's no way to look them up again later.
Deliberately SQLite from the start rather than a flat JSON cache (contrast with the
original docs/spec-v1.md) — Phase 5 analytics needs history to accumulate across
scrapes, and every scrape is logged as its own row rather than overwritten, so "today's
schedule" is just the latest scrape per slot and the full table is what analytics later
reads from.

One database file per club, not a `club_id` column — `path` already does the per-club
separation (e.g. `data/<club_slug>.db`, one per `clubs/*.yaml`), matching how
club_config.py already treats each club as its own file. Keeps every function's
signature here identical to what a single-club tool would need.

Four tables:
- `scrapes` — one row per scrape *event* (course/date/timestamp) — a batch header.
- `slots` and `weather_points` — the actual per-time-slot data for one scrape, each row
  pointing back at its `scrapes.id`. Split out (rather than one wide flat table) because
  weather is a separate axis from occupancy — a slot can be re-scraped for occupancy
  independent of a weather refresh, and booking_watch.py needs to diff *just* the
  weather side between two scrapes without caring about player names.
- `confirmed_bookings` — what *you* actually played (see ConfirmedBooking in
  models.py). Revised 2026-09-05: populated automatically each scrape from pc caddie's
  own "My Reservations" page (scraper.scrape_my_reservations), not primarily by hand —
  the TUI's `c` keybinding remains as a fallback for the same-day-booking timing gap
  described in ROADMAP.md Phase 1, not the main path. Kept as its own table because it
  answers a different question than scraped player-name matching can reliably answer on
  its own (most players show as anonymized "Member (H.H)", not by name).
- `booking_changes` — added 2026-09-06 alongside `tui.py`: booking_watch.py's
  `check_for_changes()` is computed during the *scheduled* scrape (a separate process
  from the interactive TUI), so a detected change needs to be persisted somewhere for
  the TUI to pick up next time it opens, rather than only ever existing as an in-memory
  return value that nothing reads. Flattened rather than storing a serialized
  `BookingChange` — just enough fields to show a banner — and `acknowledged` lets the
  TUI mark a banner as seen without deleting the historical record. `params` (added
  the same day, once the bilingual UI work revealed `message` alone can't be
  localized after the fact — it was already rendered in whatever language was active
  at scrape time) is the structured (JSON) form of the same fact `kind` + `message`
  represent; `i18n.render_booking_change()` uses `kind` + `params` to show the change
  in whatever language is current when the TUI actually displays it, not whatever was
  current hours or days earlier when the scheduled scrape ran.

Implemented and tested 2026-09-06. Not yet covered here: a lookup for a *specific*
historical scrape (e.g. "the schedule as of when this booking was confirmed") — only
"give me the latest" exists so far. booking_watch.py's baseline/latest diffing can use
`load_latest_schedule()` twice, once before and once after a new scrape lands; a
by-timestamp lookup can be added if that turns out not to be precise enough once
scrape_once.py is wired up.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import ConfirmedBooking, Schedule, Slot, WeatherPoint

DEFAULT_DB_PATH = Path("teetime.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS scrapes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course TEXT NOT NULL,
    date TEXT NOT NULL,        -- YYYY-MM-DD
    scraped_at TEXT NOT NULL   -- ISO 8601 timestamp
);

CREATE TABLE IF NOT EXISTS slots (
    scrape_id INTEGER NOT NULL REFERENCES scrapes(id),
    time TEXT NOT NULL,        -- HH:MM
    booked INTEGER NOT NULL,
    capacity INTEGER NOT NULL,
    players TEXT NOT NULL,     -- JSON-encoded list[str]
    block_reason TEXT          -- NULL = real occupancy (or fully open)
);

CREATE TABLE IF NOT EXISTS weather_points (
    scrape_id INTEGER NOT NULL REFERENCES scrapes(id),
    time TEXT NOT NULL,                    -- matches a slot's time
    precipitation_probability REAL,
    precipitation_mm REAL,
    wind_speed_kph REAL,
    temperature_c REAL
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

CREATE TABLE IF NOT EXISTS booking_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course TEXT NOT NULL,
    date TEXT NOT NULL,
    time TEXT,                 -- the booking's own time, for display
    kind TEXT NOT NULL,        -- one of booking_watch.py's change-kind constants
    message TEXT NOT NULL,     -- plain-language English, kept as a fallback/for any
                                -- non-TUI consumer -- the TUI itself re-renders from
                                -- kind + params in the current language instead (see
                                -- i18n.py's render_booking_change(), added 2026-09-06)
    params TEXT NOT NULL DEFAULT '{}', -- JSON-encoded dict, e.g. {"count": 2, "time": "14:00"}
    detected_at TEXT NOT NULL, -- ISO 8601 timestamp
    acknowledged INTEGER NOT NULL DEFAULT 0
);
"""


def init_db(path: Path = DEFAULT_DB_PATH) -> None:
    """Create `path`'s schema if it doesn't exist yet. Every other function in this
    module calls this first, so this is also the one place that needs to create
    `path`'s parent directory — sqlite3 happily creates the database *file* itself
    but not any missing directory in its path. Found live 2026-09-07: opening the TUI
    for the very first time, before `scrape_once.py` had ever run to create `data/`
    itself, crashed with `OperationalError: unable to open database file` — the
    directory just didn't exist yet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)


def save_schedule(schedule: Schedule, path: Path = DEFAULT_DB_PATH) -> int:
    """Log one scrape's slots (and weather, if present) as a new batch — never
    overwrite, history matters. Returns the new scrape's row id."""
    init_db(path)
    scraped_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as conn:
        cursor = conn.execute(
            "INSERT INTO scrapes (course, date, scraped_at) VALUES (?, ?, ?)",
            (schedule.course, schedule.date, scraped_at),
        )
        scrape_id = cursor.lastrowid
        conn.executemany(
            "INSERT INTO slots (scrape_id, time, booked, capacity, players, block_reason) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    scrape_id,
                    slot.time,
                    slot.booked,
                    slot.capacity,
                    json.dumps(slot.players),
                    slot.block_reason,
                )
                for slot in schedule.slots
            ],
        )
        conn.executemany(
            "INSERT INTO weather_points "
            "(scrape_id, time, precipitation_probability, precipitation_mm, "
            "wind_speed_kph, temperature_c) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    scrape_id,
                    point.time,
                    point.precipitation_probability,
                    point.precipitation_mm,
                    point.wind_speed_kph,
                    point.temperature_c,
                )
                for point in schedule.weather
            ],
        )
        return scrape_id


def last_scraped_at(course: str, date: str, path: Path = DEFAULT_DB_PATH) -> str | None:
    """The ISO 8601 timestamp of the most recent scrape for a course/date, or None if
    never scraped. Added 2026-09-06 so scrape_once.py can decide whether a course/date
    is actually *due* for a re-scrape yet, rather than always re-scraping on every
    run — the mechanism behind the adjustable scrape interval (see ROADMAP.md Phase 1,
    "Adjustable scrape interval")."""
    init_db(path)
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT scraped_at FROM scrapes WHERE course = ? AND date = ? "
            "ORDER BY id DESC LIMIT 1",
            (course, date),
        ).fetchone()
    return row[0] if row else None


def distinct_scraped_dates(course: str, path: Path = DEFAULT_DB_PATH) -> list[str]:
    """Every date this course has ever been scraped for, oldest first. Added
    2026-09-06 for analytics.py — it needs to walk every historical date to build the
    crowd heatmap, one `load_latest_schedule()` call per date (see that module for why
    the *latest* scrape per date, not every scrape ever made for it, is what a
    historical heatmap should count)."""
    init_db(path)
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT date FROM scrapes WHERE course = ? ORDER BY date", (course,)
        ).fetchall()
    return [row[0] for row in rows]


def load_latest_schedule(course: str, date: str, path: Path = DEFAULT_DB_PATH) -> Schedule | None:
    """Return the most recent scrape's slots (+ weather, if any was saved) for a
    course/date, or None if never scraped. `sun_times` and `available_courses` aren't
    persisted here (see module docstring) — a caller that needs them fills those in
    separately after loading."""
    init_db(path)
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT id FROM scrapes WHERE course = ? AND date = ? "
            "ORDER BY id DESC LIMIT 1",
            (course, date),
        ).fetchone()
        if row is None:
            return None
        scrape_id = row[0]

        slot_rows = conn.execute(
            "SELECT time, booked, capacity, players, block_reason FROM slots "
            "WHERE scrape_id = ? ORDER BY time",
            (scrape_id,),
        ).fetchall()
        slots = [
            Slot(
                time=time,
                booked=booked,
                capacity=capacity,
                players=json.loads(players),
                block_reason=block_reason,
            )
            for time, booked, capacity, players, block_reason in slot_rows
        ]

        weather_rows = conn.execute(
            "SELECT time, precipitation_probability, precipitation_mm, wind_speed_kph, "
            "temperature_c FROM weather_points WHERE scrape_id = ? ORDER BY time",
            (scrape_id,),
        ).fetchall()
        weather = [
            WeatherPoint(
                time=time,
                precipitation_probability=precipitation_probability,
                precipitation_mm=precipitation_mm,
                wind_speed_kph=wind_speed_kph,
                temperature_c=temperature_c,
            )
            for time, precipitation_probability, precipitation_mm, wind_speed_kph, temperature_c in weather_rows
        ]

    events = sorted({slot.block_reason for slot in slots if slot.block_reason})
    return Schedule(date=date, course=course, slots=slots, weather=weather, events=events)


def save_confirmed_booking(booking: ConfirmedBooking, path: Path = DEFAULT_DB_PATH) -> None:
    """Record a confirmed booking (or a confirmed "not playing"). Never overwrite —
    each confirmation (including a re-confirmation) is its own row, matching how
    scrapes are never overwritten either."""
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO confirmed_bookings "
            "(course, date, time, holes, source, confirmed_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                booking.course,
                booking.date,
                booking.time,
                booking.holes,
                booking.source,
                booking.confirmed_at,
            ),
        )


def load_confirmed_booking(course: str, date: str, path: Path = DEFAULT_DB_PATH) -> ConfirmedBooking | None:
    """Return the most recently confirmed booking for a course/date, or None if never
    confirmed. If confirmed more than once (e.g. an automatic "my_reservations" read
    following an earlier manual `c` confirmation), the latest row wins."""
    init_db(path)
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT course, date, time, holes, source, confirmed_at "
            "FROM confirmed_bookings WHERE course = ? AND date = ? "
            "ORDER BY id DESC LIMIT 1",
            (course, date),
        ).fetchone()
    if row is None:
        return None
    course_, date_, time, holes, source, confirmed_at = row
    return ConfirmedBooking(
        date=date_, course=course_, time=time, holes=holes, source=source, confirmed_at=confirmed_at
    )


def load_all_confirmed_bookings(path: Path = DEFAULT_DB_PATH) -> list[ConfirmedBooking]:
    """Every course/date that's ever had a confirmed booking in this club's database,
    latest confirmation per course/date (same "latest wins" rule as
    load_confirmed_booking()), oldest date first. Added 2026-09-06 for analytics.py's
    personal_stats() — that spans every course at a club, not just one, so it needs
    this instead of looping load_confirmed_booking() over guessed course/date pairs."""
    init_db(path)
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT course, date, time, holes, source, confirmed_at FROM confirmed_bookings "
            "WHERE id IN (SELECT MAX(id) FROM confirmed_bookings GROUP BY course, date) "
            "ORDER BY date"
        ).fetchall()
    return [
        ConfirmedBooking(date=date, course=course, time=time, holes=holes, source=source, confirmed_at=confirmed_at)
        for course, date, time, holes, source, confirmed_at in rows
    ]


def save_booking_change(
    course: str,
    date: str,
    time: str | None,
    kind: str,
    message: str,
    params: dict | None = None,
    path: Path = DEFAULT_DB_PATH,
) -> None:
    """Persist one detected booking_watch.BookingChange so the TUI can show it as a
    banner next time it opens — see the module docstring's `booking_changes` note.
    Takes plain fields rather than a BookingChange object so storage.py doesn't need to
    import booking_watch.py just for a dataclass shape. `params` is JSON-encoded —
    `{}` if not given, so old-style callers that only pass `message` still work."""
    init_db(path)
    detected_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO booking_changes (course, date, time, kind, message, params, detected_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (course, date, time, kind, message, json.dumps(params or {}), detected_at),
        )


def load_unacknowledged_booking_changes(path: Path = DEFAULT_DB_PATH) -> list[dict]:
    """Every not-yet-seen booking change, oldest first — what the TUI's home screen
    shows as banners. Returns plain dicts
    (id/course/date/time/kind/message/params/detected_at) rather than reconstructing a
    full BookingChange (which would need a full ConfirmedBooking round-tripped back
    out too) — display only needs these fields."""
    init_db(path)
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT id, course, date, time, kind, message, params, detected_at FROM booking_changes "
            "WHERE acknowledged = 0 ORDER BY id"
        ).fetchall()
    return [
        {
            "id": row[0],
            "course": row[1],
            "date": row[2],
            "time": row[3],
            "kind": row[4],
            "message": row[5],
            "params": json.loads(row[6]) if row[6] else {},
            "detected_at": row[7],
        }
        for row in rows
    ]


def acknowledge_booking_changes(ids: list[int], path: Path = DEFAULT_DB_PATH) -> None:
    """Mark banners as seen — doesn't delete the row, just stops it showing again next
    time the TUI opens."""
    if not ids:
        return
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.executemany("UPDATE booking_changes SET acknowledged = 1 WHERE id = ?", [(i,) for i in ids])
