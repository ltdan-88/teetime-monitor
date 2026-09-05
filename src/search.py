"""Structured search across multiple already-scraped days (ROADMAP.md Phase 4),
used two ways:

- **Ad hoc**, via the TUI's search form: criteria typed in on the spot for a one-off
  need, e.g. "3 players, weekdays only, after 15:00, at least 20 minutes clear of any
  other flight."
- **Default**, via recommend.py: the same SearchCriteria shape, but saved in the active
  club's `availability` block and run automatically against every day in the overview,
  so the week's recommended slots show up without typing anything. This is what
  replaced the older, flatter idea of a single "preferences" block — same engine, just
  two entry points (typed-in vs saved-as-default).

This module does the *hard* filtering only — party size and time windows are exact
checks, not judgment calls, so plain code (not AI) is both simpler and more reliable
here. Ranking the results (dry, calm, safely-before-sunset first, with plain-language
reasons) is a separate step via `ai_assist.rank_slots()`, called by recommend.py for the
saved-default path and by the TUI's ad hoc search handler for the typed-in path — see
ROADMAP.md's "AI placement" note for why that split exists.

NOT YET IMPLEMENTED.
"""

from dataclasses import dataclass

from .models import Schedule, SlotMatch, TimeWindow


@dataclass
class SearchCriteria:
    min_open_spots: int = 1  # e.g. 1 for "always play alone", 3 for a 3-player group

    # A day with no window set for its type is skipped entirely. Setting only
    # weekday_window (leaving weekend_window as None) means "weekdays only" — same
    # effect as the old ad hoc "weekdays_only" flag, just expressed as an omission.
    weekday_window: TimeWindow | None = None  # Mon-Fri, e.g. after "17:00"
    weekend_window: TimeWindow | None = None  # Sat-Sun, e.g. after "10:00"

    buffer_minutes: int = 0  # min gap to the nearest other booked flight, either side


def search(schedules: list[Schedule], criteria: SearchCriteria) -> list[SlotMatch]:
    """Return matching slots across all given days — filtered, not yet ranked
    (`score`/`reasons` unset). Pass the result to `ai_assist.rank_slots()` for that."""
    raise NotImplementedError("search.py is a stub — see ROADMAP.md Phase 4")
