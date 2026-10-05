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
3. Hands what's left plus `prioritize_friends` and `avoid_predicted_crowd` (the
   latter now genuinely wired to `analytics.crowd_heatmap()`/`predict_crowding()`,
   2026-09-10 — see `ranked_matches()`'s own `crowd_estimates` parameter) to
   `ai_assist.rank_slots()`, which weighs the remaining nuanced trade-offs (e.g.
   "slightly more rain but much emptier") and writes plain-language `reasons`. This step
   is a genuine improvement, not a prerequisite — steps 1+2 alone already turn "scan the
   tee sheet by hand" into a short, sane list; this makes picking among that list easier
   too, but the list is already useful without it. Gated on the club's
   `ai_assist.enabled` flag (now that ai_assist.py is real and each call actually costs
   money) and any failure of the call itself — `weekly_picks()` falls back to the
   plain filtered list either way, rather than the whole recommendation failing over a
   step that was always meant to be optional.

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

import dataclasses
from datetime import datetime

from . import ai_assist, i18n, playability
from . import weather as weather_module
from .models import Schedule, Slot, SlotMatch, TimeWindow
from .scraper import _holes_from_course_label
from .search import SearchCriteria, _window_for_date, resolve_buffer_minutes, search

# See the module docstring's "genuine design gap" note — club.example.yaml's
# avoid_rain/avoid_wind are booleans, not thresholds, so exclude_unplayable() needs its
# own numeric cutoffs to act as a hard filter. Overridable per club via the matching
# `avoid_*` keys below, alongside the already-numeric avoid_temp_below_c/above_c.
DEFAULT_AVOID_RAIN_PROBABILITY_PERCENT = 50
DEFAULT_AVOID_RAIN_MM = 1.0
DEFAULT_AVOID_WIND_KPH = 30


def _clock_text(value) -> str | None:
    """A window bound as "HH:MM". PyYAML reads an unquoted `after: 17:00` as the
    sexagesimal int 1020 (17*60), which would then be compared against slot-time
    strings and raise TypeError -- turned back into "17:00" here."""
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value // 60:02d}:{value % 60:02d}"
    return value


def default_criteria_from_config(config: dict) -> SearchCriteria:
    """Build a SearchCriteria from the active club's `availability` block."""
    availability = config.get("availability", {})

    def _window(key: str) -> TimeWindow | None:
        raw = availability.get(key)
        if raw is None:
            return None
        return TimeWindow(after=_clock_text(raw.get("after")), before=_clock_text(raw.get("before")))

    return SearchCriteria(
        min_open_spots=availability.get("min_open_spots", 1),
        weekday_window=_window("weekday_window"),
        weekend_window=_window("weekend_window"),
        buffer_before_minutes=resolve_buffer_minutes(availability, "before", 0),
        buffer_after_minutes=resolve_buffer_minutes(availability, "after", 0),
    )


def window_for_date(date: str, config: dict) -> TimeWindow | None:
    """Your own saved availability window that applies to `date` -- the weekday
    or the weekend one, exactly as `search()` itself picks it -- or None with no
    `availability` rules (or no window for that day type) at all. Shared by
    both front ends (2026-09-27, bundle C of the TUI/GUI consistency audit) so
    "which slots are in your window" can never be decided two different ways:
    the TUI calls it directly, the GUI gets it per date from `picks_cli.py`."""
    if not config.get("availability"):
        return None
    return _window_for_date(date, default_criteria_from_config(config))


def latest_start(schedule: Schedule, config: dict) -> str | None:
    """The latest tee time on `schedule`'s own day that still finishes a round
    of this course's length (plus your daylight buffer) before sunset -- the
    same threshold `exclude_unplayable()`'s daylight check applies, stated as a
    clock time instead of a yes/no. None without a sunset to measure against."""
    if schedule.sun_times is None:
        return None
    return playability.latest_playable_start(
        schedule.sun_times.sunset,
        _round_duration_minutes(schedule.course, config),
        config.get("daylight_buffer_minutes", 0),
    )


def window_too_late_hint(
    schedules: list[Schedule], config: dict, alternatives: dict[str, dict | None] | None = None
) -> dict | None:
    """One standing explanation for the case that otherwise just repeats "too
    dark to finish" on day after day (2026-09-27, bundle C -- found in the
    audit's own renders: 3 of 5 days said exactly that, because a 16:00 weekday
    window plus a ~4-hour 18-hole round no longer fits before an autumn
    sunset). Returned when your window *opens* after the latest start that
    still finishes before dark on at least two of `schedules` -- one odd day
    isn't a pattern worth a standing hint. The first such day's own numbers,
    which is what both front ends phrase the hint from:

        {"window_after": "16:00", "latest_start": "14:40", "sunset": "19:10",
         "round_minutes": 240, "days": 3}

    `alternatives` ({date: `shorter_round_alternative()`'s result or None},
    2026-10-05) adds `"alternative_courses"` -- the distinct courses offered as
    a shorter round on the flagged days, in date order -- so the hint can say
    where a round still fits, not only that the full one doesn't. Absent when
    no flagged day has one.
    """
    flagged = []
    for schedule in schedules:
        window = window_for_date(schedule.date, config)
        latest = latest_start(schedule, config)
        if window is None or window.after is None or latest is None:
            continue
        if window.after > latest:
            flagged.append((schedule, window, latest))
    if len(flagged) < 2:
        return None
    schedule, window, latest = flagged[0]
    hint = {
        "window_after": window.after,
        "latest_start": latest,
        "sunset": schedule.sun_times.sunset,
        "round_minutes": _round_duration_minutes(schedule.course, config),
        "days": len(flagged),
    }
    alternative_courses: list[str] = []
    for flagged_schedule, _, _ in flagged:
        alternative = (alternatives or {}).get(flagged_schedule.date)
        if alternative is not None and alternative["course"] not in alternative_courses:
            alternative_courses.append(alternative["course"])
    if alternative_courses:
        hint["alternative_courses"] = alternative_courses
    return hint


def _schedule_for(candidate: SlotMatch, schedules: list[Schedule]) -> Schedule | None:
    for schedule in schedules:
        if schedule.date == candidate.date and schedule.course == candidate.course:
            return schedule
    return None


def _round_duration_minutes(course: str, config: dict) -> int:
    """config["round_duration_minutes"] only has "nine"/"eighteen" keys (see
    clubs/club.example.yaml) — a genuinely 6-hole course (this club's "6 Loch Platz")
    has no dedicated bucket, so anything under 18 holes maps to "nine" as a reasonable
    proxy (a 6-hole round takes less time than a 9-hole one anyway, so this only ever
    over-estimates the duration, never under-estimates it into an unsafe recommendation).

    Reuses `scraper._holes_from_course_label()` rather than its own regex (found and
    fixed 2026-09-07: the previous `r"(\\d+)\\s*Loch"` pattern required "Loch"
    immediately after the number with no hyphen — silently failed to match a second
    real club's own naming, e.g. "18-Loch Schleife", falling back to `18` for
    literally every one of its courses, including its actual 9-hole and short-course
    options). A genuinely unknown hole count (`None` — e.g. that same club's
    "Kurzplatz", a short/pitch-and-putt course with no leading number at all) assumes
    the *longer* 18-hole duration here specifically, not the "under 18 -> nine"
    shortcut above: overestimating a round's length only ever costs a missed
    recommendation, never approves a genuinely unsafe one — the opposite of what an
    underestimate would risk."""
    holes = _holes_from_course_label(course)
    if holes is None:
        key, default = "eighteen", 240
    else:
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

    def _limit(key: str, default: float) -> float:
        # Settings saves a cleared field as an explicit null, so `.get(key, default)`
        # alone would hand back None and the comparison below would raise TypeError.
        value = preferences.get(key)
        return default if value is None else value

    if preferences.get("avoid_rain"):
        prob_limit = _limit("avoid_rain_probability_percent", DEFAULT_AVOID_RAIN_PROBABILITY_PERCENT)
        mm_limit = _limit("avoid_rain_mm", DEFAULT_AVOID_RAIN_MM)
        if conditions.max_precipitation_probability is not None and conditions.max_precipitation_probability > prob_limit:
            return True
        if conditions.max_precipitation_mm is not None and conditions.max_precipitation_mm > mm_limit:
            return True

    if preferences.get("avoid_wind"):
        wind_limit = _limit("avoid_wind_kph", DEFAULT_AVOID_WIND_KPH)
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


def unplayable_reasons(candidates: list[SlotMatch], schedules: list[Schedule], config: dict) -> set[str]:
    """Which of `exclude_unplayable()`'s two checks — `"daylight"`, `"weather"`, or
    both — actually rejected the given candidates. A pure re-check for display
    purposes only, not a third filtering pass; `exclude_unplayable()` itself is
    unaffected and stays the single source of truth for what's actually playable.

    Added 2026-09-08, direct feedback: "In the overview it says there are no dry
    timeslots, but ... rain is only in the morning" — real confusion traced to a
    real gap, not a bug in the filtering itself: `tui._day_pick_text()`'s "no dry
    picks" message unconditionally implied rain, but `exclude_unplayable()` can
    reject a candidate for *either* reason, and `sun_times` only started actually
    persisting through storage.py the same day (see that module's `init_db()`
    docstring) — meaning the daylight check could only start really excluding
    anything, for the first time, right as this exact confusion was reported. A
    tee time that's simply too late to finish before dark was very likely being
    labeled as if it were a rain problem instead."""
    reasons: set[str] = set()
    for candidate in candidates:
        schedule = _schedule_for(candidate, schedules)
        if schedule is None:
            continue
        if _fails_playability(candidate, schedule, config):
            reasons.add("daylight")
        if _fails_weather(candidate, schedule, config):
            reasons.add("weather")
    return reasons


def _slot_avg_known_handicap(slot: Slot, known_handicaps: dict[str, float]) -> float | None:
    """Average handicap of `slot`'s own players, counting only names
    `known_handicaps` actually has a value for (2026-09-27, direct follow-up:
    "would it make sense to have the option to choose to play with similar HCP or
    with better HCP") -- `None` for an empty slot or one whose players are all
    unrecognized, not a fabricated 0. This reads real, already-known per-slot
    fact, not a statistical pattern across scrape history -- see the friends-
    heatmap/field-composition-by-time ideas this same conversation ruled out for
    the opposite reason."""
    hcps = [known_handicaps[name] for name in slot.players if name in known_handicaps]
    return sum(hcps) / len(hcps) if hcps else None


def _deterministic_order(
    playable: list[SlotMatch],
    config: dict,
    friend_names: set[str] | None,
    known_handicaps: dict[str, float] | None,
    my_handicap: float | None,
) -> list[SlotMatch]:
    """`ranked_matches()`'s deterministic re-ordering -- the HCP sort, then the
    friends sort, both stable -- factored out 2026-10-05 so
    `shorter_round_alternative()` ranks its picks exactly the way the main pick
    is ranked before any AI step. See `ranked_matches()`'s own docstring for
    what each sort means."""
    preferences_for_sort = config.get("preferences", {})
    hcp_preference = preferences_for_sort.get("hcp_preference", "off")
    if hcp_preference in ("similar", "better") and known_handicaps:

        def _hcp_sort_key(match: SlotMatch) -> tuple[int, float]:
            avg = _slot_avg_known_handicap(match.slot, known_handicaps)
            if avg is None:
                return (1, 0.0)
            if hcp_preference == "similar" and my_handicap is not None:
                return (0, abs(avg - my_handicap))
            return (0, avg)  # "better" (or "similar" with no my_handicap yet): lowest first

        playable = sorted(playable, key=_hcp_sort_key)
    if preferences_for_sort.get("prioritize_friends") and friend_names:
        playable = sorted(playable, key=lambda match: 0 if set(match.slot.players) & friend_names else 1)
    return playable


def shorter_round_alternative(
    date: str,
    selected_course: str,
    schedules_by_course: dict[str, Schedule],
    config: dict,
    friend_names: set[str] | None = None,
    known_handicaps: dict[str, float] | None = None,
    my_handicap: float | None = None,
) -> dict | None:
    """A shorter round that still finishes before dark, for a day whose own pick
    on `selected_course` was ruled out by daylight alone (2026-10-05, real
    motivation: in October a 16:00 weekday window plus a ~4-hour 18-hole round
    made every weekday read "too dark to finish", while the same club's 9-hole
    courses -- already scraped into the same club DB -- had plenty of open slots
    that would have finished in time). Returns

        {"course": "9 Loch Tee 1", "time": "16:10", "holes": 9}

    or None. `schedules_by_course` is every course scraped for `date` (the
    selected one included), keyed by course name.

    Only ever offered when daylight is the *only* reason (`unplayable_reasons()`
    == {"daylight"}): rain or wind doesn't stop at a shorter round, so a weather
    verdict -- alone or alongside daylight -- gets no alternative. A day that
    had a pick anyway, or no in-window candidates at all, gets none either.

    Siblings are courses whose hole count `scraper._holes_from_course_label()`
    actually knows and that is below the selected course's; an unknown count
    (e.g. "Kurzplatz") is skipped, never guessed -- and with the *selected*
    course's own count unknown, there's nothing to compare against, so None.

    Same pipeline as the main pick, minus the AI step: `search()` with your own
    `availability` criteria (window, party size, buffers), then
    `exclude_unplayable()` -- round length from each sibling's own hole count via
    `_round_duration_minutes()`, the same daylight buffer and weather limits --
    then `_deterministic_order()`. Deliberately no `ai_assist.rank_slots()` call:
    this is a fallback suggestion shown in place of a "too dark" note, not worth
    a paid call per course per day. "Best" here is still earliest first (across
    all siblings; on a tie, the course with more holes -- closer to the round you
    wanted -- then by name), re-ordered only by the friends/HCP preferences: unlike
    the main pick (2026-10-05, `quality.py`) it is not quality-scored, since the
    sibling courses have no crowd history loaded here and a dark-hours fallback is
    not worth a second scoring path."""
    selected = schedules_by_course.get(selected_course)
    if selected is None or selected.date != date or not config.get("availability"):
        return None
    criteria = default_criteria_from_config(config)
    candidates = search([selected], criteria)
    if not candidates or exclude_unplayable(candidates, [selected], config):
        return None
    if unplayable_reasons(candidates, [selected], config) != {"daylight"}:
        return None
    selected_holes = _holes_from_course_label(selected_course)
    if selected_holes is None:
        return None

    siblings: list[Schedule] = []
    holes_by_course: dict[str, int] = {}
    for course, schedule in schedules_by_course.items():
        if course == selected_course or schedule.date != date:
            continue
        holes = _holes_from_course_label(course)
        if holes is None or holes >= selected_holes:
            continue
        if schedule.sun_times is None:
            # A sibling saved without sun times (its first scrapes fell in a
            # sun-times fetch outage) would pass the daylight check outright --
            # "unknown, not assumed bad" -- and could suggest an 18:40 start on
            # an 18:50 sunset (2026-10-05). Same club, same date: the selected
            # course's sunset, which the daylight gate above just used, applies.
            schedule = dataclasses.replace(schedule, sun_times=selected.sun_times)
        siblings.append(schedule)
        holes_by_course[course] = holes
    if not siblings:
        return None

    sibling_candidates = sorted(
        search(siblings, criteria),
        key=lambda match: (match.slot.time, -holes_by_course[match.course], match.course),
    )
    playable = exclude_unplayable(sibling_candidates, siblings, config)
    playable = _deterministic_order(playable, config, friend_names, known_handicaps, my_handicap)
    if not playable:
        return None
    best = playable[0]
    return {"course": best.course, "time": best.slot.time, "holes": holes_by_course[best.course]}


def ranked_matches(
    schedules: list[Schedule],
    criteria: SearchCriteria,
    config: dict,
    crowd_estimates: dict[tuple[str, str, str], float] | None = None,
    friend_names: set[str] | None = None,
    known_handicaps: dict[str, float] | None = None,
    my_handicap: float | None = None,
    rank_by_quality: bool = False,
    now: datetime | None = None,
    quality_crowd_estimates: dict[tuple[str, str, str], float] | None = None,
    quality_sun_times=None,
) -> list[SlotMatch]:
    """Search + exclude_unplayable + (best-effort) AI ranking for a given
    `SearchCriteria` -- the general form `weekly_picks()` below is built on
    (factored out 2026-09-08, Phase 4's ad hoc search screen: same three-step
    pipeline, just with typed-in criteria in place of your saved defaults).

    Steps 1+2 (search + exclude_unplayable) are the deterministic baseline and always
    run for real. Step 3 (ai_assist.rank_slots) is a genuine improvement, not a
    prerequisite (see module docstring): skipped entirely if the club's
    `ai_assist.enabled` is false (now that ai_assist.py is real and actually costs
    money per call, this flag needs to actually be checked, not just documented), and
    any failure calling it (no API key configured yet, a network hiccup, a rate limit)
    falls back to returning the filtered list as-is (unranked, no `reasons`) rather
    than raising — a short sane list beats no list at all.

    `crowd_estimates` -- {(date, course, time): predicted occupancy 0-1} -- is
    optional and deliberately *not* computed here: `analytics.crowd_heatmap()` needs
    a club's public holidays (a live fetch) and its own SQLite history, and this
    module stays a pure function over already-fetched inputs, same reasoning
    `schedules` itself is handed in rather than scraped here. The caller (tui.py)
    only bothers computing this at all once `ai_assist.avoid_predicted_crowd` is
    actually on -- see that setting's own docstring in settings_screen.py for why it
    moved under "AI ranking" rather than living in "Priorities": it only ever does
    anything through this exact path.

    `friend_names` (2026-09-27, `storage.load_friend_names()`) is the same
    "caller already has it, hand it in" convention `crowd_estimates` already
    follows. When `preferences.prioritize_friends` is on and any names were given,
    a stable sort moves a match whose slot has a marked friend ahead of the rest,
    preserving relative order otherwise -- this is the *deterministic* half, and it
    runs whether or not `ai_assist.enabled` is on, unlike everything below this
    point. When AI ranking also runs, the same names feed a friend *count* (never a
    name -- see `ai_assist._describe_candidate()`'s own docstring) into its prompt
    instead.

    `known_handicaps`/`my_handicap` (2026-09-27, direct follow-up: "would it make
    sense to have the option to choose to play with similar HCP or with better HCP
    for better pace?") follow the identical shape and reasoning as `friend_names`
    -- `storage.load_known_players()`'s own handicaps, "caller already has it,
    hand it in." `preferences.hcp_preference` ("similar" or "better", "off" by
    default) drives a second deterministic stable sort, applied *before* the
    friends sort above so friends still take priority and HCP only breaks ties
    within each friend/non-friend group: "similar" ranks a slot by how close its
    already-booked players' average handicap is to `my_handicap`; "better" ranks
    by that average directly (lower first -- a stronger field plays faster). A
    slot with no known-handicap players at all (most future slots -- nobody's
    booked into them yet) sorts after every slot that *does* have a real field to
    judge, rather than being scored as if it had one. This is a real, already-
    known per-slot fact, never an inferred pattern across scrape history -- see
    `_slot_avg_known_handicap()`'s own docstring for why that distinction
    mattered here. When AI ranking also runs, the field's average handicap (never
    names) feeds into the same per-candidate description `friend_count` already
    does, and `my_handicap` itself joins the `preferences` JSON already sent
    wholesale in the prompt, since it's a fact about the user, not a per-slot one.

    `rank_by_quality` (2026-10-05, off by default) orders the playable slots by
    `quality.score_matches()` -- weather margin, room around the group, predicted
    crowd, daylight cushion -- best first, so the first match is "the best slot", not
    just "the earliest". Equal scores keep chronological order (date, time, course).
    The friend and handicap sorts below it are stable, so they stay *above* the
    score: the score only orders within an equal friend/handicap tier. Each match's
    `score` is then the quality score and `quality_reasons` its reason keys. With AI
    ranking on, the AI receives this score-sorted list (same single call, same cache)
    and still decides the final order; `quality_reasons` survive it (its own prose
    lands in `reasons`). Off, `ranked_matches()` behaves exactly as before -- the ad hoc
    search keeps its chronological list, since its results span many days and a
    score-sort across them would shuffle the days. `now` is the club's wall clock for
    `quality.score_matches()`'s "slot already under way" rule. Its crowd factor reads
    `quality_crowd_estimates`, falling back to `crowd_estimates` -- a separate argument
    because `crowd_estimates` also reaches the AI prompt, and that must stay opt-in
    (`avoid_predicted_crowd`) while the free score always wants the crowd (no history:
    the factor is skipped, see there). `quality_sun_times` is the same kind of
    scoring-only extra: a sibling course's sun times for a schedule that has none of its
    own (see `quality.score_matches()`'s `fallback_sun_times`).

    With `rank_by_quality`, a slot already under way today is the *primary* ordering key:
    the friend and handicap sorts run over the slots still ahead only and the past ones
    follow chronologically, so a friend in a 16:00 slot can't make it the Pick at 16:05
    (2026-10-05).
    """
    candidates = search(schedules, criteria)
    playable = exclude_unplayable(candidates, schedules, config)
    if rank_by_quality:
        # Imported here: quality.py imports this module for the shared round-duration
        # and weather-limit logic, so a top-level import would be circular.
        from . import quality

        crowd = quality_crowd_estimates if quality_crowd_estimates is not None else crowd_estimates
        scored = quality.score_matches(playable, schedules, config, crowd, now, quality_sun_times)
        scored.sort(key=lambda s: (-s.score, s.match.date, s.match.slot.time, s.match.course))
        for item in scored:
            item.match.score = item.score
            item.match.quality_reasons = item.reasons
        # Slots already under way sort below every slot still ahead whatever their friends
        # or handicap tier (2026-10-05): order only the future ones, append the past.
        future = [item.match for item in scored if item.score != quality.PAST_SLOT_SCORE]
        past = [item.match for item in scored if item.score == quality.PAST_SLOT_SCORE]
        playable = _deterministic_order(future, config, friend_names, known_handicaps, my_handicap) + past
    else:
        playable = _deterministic_order(playable, config, friend_names, known_handicaps, my_handicap)

    ai_config = config.get("ai_assist", {})
    if not ai_config.get("enabled", False):
        return playable

    context = {
        "schedules": {(schedule.date, schedule.course): schedule for schedule in schedules},
        "config": config,
        # Per course, so the prompt describes weather over the same window
        # `_fails_weather()` just checked (120 min for a 9-hole course, not 240).
        "round_duration_minutes": {
            schedule.course: _round_duration_minutes(schedule.course, config) for schedule in schedules
        },
    }
    if crowd_estimates:
        context["crowd_estimates"] = crowd_estimates
    if friend_names:
        context["friend_names"] = friend_names
    if known_handicaps:
        context["known_handicaps"] = known_handicaps
    preferences = {
        **config.get("preferences", {}),
        "avoid_predicted_crowd": ai_config.get("avoid_predicted_crowd", False),
    }
    if my_handicap is not None:
        preferences["my_handicap"] = my_handicap
    try:
        return ai_assist.rank_slots(
            playable,
            context=context,
            preferences=preferences,
            provider=ai_config.get("provider", "anthropic"),
            model=ai_config.get("model"),
            language=i18n.get_language(),
        )
    except Exception:
        return playable


def only_with_friend(matches: list[SlotMatch], friend_names: set[str]) -> list[SlotMatch]:
    """Just the matches whose slot already has a marked friend in it -- ad hoc
    search's own "friends only" filter (2026-09-28, direct follow-up to
    `prioritize_friends`: "implement players or friends into the search"). A
    genuinely different effect from that preference's own sort: `prioritize_friends`
    only ever *reorders* `ranked_matches()`'s own output (a friend's slot moves
    first, a slot with no friend still shows, just lower down); this *removes*
    every slot with no friend at all, for the case a search is specifically for
    "when can I play with someone I know," not "prefer it, but show me everything
    else too." A pure function over already-ranked matches, not folded into
    `ranked_matches()` itself, since it's a hard exclude a caller opts into
    per-search, unlike the sort (which is a standing preference)."""
    return [match for match in matches if set(match.slot.players) & friend_names]


def only_with_player(matches: list[SlotMatch], player_name: str) -> list[SlotMatch]:
    """Just the matches with `player_name` (an exact name, e.g. picked from a
    dropdown built off `storage.load_known_players()`) already in the slot --
    the other half of the same direct request `only_with_friend()` answers, for
    "when can I play with this one specific person" rather than any friend."""
    return [match for match in matches if player_name in match.slot.players]


def weekly_picks(
    schedules: list[Schedule], config: dict, crowd_estimates: dict[tuple[str, str, str], float] | None = None
) -> list[SlotMatch]:
    """Best-ranked matches for the week, using your saved default availability --
    see `ranked_matches()` above for the actual three-step pipeline this just
    supplies the usual criteria to (including `crowd_estimates` -- see that
    parameter's own docstring there)."""
    criteria = default_criteria_from_config(config)
    return ranked_matches(schedules, criteria, config, crowd_estimates)


def diversify_by_day(picks: list[SlotMatch], max_count: int) -> list[SlotMatch]:
    """At most one pick per date, in `picks`' own order (best-first once AI ranking is
    on, otherwise `search()`'s natural chronological order) -- capped at `max_count`
    distinct days.

    Added 2026-09-08, direct feedback on a real overview screenshot: "This week's
    picks" showed five different times, all on the same day, with the rest of the
    week entirely absent. Root cause was `tui.OverviewScreen._update_picks()` simply
    truncating `weekly_picks()`'s output to its first N entries -- and `search()`
    walks schedules in date order, exhausting every matching slot in the *first* day
    before ever looking at the next one, so a day with enough open slots to fill the
    whole displayed list crowds out every other day, regardless of whether a later day
    also has good options. This doesn't change what counts as a good slot (that's
    still `ranked_matches()`'s job) -- it only changes which of the already-ranked
    picks get shown, so the visible list actually reflects the whole week rather than
    whichever single day happened to be scanned first."""
    seen_dates: set[str] = set()
    diversified: list[SlotMatch] = []
    for pick in picks:
        if pick.date in seen_dates:
            continue
        seen_dates.add(pick.date)
        diversified.append(pick)
        if len(diversified) >= max_count:
            break
    return diversified
