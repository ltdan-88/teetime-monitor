"""quality.py -- the deterministic slot score behind the day's Pick (2026-10-05)."""

import re
from datetime import datetime

from src import clock, i18n, pipeline, quality, recommend, storage
from src.models import Schedule, Slot, SunTimes, WeatherPoint
from src.quality import (
    MAX_REASONS,
    NEUTRAL_SUBSCORE,
    PAST_SLOT_SCORE,
    REASON_KEYS,
    WEIGHT_CROWD,
    WEIGHT_DAYLIGHT,
    WEIGHT_RAIN,
    WEIGHT_ROOM,
    WEIGHT_TEMPERATURE,
    WEIGHT_WIND,
    score_matches,
)
from src.search import search

DATE = "2026-10-07"  # a Wednesday
COURSE18 = "18 Loch Tee 1"
COURSE9 = "9 Loch Tee 1"
SUNSET = "20:30"  # late enough that daylight never decides these tests unless one says so


def _hourly(rain=0.0, wind=5.0, temp=18.0, mm=0.0, hours=range(8, 22), overrides=None):
    """An hourly forecast; `overrides` is {"HH:00": {field: value}}."""
    points = []
    for hour in hours:
        stamp = f"{hour:02d}:00"
        fields = {"precipitation_probability": rain, "precipitation_mm": mm, "wind_speed_kph": wind, "temperature_c": temp}
        fields.update((overrides or {}).get(stamp, {}))
        points.append(WeatherPoint(time=stamp, **fields))
    return points


def _slots(times, booked=None):
    booked = booked or {}
    return [Slot(time=t, booked=booked.get(t, 0), capacity=4) for t in times]


def _schedule(times, course=COURSE9, weather=None, sunset=SUNSET, booked=None):
    return Schedule(
        date=DATE,
        course=course,
        slots=_slots(times, booked),
        weather=_hourly() if weather is None else weather,
        sun_times=SunTimes(sunrise="07:00", sunset=sunset) if sunset else None,
    )


def _config(**preferences):
    return {
        "availability": {"weekday_window": {"after": "08:00"}},
        "preferences": {"avoid_rain": True, "avoid_rain_probability_percent": 50, **preferences},
    }


def _matches(schedule, config=None):
    config = config or _config()
    return search([schedule], recommend.default_criteria_from_config(config))


def _score(schedule, time, config=None, crowd=None, now=None):
    config = config or _config()
    matches = [m for m in _matches(schedule, config) if m.slot.time == time]
    return score_matches(matches, schedule, config, crowd, now)[0]


# --- the weights -------------------------------------------------------------------------


def test_weights_sum_to_one_hundred_points():
    total = WEIGHT_RAIN + WEIGHT_WIND + WEIGHT_TEMPERATURE + WEIGHT_ROOM + WEIGHT_CROWD + WEIGHT_DAYLIGHT
    assert total == 100


def test_a_slot_with_nothing_known_scores_neutral_everywhere():
    # No weather, no sunset, no history, no neighbours at all: only the room factor can
    # speak (nothing nearby, full marks); everything unknown sits at the neutral midpoint.
    schedule = _schedule(["15:00"], weather=[], sunset=None)
    scored = _score(schedule, "15:00")
    expected = NEUTRAL_SUBSCORE * (WEIGHT_RAIN + WEIGHT_WIND + WEIGHT_TEMPERATURE + WEIGHT_CROWD + WEIGHT_DAYLIGHT) + WEIGHT_ROOM
    assert scored.score == expected
    assert scored.reasons == ["room_around"]


# --- weather margin ----------------------------------------------------------------------


def test_a_dry_later_slot_beats_a_rainy_earlier_slot():
    # 9-hole round (120 min). Rain (40 % of a 50 % limit -- still playable) around 15:00-16:00,
    # dry from 17:00 on.
    weather = _hourly(overrides={"15:00": {"precipitation_probability": 40}, "16:00": {"precipitation_probability": 40}})
    schedule = _schedule(["15:00", "17:00"], weather=weather)
    config = _config()
    both = recommend.ranked_matches([schedule], recommend.default_criteria_from_config(config), config, rank_by_quality=True)
    assert [m.slot.time for m in both] == ["17:00", "15:00"]
    assert "dry" in both[0].quality_reasons
    assert "dry" not in both[1].quality_reasons


def test_rain_margin_is_measured_against_the_users_own_limit():
    weather = _hourly(rain=20)
    schedule = _schedule(["15:00"], weather=weather)
    strict = _score(schedule, "15:00", _config(avoid_rain_probability_percent=25))
    relaxed = _score(schedule, "15:00", _config(avoid_rain_probability_percent=80))
    assert relaxed.score > strict.score
    assert "dry" in relaxed.reasons  # 20 % of an 80 % limit is a clear margin
    assert "dry" not in strict.reasons  # 20 % of a 25 % limit is not


def test_rain_amount_counts_as_well_as_probability():
    schedule_dry = _schedule(["15:00"], weather=_hourly(rain=0, mm=0))
    schedule_wet = _schedule(["15:00"], weather=_hourly(rain=0, mm=0.8))  # under the 1 mm default limit
    assert _score(schedule_dry, "15:00").score > _score(schedule_wet, "15:00").score


def test_rain_and_wind_only_count_when_the_user_switched_them_on(monkeypatch):
    monkeypatch.setattr(quality, "MAX_REASONS", 6)  # so the cap hides none of the six
    windy = _schedule(["15:00"], weather=_hourly(wind=25, rain=45))
    calm = _schedule(["15:00"], weather=_hourly(wind=0, rain=0))
    off = {"avoid_rain": False, "avoid_wind": False}
    assert _score(windy, "15:00", _config(**off)).score == _score(calm, "15:00", _config(**off)).score
    assert not {"dry", "calm"} & set(_score(calm, "15:00", _config(**off)).reasons)
    on = {"avoid_rain": True, "avoid_wind": True}
    assert _score(calm, "15:00", _config(**on)).score > _score(windy, "15:00", _config(**on)).score
    assert {"dry", "calm"} <= set(_score(calm, "15:00", _config(**on)).reasons)


def test_wind_margin_uses_the_wind_limit(monkeypatch):
    monkeypatch.setattr(quality, "MAX_REASONS", 6)  # so the cap hides none of the six
    schedule = _schedule(["15:00"], weather=_hourly(wind=14))
    tight = _score(schedule, "15:00", _config(avoid_wind=True, avoid_wind_kph=20))
    loose = _score(schedule, "15:00", _config(avoid_wind=True, avoid_wind_kph=60))
    assert loose.score > tight.score
    assert "calm" in loose.reasons and "calm" not in tight.reasons


def test_temperature_margin_inside_floor_and_ceiling(monkeypatch):
    monkeypatch.setattr(quality, "MAX_REASONS", 6)  # so the cap hides none of the six
    comfortable = _schedule(["15:00"], weather=_hourly(temp=18))
    chilly = _schedule(["15:00"], weather=_hourly(temp=11))  # 1 degree above a 10 degree floor
    config = _config(avoid_temp_below_c=10, avoid_temp_above_c=30)
    assert _score(comfortable, "15:00", config).score > _score(chilly, "15:00", config).score
    assert "mild" in _score(comfortable, "15:00", config).reasons
    assert "mild" not in _score(chilly, "15:00", config).reasons
    hot = _schedule(["15:00"], weather=_hourly(temp=29))
    assert "mild" not in _score(hot, "15:00", config).reasons
    # No floor/ceiling set: temperature is unknown, never a reason.
    assert "mild" not in _score(comfortable, "15:00").reasons


def test_weather_is_judged_over_the_real_round_nine_holes_versus_eighteen():
    # Heavy-ish rain only from 18:00. A 9-hole round from 15:30 is over by 17:30; an
    # 18-hole one (240 min) runs into it.
    weather = _hourly(overrides={"18:00": {"precipitation_probability": 45}})
    nine = _score(_schedule(["15:30"], course=COURSE9, weather=weather), "15:30")
    eighteen = _score(_schedule(["15:30"], course=COURSE18, weather=weather), "15:30")
    assert nine.score > eighteen.score
    assert "dry" in nine.reasons and "dry" not in eighteen.reasons
    # and a club's own pace is honoured: 90-minute nines end even earlier
    config = {**_config(), "round_duration_minutes": {"nine": 90, "eighteen": 150}}
    assert _score(_schedule(["15:30"], course=COURSE18, weather=weather), "15:30", config).score > eighteen.score


def test_no_forecast_is_neutral_not_good():
    unknown = _score(_schedule(["15:00"], weather=[]), "15:00")
    dry = _score(_schedule(["15:00"]), "15:00")
    assert "dry" not in unknown.reasons
    assert dry.score > unknown.score


# --- room around the group ---------------------------------------------------------------


def test_more_room_around_a_slot_scores_higher():
    # 15:00 has a booked flight ten minutes after it, 16:00 is on its own.
    schedule = _schedule(["15:00", "15:10", "16:00", "17:00"], booked={"15:10": 2, "16:40": 1})
    crowded = _score(schedule, "15:00")
    roomy = _score(schedule, "16:00")
    assert roomy.score > crowded.score
    assert "room_around" not in crowded.reasons


def test_a_flight_beyond_the_horizon_costs_nothing():
    schedule = _schedule(["15:00", "16:30"], booked={"16:30": 1})
    # 90 minutes to the next flight, none before: both sides full
    assert "room_around" in _score(schedule, "15:00").reasons


def test_the_users_own_buffer_widens_what_counts_as_roomy():
    schedule = _schedule(["15:00", "16:10"], booked={"16:10": 1})  # 70 minutes of gap after 15:00
    plain = _config()
    wide = {**_config(), "availability": {"weekday_window": {"after": "08:00"}, "buffer_after_minutes": 60}}
    assert _score(schedule, "15:00", plain).score > _score(schedule, "15:00", wide).score


def test_blocked_slots_count_as_flights_for_the_room_factor():
    schedule = _schedule(["15:00", "15:10"])
    schedule.slots[1] = Slot(time="15:10", booked=0, capacity=4, block_reason="Turnier")
    open_schedule = _schedule(["15:00", "15:10"])
    assert _score(schedule, "15:00").score < _score(open_schedule, "15:00").score


# --- predicted crowd ---------------------------------------------------------------------


def test_a_quieter_hour_scores_higher_and_earns_quiet():
    schedule = _schedule(["15:00", "17:00"])
    crowd = {(DATE, COURSE9, "15:00"): 0.8, (DATE, COURSE9, "17:00"): 0.1}
    busy, quiet = _score(schedule, "15:00", crowd=crowd), _score(schedule, "17:00", crowd=crowd)
    assert quiet.score > busy.score
    assert "quiet" in quiet.reasons and "quiet" not in busy.reasons


def test_crowd_factor_is_skipped_without_history():
    schedule = _schedule(["15:00", "17:00"])
    without = [_score(schedule, t) for t in ("15:00", "17:00")]
    assert without[0].score == without[1].score  # nothing to tell them apart
    empty = [_score(schedule, t, crowd={}) for t in ("15:00", "17:00")]
    assert [s.score for s in empty] == [s.score for s in without]
    # One hour has history, the other has not: the one without is neutral, not penalised.
    partial = {(DATE, COURSE9, "17:00"): 0.5}
    assert _score(schedule, "15:00", crowd=partial).score == without[0].score
    assert all("quiet" not in s.reasons for s in without + empty)


# --- daylight cushion --------------------------------------------------------------------


def test_more_daylight_to_spare_scores_higher_and_is_capped():
    # 9-hole = 120 min, sunset 19:00: a 14:00 start ends at 16:00 (3 h to spare), 15:30 ends
    # at 17:30 (90 min), 16:30 ends 18:30 (30 min).
    schedule = _schedule(["14:00", "15:30", "16:30"], sunset="19:00")
    early, mid, late = (_score(schedule, t) for t in ("14:00", "15:30", "16:30"))
    assert early.score == mid.score  # both at or beyond the cap
    assert mid.score > late.score
    assert "daylight_spare" in early.reasons and "daylight_spare" not in late.reasons


def test_no_sunset_is_neutral():
    assert "daylight_spare" not in _score(_schedule(["14:00"], sunset=None), "14:00").reasons


def test_a_fallback_sunset_stands_in_for_a_schedule_saved_without_one():
    from src.models import SunTimes as Sun

    schedule = _schedule(["15:00", "17:30"], sunset=None)
    config = _config()
    matches = _matches(schedule, config)
    plain = {s.match.slot.time: s for s in score_matches(matches, schedule, config)}
    assert plain["15:00"].score == plain["17:30"].score  # neutral daylight: nothing tells them apart
    borrowed = {s.match.slot.time: s for s in score_matches(matches, schedule, config, None, None, Sun("07:00", "19:00"))}
    assert borrowed["15:00"].score > borrowed["17:30"].score  # 17:30 + 2 h finishes after sunset
    assert "daylight_spare" in borrowed["15:00"].reasons
    # a schedule with its own sunset never takes the fallback
    own = _schedule(["15:00", "17:30"], sunset="22:00")
    own_scores = score_matches(_matches(own, config), own, config, None, None, Sun("07:00", "16:00"))
    assert own_scores[0].score == own_scores[1].score


# --- reasons -----------------------------------------------------------------------------


def test_reasons_are_capped_and_ordered_by_contribution():
    schedule = _schedule(["14:00"], weather=_hourly(rain=0, wind=0, temp=18))
    config = _config(avoid_wind=True, avoid_temp_below_c=5, avoid_temp_above_c=30)
    crowd = {(DATE, COURSE9, "14:00"): 0.0}
    scored = _score(schedule, "14:00", config, crowd)
    # dry (22), room_around (20), quiet (20), daylight_spare (15), calm (13), mild (10) all
    # qualify; only the top three, biggest contribution first (ties in REASON_KEYS order).
    assert scored.reasons == ["dry", "room_around", "quiet"]
    assert len(scored.reasons) == MAX_REASONS
    assert set(scored.reasons) <= set(REASON_KEYS)


def test_a_slot_with_nothing_notable_has_no_reasons():
    # Rain right at its limit, a flight ten minutes either side, a packed hour, little light.
    weather = _hourly(rain=45)
    schedule = _schedule(["16:00", "15:50", "16:10"], weather=weather, sunset="18:30", booked={"15:50": 1, "16:10": 1})
    crowd = {(DATE, COURSE9, "16:00"): 0.9}
    assert _score(schedule, "16:00", crowd=crowd).reasons == []


def test_scoring_is_deterministic_and_independent_of_input_order():
    weather = _hourly(overrides={"16:00": {"precipitation_probability": 30}})
    schedule = _schedule(["15:00", "15:10", "16:00", "17:00"], weather=weather, booked={"15:10": 2})
    config = _config()
    matches = _matches(schedule, config)
    first = score_matches(matches, schedule, config)
    again = score_matches(matches, schedule, config)
    reversed_ = score_matches(list(reversed(matches)), schedule, config)
    assert [(s.match.slot.time, s.score, s.reasons) for s in first] == [(s.match.slot.time, s.score, s.reasons) for s in again]
    assert {s.match.slot.time: (s.score, s.reasons) for s in first} == {
        s.match.slot.time: (s.score, s.reasons) for s in reversed_
    }
    assert [s.match for s in first] == matches  # scoring never reorders


def test_scores_stay_between_zero_and_one_hundred():
    schedule = _schedule(["15:00"], weather=_hourly(rain=100, mm=9, wind=90, temp=-5))
    worst = _score(schedule, "15:00", _config(avoid_wind=True, avoid_temp_below_c=5))
    best = _score(_schedule(["12:00"]), "12:00", crowd={(DATE, COURSE9, "12:00"): 0.0})
    assert 0 <= worst.score < best.score <= 100


def test_a_schedule_missing_from_the_list_scores_neutral_instead_of_crashing():
    schedule = _schedule(["15:00"])
    matches = _matches(schedule)
    scored = score_matches(matches, [], _config())
    assert scored[0].reasons == []


# --- slots already under way -------------------------------------------------------------


def test_a_slot_already_started_today_scores_below_every_future_slot():
    schedule = _schedule(["15:00", "17:00"])
    now = datetime(2026, 10, 7, 16, 0)
    past = _score(schedule, "15:00", now=now)
    future = _score(schedule, "17:00", now=now)
    assert past.score == PAST_SLOT_SCORE and past.reasons == []
    assert future.score > past.score
    # Another day's "past" times are not past.
    assert _score(schedule, "15:00", now=datetime(2026, 10, 6, 23, 0)).score > 0


# --- ordering inside ranked_matches ------------------------------------------------------


def _ranked(schedule, config=None, **kwargs):
    config = config or _config()
    return recommend.ranked_matches(
        [schedule], recommend.default_criteria_from_config(config), config, rank_by_quality=True, **kwargs
    )


def test_equal_scores_keep_the_earliest_slot_first():
    schedule = _schedule(["15:00", "17:00", "16:00"])  # identical conditions, spread far apart
    assert [m.slot.time for m in _ranked(schedule)] == ["15:00", "16:00", "17:00"]


def test_ranked_matches_without_the_flag_is_still_chronological():
    weather = _hourly(overrides={"15:00": {"precipitation_probability": 40}})
    schedule = _schedule(["15:00", "17:00"], weather=weather)
    config = _config()
    plain = recommend.ranked_matches([schedule], recommend.default_criteria_from_config(config), config)
    assert [m.slot.time for m in plain] == ["15:00", "17:00"]
    assert all(m.quality_reasons == [] and m.score == 0.0 for m in plain)


def test_a_friend_tier_beats_a_better_score():
    weather = _hourly(overrides={"15:00": {"precipitation_probability": 45}, "16:00": {"precipitation_probability": 45}})
    schedule = _schedule(["15:00", "17:00"], weather=weather)
    schedule.slots[0].players = ["Pat"]
    schedule.slots[0].booked = 1
    config = {**_config(), "preferences": {"avoid_rain": True, "avoid_rain_probability_percent": 50, "prioritize_friends": True}}
    ranked = _ranked(schedule, config, friend_names={"Pat"})
    assert [m.slot.time for m in ranked] == ["15:00", "17:00"]  # the friend's slot, though wetter
    assert ranked[0].score < ranked[1].score  # the score really did prefer 17:00
    # without the preference the score decides
    ranked = _ranked(schedule, _config(), friend_names={"Pat"})
    assert [m.slot.time for m in ranked] == ["17:00", "15:00"]


def test_a_slot_already_under_way_sorts_below_every_future_slot_even_with_a_friend():
    schedule = _schedule(["16:00", "16:10", "17:00"])
    schedule.slots[0].players = ["Pat"]
    schedule.slots[0].booked = 1
    config = {**_config(), "preferences": {"avoid_rain": True, "prioritize_friends": True}}
    now = datetime(2026, 10, 7, 16, 5)
    ranked = _ranked(schedule, config, friend_names={"Pat"}, now=now)
    assert [m.slot.time for m in ranked] == ["17:00", "16:10", "16:00"]  # 17:00: more room than 16:10
    # the friend tier still works among the slots that are still ahead
    schedule.slots[1].players = ["Pat"]
    schedule.slots[1].booked = 1
    ranked = _ranked(schedule, config, friend_names={"Pat"}, now=now)
    assert [m.slot.time for m in ranked] == ["16:10", "17:00", "16:00"]


def test_the_handicap_preference_also_stays_above_the_score():
    weather = _hourly(overrides={"15:00": {"precipitation_probability": 45}, "16:00": {"precipitation_probability": 45}})
    schedule = _schedule(["15:00", "17:00"], weather=weather)
    schedule.slots[0].players = ["Ann"]
    schedule.slots[0].booked = 1
    config = {**_config(), "preferences": {"avoid_rain": True, "avoid_rain_probability_percent": 50, "hcp_preference": "better"}}
    ranked = _ranked(schedule, config, known_handicaps={"Ann": 5.0})
    assert [m.slot.time for m in ranked] == ["15:00", "17:00"]  # a known field sorts before an unknown one


def test_ranked_matches_attaches_score_and_reason_keys():
    schedule = _schedule(["15:00"])
    [match] = _ranked(schedule)
    assert match.score > 0
    assert match.quality_reasons and set(match.quality_reasons) <= set(REASON_KEYS)
    assert match.reasons == []  # `reasons` stays the AI's, empty without it


def test_the_crowd_factor_reaches_ranked_matches():
    schedule = _schedule(["15:00", "17:00"])
    crowd = {(DATE, COURSE9, "15:00"): 0.9, (DATE, COURSE9, "17:00"): 0.1}
    assert [m.slot.time for m in _ranked(schedule, quality_crowd_estimates=crowd)] == ["17:00", "15:00"]
    assert [m.slot.time for m in _ranked(schedule, crowd_estimates=crowd)] == ["17:00", "15:00"]
    assert [m.slot.time for m in _ranked(schedule)] == ["15:00", "17:00"]


def test_the_ai_receives_the_score_sorted_list_and_keeps_the_quality_reasons(monkeypatch):
    weather = _hourly(overrides={"15:00": {"precipitation_probability": 40}, "16:00": {"precipitation_probability": 40}})
    schedule = _schedule(["15:00", "17:00"], weather=weather)
    config = {**_config(), "ai_assist": {"enabled": True}}
    seen = []

    def fake_rank_slots(candidates, context, preferences, provider, model, language):
        seen.append([c.slot.time for c in candidates])
        for c in candidates:
            c.score, c.reasons = 90.0, ["emptier"]
        return list(reversed(candidates))  # the AI disagrees

    monkeypatch.setattr(recommend.ai_assist, "rank_slots", fake_rank_slots)
    ranked = recommend.ranked_matches([schedule], recommend.default_criteria_from_config(config), config, rank_by_quality=True)
    assert seen == [["17:00", "15:00"]]  # best score first, one call
    assert [m.slot.time for m in ranked] == ["15:00", "17:00"]  # the AI had the last word
    assert ranked[0].reasons == ["emptier"]
    assert "dry" in ranked[1].quality_reasons  # the deterministic why survived the AI step


# --- the pipeline the Pick comes from ----------------------------------------------------


def _pipeline_config(**extra):
    return {**_config(), "availability": {"weekday_window": {"after": "14:00"}}, **extra}


def test_the_pipelines_first_playable_is_the_best_slot_and_the_stars_are_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: "2026-10-05")
    weather = _hourly(overrides={"15:00": {"precipitation_probability": 40}, "16:00": {"precipitation_probability": 40}})
    schedule = _schedule(["15:00", "17:00", "17:10"], weather=weather)
    config = _pipeline_config()
    candidates, playable = pipeline._availability_pipeline(schedule, config, "0000001", {})
    assert [m.slot.time for m in candidates] == ["15:00", "17:00", "17:10"]
    assert playable[0].slot.time != "15:00"  # no longer simply the earliest
    assert playable[0].slot.time == "17:00"
    assert pipeline._recommended_times_for(schedule, config, "0000001", {}) == {"15:00", "17:00", "17:10"}


def test_the_pipeline_borrows_a_sibling_courses_sunset_for_scoring_only(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: "2026-10-05")
    weather = _hourly(overrides={"15:00": {"precipitation_probability": 30}, "16:00": {"precipitation_probability": 30}})
    schedule = _schedule(["15:00", "17:30"], weather=weather, sunset=None)
    config = _pipeline_config()
    _, playable = pipeline._availability_pipeline(schedule, config, "0000001", {})
    assert [m.slot.time for m in playable] == ["17:30", "15:00"]  # nothing known about the light
    db = pipeline._db_path("0000001")
    storage.save_schedule(_schedule(["10:00"], course=COURSE18, sunset="19:00"), path=db)
    _, playable = pipeline._availability_pipeline(schedule, config, "0000001", {})
    assert [m.slot.time for m in playable] == ["15:00", "17:30"]  # 17:30 + 2 h ends after dusk
    # scoring only: the hard filter and the star markers still treat the sunset as unknown
    assert {m.slot.time for m in playable} == {"15:00", "17:30"}


def test_the_pipeline_feeds_the_crowd_estimates_holiday_blind(tmp_path, monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: "2026-10-05")
    schedule = _schedule(["15:00", "17:00"])
    calls = []

    def fake_compute(schedules, config, club_id, db_path=None, fetch_holidays=True, use_holidays=True):
        calls.append(use_holidays)
        return {(DATE, COURSE9, "15:00"): 0.9, (DATE, COURSE9, "17:00"): 0.1}

    monkeypatch.setattr(pipeline, "_compute_crowd_estimates", fake_compute)
    _, playable = pipeline._availability_pipeline(schedule, _pipeline_config(), "0000001", {})
    assert [m.slot.time for m in playable] == ["17:00", "15:00"]
    assert "quiet" in playable[0].quality_reasons
    assert calls == [False]  # never a holiday fetch (and never an AI-gated estimate here)


def test_the_pipeline_survives_an_unreadable_history_database(monkeypatch):
    import sqlite3

    monkeypatch.setattr(clock, "today", lambda: "2026-10-05")

    def broken(*args, **kwargs):
        raise sqlite3.DatabaseError("file is not a database")

    monkeypatch.setattr(pipeline, "_compute_crowd_estimates", broken)
    schedule = _schedule(["15:00", "17:00"])
    _, playable = pipeline._availability_pipeline(schedule, _pipeline_config(), "0000001", {})
    assert [m.slot.time for m in playable] == ["15:00", "17:00"]


def test_the_pipeline_reads_real_history_for_the_crowd(tmp_path, monkeypatch):
    """End to end through analytics: three finished Wednesdays that were busy at 15:xx and
    empty at 17:xx make the 17:xx slot the Pick, with no holiday fetch at all."""
    monkeypatch.setattr(clock, "today", lambda: "2026-10-05")
    monkeypatch.setattr(pipeline.calendar_context, "fetch_public_holidays", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    db = pipeline._db_path("0000001")
    for past in ("2026-09-16", "2026-09-23", "2026-09-30"):  # Wednesdays
        day = Schedule(
            date=past,
            course=COURSE9,
            slots=[Slot(time="15:00", booked=4, capacity=4), Slot(time="17:00", booked=0, capacity=4)],
        )
        storage.save_schedule(day, path=db)
    schedule = _schedule(["15:00", "17:00"])
    config = {**_pipeline_config(), "calendar": {"country_code": "DE"}}
    _, playable = pipeline._availability_pipeline(schedule, config, "0000001", {})
    assert [m.slot.time for m in playable] == ["17:00", "15:00"]
    assert "quiet" in playable[0].quality_reasons


def test_local_now_reads_the_clock_seam(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: "2026-10-05")
    monkeypatch.setattr(clock, "now_hhmm", lambda: "16:45")
    assert pipeline._local_now() == datetime(2026, 10, 5, 16, 45)


def test_a_slot_already_under_way_today_is_not_the_pick(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: DATE)
    monkeypatch.setattr(clock, "now_hhmm", lambda: "15:30")
    schedule = _schedule(["15:00", "17:00"])
    _, playable = pipeline._availability_pipeline(schedule, _pipeline_config(), "0000001", {})
    assert [m.slot.time for m in playable] == ["17:00", "15:00"]


# --- text --------------------------------------------------------------------------------


def test_reasons_text_localises_and_skips_unknown_keys():
    i18n.set_language("en")
    assert quality.reasons_text(["dry", "room_around", "daylight_spare"]) == "dry · room around you · daylight to spare"
    assert quality.reasons_text(["dry", "bogus"]) == "dry"
    assert quality.reasons_text([]) == ""
    i18n.set_language("de")
    assert quality.reasons_text(["dry", "quiet"]) == "trocken · ruhige Stunde"


def test_every_reason_key_has_both_translations_without_placeholders():
    for key in REASON_KEYS:
        for lang in ("en", "de"):
            text = i18n._STRINGS[lang][f"quality.reason.{key}"]
            assert text and not re.search(r"{\w+}", text)
    assert "{reasons}" in i18n._STRINGS["en"]["overview.pick_reasons"]
    assert "{reasons}" in i18n._STRINGS["de"]["overview.pick_reasons"]
