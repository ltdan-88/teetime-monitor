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

Five tables:
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
- `known_players` — added 2026-09-27, once authenticated scraping made real names
  possible at all (see `scraper.scrape_schedule()`'s own `client` parameter): every
  name ever seen in a `Slot.players` list, so it's browsable as a directory rather
  than buried in whichever day's scrape happened to record it, with `is_friend` the
  one field a person actually edits (via the TUI/GUI's own directory screen) — see
  `models.KnownPlayer`.
- `scrape_runs` — added 2026-10-05: one row per `scrape_once.scrape_due_for_club()`
  call (the launchd agent, the TUI's timer, the GUI's Refresh), including passes where
  nothing was due. Found live: pc caddie rejected the login for both real clubs for ~20
  hours and every pass silently fell back to anonymous (no player names), and the
  course list failed intermittently overnight -- the only trace was a log file nobody
  reads. `scrape_health()` summarizes these rows for both front ends' health line.
  Pruned to `SCRAPE_RUN_RETENTION_DAYS` on every write -- an operational log, not
  history worth keeping forever like `scrapes`.

Implemented and tested 2026-09-06. Not yet covered here: a lookup for a *specific*
historical scrape (e.g. "the schedule as of when this booking was confirmed") — only
"give me the latest" exists so far. booking_watch.py's baseline/latest diffing can use
`load_latest_schedule()` twice, once before and once after a new scrape lands; a
by-timestamp lookup can be added if that turns out not to be precise enough once
scrape_once.py is wired up.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import (
    ConfirmedBooking,
    KnownPlayer,
    PlayerSighting,
    Schedule,
    Slot,
    SunTimes,
    WeatherPoint,
    family_name,
    looks_like_player_name,
)

DEFAULT_DB_PATH = Path("teetime.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS scrapes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course TEXT NOT NULL,
    date TEXT NOT NULL,        -- YYYY-MM-DD
    scraped_at TEXT NOT NULL,  -- ISO 8601 timestamp
    sunrise TEXT,              -- HH:MM, local time -- NULL if never fetched
    sunset TEXT,               -- HH:MM, local time -- NULL if never fetched
    events TEXT,               -- JSON-encoded list[str] -- NULL/'[]' means none
    authenticated INTEGER      -- 1 logged-in fetch (real names), 0 anonymous, NULL unknown (older rows)
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
    temperature_c REAL,
    weather_code INTEGER                   -- WMO code (Open-Meteo) -- see weather_icons.py
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

CREATE TABLE IF NOT EXISTS club_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL        -- JSON-encoded
);

CREATE TABLE IF NOT EXISTS known_players (
    name TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,  -- ISO 8601 timestamp
    last_seen TEXT NOT NULL,   -- ISO 8601 timestamp
    is_friend INTEGER NOT NULL DEFAULT 0,
    gender TEXT,               -- "male" / "female" / "unknown" / NULL -- see
                                -- models.PlayerSighting
    member_status TEXT,        -- "member" / "guest" / NULL
    handicap REAL              -- most recently seen value, NULL if never shown
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,          -- ISO 8601, UTC
    finished_at TEXT NOT NULL,         -- ISO 8601, UTC
    source TEXT NOT NULL,              -- 'agent' / 'tui' / 'gui'
    attempted INTEGER NOT NULL DEFAULT 0,  -- course/date pairs actually tried
    saved INTEGER NOT NULL DEFAULT 0,      -- schedules saved
    failed INTEGER NOT NULL DEFAULT 0,
    authenticated INTEGER,             -- 1/0, NULL = no credentials configured
    error_kind TEXT,                   -- NULL or one of SCRAPE_ERROR_KINDS
    error_message TEXT                 -- short, never credentials
);

-- Every scrape appends a full day of slots and nothing is ever deleted, so without
-- these each load_latest_schedule() scanned the whole history (the heatmap calls it
-- once per date, so its cost grew quadratically). IF NOT EXISTS: an existing
-- database picks them up on its next init_db().
CREATE INDEX IF NOT EXISTS idx_slots_scrape ON slots(scrape_id, time);
CREATE INDEX IF NOT EXISTS idx_weather_scrape ON weather_points(scrape_id, time);
CREATE INDEX IF NOT EXISTS idx_scrapes_course_date ON scrapes(course, date);
CREATE INDEX IF NOT EXISTS idx_scrape_runs_started ON scrape_runs(started_at);
"""

# See the module docstring's `scrape_runs` note.
SCRAPE_RUN_SOURCES = ("agent", "tui", "gui")
SCRAPE_ERROR_LOGIN_REJECTED = "login_rejected"
SCRAPE_ERROR_NETWORK = "network"
SCRAPE_ERROR_NO_TEE_SHEET = "no_tee_sheet"
SCRAPE_ERROR_OTHER = "other"
SCRAPE_ERROR_KINDS = (
    SCRAPE_ERROR_LOGIN_REJECTED,
    SCRAPE_ERROR_NETWORK,
    SCRAPE_ERROR_NO_TEE_SHEET,
    SCRAPE_ERROR_OTHER,
)
SCRAPE_RUN_RETENTION_DAYS = 30
SCRAPE_ERROR_MESSAGE_MAX_CHARS = 300


# How long a statement waits for another process's lock before "database is locked"
# (2026-10-05). Three processes share each club's file -- the launchd agent's scrape,
# the TUI's worker and the GUI's refresh/writes -- so a short wait is normal, a failure
# is not. The GUI's Store.swift uses the same 5000.
BUSY_TIMEOUT_MS = 5000

# Bumped when the schema changes shape. Stored in `PRAGMA user_version` by init_db() so
# the GUI (which reads the file directly) can tell, and tolerates a *newer* value than
# it knows without failing: an older app must keep reading a database a newer one
# already touched. init_db() never lowers it.
SCHEMA_VERSION = 1


def _open(path: Path, *, wal: bool) -> sqlite3.Connection:
    """The one place a club-database connection is opened: busy timeout always, and (when `wal`)
    write-ahead logging. WAL is persistent in the file, so this only switches a
    database that isn't in it yet -- the readers no longer block the writer, and the
    writer no longer blocks readers (the old rollback journal let a scrape's commit
    fail a GUI read). Switching needs a moment of exclusive access; if another process
    holds the file right then, or the filesystem can't do WAL (network share, read-only),
    the database just stays in its current mode and the next connection tries again.
    Note WAL leaves `<db>-wal` / `<db>-shm` beside the file: copy a database with
    backup_db(), never by copying the bare `.db`."""
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000)
    try:
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        if wal:
            try:
                if conn.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
                    conn.execute("PRAGMA journal_mode = WAL")
            except sqlite3.OperationalError:
                pass
    except BaseException:
        conn.close()
        raise
    return conn


@contextmanager
def _connect(path: Path) -> Iterator[sqlite3.Connection]:
    """`sqlite3.connect()` used as a context manager only commits or rolls back -- it
    never closes the connection, which then lingers (with its file handle) until
    garbage collection. This commits/rolls back the same way and then closes. Every
    club-database connection comes from here (see _open() for the pragmas); the
    backup destination and paths._is_teetime_db()'s read-only probe are deliberate
    exceptions."""
    conn = _open(path, wal=True)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


# Public name of _connect() for the other modules that query a club database directly
# (analytics.py), so they get the same busy timeout and WAL.
connect = _connect


def schema_version(path: Path) -> int:
    """`PRAGMA user_version` of `path` (0 for a database that predates it)."""
    with _connect(path) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def init_db(path: Path = DEFAULT_DB_PATH) -> None:
    """Create `path`'s schema if it doesn't exist yet. Every other function in this
    module calls this first, so this is also the one place that needs to create
    `path`'s parent directory — sqlite3 happily creates the database *file* itself
    but not any missing directory in its path. Found live 2026-09-07: opening the TUI
    for the very first time, before `scrape_once.py` had ever run to create `data/`
    itself, crashed with `OperationalError: unable to open database file` — the
    directory just didn't exist yet.

    Also migrates an existing `scrapes` table that predates the `sunrise`/`sunset`/
    `events` columns (2026-09-08, direct feedback: "don't forget about the sunrise
    and sunset times" — surfaced that these were never actually persisted at all,
    only ever attached in memory during a scrape and then silently dropped, since
    `CREATE TABLE IF NOT EXISTS` is a no-op against a table that already exists in
    an older shape; `events` followed the next day for the identical reason, see
    `load_latest_schedule()`'s own docstring), and (2026-09-11, same reasoning) an
    existing `weather_points` table that predates `weather_code` — added for the
    weather-condition-icon feature (see weather_icons.py), direct feedback: "I also
    would like icons for when it is sunny, overcast, foggy, snowing etc." Every real
    scrape ever recorded is exactly the kind of history this whole module exists to
    keep — pc caddie hides the past, so there's no re-scraping it later — so an
    `ALTER TABLE` here, not a fresh/rebuilt database, is what keeps that history
    intact while still picking up the new columns. (A row saved before this column
    existed just reads back with `weather_code=None` — no icon shown, same
    "no migration needed for the actual data" stance as `events` above.)"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(path) as conn:
        conn.executescript(SCHEMA)
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(scrapes)")}
        if "authenticated" not in existing_columns:
            conn.execute("ALTER TABLE scrapes ADD COLUMN authenticated INTEGER")
        for column in ("sunrise", "sunset", "events"):
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE scrapes ADD COLUMN {column} TEXT")
        existing_weather_columns = {row[1] for row in conn.execute("PRAGMA table_info(weather_points)")}
        if "weather_code" not in existing_weather_columns:
            conn.execute("ALTER TABLE weather_points ADD COLUMN weather_code INTEGER")
        # 2026-09-27, same reasoning: `known_players` predates gender/member_status/
        # handicap (added once the directory's own "further scrapable information?"
        # question got checked directly against the live authenticated tee sheet) --
        # every name already recorded (this club's real directory: 373 of them) just
        # reads back with all three NULL until its next sighting fills them in.
        existing_player_columns = {row[1] for row in conn.execute("PRAGMA table_info(known_players)")}
        for column, column_type in (("gender", "TEXT"), ("member_status", "TEXT"), ("handicap", "REAL")):
            if column not in existing_player_columns:
                conn.execute(f"ALTER TABLE known_players ADD COLUMN {column} {column_type}")
        # 2026-10-05: stamp the schema version, but never lower a newer app's.
        if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def save_schedule(schedule: Schedule, path: Path = DEFAULT_DB_PATH, authenticated: bool | None = None) -> int:
    """Log one scrape's slots (and weather/sun times/events, if present) as a new
    batch — never overwrite, history matters. Returns the new scrape's row id.
    `authenticated` records whether the fetch was logged in (names visible): True/False, or
    None when unknown -- scrape_once re-fetches anonymous days once a login is available."""
    init_db(path)
    scraped_at = datetime.now(UTC).isoformat()
    sunrise = schedule.sun_times.sunrise if schedule.sun_times is not None else None
    sunset = schedule.sun_times.sunset if schedule.sun_times is not None else None
    with _connect(path) as conn:
        cursor = conn.execute(
            "INSERT INTO scrapes (course, date, scraped_at, sunrise, sunset, events, authenticated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                schedule.course, schedule.date, scraped_at, sunrise, sunset, json.dumps(schedule.events),
                None if authenticated is None else int(authenticated),
            ),
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
            "wind_speed_kph, temperature_c, weather_code) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    scrape_id,
                    point.time,
                    point.precipitation_probability,
                    point.precipitation_mm,
                    point.wind_speed_kph,
                    point.temperature_c,
                    point.weather_code,
                )
                for point in schedule.weather
            ],
        )
        return scrape_id


def last_scrape_authenticated(course: str, date: str, path: Path = DEFAULT_DB_PATH) -> bool | None:
    """Whether the most recent scrape of this course/date was a logged-in fetch (True/False),
    or None when unknown (a row from before this was recorded) or never scraped."""
    init_db(path)
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT authenticated FROM scrapes WHERE course = ? AND date = ? ORDER BY id DESC LIMIT 1",
            (course, date),
        ).fetchone()
    return None if row is None or row[0] is None else bool(row[0])


def last_scraped_at(course: str, date: str, path: Path = DEFAULT_DB_PATH) -> str | None:
    """The ISO 8601 timestamp of the most recent scrape for a course/date, or None if
    never scraped. Added 2026-09-06 so scrape_once.py can decide whether a course/date
    is actually *due* for a re-scrape yet, rather than always re-scraping on every
    run — the mechanism behind the adjustable scrape interval (see ROADMAP.md Phase 1,
    "Adjustable scrape interval")."""
    init_db(path)
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT scraped_at FROM scrapes WHERE course = ? AND date = ? "
            "ORDER BY id DESC LIMIT 1",
            (course, date),
        ).fetchone()
    return row[0] if row else None


def first_confirmed_at(course: str, date: str, time: str, path: Path = DEFAULT_DB_PATH) -> str | None:
    """The earliest `confirmed_at` ever recorded for this exact course/date/time, or
    None if it's never been confirmed. `confirmed_bookings` never overwrites (see the
    module docstring) — a re-sync every pass inserts a fresh row with `confirmed_at`
    reset to "now" (scraper.py), so only the *earliest* row is a usable proxy for "when
    this booking was first seen," not the latest one `load_confirmed_booking()` returns.

    Added 2026-09-20, direct report: a booking's very first scrape after being placed
    always showed its own booked-count jump (0 -> your own party) as booking_watch.py's
    PARTY_GREW — "another player joined" — when the "1 more player" was actually just
    you. See `booking_watch.check_for_changes()`'s own docstring for how this is used:
    a PARTY_GREW change is suppressed when the comparison's own baseline scrape
    predates this timestamp, since any growth across that boundary can't be told apart
    from your own booking appearing for the first time."""
    init_db(path)
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT MIN(confirmed_at) FROM confirmed_bookings WHERE course = ? AND date = ? AND time = ?",
            (course, date, time),
        ).fetchone()
    return row[0] if row and row[0] else None


def distinct_scraped_dates(course: str, path: Path = DEFAULT_DB_PATH) -> list[str]:
    """Every date this course has ever been scraped for, oldest first. Added
    2026-09-06 for analytics.py — it needs to walk every historical date to build the
    crowd heatmap, one `load_latest_schedule()` call per date (see that module for why
    the *latest* scrape per date, not every scrape ever made for it, is what a
    historical heatmap should count)."""
    init_db(path)
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT date FROM scrapes WHERE course = ? ORDER BY date", (course,)
        ).fetchall()
    return [row[0] for row in rows]


def courses_scraped_on(date: str, path: Path = DEFAULT_DB_PATH) -> list[str]:
    """Every course with at least one scrape saved for `date`, alphabetically.
    Added 2026-10-05 for `recommend.shorter_round_alternative()`: the club's
    other courses it may suggest a shorter round on are whatever was actually
    scraped for that day, not a live course list."""
    init_db(path)
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT course FROM scrapes WHERE date = ? ORDER BY course", (date,)
        ).fetchall()
    return [row[0] for row in rows]


def upcoming_courses(today: str, path: Path = DEFAULT_DB_PATH) -> list[str]:
    """Courses still being scraped (a scrape for `today` or later), alphabetically --
    the club's current lineup, which `SELECT DISTINCT course` over all history is not
    (a club's DB can hold retired names). Falls back to every course ever scraped when
    nothing is upcoming. Same rule as `Store.courses()` in macos/Sources/Store.swift;
    what the per-course settings rows list (2026-10-05)."""
    init_db(path)
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT course FROM scrapes WHERE date >= ? ORDER BY course", (today,)
        ).fetchall()
        if not rows:
            rows = conn.execute("SELECT DISTINCT course FROM scrapes ORDER BY course").fetchall()
    return [row[0] for row in rows]


def load_latest_schedule(course: str, date: str, path: Path = DEFAULT_DB_PATH) -> Schedule | None:
    """Return the most recent scrape's slots (+ weather + sun times + events, if any
    was saved) for a course/date, or None if never scraped. `available_courses` isn't
    persisted here (see module docstring) — a caller that needs it fills it in
    separately after loading. `sun_times` *is* now (2026-09-08 — see `init_db()`'s
    own docstring for the real gap this closed: it used to be fetched at scrape
    time and then silently dropped, never actually reaching anything that loads a
    schedule back out, including every real TUI display and the daylight half of
    `recommend.exclude_unplayable()`).

    `events` is read back verbatim from what `save_schedule()` stored, not
    re-derived from the loaded slots' own `block_reason` the way this used to work
    (found 2026-09-09 while splitting the overview's Weather/Events columns: a
    `Slot` only ever carries `block_reason` text, never which `data-status` produced
    it, so re-deriving here could never tell a genuine block-time event apart from a
    disable-time advance-booking notice — reintroducing, on every single load, the
    exact bug `scraper._event_names()` had already been fixed to avoid at scrape
    time the day before). A row saved before this column existed reads back as no
    events (`events_json` is `None`) rather than falling back to the old buggy
    re-derivation — the next real scrape overwrites it with the correct value
    anyway, same "no migration needed yet" stance as everywhere else in this
    project."""
    init_db(path)
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT id, sunrise, sunset, events FROM scrapes WHERE course = ? AND date = ? "
            "ORDER BY id DESC LIMIT 1",
            (course, date),
        ).fetchone()
        if row is None:
            return None
        scrape_id, sunrise, sunset, events_json = row
        sun_times = SunTimes(sunrise=sunrise, sunset=sunset) if sunrise and sunset else None
        events = json.loads(events_json) if events_json else []

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

        # Weather (and the sun times that come with it) falls back to the most recent
        # earlier scrape that actually has some, when this one doesn't -- slots always
        # stay from the latest scrape, since occupancy is the thing that must be fresh.
        #
        # Found live 2026-09-17 from a direct report ("sometimes weather data wasn't
        # pulled for every day in the overview"): Open-Meteo was unreachable for about
        # seven hours, and every scrape in that window saved a schedule with zero
        # weather points. `save_schedule()` never overwrites -- each scrape is its own
        # row -- so those weather-less rows simply became "the latest", and the
        # overview showed nothing for those days even though perfectly good weather sat
        # one row above, fetched an hour earlier. Eight consecutive scrapes of one
        # course/date in the real database, 09:49 to 16:56, all wx=0, with wx=24
        # immediately before and after.
        #
        # A few-hours-stale forecast for a future day is far better than a blank
        # column, and this also repairs every already-corrupted row on read rather
        # than needing the next successful scrape to land first.
        weather_scrape_id = scrape_id
        if not conn.execute(
            "SELECT 1 FROM weather_points WHERE scrape_id = ? LIMIT 1", (scrape_id,)
        ).fetchone():
            fallback = conn.execute(
                "SELECT s.id, s.sunrise, s.sunset FROM scrapes s "
                "WHERE s.course = ? AND s.date = ? AND s.id < ? "
                "AND EXISTS (SELECT 1 FROM weather_points w WHERE w.scrape_id = s.id) "
                "ORDER BY s.id DESC LIMIT 1",
                (course, date, scrape_id),
            ).fetchone()
            if fallback is not None:
                weather_scrape_id, fallback_sunrise, fallback_sunset = fallback
                if sun_times is None and fallback_sunrise and fallback_sunset:
                    sun_times = SunTimes(sunrise=fallback_sunrise, sunset=fallback_sunset)

        weather_rows = conn.execute(
            "SELECT time, precipitation_probability, precipitation_mm, wind_speed_kph, "
            "temperature_c, weather_code FROM weather_points WHERE scrape_id = ? ORDER BY time",
            (weather_scrape_id,),
        ).fetchall()
        weather = [
            WeatherPoint(
                time=time,
                precipitation_probability=precipitation_probability,
                precipitation_mm=precipitation_mm,
                wind_speed_kph=wind_speed_kph,
                temperature_c=temperature_c,
                weather_code=weather_code,
            )
            for time, precipitation_probability, precipitation_mm, wind_speed_kph, temperature_c, weather_code in weather_rows
        ]

    return Schedule(date=date, course=course, slots=slots, weather=weather, sun_times=sun_times, events=events)


def save_confirmed_booking(booking: ConfirmedBooking, path: Path = DEFAULT_DB_PATH) -> None:
    """Record a confirmed booking (or a confirmed "not playing"). Never overwrite —
    each confirmation (including a re-confirmation) is its own row, matching how
    scrapes are never overwritten either."""
    init_db(path)
    with _connect(path) as conn:
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
    with _connect(path) as conn:
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
    with _connect(path) as conn:
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
    detected_at = datetime.now(UTC).isoformat()
    with _connect(path) as conn:
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
    with _connect(path) as conn:
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
    with _connect(path) as conn:
        conn.executemany("UPDATE booking_changes SET acknowledged = 1 WHERE id = ?", [(i,) for i in ids])


def save_location(location: dict, path: Path = DEFAULT_DB_PATH) -> None:
    """Cache a club's geocoded {"lat", "lon"} in its own db (added 2026-09-08, direct
    feedback: "I don't want to first save a club in order to see weather forecast" —
    a club can be opened and scraped without ever being favorited (see tui.py's
    _open_club()), and it already gets this same per-club db file the moment it's
    scraped, regardless of favorite status, so this is where its location lives too
    now — not clubs/*.yaml, which a club like this may never have at all. A row here
    persists across restarts the same way a favorited club's location does, just
    without requiring the favorite."""
    init_db(path)
    with _connect(path) as conn:
        conn.execute(
            "INSERT INTO club_meta (key, value) VALUES ('location', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps(location),),
        )


def load_location(path: Path = DEFAULT_DB_PATH) -> dict | None:
    """The {"lat", "lon"} save_location() cached for this club, or None if it's never
    been geocoded (or this club has no db file yet at all)."""
    if not path.exists():
        return None
    init_db(path)
    with _connect(path) as conn:
        row = conn.execute("SELECT value FROM club_meta WHERE key = 'location'").fetchone()
    return json.loads(row[0]) if row else None


def save_my_handicap(handicap: float, path: Path = DEFAULT_DB_PATH) -> None:
    """Cache your own live handicap index (2026-09-27, direct follow-up: "would it
    make sense to have the option to choose to play with similar HCP or with better
    HCP") -- same `club_meta` key-value store `save_location()` already uses for a
    single standing fact about this account, not a new table for one float. Per-db
    (per-club) like everything else here, even though your own handicap is really a
    personal fact, not a club one -- consistent with how this module's own per-file
    split already works, and harmless: `scraper._parse_my_handicap_html()` re-reads
    the real value on every sync pass regardless of which club triggered it."""
    init_db(path)
    with _connect(path) as conn:
        conn.execute(
            "INSERT INTO club_meta (key, value) VALUES ('my_handicap', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps(handicap),),
        )


def load_my_handicap(path: Path = DEFAULT_DB_PATH) -> float | None:
    """The handicap `save_my_handicap()` cached, or None if it's never been synced yet
    (or this club has no db file yet at all)."""
    if not path.exists():
        return None
    init_db(path)
    with _connect(path) as conn:
        row = conn.execute("SELECT value FROM club_meta WHERE key = 'my_handicap'").fetchone()
    return json.loads(row[0]) if row else None


_PURGED_PATHS: set[str] = set()


def purge_non_player_names(path: Path = DEFAULT_DB_PATH) -> int:
    """Deletes `known_players` rows that were recorded before the scraper learned to
    tell an event/note from a name (see `models.looks_like_player_name()`). A row marked as a friend is never deleted. Returns
    how many were removed."""
    if not path.exists():
        return 0
    init_db(path)
    with _connect(path) as conn:
        junk = [
            (name,)
            for (name,) in conn.execute("SELECT name FROM known_players WHERE is_friend = 0").fetchall()
            if not looks_like_player_name(name)
        ]
        conn.executemany("DELETE FROM known_players WHERE name = ?", junk)
    return len(junk)


def record_seen_players(sightings: list[PlayerSighting], seen_at: str, path: Path = DEFAULT_DB_PATH) -> None:
    """Upsert each sighting into `known_players` -- a new row (both timestamps set to
    `seen_at`) the first time a name is ever seen, or just `last_seen` bumped (plus
    gender/member_status/handicap refreshed) on every later sighting. `is_friend` is
    never touched here, on purpose: it's the one field a person actually sets (via the
    directory screen), and a later scrape re-seeing an already-marked friend must not
    silently reset it back to false.

    `gender`/`member_status`/`handicap` use `COALESCE(excluded.x, known_players.x)` on
    conflict rather than a flat overwrite -- a guest's cell sometimes omits the
    handicap span entirely (see `scraper._parse_hcp_span()`), and a `None` from *that*
    sighting shouldn't erase a real value an earlier one already recorded.

    Called once per scrape (`scrape_once.run()`, right after `save_schedule()`) with
    that scrape's own distinct players (by name -- last one wins for any duplicate
    within the same scrape, which never differs in practice) -- piggybacks on a fetch
    that's already happening rather than a separate pass over the whole database."""
    sightings = [sighting for sighting in sightings if looks_like_player_name(sighting.name)]
    if not sightings:
        return
    init_db(path)
    if str(path) not in _PURGED_PATHS:  # a one-time legacy cleanup, not per scrape
        _PURGED_PATHS.add(str(path))
        purge_non_player_names(path)
    with _connect(path) as conn:
        conn.executemany(
            "INSERT INTO known_players (name, first_seen, last_seen, gender, member_status, handicap) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET "
            "last_seen = excluded.last_seen, "
            "gender = COALESCE(excluded.gender, known_players.gender), "
            "member_status = COALESCE(excluded.member_status, known_players.member_status), "
            "handicap = COALESCE(excluded.handicap, known_players.handicap)",
            [
                (sighting.name, seen_at, seen_at, sighting.gender, sighting.member_status, sighting.handicap)
                for sighting in sightings
            ],
        )


def load_known_players(path: Path = DEFAULT_DB_PATH) -> list[KnownPlayer]:
    """Every name ever seen in this club's own scrapes, sorted alphabetically by
    family name (2026-09-27, direct request; "better: make the player directory
    sortable and searchable" -- this is just the default order both front ends load
    with, before any in-screen re-sort) -- the directory screen's own listing (both
    front ends). Sorted in Python, not SQL: `family_name()`'s own last-whitespace-
    token rule isn't expressible as a plain `ORDER BY`."""
    if not path.exists():
        return []
    init_db(path)
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT name, first_seen, last_seen, is_friend, gender, member_status, handicap FROM known_players"
        ).fetchall()
    players = [
        KnownPlayer(
            name=name,
            first_seen=first_seen,
            last_seen=last_seen,
            is_friend=bool(is_friend),
            gender=gender,
            member_status=member_status,
            handicap=handicap,
        )
        for name, first_seen, last_seen, is_friend, gender, member_status, handicap in rows
    ]
    players.sort(key=lambda p: (family_name(p.name).casefold(), p.name.casefold()))
    return players


def load_friend_names(path: Path = DEFAULT_DB_PATH) -> set[str]:
    """Just the names marked `is_friend` -- what `recommend.ranked_matches()` actually
    needs, without loading (or the caller having to filter) the whole directory."""
    if not path.exists():
        return set()
    init_db(path)
    with _connect(path) as conn:
        rows = conn.execute("SELECT name FROM known_players WHERE is_friend = 1").fetchall()
    return {name for (name,) in rows}


def load_player_genders(path: Path = DEFAULT_DB_PATH) -> dict[str, str]:
    """Name -> "male"/"female" for every known player whose gender is recorded (the
    site's own "unknown" marker is left out) -- what colours names in the overview."""
    if not path.exists():
        return {}
    init_db(path)
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT name, gender FROM known_players WHERE gender IN ('male', 'female')"
        ).fetchall()
    return dict(rows)


def load_known_handicaps(path: Path = DEFAULT_DB_PATH) -> dict[str, float]:
    """Name -> handicap for every known player who actually has one recorded --
    what `recommend.ranked_matches()`'s own `known_handicaps` param wants, without
    every call site repeating the same `load_known_players()` + filter-and-dict-
    comprehension. Same shape of shortcut `load_friend_names()` already is over
    `load_known_players()`."""
    if not path.exists():
        return {}
    init_db(path)
    with _connect(path) as conn:
        rows = conn.execute("SELECT name, handicap FROM known_players WHERE handicap IS NOT NULL").fetchall()
    return dict(rows)


def load_player_handicaps(path: Path = DEFAULT_DB_PATH) -> dict[str, float]:
    """Name -> most recently seen handicap for every known player who has one (NULL is
    left out -- guests often have none) -- what shows "(18.4)" after a name in the
    overview (2026-10-05). The same rows `load_known_handicaps()` reads for ranking;
    kept as its own name so the display path and the ranking path can diverge (the
    display one honours the show_handicaps preference at its call sites)."""
    return load_known_handicaps(path)


def set_player_friend(name: str, is_friend: bool, path: Path = DEFAULT_DB_PATH) -> None:
    """Mark (or unmark) one known name as a friend -- the directory screen's own edit
    action. A no-op if `name` was never actually seen (nothing to mark), rather than
    inserting a friend with no real sighting behind it."""
    init_db(path)
    with _connect(path) as conn:
        conn.execute("UPDATE known_players SET is_friend = ? WHERE name = ?", (int(is_friend), name))


def record_scrape_run(
    *,
    started_at: str,
    finished_at: str,
    source: str,
    attempted: int,
    saved: int,
    failed: int,
    authenticated: bool | None,
    error_kind: str | None = None,
    error_message: str | None = None,
    path: Path = DEFAULT_DB_PATH,
) -> None:
    """Log one scrape pass (see the module docstring's `scrape_runs` note) and prune
    rows older than `SCRAPE_RUN_RETENTION_DAYS` in the same transaction. Keyword-only:
    ten positional fields of mostly ints is an argument-order bug waiting to happen.

    `error_message` is truncated here as a last line of defence; the caller
    (`scrape_once`) is the one that strips credentials, since only it knows them."""
    if source not in SCRAPE_RUN_SOURCES:
        raise ValueError(f"unknown scrape run source {source!r}")
    if error_kind is not None and error_kind not in SCRAPE_ERROR_KINDS:
        raise ValueError(f"unknown scrape error kind {error_kind!r}")
    if error_message is not None:
        error_message = error_message.strip()[:SCRAPE_ERROR_MESSAGE_MAX_CHARS] or None
    init_db(path)
    cutoff = (datetime.now(UTC) - timedelta(days=SCRAPE_RUN_RETENTION_DAYS)).isoformat()
    with _connect(path) as conn:
        conn.execute(
            "INSERT INTO scrape_runs (started_at, finished_at, source, attempted, saved, failed, "
            "authenticated, error_kind, error_message) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                started_at,
                finished_at,
                source,
                attempted,
                saved,
                failed,
                None if authenticated is None else int(authenticated),
                error_kind,
                error_message,
            ),
        )
        conn.execute("DELETE FROM scrape_runs WHERE started_at < ?", (cutoff,))


def scrape_run_succeeded(saved: int, attempted: int, error_kind: str | None) -> bool:
    """A run counts as a success when it saved something, or when nothing was due and
    nothing went wrong (the agent is alive and simply had no work). A login-rejected run
    that still saved anonymously *is* a success here -- data arrived; the missing names
    are `login_rejected_since`'s job, not the failure streak's.

    The same goes for a pass where nothing was due and the login was the *only* thing
    that went wrong (2026-10-05, review): the agent runs every 15 minutes against a
    6-hour default interval, so most passes are no-ops, and during a login outage every
    one of them was counted as a failure -- three in a row turned the amber "login
    rejected" line into a red "scrapes failing" one while schedules were still saving
    anonymously. `scrape_once` only records such a pass as `login_rejected` when no
    other error happened (see its `_RunStats.error()`)."""
    return saved > 0 or (attempted == 0 and error_kind in (None, SCRAPE_ERROR_LOGIN_REJECTED))


def empty_scrape_health() -> dict:
    """What `scrape_health()` returns for a database with no recorded runs at all (a
    fresh club, or one whose db predates `scrape_runs`) -- both front ends show nothing
    for it."""
    return {
        "last_run_at": None,
        "last_success_at": None,
        "last_error_kind": None,
        "last_error_message": None,
        "consecutive_failed_runs": 0,
        "failing_since": None,
        "login_rejected_since": None,
    }


def scrape_health(path: Path = DEFAULT_DB_PATH) -> dict:
    """A summary of this club's recent `scrape_runs`, newest first:

    - `last_run_at` / `last_success_at`: `finished_at` of the newest run / newest
      successful run (see `scrape_run_succeeded()`).
    - `last_error_kind` / `last_error_message`: the newest run's own error, None if that
      run was clean.
    - `consecutive_failed_runs`: how many of the newest runs in a row were not
      successes; `failing_since` is the `started_at` of the oldest of them (None when
      the newest run succeeded). Not in the original spec -- added so the "failing
      since" line can say when it started rather than when it was last seen.
    - `login_rejected_since`: `started_at` of the oldest run in the current streak of
      `login_rejected` runs, else None. A run whose login outcome is unknown
      (authenticated = 0 with some *other* error, e.g. offline before the login POST)
      neither extends nor breaks the streak -- one network blip in the middle of a
      day-long rejection shouldn't reset "since" to an hour ago. A successful login
      (authenticated = 1) or no credentials at all (NULL) ends it.

    Mirrored by `Store.scrapeHealth()` in the GUI (cross-checked by
    `scripts/cross_language_reference.py`)."""
    health = empty_scrape_health()
    if not path.exists():
        return health
    init_db(path)
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT started_at, finished_at, attempted, saved, authenticated, error_kind, error_message "
            "FROM scrape_runs ORDER BY started_at DESC, id DESC"
        ).fetchall()
    if not rows:
        return health
    _, newest_finished, _, _, _, newest_kind, newest_message = rows[0]
    health["last_run_at"] = newest_finished
    health["last_error_kind"] = newest_kind
    health["last_error_message"] = newest_message

    failure_streak_open = True
    login_streak_open = True
    for started_at, finished_at, attempted, saved, authenticated, error_kind, _message in rows:
        succeeded = scrape_run_succeeded(saved, attempted, error_kind)
        if succeeded and health["last_success_at"] is None:
            health["last_success_at"] = finished_at
        if failure_streak_open:
            if succeeded:
                failure_streak_open = False
            else:
                health["consecutive_failed_runs"] += 1
                health["failing_since"] = started_at
        if login_streak_open:
            if error_kind == SCRAPE_ERROR_LOGIN_REJECTED:
                health["login_rejected_since"] = started_at
            elif not (authenticated == 0 and error_kind is not None):
                login_streak_open = False
        if not failure_streak_open and not login_streak_open and health["last_success_at"] is not None:
            break
    return health


def backup_db(source: Path, destination: Path) -> None:
    """A consistent copy of `source` via SQLite's online backup API (safe while another
    process is writing, unlike a plain file copy). Written to a temporary name and
    renamed into place, so an interrupted backup never looks like a finished one."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    partial.unlink(missing_ok=True)
    # Not _connect(): a backup must not switch the source's journal mode as a side effect.
    # The backup API reads one consistent snapshot through the WAL (committed frames
    # included), so the result is a self-contained file with no -wal/-shm of its own.
    src = _open(source, wal=False)
    try:
        dst = sqlite3.connect(partial)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    partial.replace(destination)
