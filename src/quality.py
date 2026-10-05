"""A deterministic, explainable quality score for playable slots (2026-10-05).

Why this exists: with AI ranking off (the default) `recommend.ranked_matches()` returns
the playable slots in chronological order, so the day's Pick -- the "★ HH:MM" in the
Pick column and the GUI's pick badge -- meant "earliest slot in your window", which is
what the maintainer's old "why does it always recommend 16:00?" was about. AI ranking can
reorder but costs paid calls. This module is the free, offline answer: score every
playable slot from data already in hand and let the best one be the Pick.

Pure functions over already-fetched inputs -- no I/O, no Textual, no clock reads (the
caller hands in `now`) -- so the same inputs always give the same scores and reasons.

Four factors, each turned into a sub-score between 0 (bad) and 1 (as good as it gets):

- weather margin (rain, wind, temperature): how far the forecast over the *real* round
  (`weather.conditions_during_round()` over `recommend._round_duration_minutes()`: 9 vs
  18 holes, your own pace) stays below your own limits. Dry and calm is best. Each part
  counts only when you switched it on, exactly like the hard filter
  (`recommend._fails_weather()`): rain with `avoid_rain`, wind with `avoid_wind` (limits:
  your thresholds, else `recommend`'s DEFAULT_AVOID_*), temperature when you set a
  floor/ceiling. Someone who turned "avoid wind" off said they don't mind wind, so a
  breezy slot is not marked down for them -- and never earns a "calm" reason.
- room around the group: how far the nearest other flight (booked players or a block)
  is before and after the slot, measured against your own buffer plus ROOM_EXTRA_MINUTES.
  (The hard buffer filter already keeps flights out of the buffer itself; this prefers
  more space than the minimum.)
- predicted crowd for that hour (`analytics` crowd estimates: quieter is better).
- daylight cushion: minutes between the round's end and sunset, capped.

Anything unknowable (no forecast that far, no sunset, no crowd history for that hour)
scores NEUTRAL_SUBSCORE: it neither helps nor hurts the slot, so it can't tilt the
ranking, and it never produces a reason.

Reasons: a factor that is notably good (sub-score >= REASON_MIN_SUBSCORE) becomes a
reason KEY -- "dry", "calm", "mild", "room_around", "quiet", "daylight_spare" -- at most
MAX_REASONS, ordered by how many score points it contributed. The keys are localised at
the edges (`i18n` "quality.reason.<key>" in the TUI, `I18n.swift` in the GUI), never here.
"""

import bisect
from dataclasses import dataclass
from datetime import datetime

from . import i18n, recommend
from . import weather as weather_module
from .models import Schedule, SlotMatch
from .search import _is_another_flight, _minutes_since_midnight, resolve_buffer_minutes

# --- Weights. They sum to 100, so a score reads as "points out of 100" and one number
# is directly comparable to another. Weather is the biggest lever on whether a round is
# pleasant at all; room and crowd are the other two things the player feels on the
# course; daylight is the smallest because the hard playability check already guarantees
# the round fits -- this only prefers not finishing in the dark's last minutes.
WEIGHT_RAIN = 22
WEIGHT_WIND = 13
WEIGHT_TEMPERATURE = 10  # the three weather weights: 45 in all
WEIGHT_ROOM = 20
WEIGHT_CROWD = 20
WEIGHT_DAYLIGHT = 15

# What an unknown factor (no forecast, no sunset, no crowd history) is worth.
NEUTRAL_SUBSCORE = 0.5

# Degrees of room inside the temperature floor/ceiling that count as fully comfortable.
TEMPERATURE_FULL_MARGIN_C = 5.0

# Free room, in minutes beyond your own buffer, that counts as "plenty of space": a
# flight at least buffer + this many minutes away (before/after) scores full marks.
ROOM_EXTRA_MINUTES = 30

# Minutes of light between the round's end and sunset that count as "plenty".
DAYLIGHT_FULL_CUSHION_MINUTES = 90

# A sub-score at or above this is notably good -> worth naming as a reason. With the
# default limits that is: rain probability <= 15 % (of 50), wind <= 9 kph (of 30),
# 3.5 degrees inside the temperature limit, a predicted occupancy <= 30 %, a flight at
# least 42 minutes away (no buffer), ~63 minutes of daylight to spare (of 90).
REASON_MIN_SUBSCORE = 0.7
MAX_REASONS = 3

# A slot that has already started today is not a real option: it sorts below every slot
# still ahead (but is still ranked, so a day whose slots have all passed keeps its
# earliest-first order instead of losing its Pick).
PAST_SLOT_SCORE = -1.0

REASON_KEYS = ("dry", "calm", "mild", "room_around", "quiet", "daylight_spare")


@dataclass
class ScoredMatch:
    match: SlotMatch
    score: float  # 0-100, or PAST_SLOT_SCORE for a slot already under way
    reasons: list[str]  # reason keys, best contribution first, at most MAX_REASONS


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _margin(value: float, limit: float) -> float:
    """1.0 at nothing, 0.0 at/over `limit` (a limit of zero or less: any amount is over)."""
    if limit <= 0:
        return 1.0 if value <= 0 else 0.0
    return _clamp(1 - value / limit)


def _limit(preferences: dict, key: str, default: float) -> float:
    # Settings saves a cleared field as an explicit null (same as recommend._fails_weather).
    value = preferences.get(key)
    return default if value is None else value


def _weather_subscores(conditions, preferences: dict) -> dict[str, float | None]:
    """{"rain"|"wind"|"temperature": sub-score or None when unknowable or switched off}
    for one round's worst-case `RoundConditions` (None conditions: everything unknown)."""
    unknown: dict[str, float | None] = {"rain": None, "wind": None, "temperature": None}
    if conditions is None:
        return unknown
    result = dict(unknown)

    rain_parts = []
    if preferences.get("avoid_rain"):
        if conditions.max_precipitation_probability is not None:
            limit = _limit(preferences, "avoid_rain_probability_percent", recommend.DEFAULT_AVOID_RAIN_PROBABILITY_PERCENT)
            rain_parts.append(_margin(conditions.max_precipitation_probability, limit))
        if conditions.max_precipitation_mm is not None:
            limit = _limit(preferences, "avoid_rain_mm", recommend.DEFAULT_AVOID_RAIN_MM)
            rain_parts.append(_margin(conditions.max_precipitation_mm, limit))
    if rain_parts:
        result["rain"] = min(rain_parts)  # the worse of the two readings

    if preferences.get("avoid_wind") and conditions.max_wind_speed_kph is not None:
        limit = _limit(preferences, "avoid_wind_kph", recommend.DEFAULT_AVOID_WIND_KPH)
        result["wind"] = _margin(conditions.max_wind_speed_kph, limit)

    margins_c = []
    floor = preferences.get("avoid_temp_below_c")
    if floor is not None and conditions.min_temperature_c is not None:
        margins_c.append(conditions.min_temperature_c - floor)
    ceiling = preferences.get("avoid_temp_above_c")
    if ceiling is not None and conditions.max_temperature_c is not None:
        margins_c.append(ceiling - conditions.max_temperature_c)
    if margins_c:
        result["temperature"] = _clamp(min(margins_c) / TEMPERATURE_FULL_MARGIN_C)
    return result


class _Neighbours:
    """Where the other flights of one day are, for the room-around factor: the sorted
    start minutes of every slot that `search._is_another_flight()` counts."""

    def __init__(self, schedule: Schedule):
        self._minutes = sorted(_minutes_since_midnight(s.time) for s in schedule.slots if _is_another_flight(s))

    def gaps(self, slot) -> tuple[int | None, int | None]:
        """(minutes back to the nearest other flight before `slot`, minutes on to the
        nearest one after it), None for a side with no flight at all. The slot's own
        entry and any flight at the very same minute are not neighbours."""
        minute = _minutes_since_midnight(slot.time)
        minutes = self._minutes
        before_index = bisect.bisect_left(minutes, minute) - 1
        after_index = bisect.bisect_right(minutes, minute)
        before = minute - minutes[before_index] if before_index >= 0 else None
        after = minutes[after_index] - minute if after_index < len(minutes) else None
        return before, after


def _room_subscore(gaps: tuple[int | None, int | None], buffer_before: int, buffer_after: int) -> float:
    before, after = gaps
    sides = []
    for gap, buffer in ((before, buffer_before), (after, buffer_after)):
        sides.append(1.0 if gap is None else _clamp(gap / (buffer + ROOM_EXTRA_MINUTES)))
    return sum(sides) / len(sides)


def _daylight_subscore(
    slot_time: str, schedule: Schedule, duration_minutes: int, fallback_sun_times=None
) -> float | None:
    sun_times = schedule.sun_times or fallback_sun_times
    if sun_times is None or not sun_times.sunset:
        return None
    end = _minutes_since_midnight(slot_time) + duration_minutes
    cushion = _minutes_since_midnight(sun_times.sunset) - end
    return _clamp(cushion / DAYLIGHT_FULL_CUSHION_MINUTES)


def score_matches(
    matches: list[SlotMatch],
    schedules: Schedule | list[Schedule],
    config: dict,
    crowd_estimates: dict[tuple[str, str, str], float] | None = None,
    now: datetime | None = None,
    fallback_sun_times=None,
) -> list[ScoredMatch]:
    """One `ScoredMatch` per match, in the matches' own order -- scoring never sorts
    (`recommend.ranked_matches()` does, with the friend/handicap tiers above the score).

    `schedules` -- the schedule(s) the matches came from, found by (date, course); a
    match whose schedule isn't there scores neutral on every schedule-based factor.
    `config` is the merged club config (`preferences`, `round_duration_minutes`,
    `availability` buffers). `crowd_estimates` is `{(date, course, time): occupancy 0-1}`
    as `pipeline._compute_crowd_estimates()` builds it; None or a missing entry skips
    the crowd factor (neutral, no reason) -- there simply isn't enough history yet.
    `now` (naive local datetime, the club's wall clock): a slot on `now`'s own date
    whose start is before it scores PAST_SLOT_SCORE. None: nothing counts as past.
    `fallback_sun_times` (2026-10-05): a sibling course's sun times for the same club and
    date, used only for a schedule saved without its own (an older scrape from a sun-times
    outage) -- otherwise the daylight factor is neutral for every slot of that day and
    nothing would stop a late start from winning. The caller finds it (the DB lookup is
    I/O); None leaves such a day neutral, as before. Only the *score* uses it: the hard
    playability filter and the star markers are untouched."""
    schedule_list = [schedules] if isinstance(schedules, Schedule) else schedules
    by_key = {(schedule.date, schedule.course): schedule for schedule in schedule_list}
    neighbours: dict[tuple[str, str], _Neighbours] = {}
    preferences = config.get("preferences", {})
    availability = config.get("availability", {})
    buffer_before = resolve_buffer_minutes(availability, "before", 0)
    buffer_after = resolve_buffer_minutes(availability, "after", 0)
    now_date = now.date().isoformat() if now is not None else None
    now_time = now.strftime("%H:%M") if now is not None else None

    scored: list[ScoredMatch] = []
    for match in matches:
        slot_time = match.slot.time
        if now_date == match.date and slot_time < now_time:
            scored.append(ScoredMatch(match, PAST_SLOT_SCORE, []))
            continue
        key = (match.date, match.course)
        schedule = by_key.get(key)
        duration = recommend._round_duration_minutes(match.course, config)

        subscores: dict[str, float | None] = {"rain": None, "wind": None, "temperature": None}
        room = daylight = None
        if schedule is not None:
            conditions = weather_module.conditions_during_round(schedule.weather, slot_time, duration)
            subscores = _weather_subscores(conditions, preferences)
            if key not in neighbours:
                neighbours[key] = _Neighbours(schedule)
            room = _room_subscore(neighbours[key].gaps(match.slot), buffer_before, buffer_after)
            daylight = _daylight_subscore(slot_time, schedule, duration, fallback_sun_times)
        occupancy = (crowd_estimates or {}).get((match.date, match.course, slot_time))
        quiet = None if occupancy is None else _clamp(1 - occupancy)

        # (reason key, weight, sub-score or None) in REASON_KEYS order, which is also the
        # tie-break between equal contributions.
        factors = [
            ("dry", WEIGHT_RAIN, subscores["rain"]),
            ("calm", WEIGHT_WIND, subscores["wind"]),
            ("mild", WEIGHT_TEMPERATURE, subscores["temperature"]),
            ("room_around", WEIGHT_ROOM, room),
            ("quiet", WEIGHT_CROWD, quiet),
            ("daylight_spare", WEIGHT_DAYLIGHT, daylight),
        ]
        total = 0.0
        contributions: list[tuple[float, int, str]] = []
        for order, (reason, weight, sub) in enumerate(factors):
            total += weight * (NEUTRAL_SUBSCORE if sub is None else sub)
            if sub is not None and sub >= REASON_MIN_SUBSCORE:
                contributions.append((-weight * sub, order, reason))
        contributions.sort()
        reasons = [reason for _, _, reason in contributions[:MAX_REASONS]]
        # Rounded so float noise can never split two slots that are really equal.
        scored.append(ScoredMatch(match, round(total, 2), reasons))
    return scored


def reasons_text(reasons: list[str]) -> str:
    """The localised, " · "-joined sentence body for reason keys ("dry · room around
    you"), shared by the TUI's row detail; an unknown key is skipped. The GUI does the
    same decoding in `I18n.swift` from the same "quality.reason.<key>" strings."""
    return " · ".join(i18n.t(f"quality.reason.{key}") for key in reasons if key in REASON_KEYS)
