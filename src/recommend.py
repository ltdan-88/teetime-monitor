"""Turn your saved default availability into the week's recommended slots, automatically
(ROADMAP.md Phase 3).

Three-step wrapper — two deterministic, one AI, in that order:
1. Builds a SearchCriteria from the active club's `availability` block (your standing
   rules — e.g. "workdays after 17:00, weekends after 10:00, always alone") and runs it
   via search.py across every day in the overview — exact, no AI involved.
2. `exclude_unplayable()` drops candidates that fail a deterministic sanity check: not
   enough daylight left to finish (playability.py) or weather past the club's
   `preferences` thresholds (avoid_rain/avoid_wind/avoid_temp_*) *at any point during
   the round*, not just at tee-off — see weather.conditions_during_round(), added
   2026-09-05 after user feedback that weather checked only at the start time misses
   conditions changing mid-round (e.g. rain rolling in at hour 3 of a 4-hour round).
   Revised the same day for a second reason: a recommendation that's raining or too
   dark to finish isn't actually a good one, so this whole step has to happen before
   anything gets called "recommended" — it's not an AI-ranking nicety, it's part of the
   baseline. Still no AI needed; these are plain threshold checks against
   already-fetched weather/playability data, aggregated across the round's duration.
3. Hands what's left plus the club's `preferences` block (prioritize_friends, and
   avoid_predicted_crowd once analytics.py's crowd_heatmap exists) to
   `ai_assist.rank_slots()`, which weighs the remaining nuanced trade-offs (e.g.
   "slightly more rain but much emptier") and writes plain-language `reasons`. This step
   is a genuine improvement, not a prerequisite — steps 1+2 alone already turn "scan the
   tee sheet by hand" into a short, sane list; this makes picking among that list easier
   too, but the list is already useful without it.

The TUI's ad hoc search form (search.py + exclude_unplayable + ai_assist.rank_slots,
same three steps) is for the one-off exceptions — e.g. a week you're playing with
friends instead of alone — that don't match your usual defaults. Same engine, different
criteria in.

NOT YET IMPLEMENTED.
"""

from . import ai_assist
from .models import Schedule, SlotMatch
from .search import SearchCriteria, search


def default_criteria_from_config(config: dict) -> SearchCriteria:
    """Build a SearchCriteria from the active club's `availability` block."""
    raise NotImplementedError("recommend.py is a stub — see ROADMAP.md Phase 3")


def exclude_unplayable(
    candidates: list[SlotMatch], schedules: list[Schedule], config: dict
) -> list[SlotMatch]:
    """Drop candidates that fail a deterministic sanity check across their *entire*
    round duration, not just their tee-off moment:

    - Not enough daylight left to finish (playability.is_playable(), using
      config["round_duration_minutes"] and config["daylight_buffer_minutes"])
    - Weather past the club's preference thresholds at any point during the round
      (weather.conditions_during_round(), matched against config["preferences"]'s
      avoid_rain/avoid_wind/avoid_temp_below_c/avoid_temp_above_c)

    Looks up each candidate's Schedule (by date/course) in `schedules` for its
    sun_times/weather. Run this before ai_assist.rank_slots(), not after: a slot that
    fails this check was never a good recommendation regardless of how it'd otherwise
    rank.
    """
    raise NotImplementedError("recommend.py is a stub — see ROADMAP.md Phase 3")


def weekly_picks(schedules: list[Schedule], config: dict) -> list[SlotMatch]:
    """Best-ranked matches for the week, using your saved default availability.

    criteria = default_criteria_from_config(config)
    candidates = search(schedules, criteria)                    # exact filter
    playable = exclude_unplayable(candidates, schedules, config)   # deterministic sanity check
    return ai_assist.rank_slots(playable, context={...}, preferences=config["preferences"])
    """
    raise NotImplementedError("recommend.py is a stub — see ROADMAP.md Phase 3")
