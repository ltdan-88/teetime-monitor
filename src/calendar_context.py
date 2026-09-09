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


def fetch_public_holidays(country_code: str, year: int) -> list[str]:
    """Dates (YYYY-MM-DD) of public holidays in one country/year."""
    response = httpx.get(f"{NAGER_DATE_URL}/{year}/{country_code}", timeout=15)
    response.raise_for_status()
    return [entry["date"] for entry in response.json()]


def _in_vacation(date: str, vacation_ranges: list[DateRange]) -> bool:
    return any(vr.start <= date <= vr.end for vr in vacation_ranges)


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
