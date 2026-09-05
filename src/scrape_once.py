"""Headless, no-TUI scrape-and-store — meant to run on a schedule (cron/launchd).

Exists because pc caddie hides past tee sheets: any day nobody opens the TUI is a gap in
history that can never be filled in later. Running this once a day (or however often
makes sense) keeps the `scrapes` table current without relying on you remembering to
open the app. See ROADMAP.md Phase 1 "Known risks".

This does NOT confirm a booking on your behalf — confirmed_bookings is still a manual,
TUI-only action (src/tui.py), since only you know which slot was actually yours.

Example cron entry (once implemented, adjust paths):
    0 6 * * * cd /path/to/teetime-monitor && .venv/bin/python -m src.scrape_once

NOT YET IMPLEMENTED.
"""

from . import storage
from .scraper import scrape_schedule


def run(course: str, date: str) -> None:
    """Scrape one course/date and persist it. Intended to be called by cron/launchd."""
    raise NotImplementedError("scrape_once.py is a stub — see ROADMAP.md Phase 1")


if __name__ == "__main__":
    raise NotImplementedError("scrape_once.py is a stub — see ROADMAP.md Phase 1")
