"""Tee-sheet fetching + parsing for a pc caddie club portal (ROADMAP.md Phase 1).

Confirmed by a real walkthrough of the user's club (2026-09-05, see ROADMAP.md
"Confirmed pc caddie markup reference") — this is no longer guesswork the way the rest
of this module's history suggests:

- The tee sheet lives directly on pc caddie, not behind the club's marketing-site
  iframe: `https://www.pccaddie.net/clubs/<club_id>/app.php?cat=tt_timetable_course`.
  Date and course selection are a plain query string (`date=DAY|<date>&alias=ALIAS|
  <code>`) — confirmed working as a GET, no dropdown/form interaction needed at all.
- **No login needed** to read occupancy — only to see real names, "My Reservations,"
  and to book.
- Course selection is a fixed 3-option picker (confirmed aliases below), not a rotating
  list — the weekly A/B/C loop combination shows as a separate "Runde X+Y" banner.
- **Parsing turned out to be mostly deterministic, not messy** — revised 2026-09-05
  after actually inspecting the markup. `td.seats-free-N` gives the free-seat count
  directly; `tt-grau` vs `tt-rot` marks a normal vs. event-blocked row; time comes from
  `.pcco-tt-timestamp`. Plain code parses all of this — no AI call needed for it. The
  one genuinely ambiguous piece is a booking cell's `.tt-show-name` text, which can be
  the literal "Occupied" (anonymized member), an event/lesson/guest/sponsor label, an
  advance-booking-window notice (not real occupancy — see ROADMAP.md "Known risks"), or
  presumably a friend's real name (not yet observed). That one piece goes through
  `ai_assist.classify_booking_label()`.
- The "Overview Areas" page (`cat=tt_timetable_course_alias`) gives all 3 courses'
  aggregate occupied/free counts for one date in a single request — a better source for
  the Phase 4 multi-day overview than looping the per-course page 3x.

Still unverified: the real login form. If the tee sheet renders inside an iframe
elsewhere (unlikely, given the above), use `page.frame_locator(...)` instead of
top-level page selectors. Also worth reconsidering once implementation starts: since
these pages are confirmed server-rendered HTML (a plain same-origin `fetch()` returns
full markup), a full Playwright browser may only be needed for the login step itself —
log in once to get session cookies, then use a lighter HTTP client (`httpx`) for the
repeated scheduled scrapes.
"""

import re

from . import ai_assist
from .models import ConfirmedBooking, Schedule, Slot

# Confirmed 2026-09-05 by inspecting the real site — these are real values, not guesses.
COURSE_ALIASES: dict[str, str] = {
    "18 Loch Tee 1": "COUB",
    "9 Loch Tee 1": "COU1",
    "6 Loch Platz": "COU6",
}

TEE_SHEET_CATEGORY = "tt_timetable_course"
OVERVIEW_AREAS_CATEGORY = "tt_timetable_course_alias"
MY_RESERVATIONS_CATEGORY = "reservations"
EVENTS_CALENDAR_CATEGORY = "ts_calendar"
LESSONS_CALENDAR_CATEGORY = "ts_calendar_course"

# Confirmed 2026-09-05: td.seats-free-N is the free-seat count for that time, directly.
_SEATS_FREE_RE = re.compile(r"seats-free-(\d)")

# Confirmed 2026-09-05: the literal anonymized placeholder in a .tt-show-name span.
ANONYMIZED_LABEL = "Occupied"


def club_url(club_id: str, cat: str, date: str | None = None, alias: str | None = None) -> str:
    """Build a direct pc caddie URL, bypassing the marketing-site iframe wrapper
    entirely. `date` (YYYY-MM-DD) and `alias` (a COURSE_ALIASES value) are optional
    query params, confirmed to work as a plain GET with no form interaction needed."""
    url = f"https://www.pccaddie.net/clubs/{club_id}/app.php?cat={cat}"
    if date:
        url += f"&date=DAY|{date}"
    if alias:
        url += f"&alias=ALIAS|{alias}"
    return url


def parse_seats_free(time_cell_class: str) -> int | None:
    """Extract the free-seat count from a time cell's class attribute (e.g.
    "seats-free-2 tt-grau" -> 2). Pure deterministic parsing, no AI needed."""
    match = _SEATS_FREE_RE.search(time_cell_class)
    return int(match.group(1)) if match else None


# Fill in once the real login form is found by manual inspection — still genuinely
# unverified, unlike the rest of this module.
SELECTORS: dict[str, str] = {
    # "login_username": "",
    # "login_password": "",
    # "login_submit": "",
}


def scrape_schedule(club_id: str, course: str, date: str) -> Schedule:
    """Fetch the tee sheet (no login needed) and parse one day's full schedule.

    Raises NotImplementedError until the HTML-parsing plumbing (e.g. BeautifulSoup
    against table.pcco-tt-timetable) is wired up. Roughly:

        html = fetch(club_url(club_id, TEE_SHEET_CATEGORY, date, COURSE_ALIASES[course]))
        slots = []
        for row in soup.select("tr.pcco-tt-time-person"):
            time = row.select_one(".pcco-tt-timestamp").text
            free = parse_seats_free(row.select_one("td")["class"])
            players, block_reason = [], None
            for cell in row.select(".tt-show-name"):
                text = cell.text.strip()
                if text == ANONYMIZED_LABEL:
                    continue  # counted in `booked`, not a real name
                classified = ai_assist.classify_booking_label(text)  # only ambiguous text
                if classified.label == "friend_name":
                    players.append(classified.raw_text)
                elif classified.label != "anonymized":
                    block_reason = classified.raw_text  # event/lesson/guest/advance-window
            slots.append(Slot(time=time, booked=4 - free, capacity=4,
                               players=players, block_reason=block_reason))
        return Schedule(date=date, course=course, slots=slots,
                         available_courses=list(COURSE_ALIASES))
    """
    raise NotImplementedError(
        "scraper.py is a stub — see the module docstring and ROADMAP.md Phase 1"
    )


def scrape_overview_areas(club_id: str, date: str) -> dict[str, tuple[int, int]]:
    """Fetch the "Overview Areas" page — all 3 courses' (booked, capacity) totals for
    one date in a single request (ROADMAP.md Phase 4). No names, deterministic parsing
    of `i.fa-ban.occupied` / `i.fa-circle-o.bookable` icon counts per course."""
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
    Phase 1). Note: events also show directly in the tee sheet as a `tt-rot`-classed
    row carrying the event name, so this calendar is mainly useful for looking further
    ahead than the 5-day tee-sheet window reaches, not the only source."""
    raise NotImplementedError(
        "scraper.py is a stub — see the module docstring and ROADMAP.md Phase 1"
    )
