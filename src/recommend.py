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

Implemented 2026-09-06, steps 1+2 (the deterministic baseline) fully tested. Step 3
(`ai_assist.rank_slots()`) is still a stub, so `weekly_picks()` catches that
specifically and falls back to returning the filtered-but-unranked list — matching this
module's own stated point: steps 1+2 alone are already a short, sane list, not a
placeholder waiting on AI to be useful.

One genuine design gap found while implementing exclude_unplayable(), not resolved
before now: club.example.yaml's `preferences.avoid_rain`/`avoid_wind` are plain
booleans ("do you care about this at all"), not numeric cutoffs — but a *hard* filter
needs an actual number to compare against, unlike `ai_assist.rank_slots()`'s softer
weighing. Resolved here with sensible, overridable defaults (see the
`DEFAULT_AVOID_*` constants below) rather than blocking on it — a club can override
them via new optional `avoid_rain_probability_percent`/`avoid_rain_mm`/`avoid_wind_kph`
keys in its own YAML, but existing configs work unchanged. Worth the user's own
sign-off on the actual numbers later; flagged rather than silently assumed.
"""

import re

from . import ai_assist, playability
from . import weather as weather_module
from .models import Schedule, SlotMatch, TimeWindow
from .search import SearchCriteria, search

# See the module docstring's "genuine design gap" note — club.example.yaml's
# avoid_rain/avoid_wind are booleans, not thresholds, so exclude_unplayable() needs its
# own numeric cutoffs to act as a hard filter. Overridable per club via the matching
# `avoid_*` keys below, alongside the already-numeric avoid_temp_below_c/above_c.
DEFAULT_AVOID_RAIN_PROBABILITY_PERCENT = 50
DEFAULT_AVOID_RAIN_MM = 1.0
DEFAULT_AVOID_WIND_KPH = 30


def default_criteria_from_config(config: dict) -> SearchCriteria:
    """Build a SearchCriteria from the active club's `availability` block."""
    availability = config.get("availability", {})

    def _window(key: str) -> TimeWindow | None:
        raw = availability.get(key)
        if raw is None:
            return None
        return TimeWindow(after=raw.get("after"), before=raw.get("before"))

    return SearchCriteria(
        min_open_spots=availability.get("min_open_spots", 1),
        weekday_window=_window("weekday_window"),
        weekend_window=_window("weekend_window"),
        buffer_minutes=availability.get("buffer_minutes", 0),
    )


def _schedule_for(candidate: SlotMatch, schedules: list[Schedule]) -> Schedule | None:
    for schedule in schedules:
        if schedule.date == candidate.date and schedule.course == candidate.course:
            return schedule
    return None


def _holes_for_course(course: str) -> int:
    """Course names are "18 Loch Tee 1" / "9 Loch Tee 1" / "6 Loch Platz" — pull the
    leading number out directly rather than hardcoding a name-to-holes map, so a
    differently-named club's course still works."""
    match = re.search(r"(\d+)\s*Loch", course)
    return int(match.group(1)) if match else 18


def _round_duration_minutes(course: str, config: dict) -> int:
    """config["round_duration_minutes"] only has "nine"/"eighteen" keys (see
    clubs/club.example.yaml) — a genuinely 6-hole course (this club's "6 Loch Platz")
    has no dedicated bucket, so anything under 18 holes maps to "nine" as a reasonable
    proxy (a 6-hole round takes less time than a 9-hole one anyway, so this only ever
    over-estimates the duration, never under-estimates it into an unsafe recommendation)."""
    holes = _holes_for_course(course)
    key = "eighteen" if holes >= 18 else "nine"
    default = 240 if key == "eighteen" else 120
    return config.get("round_duration_minutes", {}).get(key, default)


def _fails_playability(candidate: SlotMatch, schedule: Schedule, config: dict) -> bool:
    if schedule.sun_times is None:
        return False  # can't check without a sunset time -- unknown, not assumed bad
    duration = _round_duration_minutes(candidate.course, config)
    buffer_minutes = config.get("daylight_buffer_minutes", 0)
    return not playability.is_playable(
        candidate.slot.time, schedule.sun_times.sunset, duration, buffer_minutes
    )


def _fails_weather(candidate: SlotMatch, schedule: Schedule, config: dict) -> bool:
    duration = _round_duration_minutes(candidate.course, config)
    conditions = weather_module.conditions_during_round(schedule.weather, candidate.slot.time, duration)
    if conditions is None:
        return False  # no forecast reaches this far -- unknown, not assumed bad

    preferences = config.get("preferences", {})

    if preferences.get("avoid_rain"):
        prob_limit = preferences.get(
            "avoid_rain_probability_percent", DEFAULT_AVOID_RAIN_PROBABILITY_PERCENT
        )
        mm_limit = preferences.get("avoid_rain_mm", DEFAULT_AVOID_RAIN_MM)
        if conditions.max_precipitation_probability is not None and conditions.max_precipitation_probability > prob_limit:
            return True
        if conditions.max_precipitation_mm is not None and conditions.max_precipitation_mm > mm_limit:
            return True

    if preferences.get("avoid_wind"):
        wind_limit = preferences.get("avoid_wind_kph", DEFAULT_AVOID_WIND_KPH)
        if conditions.max_wind_speed_kph is not None and conditions.max_wind_speed_kph > wind_limit:
            return True

    temp_floor = preferences.get("avoid_temp_below_c")
    if temp_floor is not None and conditions.min_temperature_c is not None and conditions.min_temperature_c < temp_floor:
        return True

    temp_ceiling = preferences.get("avoid_temp_above_c")
    if temp_ceiling is not None and conditions.max_temperature_c is not None and conditions.max_temperature_c > temp_ceiling:
        return True

    return False


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
    rank. A candidate whose Schedule isn't in `schedules` at all passes through
    unfiltered — there's nothing to check it against, and silently dropping it would be
    a worse failure mode than showing an unverified slot.
    """
    playable = []
    for candidate in candidates:
        schedule = _schedule_for(candidate, schedules)
        if schedule is None:
            playable.append(candidate)
            continue
        if _fails_playability(candidate, schedule, config):
            continue
        if _fails_weather(candidate, schedule, config):
            continue
        playable.append(candidate)
    return playable


def weekly_picks(schedules: list[Schedule], config: dict) -> list[SlotMatch]:
    """Best-ranked matches for the week, using your saved default availability.

    Steps 1+2 (search + exclude_unplayable) are the deterministic baseline and always
    run for real. Step 3 (ai_assist.rank_slots) is a genuine improvement, not a
    prerequisite (see module docstring) — while it's still a stub, this falls back to
    returning the filtered list as-is (unranked, no `reasons`) rather than raising,
    since a short sane list beats no list at all.
    """
    criteria = default_criteria_from_config(config)
    candidates = search(schedules, criteria)
    playable = exclude_unplayable(candidates, schedules, config)
    try:
        return ai_assist.rank_slots(playable, context={"config": config}, preferences=config.get("preferences", {}))
    except NotImplementedError:
        return playable
