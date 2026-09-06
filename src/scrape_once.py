"""Headless, no-TUI scrape-and-store — meant to run on a schedule (cron/launchd).

Exists because pc caddie hides past tee sheets: any day nobody opens the TUI is a gap in
history that can never be filled in later.

`run()` is real as of 2026-09-06 for the part that doesn't need login: scrape one
club/course/date's tee sheet and save it via storage.py. The login-dependent half —
reading "My Reservations" to populate confirmed_bookings automatically, and then
running booking_watch.check_for_changes() against a confirmed booking — degrades
gracefully instead of crashing the whole run: both are wrapped so a still-
NotImplementedError call (scrape_my_reservations, the real login form itself, is
explicitly deferred until the user can walk through it live) is caught and skipped,
not fatal. This matters specifically because `main()` below is meant to run
unattended — one club's login step not existing yet shouldn't stop every other
club/course/date in the same run from being scraped and saved.

Once scrape_my_reservations() is real, the graceful-skip paths below start doing
real work with no further changes needed here — that's the point of catching
NotImplementedError specifically rather than a bare `except Exception`.

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

`main()` loops every saved club (club_config.list_clubs()) and, for each, every course
x every day in that club's `overview_days` window — so one cron entry with no
arguments covers everything currently configured, throttled per course/date as above.

Not installed as an actual cron/launchd job by this session — that's a standing,
persistent change and stays the user's call to make (and verify paths/venv for)
themselves.
"""

from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import booking_watch, club_config, storage
from .scraper import COURSE_ALIASES, scrape_my_reservations, scrape_schedule

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


def run(club_id: str, course: str, date: str) -> list[booking_watch.BookingChange]:
    """Scrape one club/course/date's schedule and persist it, best-effort persisting
    "My Reservations" too, then check any confirmed booking for that date against what
    changed since the previous scrape. Intended to be called by cron/launchd — returns
    whatever BookingChanges were detected (currently always empty until
    booking_watch.check_for_changes() itself is implemented) so a caller/test can
    inspect what happened without needing separate storage for it yet.
    """
    DATA_DIR.mkdir(exist_ok=True)
    db_path = _db_path(club_id)

    # The schedule as of the *previous* scrape, if any — needed as booking_watch's
    # "baseline" before this new scrape becomes "latest". None on the very first scrape
    # for this course/date, which just means there's nothing yet to compare against.
    baseline = storage.load_latest_schedule(course, date, path=db_path)

    latest = scrape_schedule(club_id, course, date)
    storage.save_schedule(latest, path=db_path)

    # Needs login — not yet implemented (the real login form is still genuinely
    # unverified, see scraper.py's SELECTORS). Caught specifically so this one
    # still-stubbed piece doesn't take down the whole scheduled run.
    try:
        for booking in scrape_my_reservations(club_id):
            storage.save_confirmed_booking(booking, path=db_path)
    except NotImplementedError:
        pass

    changes: list[booking_watch.BookingChange] = []
    if baseline is not None:
        confirmed = storage.load_confirmed_booking(course, date, path=db_path)
        if confirmed is not None and confirmed.time is not None:
            config = _club_config_for_id(club_id)
            buffer_minutes = config.get("availability", {}).get("buffer_minutes", 20)
            holes_key = "eighteen" if confirmed.holes == 18 else "nine"
            round_duration = config.get("round_duration_minutes", {}).get(holes_key, 240)
            try:
                changes = booking_watch.check_for_changes(
                    confirmed, baseline, latest, buffer_minutes, round_duration
                )
            except NotImplementedError:
                pass

    return changes


def _club_config_for_id(club_id: str) -> dict:
    """club_config.py keys clubs by their local clubs/*.yaml filename slug, not the pc
    caddie numeric club_id run() otherwise uses throughout — this bridges the two by
    matching on the config's own `club_id:` field. Returns {} (falling back to run()'s
    hardcoded defaults above) if no saved club's config matches, which can legitimately
    happen in a test that calls run() directly without a real clubs/*.yaml on disk."""
    for slug in club_config.list_clubs():
        config = club_config.load_club_config(slug)
        if config.get("club_id") == club_id:
            return config
    return {}


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


def main() -> None:
    for slug in club_config.list_clubs():
        config = club_config.load_club_config(slug)
        club_id = config.get("club_id")
        if not club_id:
            print(f"[scrape_once] {slug}: no club_id set in its config, skipping")
            continue
        overview_days = config.get("overview_days", 5)
        today = date_cls.today()
        for offset in range(overview_days):
            target_date = (today + timedelta(days=offset)).isoformat()
            for course in COURSE_ALIASES:
                if not _should_scrape(club_id, course, target_date, config):
                    continue
                try:
                    run(club_id, course, target_date)
                except Exception as exc:  # noqa: BLE001 — one bad course/date/club
                    # must not stop every other one in an unattended run.
                    print(f"[scrape_once] {slug}/{course}/{target_date} failed: {exc}")


if __name__ == "__main__":
    main()
