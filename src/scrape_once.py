"""Headless, no-TUI scrape-and-store — meant to run on a schedule (cron/launchd).

Exists because pc caddie hides past tee sheets: any day nobody opens the TUI is a gap in
history that can never be filled in later. Run this **more than once a day** (e.g.
morning and evening), not just daily — see ROADMAP.md Phase 1 "confirmed bookings,
automatic first, manual as fallback" for why once-daily leaves a same-day-booking gap.

Also reads "My Reservations" (via scraper.scrape_my_reservations) to populate
confirmed_bookings automatically — revised 2026-09-05 once the real site turned out to
have a dedicated page for this. The TUI's manual `c` keybinding stays as a fallback
safety net for whatever timing gap this automatic read still misses, not removed.

Runs booking_watch.check_for_changes() for every upcoming confirmed booking after each
scrape (added 2026-09-06) — comparing this scrape against the previous one for that
slot, so someone joining your flight or your buffer eroding gets caught as soon as the
next scheduled scrape sees it, not just whenever you happen to reopen the app. Any
detected BookingChange is stored for the TUI's home screen to show as a banner next
time it opens — this script itself never pushes a notification anywhere.

Example cron entries (once implemented, adjust paths):
    0 6,18 * * * cd /path/to/teetime-monitor && .venv/bin/python -m src.scrape_once

NOT YET IMPLEMENTED.
"""

from . import booking_watch, storage
from .scraper import scrape_my_reservations, scrape_schedule


def run(club_id: str, course: str, date: str) -> None:
    """Scrape one club/course/date's schedule and "My Reservations", persisting both,
    then check any upcoming confirmed booking for that date against what changed since
    the previous scrape. Intended to be called by cron/launchd."""
    raise NotImplementedError("scrape_once.py is a stub — see ROADMAP.md Phase 1")


if __name__ == "__main__":
    raise NotImplementedError("scrape_once.py is a stub — see ROADMAP.md Phase 1")
