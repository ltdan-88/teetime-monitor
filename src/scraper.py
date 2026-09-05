"""Playwright login + navigation for a pc caddie club portal (ROADMAP.md Phase 1).

NOT YET IMPLEMENTED. The real login form is unknown until the portal is inspected by
hand — that manual walkthrough (log in, find the username/password/submit fields, the
course-selector control, and whatever container holds the tee sheet) is the first task
here, before writing any scrape logic. Fill in SELECTORS below.

If the tee sheet renders inside an iframe, use `page.frame_locator(...)` instead of
top-level page selectors.

Deliberately *not* a full booking-table selector set (contrast with the original
docs/spec-v1.md plan). Revised 2026-09-05: parsing the actual slot rows — times,
occupancy, player names, any tournament/event note, the currently-available courses for
the Phase 0 27-hole rotation — is handed to `ai_assist.extract_schedule()` instead of
hand-mapped `slot_row`/`slot_time`/`slot_players` selectors. That table's exact markup,
cell merging, and booked-vs-free rendering are all unknowns too, and messy/varying HTML
into structured data is exactly the kind of step an LLM handles better than a selector
dict that breaks on the next site redesign. Login/navigation stays plain Playwright —
stable, simple, not a parsing problem.
"""

from . import ai_assist
from .models import Schedule

# Fill in once real selectors are found by manual inspection. Deliberately small — just
# enough to log in and scope down what gets handed to ai_assist.extract_schedule().
SELECTORS: dict[str, str] = {
    # "login_username": "",
    # "login_password": "",
    # "login_submit": "",
    # "course_selector": "",
    # "tee_sheet_container": "",
}


def scrape_schedule(course: str, date: str) -> Schedule:
    """Log in, navigate to the tee sheet, and extract one day's full schedule.

    Raises NotImplementedError until SELECTORS is filled in for login/navigation and
    ai_assist.extract_schedule() is wired up for parsing the result. Roughly:

        page = ...  # Playwright login + navigate using SELECTORS
        html = page.locator(SELECTORS["tee_sheet_container"]).inner_html()
        extracted = ai_assist.extract_schedule(html)
        return Schedule(date=date, course=course, slots=[...from extracted.slots...],
                         events=extracted.events, available_courses=extracted.available_courses)
    """
    raise NotImplementedError(
        "scraper.py is a stub — see the module docstring and ROADMAP.md Phase 1"
    )
