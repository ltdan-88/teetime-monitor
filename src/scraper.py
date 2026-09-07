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
- Course selection is a fixed picker (not a rotating list — the weekly A/B/C loop
  combination shows as a separate "Runde X+Y" banner), but **the options themselves
  are per-club, not universal**: `COURSE_ALIASES` below is Musterhausen's own
  confirmed 3-option set (18/9/6-hole, codes COUB/COU1/COU6). Confirmed wrong for a
  second real club added 2026-09-07 ("Golf Club Sonnenberg e.V.") — five options with
  entirely different codes (A001/1810/1811/0901/0601) — see `fetch_course_aliases()`
  for the fix: read this same club's own "Area" `<select>` on demand instead of
  assuming any fixed set.
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

`fetch_club_directory()` (added 2026-09-07) reads "My Golf"'s `<select
id="user_association_club">` — the entire pc caddie platform directory, rendered
server-side rather than fetched per keystroke (confirmed via `read_network_requests`
while inspecting live: nothing fires as you type in the site's own search box). This
is what backs `club_picker.py`'s searchable "add a club by name" screen — see that
module and `_parse_club_directory_html()`.

**Cross-club validation (2026-09-07)** — everything above was written against two real
clubs, so it was checked against a spread of 45 more, sampled across German, Swiss,
Luxembourgish and Italian-speaking clubs by probing public tee-sheet URLs (club ids
are `0` + country calling code + a club number: 049 = DE, 041 = CH, 0352 = LU). What
held, and what didn't:

- Held everywhere: `table.pcco-tt-timetable`, `tr.pcco-tt-time-person`, and the
  `data-time` / `data-status` / `data-seat_bookable` attributes — present and populated
  on all 3227 rows scanned, no exceptions. Seats per slot was 4 on every club (now read
  off the header anyway, see `_capacity_from_table()`).
- **Nearly half of clubs have no course selector at all** — 18 of the 39 with a working
  tee sheet. They run a single course and address it with no `alias` parameter. This
  had been a hard `NotImplementedError`, i.e. the tool was unusable for 46% of clubs.
- **Six clubs publish no tee sheet at all.** Now `NoTeeSheetError`, a plain explainable
  state rather than a crash.
- **Four more anonymized-placeholder variants** (French and Italian, long and short
  form) — without them, every occupied slot at a Swiss or Luxembourgish club was
  reporting the placeholder text as a player's real name.
- **Course notes were being read as player names** on 27 of 45 clubs — see the colspan
  rule in `_parse_slot_row()`, the structural fix for it.
- **The bookable-date window is wildly per-club**: 1 to 31 days across the sample, most
  commonly 8, against a configured default of 5 — see `fetch_available_dates()`.

Two limits of that sweep, stated rather than glossed: it was read-only and anonymous
(so it says nothing about how a *friend's* real name renders — still unconfirmed, see
ROADMAP.md), and 45 clubs is a sample, not the whole platform. It covers the failure
modes that actually showed up, not a proof that none remain.
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
CLUB_DIRECTORY_CATEGORY = "golf"  # "My Golf" -- see fetch_club_directory() below

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
    # German — the server's default locale
    "Namensanzeige nach dem Login",  # long form
    "Belegt",  # short form — caught live 2026-09-06
    # English — seen with the browser session set to EN
    "Please login to see names",  # long form
    "Occupied",  # short form, logged in but not a friend — seen 2026-09-05
    # French / Italian — added 2026-09-07 by the cross-club sweep (see module
    # docstring's "Cross-club validation"). Swiss and Luxembourgish clubs serve the
    # same page in their own locale, and without these four the placeholder text was
    # being read as a real player's name on every occupied slot those clubs have.
    "Veuillez faire le login pour visualiser les noms",  # French, long form
    "Occupe",  # French, short form
    "Per visualizzare i nomi bisogna fare il login",  # Italian, long form
    "Occupato",  # Italian, short form
}

# data-status values confirmed 2026-09-06.
STATUS_BOOKABLE = "bookable"  # at least one seat free (data-seat_bookable > 0)
STATUS_OCCUPIED = "occupied"  # fully booked (data-seat_bookable == 0)
STATUS_PAST_TIME = "past-time"  # already-passed slot on today's own sheet — found by
# the 2026-09-07 cross-club sweep, where it was by far the most common status of all
# (2950 of 3227 rows scanned). Not a block: `data-seat_bookable` stays accurate on
# these rows, so they parse exactly like a normal row and are deliberately *not* in
# `_NON_OCCUPANCY_STATUSES` — a past slot that really was fully booked is real history,
# which is the whole point of storing every scrape. tui.py dims them at display time.
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


def _parse_slot_row(row: Tag, capacity: int = SEATS_PER_SLOT, authenticated: bool = False) -> Slot:
    """Parse one <tr class="pcco-tt-time-person"> into a Slot. Pure function over an
    already-parsed row — no I/O — so it's tested directly against fixture HTML.

    `capacity` is this club's own seats-per-slot, read off its table header by
    `_capacity_from_table()` rather than assumed — see `SEATS_PER_SLOT`.

    `authenticated` says whether the page was fetched with a logged-in session. It
    decides what an unrecognized seat-cell text means, which is genuinely ambiguous
    without it: logged in it can be a friend's real name (the whole point of
    `players`), logged out it never can be, because pc caddie only reveals names to a
    logged-in friend. `scrape_schedule()` fetches anonymously and so passes False —
    which is why `players` is always empty in practice today. Wiring an authenticated
    tee-sheet fetch through is what would make friend detection real; see ROADMAP.md's
    still-open "what an actual friend's booking looks like" risk.

    **The colspan rule** (confirmed 2026-09-07 across 39 real clubs, see the module
    docstring's "Cross-club validation"): a genuinely occupied seat is its own
    `<td>` with *no* `colspan`, one per booked player. pc caddie merges whatever seats
    are still free into a single trailing `<td colspan="N">` — and that merged cell is
    very often *not* empty, carrying a course note instead ("Nur für Mitglieder",
    "Platzpflege", "Greenfee CHF 140.-", "Keine Startzeit erforderlich!"). The earlier
    version of this function only skipped that cell when its text was blank, so on 27
    of the 45 clubs swept, ordinary course notes were being recorded as players' real
    names. Reading only non-colspan cells as seats fixes that structurally, rather than
    by trying to keep a list of every note any club might write."""
    time = row.get("data-time")
    status = row.get("data-status")
    seat_bookable_attr = row.get("data-seat_bookable")

    if seat_bookable_attr is not None:
        try:
            free = int(seat_bookable_attr)
        except ValueError:
            free = 0
    else:
        # Fallback: read the time cell's class instead (see parse_seats_free).
        time_cell = row.find("td")
        classes = " ".join(time_cell.get("class", [])) if time_cell else ""
        free = parse_seats_free(classes) or 0

    # `data-seat_bookable` can go negative on a genuinely over-full slot — found
    # 2026-09-07 on two real clubs, one reporting "-12" on a row that visibly showed
    # its 4 seats all taken (a waiting list, or a group booked past the normal seat
    # count). Taken at face value that produced a nonsensical "16/4 booked"; clamping
    # to the real seat range reports it as the full slot it plainly is.
    free = max(0, min(capacity, free))
    booked = capacity - free

    if status in _NON_OCCUPANCY_STATUSES:
        reason_span = row.select_one(".tt-show-name")
        reason = reason_span.get_text(strip=True) if reason_span else None
        return Slot(time=time, booked=booked, capacity=capacity, block_reason=reason)

    players: list[str] = []
    note: str | None = None
    for cell in row.find_all("td"):
        span = cell.select_one(".tt-show-name")
        if span is None:
            continue
        text = span.get_text(strip=True)
        if not text:
            continue
        if cell.get("colspan") is not None:
            # The merged free-seat cell — a course note at most, never a player.
            note = text
            continue
        if text in KNOWN_ANONYMIZED_LABELS:
            continue  # anonymized member booking — already counted in `booked`
        if authenticated:
            players.append(text)  # a friend's real name — only ever visible logged in
        else:
            # A real seat cell whose text isn't a known placeholder, read anonymously.
            # pc caddie only ever reveals real names to a logged-in friend (confirmed
            # on the site's own account page: "Only names of friends are visible to
            # you"), so this can't be a name — it's a club writing a note into a seat
            # cell ("Greenfee CHF 140.-", "Maximale Handicap-Summe 144", "Nur für
            # Mitglieder"). Recorded as a note, for the same reason `block_reason`
            # exists. Across the 79-club sweep this rule turned ~50 fabricated
            # "players" into notes and lost no real names, because there were none to
            # lose: `scrape_schedule()` doesn't log in.
            note = text

    return Slot(time=time, booked=booked, capacity=capacity, players=players, block_reason=note)


_SEAT_HEADER_RE = re.compile(r"^-\s*\d+\s*-$")


def _capacity_from_table(table: Tag) -> int:
    """Seats per slot for this club, counted off its own table header ("Zeit | - 1 - |
    - 2 - | - 3 - | - 4 -"). Locale-independent — the header's first cell is localized
    ("Zeit"/"Ora"/"Heure") but the seat columns are just numbers in dashes.

    Every one of the 39 real clubs swept 2026-09-07 turned out to be 4, so this
    currently always agrees with `SEATS_PER_SLOT` — read from the page anyway rather
    than hardcoded, since it's the club's own fact and costs nothing to check, and
    falls back to `SEATS_PER_SLOT` if the header isn't recognizable."""
    header = table.find("tr")
    if header is None:
        return SEATS_PER_SLOT
    seats = sum(
        1 for cell in header.find_all(["th", "td"]) if _SEAT_HEADER_RE.match(cell.get_text(strip=True))
    )
    return seats or SEATS_PER_SLOT


def parse_schedule_html(
    html: str,
    date: str,
    course: str,
    available_courses: list[str] | None = None,
    authenticated: bool = False,
) -> Schedule:
    """Parse a fetched tee-sheet page into a Schedule. Pure function, no I/O — the
    network fetch lives in scrape_schedule() so this half is directly testable against
    fixture HTML without hitting the real site.

    `available_courses` (added 2026-09-07, see `fetch_course_aliases()`'s own
    docstring for why) defaults to `COURSE_ALIASES` — Musterhausen's own confirmed
    set — only for backward compatibility with an older caller that doesn't pass a
    real club's own list; `scrape_schedule()` itself always passes the club's actual
    course names now."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.pcco-tt-timetable")
    if table is None:
        slots = []
    else:
        capacity = _capacity_from_table(table)
        slots = [
            _parse_slot_row(row, capacity, authenticated)
            for row in table.select("tr.pcco-tt-time-person")
        ]
    events = sorted({s.block_reason for s in slots if s.block_reason})
    return Schedule(
        date=date,
        course=course,
        slots=slots,
        events=events,
        available_courses=available_courses if available_courses is not None else list(COURSE_ALIASES),
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
    """"18 Loch Tee 1" -> 18, "6 Loch Platz" -> 6, "9-Loch Schleife" (a second real
    club's own naming, confirmed 2026-09-07) -> 9 — every course name seen on either
    club so far starts with its hole count, hyphen or space after the number either
    way, which is why this matches on the leading digits alone rather than requiring
    "Loch" immediately after them. Returns None (not a wrong guess) for a name with
    no leading number at all, e.g. Sonnenberg's "Kurzplatz" (a short/pitch-and-putt
    course) — genuinely unknown, not assumed to be any particular hole count."""
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


class NoTeeSheetError(Exception):
    """This club's pc caddie page has no online tee sheet at all.

    Not a parsing failure and not a bug — 6 of the 45 real clubs swept 2026-09-07
    simply don't offer online tee-time booking (some were PC CADDIE's own demo/test
    clubs). There's nothing for this tool to show for such a club, so callers surface
    this as a plain "this club doesn't publish a tee sheet" message rather than an
    error traceback or an empty screen that looks broken."""


# The single implicit course used for a club whose tee sheet has no "Area" selector —
# see `_parse_course_aliases_html()`. An empty alias code means "send no alias param at
# all", which `club_url()` already handles. Deliberately a fixed, untranslated string:
# it's stored in SQLite as a course identifier (storage.py keys schedules by course
# name), so it has to stay stable regardless of the UI language in use at the time.
SINGLE_COURSE_NAME = "Course"
SINGLE_COURSE_ALIASES: dict[str, str] = {SINGLE_COURSE_NAME: ""}


def _parse_course_aliases_html(html: str) -> dict[str, str]:
    """Parse the tee-sheet page's own "Area" `<select id="timetable_selection_alias">`
    into {display_name: alias_code} — confirmed live 2026-09-07 to be per-club, not
    universal: `COURSE_ALIASES` above (Musterhausen's confirmed 18/9/6-hole set,
    codes COUB/COU1/COU6) turned out to be specific to that one club. A second real
    club added the same day ("Golf Club Sonnenberg e.V.") has a completely different
    shape — five options ("18-Loch Schleife", its own front/back 9 split, a separate
    "9-Loch Schleife", and "Kurzplatz"), with codes like A001/1810/1811/0901/0601 that
    share no pattern with Musterhausen's at all. Sending Musterhausen's codes to
    Sonnenberg's server is exactly why "it doesn't pull any data" — the alias simply
    isn't one Sonnenberg recognizes.

    **Not every club has this selector at all** — the single most common cross-club
    failure found in the 2026-09-07 sweep: 18 of the 39 clubs with a working tee sheet
    (46%) have no "Area" `<select>` whatsoever, because they only run one course. Their
    tee sheet is perfectly scrapeable, just addressed with no `alias` parameter. Raising
    for those, as this used to, made nearly half of pc caddie's clubs unusable. They now
    get `SINGLE_COURSE_ALIASES` — one implicit course, empty alias code.

    Whether the club publishes a tee sheet *at all* is a separate question, checked by
    `fetch_course_aliases()` against the live page rather than here — a club can have a
    course selector and still have no timetable behind it (2 of the 79 clubs swept)."""
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find("select", id="timetable_selection_alias")
    if select is None:
        return dict(SINGLE_COURSE_ALIASES)
    aliases: dict[str, str] = {}
    for option in select.find_all("option"):
        value = option.get("value", "").strip()
        if not value.startswith("ALIAS|"):
            continue  # a blank placeholder option, if one exists
        code = value.removeprefix("ALIAS|")
        name = option.get_text(strip=True)
        aliases[name] = code
    # A selector that exists but offers nothing parseable still means one playable
    # course, not zero — same handling as a club with no selector at all.
    return aliases or dict(SINGLE_COURSE_ALIASES)


def _parse_available_dates_html(html: str) -> list[str]:
    """Parse the tee sheet's own "Date" `<select id="timetable_selection_date">` into a
    list of YYYY-MM-DD strings — exactly the days this club currently lets you book.

    Confirmed 2026-09-07 to vary enormously per club: the 40 real clubs swept that
    offered a date selector ranged from 1 day to 31, with 8 the single most common
    value — against a `clubs/*.yaml` `overview_days` default of 5. Asking for a date
    outside the window doesn't degrade gracefully either; the site returns a page with
    no timetable and a "Selection invalid." notice, so guessing costs a wasted request
    and an empty day. Returns [] if there's no date selector at all (5 of 45 clubs),
    which callers treat as "fall back to the configured window"."""
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find("select", id="timetable_selection_date")
    if select is None:
        return []
    dates = []
    for option in select.find_all("option"):
        value = option.get("value", "").strip()
        if value.startswith("DAY|"):
            dates.append(value.removeprefix("DAY|"))
    return dates


def fetch_available_dates(club_id: str) -> list[str]:
    """The days this club is actually taking bookings for right now, straight from its
    own tee sheet (no login needed, same public page as everything else here). See
    `_parse_available_dates_html()` for why this can't be a configured constant."""
    response = httpx.get(club_url(club_id, TEE_SHEET_CATEGORY), timeout=15, follow_redirects=True)
    response.raise_for_status()
    return _parse_available_dates_html(response.text)


def fetch_course_aliases(club_id: str) -> dict[str, str]:
    """This club's own real course options, fetched fresh — not assumed from
    `COURSE_ALIASES` (Musterhausen-only) or any other club's. No login needed, same
    as `scrape_schedule()` itself: the course selector is part of the same
    already-public tee-sheet page. Re-checked on demand rather than cached
    indefinitely, since there's no guarantee a club's own course lineup never
    changes.

    Returns a single implicit course for a club that runs only one (46% of those
    swept 2026-09-07 — see `_parse_course_aliases_html()`), and raises
    `NoTeeSheetError` for one that publishes no tee sheet at all. That last check
    lives here rather than in the pure parser because it needs the whole real page:
    a club can offer a course selector and still have no timetable behind it, which
    would otherwise surface as a course you can pick that then shows nothing."""
    url = club_url(club_id, TEE_SHEET_CATEGORY)
    response = httpx.get(url, timeout=15, follow_redirects=True)
    response.raise_for_status()
    if BeautifulSoup(response.text, "html.parser").select_one("table.pcco-tt-timetable") is None:
        raise NoTeeSheetError(
            f"Club {club_id} doesn't publish an online tee sheet on pc caddie."
        )
    return _parse_course_aliases_html(response.text)


def scrape_schedule(club_id: str, course: str, date: str, course_aliases: dict[str, str] | None = None) -> Schedule:
    """Fetch the tee sheet (no login needed) and parse one day's full schedule.

    Implemented and verified 2026-09-06 against the real site (Musterhausen, club id
    0000001) — a plain `httpx.get()`, no Playwright/browser required for this call.

    `course_aliases` (added 2026-09-07, once a second real club exposed
    `COURSE_ALIASES` as Musterhausen-specific — see `fetch_course_aliases()`'s own
    docstring) is this club's own {name: alias_code} mapping. A caller that already
    has it (tui.py, scrape_once.py — both now fetch it once per club rather than
    assuming the hardcoded constant) should pass it through; omitting it triggers a
    live `fetch_course_aliases()` call here as a convenience default, at the cost of
    one extra request.
    """
    if course_aliases is None:
        course_aliases = fetch_course_aliases(club_id)
    alias = course_aliases.get(course)
    if alias is None:
        raise ValueError(f"Unknown course {course!r} for club {club_id} — expected one of {list(course_aliases)}")
    url = club_url(club_id, TEE_SHEET_CATEGORY, date=date, alias=alias)
    response = httpx.get(url, timeout=15, follow_redirects=True)
    response.raise_for_status()
    return parse_schedule_html(response.text, date=date, course=course, available_courses=list(course_aliases))


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


def _parse_club_directory_html(html: str) -> list[tuple[str, str]]:
    """Parse "My Golf"'s embedded club-search dropdown into (club_id, name) pairs.

    Confirmed 2026-09-07: pc caddie's own "search for a club by name" feature — both
    the web version's "Home club" field on this page and the mobile app's "Alle Clubs"
    tab (see club_picker.py) — isn't backed by a live per-keystroke API call. The
    entire platform directory (1300+ clubs at the time of inspection) is rendered
    server-side into one plain `<select id="user_association_club">`, one
    `<option value="club_id">[club_id] Name</option>` per club; whatever search box
    sits on top of it is just a client-side filter over these already-loaded options."""
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find("select", id="user_association_club")
    if select is None:
        raise NotImplementedError(
            "fetch_club_directory() didn't find the confirmed 'user_association_club' "
            "<select> -- the real markup may have changed. See scraper.py's module docstring."
        )
    entries = []
    for option in select.find_all("option"):
        club_id = option.get("value", "").strip()
        if not club_id:
            continue  # the blank placeholder option, not a real club
        # Strip the redundant "[club_id] " prefix pc caddie puts in its own display
        # text -- club_picker.py re-adds it at display time, but wants a clean `name`
        # to search against.
        name = re.sub(rf"^\[{re.escape(club_id)}\]\s*", "", option.get_text(strip=True))
        entries.append((club_id, name))
    return entries


def fetch_club_directory(club_id: str, username: str, password: str) -> list[tuple[str, str]]:
    """Log in and fetch pc caddie's own full club directory — every club on the
    platform, not just this one. The mechanism behind club_picker.py's searchable
    "add a club by name" screen, matching pc caddie's own in-app club-search feature
    (see module docstring and `_parse_club_directory_html()`).

    `club_id` only needs to be *a* club you can already log into — one pc caddie
    login works across every club on the platform (confirmed 2026-09-05), so the
    directory this returns isn't limited to clubs you've saved locally. This also
    means it can't bootstrap your very first saved club (there'd be no club_id yet to
    log in with) — that one still needs its numeric id found by hand, same as
    clubs/club.example.yaml's own instructions. It's for adding the clubs *after*
    that one, matching what prompted this feature: a home club plus a few others
    visited occasionally.
    """
    client = login(club_id, username, password)
    try:
        url = club_url(club_id, CLUB_DIRECTORY_CATEGORY)
        response = client.get(url)
        response.raise_for_status()
        return _parse_club_directory_html(response.text)
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
