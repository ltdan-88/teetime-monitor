"""Turn your saved default availability into the week's recommended slots, automatically
(ROADMAP.md Phase 3).

Thin wrapper around search.py: builds a SearchCriteria from the active club's
`availability` block (your standing rules — e.g. "workdays after 17:00, weekends after
10:00, always alone") and runs it across every day in the overview, so recommended slots
show up at a glance without typing anything. The TUI's ad hoc search form (also
search.py, same SearchCriteria shape) is for the one-off exceptions — e.g. a week you're
playing with friends instead of alone — that don't match your usual defaults.

Also applies the soft scoring weights from the club's `preferences` block (avoid_rain,
avoid_wind, temperature comfort, prioritize_friends, and avoid_predicted_crowd once
analytics.py's crowd_heatmap exists) when ranking results. These are shared with ad hoc
search too — what makes a slot pleasant doesn't change just because the criteria that
surfaced it did.

NOT YET IMPLEMENTED.
"""

from .models import Schedule, SlotMatch
from .search import SearchCriteria, search


def default_criteria_from_config(config: dict) -> SearchCriteria:
    """Build a SearchCriteria from the active club's `availability` block."""
    raise NotImplementedError("recommend.py is a stub — see ROADMAP.md Phase 3")


def weekly_picks(schedules: list[Schedule], config: dict) -> list[SlotMatch]:
    """Best-ranked matches for the week, using your saved default availability."""
    raise NotImplementedError("recommend.py is a stub — see ROADMAP.md Phase 3")
