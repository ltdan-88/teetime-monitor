"""Public holidays + school-vacation awareness, and day-type classification
(ROADMAP.md Phase 2).

Public holidays are fetched via the free Nager.Date API (https://date.nager.at/), no
key needed, keyed by a club's `calendar.country_code`. School/regional vacation periods
have no reliable universal free API, so those come straight from the club's YAML
(`calendar.vacation_ranges`, entered by hand) instead.

`classify_day()` folds all of this (plus Phase 1's scraped tournament/event notes) into
one day-type tag per date, which Phase 5's crowd heatmap groups history by, and which
lets a *future* date (with no scrape history of its own yet) get a crowd estimate at
all.

Implemented 2026-09-06. `fetch_public_holidays()` is the one piece needing a live call
(mocked in tests, like weather.py's Open-Meteo calls) — `classify_day()` is pure, no
I/O, same as playability.py/weather.conditions_during_round().
"""

import re
from datetime import date as date_cls

import httpx

from .models import DateRange

NAGER_DATE_URL = "https://date.nager.at/api/v3/PublicHolidays"

# Most-specific first: a tournament on a public holiday is still a tournament day.
DAY_TYPES = ["tournament", "public_holiday", "vacation", "weekend", "workday"]

# The three DAY_TYPES analytics.crowd_heatmap() compares against "other days of the
# same kind" rather than folding into the day-of-week grid below -- a vacation-week
# Monday shouldn't be judged against a typical Monday, and (the other direction)
# shouldn't cost a typical Monday one of its own samples either. Added 2026-09-09,
# fixing a real mismatch against the original signed-off mockup: the heatmap grid
# was mocked up as actual days of the week, with holiday/vacation/tournament shown
# in a separate "special days" panel underneath -- not a workday/weekend split with
# holiday/vacation/tournament as three more buckets on the same axis, which is what
# actually got built the first time around. See analytics.py's module docstring.
SPECIAL_DAY_TYPES = ["tournament", "public_holiday", "vacation"]

# Sunday-first, matching the signed-off mockup's own column order.
WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

_DATE_FMT = "%Y-%m-%d"


def holidays_from_nager(entries: list[dict], region: str | None = None) -> list[str]:
    """The dates in a Nager.Date `/PublicHolidays` response that apply to the club.

    Nager also lists state-only holidays (`"global": false` plus a `counties` list,
    e.g. DE's Reformationstag or Buß- und Bettag). Those are kept only when `region`
    (an ISO 3166-2 code such as "DE-BW") is in their `counties`; without a region
    only nationwide holidays count, since a state holiday is an ordinary working day
    everywhere else."""
    return [
        entry["date"]
        for entry in entries
        if entry.get("global", True) or (region is not None and region in (entry.get("counties") or []))
    ]


def fetch_public_holidays(country_code: str, year: int, region: str | None = None) -> list[str]:
    """Dates (YYYY-MM-DD) of public holidays in one country/year -- nationwide ones,
    plus `region`'s own if given (see `holidays_from_nager()`)."""
    response = httpx.get(f"{NAGER_DATE_URL}/{year}/{country_code}", timeout=15)
    response.raise_for_status()
    return holidays_from_nager(response.json(), region)


def _iso_date_text(value) -> str:
    """A vacation-range bound as "YYYY-MM-DD". PyYAML reads an unquoted
    `start: 2026-07-04` as a `datetime.date`, which can't be compared with the ISO
    strings every date here is passed around as."""
    return value.isoformat() if isinstance(value, date_cls) else str(value)


def _in_vacation(date: str, vacation_ranges: list[DateRange]) -> bool:
    return any(_iso_date_text(vr.start) <= date <= _iso_date_text(vr.end) for vr in vacation_ranges)


# Words in a block-time label that mark a real competition rather than a recurring
# group, a lesson, a guest block or an instructor's name ("Dienstag-Ladies",
# "Grundkurs", "Gäste", "Marco"). Matched case-insensitively as substrings, except
# the short English words, which need word boundaries.
_TOURNAMENT_NAME_RE = re.compile(
    r"turnier|meisterschaft|championship|troph|matchplay|match play|pokal|wettspiel|liga|scramble"
    r"|\bcup\b|\bopen\b|\bpreis\b",
    re.IGNORECASE,
)

# An unrecognised event name still makes a tournament day once its blocks cover at
# least this share of the day's slots -- a competition takes over the course, a
# weekly ladies' group or a lesson blocks a few tee times.
TOURNAMENT_BLOCKED_SHARE = 0.5


def is_tournament_day(events: list[str], slots: list) -> bool:
    """Whether a scraped day counts as a "tournament" for `classify_day()`.

    `events` holds the name of every block-time row (`scraper._event_names()`), and
    most of those are routine: recurring groups, lessons, guest blocks. Treating any
    of them as a tournament moved ordinary weekdays out of the heatmap's weekday
    columns. A day is a tournament when an event name reads like one, or when slots
    blocked by those events make up at least `TOURNAMENT_BLOCKED_SHARE` of the day.
    Advance-booking notices also set `block_reason` but are never in `events`, so
    they don't count toward the share. Mirrored by
    `CalendarContext.isTournamentDay()` in macos/Sources/CalendarContext.swift."""
    if not events:
        return False
    if any(_TOURNAMENT_NAME_RE.search(name) for name in events):
        return True
    if not slots:
        return False
    names = set(events)
    blocked = sum(1 for slot in slots if slot.block_reason in names)
    return blocked / len(slots) >= TOURNAMENT_BLOCKED_SHARE


def classify_day(
    date: str,
    holidays: list[str],
    vacation_ranges: list[DateRange],
    has_tournament: bool,
) -> str:
    """One of DAY_TYPES for a given date, most-specific first."""
    if has_tournament:
        return "tournament"
    if date in holidays:
        return "public_holiday"
    if _in_vacation(date, vacation_ranges):
        return "vacation"
    is_weekend = date_cls.fromisoformat(date).weekday() >= 5  # Sat=5, Sun=6
    return "weekend" if is_weekend else "workday"
