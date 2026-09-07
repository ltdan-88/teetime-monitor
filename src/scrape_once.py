"""Headless, no-TUI scrape-and-store — meant to run on a schedule (cron/launchd).

Exists because pc caddie hides past tee sheets: any day nobody opens the TUI is a gap in
history that can never be filled in later.

`run()` scrapes one club/course/date's tee sheet and saves it via storage.py — always
real, no login needed for this part.

**Login (real as of 2026-09-06, once the actual form was inspected live — see
scraper.py's `login()`)**: `run()` also logs in and syncs "My Reservations" into
`confirmed_bookings`, via `_sync_my_reservations()` below. Every failure mode there is
best-effort, not fatal, since this must not stop an unattended run over one club:
no slug resolved for this `club_id` (can't look up credentials without it), no
`PCC_USER`/`PCC_PASS` configured yet, a `scraper.LoginError` (wrong credentials), or a
`NotImplementedError` from `scrape_my_reservations()` itself (a real booking exists
but its row markup isn't parseable yet — see that function's own docstring for why).

**Weather (added 2026-09-06, alongside making weather.py's fetch calls real)**: `run()`
also fetches the day's hourly forecast and sun times, using the club's YAML `location`
block, and attaches them to the schedule before it's saved — this is what actually
makes `recommend.exclude_unplayable()` and `booking_watch.check_for_changes()`'s
weather checks see real data instead of always getting `None` back. Skipped
(not fatal) if `location` isn't filled in yet (still the `0.0, 0.0` placeholder from
club.example.yaml — "null island," not a real course) or the request itself fails —
occupancy is still the primary thing this scrape is for, and a missing/late weather
overlay for one course/date shouldn't take that down.

**Adjustable scrape interval (added 2026-09-06, after feedback that once/twice-daily
was too infrequent, especially for a date you've actually booked)**: `main()` now
checks `_should_scrape()` before re-scraping a given course/date, using each club's
`scrape_interval_minutes` (normal) / `scrape_interval_minutes_booked` (shorter, once a
confirmed booking exists for that date — freshness matters more once there's something
to protect, see booking_watch.py) from its YAML. This flips the intended cron cadence:
fire this job *often* (e.g. every 15-30 min) and let it decide per course/date whether
a re-scrape is actually due, rather than tuning the cron schedule itself to match the
desired interval:

    */15 * * * * cd /path/to/teetime-monitor && .venv/bin/python -m src.scrape_once

`main()` loops every saved club (club_config.list_clubs()) via `scrape_due_for_club()`
(one club, every course x every day in its `overview_days` window) — so one cron
entry with no arguments covers everything currently configured, throttled per
course/date as above.

Installed as a real `launchd` job on 2026-09-07 (`~/Library/LaunchAgents/
com.teetimemonitor.scrape.plist`, firing every 15 minutes via `StartInterval`,
`_should_scrape()` still throttling what's actually fetched) — the standing,
persistent change every earlier version of this note left for "the user's own call"
has now actually been made. `tui.py` also calls `scrape_due_for_club()` directly for
whichever club it's showing — once on open and again on a timer while it stays
running — so a cron/launchd job isn't the only way this happens either; see that
module's own "Auto-refresh" docstring note. Between the two, history keeps
accumulating whether or not the TUI is ever opened on a given day, closing out the
"history can't be backfilled" risk this project has flagged since Phase 1 was first
scoped.
"""

from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import booking_watch, club_config, storage
from . import weather as weather_module
from .scraper import COURSE_ALIASES, LoginError, scrape_my_reservations, scrape_schedule

DATA_DIR = Path("data")

# See "Adjustable scrape interval" above — overridable per club via
# scrape_interval_minutes / scrape_interval_minutes_booked in its YAML.
DEFAULT_SCRAPE_INTERVAL_MINUTES = 360  # 6 hours
DEFAULT_SCRAPE_INTERVAL_MINUTES_BOOKED = 60  # 1 hour, once a booking exists for the date


def _db_path(club_id: str) -> Path:
    """One SQLite file per club (see storage.py's module docstring for why) — keyed by
    the club's own pc caddie numeric id, not the local clubs/*.yaml filename slug, since
    that id is what scraper.py's functions already take and is guaranteed unique."""
    return DATA_DIR / f"{club_id}.db"


def _attach_weather(schedule, config: dict, club_id: str, course: str, date: str) -> None:
    """Fetch the day's forecast + sun times and attach them to `schedule` in place —
    see the module docstring's "Weather" note for why this is best-effort, not fatal."""
    location = config.get("location", {})
    lat, lon = location.get("lat"), location.get("lon")
    if not lat or not lon:
        return  # still the club.example.yaml placeholder (0.0, 0.0) -- not configured
    try:
        schedule.weather = weather_module.fetch_hourly_weather(lat, lon, date)
        schedule.sun_times = weather_module.fetch_sun_times(lat, lon, date)
    except Exception as exc:  # noqa: BLE001 — a weather hiccup shouldn't sink the scrape
        print(f"[scrape_once] weather fetch failed for {club_id}/{course}/{date}: {exc}")


def run(
    club_id: str, course: str, date: str, config: dict | None = None, slug: str | None = None
) -> list[booking_watch.BookingChange]:
    """Scrape one club/course/date's schedule (plus its weather overlay) and persist
    it, best-effort syncing "My Reservations" too, then check any confirmed booking
    for that date against what changed since the previous scrape. Intended to be
    called by cron/launchd — returns whatever BookingChanges were detected, and also
    persists each one via `storage.save_booking_change()` (added 2026-09-06 alongside
    tui.py) — this runs as a separate process from the interactive TUI, so a detected
    change needs to survive somewhere for the TUI's home screen to read on next open,
    not just exist as an in-memory return value nothing else reads.

    `config`/`slug` are optional — `main()` already has each club's config and local
    clubs/*.yaml slug loaded from its own loop over `club_config.list_clubs()` and
    passes both straight through, rather than having `run()` redundantly re-derive
    them via `_club_config_and_slug_for_id()`. A caller (or test) with neither handy
    can omit both and `run()` looks them up itself the same way. `slug` specifically
    is what `_sync_my_reservations()` needs to resolve this club's credentials
    (`club_config.resolve_credentials()` is keyed by slug, not the numeric `club_id`
    used everywhere else here).
    """
    DATA_DIR.mkdir(exist_ok=True)
    db_path = _db_path(club_id)
    if config is None or slug is None:
        resolved_config, resolved_slug = _club_config_and_slug_for_id(club_id)
        config = config if config is not None else resolved_config
        slug = slug if slug is not None else resolved_slug

    # The schedule as of the *previous* scrape, if any — needed as booking_watch's
    # "baseline" before this new scrape becomes "latest". None on the very first scrape
    # for this course/date, which just means there's nothing yet to compare against.
    baseline = storage.load_latest_schedule(course, date, path=db_path)

    latest = scrape_schedule(club_id, course, date)
    _attach_weather(latest, config, club_id, course, date)
    storage.save_schedule(latest, path=db_path)

    _sync_my_reservations(club_id, slug, db_path)

    changes: list[booking_watch.BookingChange] = []
    if baseline is not None:
        confirmed = storage.load_confirmed_booking(course, date, path=db_path)
        if confirmed is not None and confirmed.time is not None:
            buffer_minutes = config.get("availability", {}).get("buffer_minutes", 20)
            holes_key = "eighteen" if confirmed.holes == 18 else "nine"
            round_duration = config.get("round_duration_minutes", {}).get(holes_key, 240)
            preferences = config.get("preferences", {})
            changes = booking_watch.check_for_changes(
                confirmed, baseline, latest, buffer_minutes, round_duration, preferences
            )
            for change in changes:
                storage.save_booking_change(
                    course=course,
                    date=date,
                    time=confirmed.time,
                    kind=change.kind,
                    message=change.message,
                    params=change.params,
                    path=db_path,
                )

    return changes


def _sync_my_reservations(club_id: str, slug: str | None, db_path: Path) -> None:
    """Best-effort: log in and save any confirmed bookings pc caddie shows for this
    account. Every failure mode here is deliberately swallowed, not propagated — see
    the module docstring's "Login" note for the full list of why. This is the
    login-dependent counterpart to the always-runs schedule scrape above."""
    if not slug:
        return  # can't resolve credentials (keyed by slug) without knowing it
    username, password = club_config.resolve_credentials(slug)
    if not username or not password:
        return  # PCC_USER/PCC_PASS not configured yet for this club
    try:
        for booking in scrape_my_reservations(club_id, username, password):
            storage.save_confirmed_booking(booking, path=db_path)
    except LoginError as exc:
        print(f"[scrape_once] login failed for {club_id}: {exc}")
    except NotImplementedError:
        pass  # a real booking exists but scraper.py can't parse its row markup yet


def _club_config_and_slug_for_id(club_id: str) -> tuple[dict, str | None]:
    """club_config.py keys clubs by their local clubs/*.yaml filename slug, not the pc
    caddie numeric club_id run() otherwise uses throughout — this bridges the two by
    matching on the config's own `club_id:` field, returning both the config and the
    slug (needed to resolve credentials via club_config.resolve_credentials(), itself
    keyed by slug). Returns ({}, None) if no saved club's config matches, which can
    legitimately happen in a test that calls run() directly without a real
    clubs/*.yaml on disk."""
    for slug in club_config.list_clubs():
        config = club_config.load_club_config(slug)
        if config.get("club_id") == club_id:
            return config, slug
    return {}, None


def _should_scrape(club_id: str, course: str, date: str, config: dict) -> bool:
    """Whether this course/date is actually due for a re-scrape yet, per the club's
    adjustable interval (shorter once a confirmed booking exists for that date) — see
    the module docstring's "Adjustable scrape interval". Lets `main()` be scheduled to
    run frequently without hammering the site on every course/date every time it fires.
    """
    db_path = _db_path(club_id)
    last = storage.last_scraped_at(course, date, path=db_path)
    if last is None:
        return True  # never scraped for this course/date -- always due

    confirmed = storage.load_confirmed_booking(course, date, path=db_path)
    is_booked = confirmed is not None and confirmed.time is not None
    interval_minutes = config.get(
        "scrape_interval_minutes_booked" if is_booked else "scrape_interval_minutes",
        DEFAULT_SCRAPE_INTERVAL_MINUTES_BOOKED if is_booked else DEFAULT_SCRAPE_INTERVAL_MINUTES,
    )

    elapsed_minutes = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 60
    return elapsed_minutes >= interval_minutes


def scrape_due_for_club(slug: str, config: dict) -> list[booking_watch.BookingChange]:
    """Scrape every course x day in `slug`'s `overview_days` window that's actually
    due per `_should_scrape()`, skipping the rest. Extracted 2026-09-07 from `main()`'s
    own per-club loop so `tui.py` can call this directly too — both once on open and
    again on a timer while it stays running (direct feedback: "I think hitting 'r'
    makes only sense as a manual override" — see that module's own "Auto-refresh"
    note) — without needing a separately-scheduled process for that to happen at all.
    One course/date's own failure is caught and skipped, not fatal, same stance as
    `main()`'s own: it must not stop the rest of this club's window, let alone (from
    `main()`) every other saved club."""
    club_id = config.get("club_id")
    if not club_id:
        print(f"[scrape_once] {slug}: no club_id set in its config, skipping")
        return []
    overview_days = config.get("overview_days", 5)
    today = date_cls.today()
    changes: list[booking_watch.BookingChange] = []
    for offset in range(overview_days):
        target_date = (today + timedelta(days=offset)).isoformat()
        for course in COURSE_ALIASES:
            if not _should_scrape(club_id, course, target_date, config):
                continue
            try:
                changes.extend(run(club_id, course, target_date, config, slug))
            except Exception as exc:  # noqa: BLE001 — one bad course/date must not
                # stop the rest of this club's window (or, from main(), every other
                # saved club).
                print(f"[scrape_once] {slug}/{course}/{target_date} failed: {exc}")
    return changes


def main() -> None:
    for slug in club_config.list_clubs():
        config = club_config.load_club_config(slug)
        scrape_due_for_club(slug, config)


if __name__ == "__main__":
    main()
