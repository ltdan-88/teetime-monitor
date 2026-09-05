"""Playwright login + tee sheet scrape for a pc caddie club portal.

NOT YET IMPLEMENTED. Per ROADMAP.md Phase 1 / docs/spec-v1.md "Known risks", the real
CSS selectors for the booking table are unknown until the portal is inspected by hand.
That manual walkthrough (log in, use browser dev tools to find the booking table, slot
cell, player-name, and course-selector selectors) is the first task here — before
writing any scrape logic, fill in SELECTORS below.

If the tee sheet renders inside an iframe, use `page.frame_locator(...)` instead of
top-level page selectors.

Also per ROADMAP.md Phase 0: this club plays 27 holes, rotating which 9-hole loops pair
up into "the 18-hole course" week to week. Whatever exposes that choice on the site
(dropdown, separate URLs, ...) is unverified — check during the same walkthrough, and
populate Schedule.available_courses with whatever's live for the requested date, rather
than trusting a hardcoded list.
"""

from .models import Schedule

# Fill in once real selectors are found by manual inspection.
SELECTORS: dict[str, str] = {
    # "login_username": "",
    # "login_password": "",
    # "login_submit": "",
    # "course_selector": "",
    # "booking_table": "",
    # "slot_row": "",
    # "slot_time": "",
    # "slot_players": "",
}


def scrape_schedule(course: str, date: str) -> Schedule:
    """Log in and pull one day's full tee sheet for one course.

    Raises NotImplementedError until SELECTORS is filled in and the scrape flow is
    written against the real portal.
    """
    raise NotImplementedError(
        "scraper.py is a stub — see the module docstring and ROADMAP.md Phase 1"
    )
