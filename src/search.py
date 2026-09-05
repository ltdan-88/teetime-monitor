"""Ad-hoc structured search across multiple already-scraped days (ROADMAP.md Phase 4).

Different from recommend.py's single per-day "pick for me": this runs on demand with
criteria typed in on the spot -- e.g. "3 players, weekdays only, after 15:00, at least
20 minutes clear of any other flight" -- and returns a ranked list of matching slots
across every day already pulled for the multi-day overview.

Reuses the same scoring approach as recommend.py (dry, calm, safely-before-sunset first)
for ranking the matches, just applied across many days/criteria instead of one fixed
daily pick.

NOT YET IMPLEMENTED.
"""

from dataclasses import dataclass

from .models import Schedule, SlotMatch


@dataclass
class SearchCriteria:
    min_open_spots: int  # e.g. 3 for a 3-player group
    time_after: str | None = None  # "15:00"
    time_before: str | None = None
    weekdays_only: bool = False
    buffer_minutes: int = 0  # min gap to the nearest other booked flight, either side


def search(schedules: list[Schedule], criteria: SearchCriteria) -> list[SlotMatch]:
    """Return matching slots across all given days, best-ranked first."""
    raise NotImplementedError("search.py is a stub — see ROADMAP.md Phase 4")
