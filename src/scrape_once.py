"""Headless, no-TUI scrape-and-store — meant to run on a schedule (cron/launchd).

Exists because pc caddie hides past tee sheets: any day nobody opens the TUI is a gap in
history that can never be filled in later. Run this **more than once a day** (e.g.
morning and evening), not just daily — see ROADMAP.md Phase 1 "confirmed bookings,
automatic first, manual as fallback" for why once-daily leaves a same-day-booking gap.

Also reads "My Reservations" (via scraper.scrape_my_reservations) to populate
confirmed_bookings automatically — revised 2026-09-05 once the real site turned out to
have a dedicated page for this. The TUI's manual `c` keybinding stays as a fallback
safety net for whatever timing gap this automatic read still misses, not removed.

Example cron entries (once implemented, adjust paths):
    0 6,18 * * * cd /path/to/teetime-monitor && .venv/bin/python -m src.scrape_once

NOT YET IMPLEMENTED.
"""

from . import storage
from .scraper import scrape_my_reservations, scrape_schedule


def run(club_id: str, course: str, date: str) -> None:
    """Scrape one club/course/date's schedule and "My Reservations", persisting both.
    Intended to be called by cron/launchd."""
    raise NotImplementedError("scrape_once.py is a stub — see ROADMAP.md Phase 1")


if __name__ == "__main__":
    raise NotImplementedError("scrape_once.py is a stub — see ROADMAP.md Phase 1")
