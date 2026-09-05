"""Turn your saved default availability into the week's recommended slots, automatically
(ROADMAP.md Phase 3).

Two-step wrapper, deterministic filter then AI ranking:
1. Builds a SearchCriteria from the active club's `availability` block (your standing
   rules — e.g. "workdays after 17:00, weekends after 10:00, always alone") and runs it
   via search.py across every day in the overview — exact, no AI involved.
2. Hands the filtered (but unranked) candidates plus the club's `preferences` block
   (avoid_rain, avoid_wind, temperature comfort, prioritize_friends, and
   avoid_predicted_crowd once analytics.py's crowd_heatmap exists) to
   `ai_assist.rank_slots()`, which does the actual weighing and writes `reasons`.

The TUI's ad hoc search form (also search.py + ai_assist.rank_slots, same two steps) is
for the one-off exceptions — e.g. a week you're playing with friends instead of alone —
that don't match your usual defaults. Same engine, different criteria in.

NOT YET IMPLEMENTED.
"""

from . import ai_assist
from .models import Schedule, SlotMatch
from .search import SearchCriteria, search


def default_criteria_from_config(config: dict) -> SearchCriteria:
    """Build a SearchCriteria from the active club's `availability` block."""
    raise NotImplementedError("recommend.py is a stub — see ROADMAP.md Phase 3")


def weekly_picks(schedules: list[Schedule], config: dict) -> list[SlotMatch]:
    """Best-ranked matches for the week, using your saved default availability.

    criteria = default_criteria_from_config(config)
    candidates = search(schedules, criteria)                    # exact filter
    return ai_assist.rank_slots(candidates, context={...}, preferences=config["preferences"])
    """
    raise NotImplementedError("recommend.py is a stub — see ROADMAP.md Phase 3")
