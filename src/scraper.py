"""Tee-sheet fetching + parsing for a pc caddie club portal (ROADMAP.md Phase 1).

Confirmed by a real walkthrough of the user's club (2026-09-05/06, see ROADMAP.md
"Confirmed pc caddie markup reference") — this is no longer guesswork the way the rest
of this module's history suggests, and as of 2026-09-06 `scrape_schedule()` is real,
tested code, verified against the live site:

- The tee sheet lives directly on pc caddie, not behind the club's marketing-site
  iframe: `https://www.pccaddie.net/clubs/<club_id>/app.php?cat=tt_timetable_course`.
  Date and course selection are a plain query string (`date=DAY|<date>&alias=ALIAS|
  <code>`) — confirmed working as a plain GET via `httpx`, no browser needed at all for
  this page.
- **No login needed** to read occupancy — only to see real names, "My Reservations,"
  and to book. Confirmed by fetching the live site with a bare `httpx.get()`, no
  cookies, no session.
- Course selection is a fixed 3-option picker (confirmed aliases below), not a rotating
  list — the weekly A/B/C loop combination shows as a separate "Runde X+Y" banner.
- **Each `<tr class="pcco-tt-time-person">` carries clean `data-*` attributes** —
  `data-time`, `data-status` (`bookable` / `occupied` / `block-time` / `disable-time`),
  and `data-seat_bookable` (the free-seat count, as an integer) — found 2026-09-06 while
  writing this parser, and a better source than the `seats-free-N` CSS class
  (`parse_seats_free()` below is kept as a documented fallback, not the primary path).
  `block-time` is a clean, direct signal for an event/lesson/guest-blocked row — no
  text-pattern matching needed to tell a block apart from real occupancy. `disable-time`
  was found later the same day, live: an "advance booking window" notice (e.g. "4 Tage
  im Voraus ab 20 Uhr buchbar") — also not real occupancy, just "not bookable yet." Both
  statuses are handled identically (`_NON_OCCUPANCY_STATUSES` below), matching how
  ROADMAP.md already designed callers to treat any `block_reason`.
- Free/empty player positions aren't individually rendered — pc caddie merges them into
  one trailing `<td colspan="N">` containing an *empty* `.tt-show-name` span. Iterating
  `.tt-show-name` spans and skipping any with blank text correctly gets just the real
  (occupied or blocked-reason) entries, no colspan arithmetic needed.
- Anonymized bookings show a placeholder in `.tt-show-name` instead of a name — four
  real variants confirmed live so far: German "Namensanzeige nach dem Login" (long form,
  the server's default locale), German "Belegt" (short form — only surfaced during an
  actual end-to-end run against the live site, not the earlier browser-based research
  pass), and English "Please login to see names" / "Occupied" (seen with the browser
  session set to EN). `KNOWN_ANONYMIZED_LABELS` below holds all four; anything else
  non-empty is treated as a real name (a friend), which held up across a full sweep of
  every date/course the live site currently offers (5 dates x 3 courses, 1092 slots,
  zero false positives after the fixes above). `ai_assist.classify_booking_label()`
  remains available as a fallback for a genuinely novel label (e.g. a language variant
  not yet seen) — not called from the normal path, since nothing observed so far has
  needed it, and gating a working scraper on an unimplemented AI call would be a bad
  trade for a case that hasn't actually occurred yet.
- The "Overview Areas" page (`cat=tt_timetable_course_alias`) gives all 3 courses'
  aggregate occupied/free counts for one date in a single request — a better source for
  the Phase 4 multi-day overview than looping the per-course page 3x.

The real login form, walked through live 2026-09-06 (the user logging in themselves —
Claude never sees or handles the password; see `login()` below): a plain HTML form,
no JavaScript, no CSRF token. `POST` to `.../app.php?cat=start` with
`service=login&rq[login]=<username>&rq[password]=<password>` sets a session cookie;
an `httpx.Client` (its own cookie jar carries that session across requests) is all
that's needed — **no Playwright/browser required for login either**, same conclusion
as `scrape_schedule()` already reached. `SELECTORS` (a Playwright selector dict) is
gone — there was never a need for it once the form turned out this simple.

`scrape_my_reservations()` is fully implemented as of 2026-09-07, once a real demo
booking existed to inspect: a populated row lives in `table.meine-buchungen`, one
`<tr>` per booking, `<td>`s for Details/Persons/Actions. The Details cell's text nodes
(split on `<br>`) are, in order: a "day, date, time" line, the club name, then the
course name last — confirmed to be exactly one of `COURSE_ALIASES`'s own keys (e.g.
"6 Loch Platz"). Confirmed in both languages: English "Mon, 2026-09-07, 19:50 o'clock"
(already ISO) and German "Mo, 07.09.2026, 19:50 Uhr" (DD.MM.YYYY, needs reordering).
The Persons cell (names, "*" apparently marking the booking's own account) isn't
parsed — `ConfirmedBooking` has no players field. Still raises `NotImplementedError`
for anything that doesn't match this confirmed shape, rather than guessing at
unseen markup — see `_parse_my_reservations_html()`.
"""

import re
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup, Tag

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

# Every player position is 1 of 4 on this club's tee sheet — confirmed via the
# "- 1 -".."- 4 -" column headers on the real page.
SEATS_PER_SLOT = 4

# Confirmed 2026-09-05: td.seats-free-N is the free-seat count for that time, directly.
# Kept as a fallback — data-seat_bookable (read directly off the <tr>) is the primary
# source, found 2026-09-06 and more robust than parsing a CSS class string.
_SEATS_FREE_RE = re.compile(r"seats-free-(\d)")

# Confirmed anonymized-placeholder text, all variants observed live so far. Anything
# else non-empty in a .tt-show-name span (on a non-blocked row) is treated as a real
# name. "Belegt" was caught by an actual end-to-end run against the live site
# (2026-09-06) showing up as a false-positive "player name" before being added here —
# exactly the risk the module docstring already flagged; ai_assist.classify_booking_label()
# is the intended fallback for the next variant that isn't in this set yet.
KNOWN_ANONYMIZED_LABELS = {
    "Namensanzeige nach dem Login",  # German (long form), the server's default locale
    "Belegt",  # German (short form) — caught live 2026-09-06
    "Please login to see names",  # English, seen when the browser session was set to EN
    "Occupied",  # English, logged in but not a friend — seen 2026-09-05
}

# data-status values confirmed 2026-09-06.
STATUS_BOOKABLE = "bookable"  # at least one seat free (data-seat_bookable > 0)
STATUS_OCCUPIED = "occupied"  # fully booked (data-seat_bookable == 0)
STATUS_BLOCK_TIME = "block-time"  # event/lesson/guest block — not real occupancy
STATUS_DISABLE_TIME = "disable-time"  # advance-booking-window notice — also not real
# occupancy, just "not bookable yet" (see ROADMAP.md "Known risks"). Caught live
# 2026-09-06: without this, "4 Tage im Voraus ab 20 Uhr buchbar (KP)" fell through to
# being treated as a real player name. Handled identically to block-time below — both
# map to Slot.block_reason, and ROADMAP.md already designed for callers to treat any
# block_reason as "not real occupancy," not distinguishing which kind.
_NON_OCCUPANCY_STATUSES = {STATUS_BLOCK_TIME, STATUS_DISABLE_TIME}


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
    "seats-free-2 tt-grau" -> 2). Fallback only — see module docstring for why
    data-seat_bookable is preferred."""
    match = _SEATS_FREE_RE.search(time_cell_class)
    return int(match.group(1)) if match else None


def _parse_slot_row(row: Tag) -> Slot:
    """Parse one <tr class="pcco-tt-time-person"> into a Slot. Pure function over an
    already-parsed row — no I/O — so it's tested directly against fixture HTML."""
    time = row.get("data-time")
    status = row.get("data-status")
    seat_bookable_attr = row.get("data-seat_bookable")

    if seat_bookable_attr is not None:
        free = int(seat_bookable_attr)
    else:
        # Fallback: read the time cell's class instead (see parse_seats_free).
        time_cell = row.find("td")
        classes = " ".join(time_cell.get("class", [])) if time_cell else ""
        free = parse_seats_free(classes) or 0

    booked = SEATS_PER_SLOT - free

    if status in _NON_OCCUPANCY_STATUSES:
        reason_span = row.select_one(".tt-show-name")
        reason = reason_span.get_text(strip=True) if reason_span else None
        return Slot(time=time, booked=booked, capacity=SEATS_PER_SLOT, block_reason=reason)

    players: list[str] = []
    for span in row.select(".tt-show-name"):
        text = span.get_text(strip=True)
        if not text:
            continue  # the merged empty-seat placeholder — not a real position
        if text in KNOWN_ANONYMIZED_LABELS:
            continue  # anonymized member booking — already counted in `booked`
        players.append(text)  # not a known placeholder — presumably a friend's real name

    return Slot(time=time, booked=booked, capacity=SEATS_PER_SLOT, players=players)


def parse_schedule_html(html: str, date: str, course: str) -> Schedule:
    """Parse a fetched tee-sheet page into a Schedule. Pure function, no I/O — the
    network fetch lives in scrape_schedule() so this half is directly testable against
    fixture HTML without hitting the real site."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.pcco-tt-timetable")
    slots = [_parse_slot_row(row) for row in table.select("tr.pcco-tt-time-person")] if table else []
    events = sorted({s.block_reason for s in slots if s.block_reason})
    return Schedule(
        date=date,
        course=course,
        slots=slots,
        events=events,
        available_courses=list(COURSE_ALIASES),
    )


class LoginError(Exception):
    """Raised when login() can't establish an authenticated session — wrong
    credentials, or the site's response no longer looks like the confirmed form."""


# The exact field name from the real login form (see module docstring) — specific
# enough that its presence in a response means "still showing the login form," i.e.
# login didn't succeed. Doubling as the login POST's own field name below.
_PASSWORD_FIELD = "rq[password]"


def login(club_id: str, username: str, password: str) -> httpx.Client:
    """Log in and return an authenticated httpx.Client — its cookie jar carries the
    session for every subsequent request made with it (pass it to scrape_my_reservations()
    and friends, or use it directly). Confirmed 2026-09-06 by inspecting the real login
    form live (see module docstring): a plain POST, no JS, no CSRF token.

    Raises LoginError if the response still looks like the login form afterward. This
    project's own rule: Claude never enters or handles a real password itself — this
    function exists so the *user's own* running instance of the tool can log in with
    credentials *they* put in `.env` (see club_config.resolve_credentials()), not
    something invoked with real credentials during development.
    """
    client = httpx.Client(timeout=15, follow_redirects=True)
    url = club_url(club_id, "start")
    response = client.post(url, data={"service": "login", "rq[login]": username, _PASSWORD_FIELD: password})
    response.raise_for_status()
    if _PASSWORD_FIELD in response.text:
        client.close()
        raise LoginError(f"Login failed for club {club_id} — check PCC_USER/PCC_PASS in .env.")
    return client


# Confirmed 2026-09-07 against a real demo booking, both languages (see module
# docstring). English is already ISO; German is DD.MM.YYYY and needs reordering.
_RESERVATION_DATETIME_RE_EN = re.compile(r"(\d{4}-\d{2}-\d{2}),\s*(\d{2}:\d{2})\s*o'clock")
_RESERVATION_DATETIME_RE_DE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4}),\s*(\d{2}:\d{2})\s*Uhr")


def _parse_reservation_datetime(text: str) -> tuple[str, str]:
    """Pull (date, time) out of a "My Reservations" row's date/time line."""
    match = _RESERVATION_DATETIME_RE_EN.search(text)
    if match:
        return match.group(1), match.group(2)
    match = _RESERVATION_DATETIME_RE_DE.search(text)
    if match:
        day, month, year, time = match.groups()
        return f"{year}-{month}-{day}", time
    raise NotImplementedError(
        f"scrape_my_reservations() can't parse this row's date/time text: {text!r} — "
        "see scraper.py's module docstring."
    )


def _holes_from_course_label(course: str) -> int | None:
    """"18 Loch Tee 1" -> 18, "6 Loch Platz" -> 6 — every confirmed COURSE_ALIASES
    label starts with its hole count."""
    match = re.match(r"(\d+)", course)
    return int(match.group(1)) if match else None


def _parse_my_reservations_html(html: str) -> list[ConfirmedBooking]:
    """Parse "My Reservations" into ConfirmedBooking rows. Confirmed live against a
    real demo booking (2026-09-07) as well as the empty state (2026-09-06 walkthrough,
    "No bookings found") — see module docstring for the confirmed row shape. Raises
    NotImplementedError for anything that doesn't match either confirmed shape, rather
    than guessing at unseen markup and silently dropping or mis-parsing a real booking."""
    if "No bookings found" in html or "Keine Buchungen gefunden" in html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="meine-buchungen")
    if table is None:
        raise NotImplementedError(
            "scrape_my_reservations() found neither the confirmed empty-state text "
            "nor the confirmed 'meine-buchungen' table — the real markup may have "
            "changed. See scraper.py's module docstring."
        )

    bookings = []
    for row in table.find_all("tr"):
        details_cell = row.find("td")
        if details_cell is None:
            continue  # the header row uses <th>, not <td> -- not a booking row
        lines = list(details_cell.stripped_strings)
        if len(lines) < 2:
            raise NotImplementedError(
                f"scrape_my_reservations() got an unrecognized Details cell: {lines!r} "
                "— see scraper.py's module docstring."
            )
        date, time = _parse_reservation_datetime(lines[0])
        course = lines[-1]  # confirmed to always be one of COURSE_ALIASES's own keys
        bookings.append(
            ConfirmedBooking(
                date=date,
                course=course,
                time=time,
                holes=_holes_from_course_label(course),
                source="my_reservations",
                confirmed_at=datetime.now(timezone.utc).isoformat(),
            )
        )
    return bookings


def scrape_schedule(club_id: str, course: str, date: str) -> Schedule:
    """Fetch the tee sheet (no login needed) and parse one day's full schedule.

    Implemented and verified 2026-09-06 against the real site (Musterhausen, club id
    0000001) — a plain `httpx.get()`, no Playwright/browser required for this call.
    """
    alias = COURSE_ALIASES.get(course)
    if alias is None:
        raise ValueError(f"Unknown course {course!r} — expected one of {list(COURSE_ALIASES)}")
    url = club_url(club_id, TEE_SHEET_CATEGORY, date=date, alias=alias)
    response = httpx.get(url, timeout=15, follow_redirects=True)
    response.raise_for_status()
    return parse_schedule_html(response.text, date=date, course=course)


def scrape_overview_areas(club_id: str, date: str) -> dict[str, tuple[int, int]]:
    """Fetch the "Overview Areas" page — all 3 courses' (booked, capacity) totals for
    one date in a single request (ROADMAP.md Phase 4). No names, deterministic parsing
    of `i.fa-ban.occupied` / `i.fa-circle-o.bookable` icon counts per course."""
    raise NotImplementedError(
        "scraper.py is a stub — see the module docstring and ROADMAP.md Phase 1"
    )


def scrape_my_reservations(club_id: str, username: str, password: str) -> list[ConfirmedBooking]:
    """Log in and read "My Reservations" — the automatic primary source for
    confirmed_bookings (ROADMAP.md Phase 1). Needs login, unlike scrape_schedule().

    Implemented 2026-09-06, fully confirmed 2026-09-07 against a real demo booking —
    see login() and _parse_my_reservations_html() for the confirmed row shape.
    `username`/`password` are the caller's responsibility to resolve
    (club_config.resolve_credentials()) — this function doesn't read `.env` itself,
    keeping it decoupled from local config file layout.
    """
    client = login(club_id, username, password)
    try:
        url = club_url(club_id, MY_RESERVATIONS_CATEGORY)
        response = client.get(url)
        response.raise_for_status()
        return _parse_my_reservations_html(response.text)
    finally:
        client.close()


def scrape_events_calendar(club_id: str, year: int) -> list[str]:
    """Read the dedicated tournaments/events calendar for a club/year (ROADMAP.md
    Phase 1). Note: events also show directly in the tee sheet as a `block-time` row
    carrying the event name (see parse_schedule_html), so this calendar is mainly
    useful for looking further ahead than the 5-day tee-sheet window reaches, not the
    only source."""
    raise NotImplementedError(
        "scraper.py is a stub — see the module docstring and ROADMAP.md Phase 1"
    )
