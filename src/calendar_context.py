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

NOT YET IMPLEMENTED.
"""

from .models import DateRange

NAGER_DATE_URL = "https://date.nager.at/api/v3/PublicHolidays"

# Most-specific first: a tournament on a public holiday is still a tournament day.
DAY_TYPES = ["tournament", "public_holiday", "vacation", "weekend", "workday"]


def fetch_public_holidays(country_code: str, year: int) -> list[str]:
    """Dates (YYYY-MM-DD) of public holidays in one country/year."""
    raise NotImplementedError("calendar_context.py is a stub — see ROADMAP.md Phase 2")


def classify_day(
    date: str,
    holidays: list[str],
    vacation_ranges: list[DateRange],
    has_tournament: bool,
) -> str:
    """One of DAY_TYPES for a given date, most-specific first."""
    raise NotImplementedError("calendar_context.py is a stub — see ROADMAP.md Phase 2")
