"""Playwright navigation + scraping for a pc caddie club portal (ROADMAP.md Phase 1).

Confirmed by a real walkthrough of the user's club (2026-09-05, see ROADMAP.md "Live
site findings") — this is no longer guesswork the way the rest of this module's history
suggests:

- The tee sheet lives directly on pc caddie, not behind the club's marketing-site
  iframe: `https://www.pccaddie.net/clubs/<club_id>/app.php?cat=tt_timetable_course`.
  Navigate straight there.
- **No login needed** to read occupancy (booked/free counts per slot) — only to see
  player names, "My Reservations," or the events calendar.
- Course selection is a fixed 3-option `<select>` (confirmed values below), not a
  rotating list — the weekly A/B/C loop combination shows as a separate "Runde X+Y"
  banner on the page instead.
- Player names are anonymized as "Member (H.H)" (their handicap) unless the player is
  on your pc caddie friends list, in which case their real name shows instead — see
  ai_assist.extract_schedule()'s job of telling these apart.

Still unverified: the real login form, and the exact markup of a booked slot cell,
"My Reservations," and the events calendar — that's the remaining manual walkthrough,
now much narrower. If the tee sheet renders inside an iframe elsewhere (unlikely, given
the above), use `page.frame_locator(...)` instead of top-level page selectors.

Deliberately *not* a full booking-table selector set (contrast with the original
docs/spec-v1.md plan) — parsing the actual slot rows is handed to
`ai_assist.extract_schedule()` instead of hand-mapped `slot_row`/`slot_time`/
`slot_players` selectors, since that markup's exact structure, cell merging, and
booked-vs-free rendering are still unknowns, and messy/varying HTML into structured
data is exactly the kind of step an LLM handles better than a selector dict that breaks
on the next site redesign. Login/navigation stays plain Playwright — stable, simple,
not a parsing problem.
"""

from . import ai_assist
from .models import ConfirmedBooking, Schedule

# Confirmed 2026-09-05 by inspecting the real site — these are real values, not guesses.
COURSE_ALIASES: dict[str, str] = {
    "18 Loch Tee 1": "COUB",
    "9 Loch Tee 1": "COU1",
    "6 Loch Platz": "COU6",
}

TEE_SHEET_CATEGORY = "tt_timetable_course"
MY_RESERVATIONS_CATEGORY = "reservations"
EVENTS_CALENDAR_CATEGORY = "ts_calendar"


def club_url(club_id: str, cat: str) -> str:
    """Build a direct pc caddie URL for one club/category, bypassing the marketing-site
    iframe wrapper entirely."""
    return f"https://www.pccaddie.net/clubs/{club_id}/app.php?cat={cat}"


# Fill in once real selectors are found by manual inspection. Deliberately small — just
# enough to log in and scope down what gets handed to ai_assist.extract_schedule().
SELECTORS: dict[str, str] = {
    # "login_username": "",
    # "login_password": "",
    # "login_submit": "",
    # "date_selector": "",       # confirmed present, real selector still unmapped
    # "course_selector": "",     # confirmed present, real selector still unmapped
    # "tee_sheet_container": "",
}


def scrape_schedule(club_id: str, course: str, date: str) -> Schedule:
    """Navigate to the tee sheet (no login needed) and extract one day's full schedule.

    Raises NotImplementedError until SELECTORS is filled in and
    ai_assist.extract_schedule() is wired up for parsing the result. Roughly:

        page.goto(club_url(club_id, TEE_SHEET_CATEGORY))
        # select date + course (COURSE_ALIASES[course]) via SELECTORS, click Show
        html = page.locator(SELECTORS["tee_sheet_container"]).inner_html()
        extracted = ai_assist.extract_schedule(html)
        return Schedule(date=date, course=course, slots=[...from extracted.slots...],
                         available_courses=list(COURSE_ALIASES))
    """
    raise NotImplementedError(
        "scraper.py is a stub — see the module docstring and ROADMAP.md Phase 1"
    )


def scrape_my_reservations(club_id: str) -> list[ConfirmedBooking]:
    """Log in and read "My Reservations" — the automatic primary source for
    confirmed_bookings (ROADMAP.md Phase 1). Needs login, unlike scrape_schedule().
    """
    raise NotImplementedError(
        "scraper.py is a stub — see the module docstring and ROADMAP.md Phase 1"
    )


def scrape_events_calendar(club_id: str, year: int) -> list[str]:
    """Read the dedicated tournaments/events calendar for a club/year (ROADMAP.md
    Phase 1) — the source for tournament/event flags, not a tee-sheet icon."""
    raise NotImplementedError(
        "scraper.py is a stub — see the module docstring and ROADMAP.md Phase 1"
    )
