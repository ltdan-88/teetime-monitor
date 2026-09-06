"""Headless, no-TUI scrape-and-store — meant to run on a schedule (cron/launchd).

Exists because pc caddie hides past tee sheets: any day nobody opens the TUI is a gap in
history that can never be filled in later. Run this **more than once a day** (e.g.
morning and evening), not just daily — see ROADMAP.md Phase 1 "confirmed bookings,
automatic first, manual as fallback" for why once-daily leaves a same-day-booking gap.

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

`main()` loops every saved club (club_config.list_clubs()) and, for each, every course
x every day in that club's `overview_days` window — so one no-argument cron entry
covers everything currently configured, matching the docstring's original example:

    0 6,18 * * * cd /path/to/teetime-monitor && .venv/bin/python -m src.scrape_once

Not installed as an actual cron/launchd job by this session — that's a standing,
persistent change and stays the user's call to make (and verify paths/venv for)
themselves.
"""

from datetime import date as date_cls
from datetime import timedelta
from pathlib import Path

from . import booking_watch, club_config, storage
from .scraper import COURSE_ALIASES, scrape_my_reservations, scrape_schedule

DATA_DIR = Path("data")


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
                try:
                    run(club_id, course, target_date)
                except Exception as exc:  # noqa: BLE001 — one bad course/date/club
                    # must not stop every other one in an unattended run.
                    print(f"[scrape_once] {slug}/{course}/{target_date} failed: {exc}")


if __name__ == "__main__":
    main()
