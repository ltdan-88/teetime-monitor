from src.models import Schedule, Slot, SlotMatch, SunTimes, TimeWindow, WeatherPoint
from src.recommend import (
    _round_duration_minutes,
    default_criteria_from_config,
    exclude_unplayable,
    ranked_matches,
    unplayable_reasons,
    weekly_picks,
)
from src.search import SearchCriteria


def test_default_criteria_from_config_reads_availability_block():
    config = {
        "availability": {
            "min_open_spots": 3,
            "weekday_window": {"after": "17:00"},
            "weekend_window": {"after": "10:00"},
            "buffer_before_minutes": 20,
            "buffer_after_minutes": 10,
        }
    }

    criteria = default_criteria_from_config(config)

    assert criteria == SearchCriteria(
        min_open_spots=3,
        weekday_window=TimeWindow(after="17:00"),
        weekend_window=TimeWindow(after="10:00"),
        buffer_before_minutes=20,
        buffer_after_minutes=10,
    )


def test_default_criteria_from_config_falls_back_to_the_old_single_buffer_key():
    # A config saved before the 2026-09-08 before/after buffer split -- resolved
    # through search.resolve_buffer_minutes(), not lost.
    config = {"availability": {"buffer_minutes": 15}}

    criteria = default_criteria_from_config(config)

    assert criteria.buffer_before_minutes == 15
    assert criteria.buffer_after_minutes == 15


def test_default_criteria_from_config_defaults_when_missing():
    criteria = default_criteria_from_config({})
    assert criteria == SearchCriteria()


def test_exclude_unplayable_drops_slot_that_finishes_after_dark():
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="17:00", booked=0, capacity=4)],
        sun_times=SunTimes(sunrise="06:30", sunset="19:47"),
    )
    candidate = SlotMatch(date="2026-09-06", course="18 Loch Tee 1", slot=schedule.slots[0], score=0.0)
    config = {"round_duration_minutes": {"eighteen": 240}, "daylight_buffer_minutes": 30}

    assert exclude_unplayable([candidate], [schedule], config) == []


def test_exclude_unplayable_keeps_slot_that_finishes_before_dark():
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="08:00", booked=0, capacity=4)],
        sun_times=SunTimes(sunrise="06:30", sunset="19:47"),
    )
    candidate = SlotMatch(date="2026-09-06", course="18 Loch Tee 1", slot=schedule.slots[0], score=0.0)
    config = {"round_duration_minutes": {"eighteen": 240}, "daylight_buffer_minutes": 30}

    result = exclude_unplayable([candidate], [schedule], config)
    assert result == [candidate]


def test_exclude_unplayable_skips_daylight_check_without_sun_times():
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="17:00", booked=0, capacity=4)],
        sun_times=None,
    )
    candidate = SlotMatch(date="2026-09-06", course="18 Loch Tee 1", slot=schedule.slots[0], score=0.0)
    config = {"round_duration_minutes": {"eighteen": 240}, "daylight_buffer_minutes": 30}

    # No sun_times to check against -- treated as unknown, not excluded.
    assert exclude_unplayable([candidate], [schedule], config) == [candidate]


def test_exclude_unplayable_drops_slot_with_heavy_rain():
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="08:00", booked=0, capacity=4)],
        weather=[WeatherPoint(time="08:00", precipitation_probability=90.0, precipitation_mm=5.0)],
    )
    candidate = SlotMatch(date="2026-09-06", course="18 Loch Tee 1", slot=schedule.slots[0], score=0.0)
    config = {"round_duration_minutes": {"eighteen": 240}, "preferences": {"avoid_rain": True}}

    assert exclude_unplayable([candidate], [schedule], config) == []


def test_exclude_unplayable_keeps_slot_with_light_rain_under_threshold():
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="08:00", booked=0, capacity=4)],
        weather=[WeatherPoint(time="08:00", precipitation_probability=10.0, precipitation_mm=0.0)],
    )
    candidate = SlotMatch(date="2026-09-06", course="18 Loch Tee 1", slot=schedule.slots[0], score=0.0)
    config = {"round_duration_minutes": {"eighteen": 240}, "preferences": {"avoid_rain": True}}

    assert exclude_unplayable([candidate], [schedule], config) == [candidate]


def test_exclude_unplayable_ignores_rain_when_avoid_rain_is_false():
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="08:00", booked=0, capacity=4)],
        weather=[WeatherPoint(time="08:00", precipitation_probability=90.0, precipitation_mm=10.0)],
    )
    candidate = SlotMatch(date="2026-09-06", course="18 Loch Tee 1", slot=schedule.slots[0], score=0.0)
    config = {"round_duration_minutes": {"eighteen": 240}, "preferences": {"avoid_rain": False}}

    assert exclude_unplayable([candidate], [schedule], config) == [candidate]


def test_exclude_unplayable_respects_custom_rain_threshold():
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="08:00", booked=0, capacity=4)],
        weather=[WeatherPoint(time="08:00", precipitation_probability=60.0, precipitation_mm=0.0)],
    )
    candidate = SlotMatch(date="2026-09-06", course="18 Loch Tee 1", slot=schedule.slots[0], score=0.0)
    config = {
        "round_duration_minutes": {"eighteen": 240},
        "preferences": {"avoid_rain": True, "avoid_rain_probability_percent": 80},
    }

    # 60% is under this club's custom 80% cutoff -- kept, even though it'd fail the
    # default 50% threshold.
    assert exclude_unplayable([candidate], [schedule], config) == [candidate]


def test_exclude_unplayable_drops_slot_with_high_wind():
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="08:00", booked=0, capacity=4)],
        weather=[WeatherPoint(time="08:00", wind_speed_kph=45.0)],
    )
    candidate = SlotMatch(date="2026-09-06", course="18 Loch Tee 1", slot=schedule.slots[0], score=0.0)
    config = {"round_duration_minutes": {"eighteen": 240}, "preferences": {"avoid_wind": True}}

    assert exclude_unplayable([candidate], [schedule], config) == []


def test_exclude_unplayable_drops_slot_too_cold():
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="08:00", booked=0, capacity=4)],
        weather=[WeatherPoint(time="08:00", temperature_c=2.0)],
    )
    candidate = SlotMatch(date="2026-09-06", course="18 Loch Tee 1", slot=schedule.slots[0], score=0.0)
    config = {"round_duration_minutes": {"eighteen": 240}, "preferences": {"avoid_temp_below_c": 5}}

    assert exclude_unplayable([candidate], [schedule], config) == []


def test_exclude_unplayable_drops_slot_too_hot():
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="08:00", booked=0, capacity=4)],
        weather=[WeatherPoint(time="08:00", temperature_c=38.0)],
    )
    candidate = SlotMatch(date="2026-09-06", course="18 Loch Tee 1", slot=schedule.slots[0], score=0.0)
    config = {"round_duration_minutes": {"eighteen": 240}, "preferences": {"avoid_temp_above_c": 32}}

    assert exclude_unplayable([candidate], [schedule], config) == []


def test_exclude_unplayable_skips_weather_check_without_forecast():
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="08:00", booked=0, capacity=4)],
        weather=[],  # forecast doesn't reach this far
    )
    candidate = SlotMatch(date="2026-09-06", course="18 Loch Tee 1", slot=schedule.slots[0], score=0.0)
    config = {"round_duration_minutes": {"eighteen": 240}, "preferences": {"avoid_rain": True}}

    assert exclude_unplayable([candidate], [schedule], config) == [candidate]


def test_exclude_unplayable_uses_nine_hole_duration_for_a_6_hole_course():
    # "6 Loch Platz" has no dedicated duration bucket -- should fall back to "nine",
    # not "eighteen" (which would over-estimate and wrongly exclude a playable slot).
    schedule = Schedule(
        date="2026-09-06",
        course="6 Loch Platz",
        slots=[Slot(time="18:00", booked=0, capacity=4)],
        sun_times=SunTimes(sunrise="06:30", sunset="19:47"),
    )
    candidate = SlotMatch(date="2026-09-06", course="6 Loch Platz", slot=schedule.slots[0], score=0.0)
    config = {
        "round_duration_minutes": {"nine": 90, "eighteen": 240},
        "daylight_buffer_minutes": 0,
    }

    # 18:00 + 90 min (nine-hole bucket) = 19:30, before sunset -- playable.
    # 18:00 + 240 min (eighteen-hole bucket) would finish at 22:00 -- would wrongly fail.
    assert exclude_unplayable([candidate], [schedule], config) == [candidate]


def test_round_duration_minutes_matches_hyphenated_18_hole_course_name():
    # Found and fixed 2026-09-07: the previous regex required "Loch" right after the
    # number with no hyphen, so a second real club's own naming ("18-Loch Schleife")
    # silently fell through to a hardcoded default instead of actually matching 18.
    config = {"round_duration_minutes": {"nine": 120, "eighteen": 240}}
    assert _round_duration_minutes("18-Loch Schleife", config) == 240


def test_round_duration_minutes_matches_hyphenated_9_hole_course_name():
    config = {"round_duration_minutes": {"nine": 120, "eighteen": 240}}
    assert _round_duration_minutes("9-Loch Schleife", config) == 120


def test_round_duration_minutes_assumes_the_safe_longer_duration_when_holes_unknown():
    # "Kurzplatz" (a short/pitch-and-putt course) has no leading number at all -- an
    # unknown hole count assumes the *longer* 18-hole duration, since overestimating a
    # round's length only ever costs a missed recommendation, never approves a
    # genuinely unsafe one.
    config = {"round_duration_minutes": {"nine": 120, "eighteen": 240}}
    assert _round_duration_minutes("Kurzplatz", config) == 240


def test_exclude_unplayable_passes_through_candidate_with_no_matching_schedule():
    candidate = SlotMatch(
        date="2026-09-06", course="18 Loch Tee 1", slot=Slot(time="08:00", booked=0, capacity=4), score=0.0
    )
    assert exclude_unplayable([candidate], [], {}) == [candidate]


# --- unplayable_reasons (2026-09-08, direct feedback: "In the overview it says
# there are no dry timeslots, but ... rain is only in the morning" -- the old
# "no dry picks" message unconditionally implied rain even when daylight was the
# real reason nothing survived) ------------------------------------------------


def test_unplayable_reasons_identifies_daylight_only():
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="17:00", booked=0, capacity=4)],
        sun_times=SunTimes(sunrise="06:30", sunset="19:47"),
    )
    candidate = SlotMatch(date="2026-09-06", course="18 Loch Tee 1", slot=schedule.slots[0], score=0.0)
    config = {"round_duration_minutes": {"eighteen": 240}, "daylight_buffer_minutes": 30}

    assert unplayable_reasons([candidate], [schedule], config) == {"daylight"}


def test_unplayable_reasons_identifies_weather_only():
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="09:00", booked=0, capacity=4)],
        weather=[WeatherPoint(time="09:00", precipitation_probability=90)],
    )
    candidate = SlotMatch(date="2026-09-06", course="18 Loch Tee 1", slot=schedule.slots[0], score=0.0)
    config = {"preferences": {"avoid_rain": True}}

    assert unplayable_reasons([candidate], [schedule], config) == {"weather"}


def test_unplayable_reasons_identifies_both():
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="18:00", booked=0, capacity=4)],
        weather=[WeatherPoint(time="18:00", precipitation_probability=90)],
        sun_times=SunTimes(sunrise="06:30", sunset="19:00"),
    )
    candidate = SlotMatch(date="2026-09-06", course="18 Loch Tee 1", slot=schedule.slots[0], score=0.0)
    config = {
        "round_duration_minutes": {"eighteen": 240},
        "daylight_buffer_minutes": 30,
        "preferences": {"avoid_rain": True},
    }

    assert unplayable_reasons([candidate], [schedule], config) == {"daylight", "weather"}


def test_unplayable_reasons_empty_when_nothing_actually_failed():
    schedule = Schedule(
        date="2026-09-06",
        course="18 Loch Tee 1",
        slots=[Slot(time="09:00", booked=0, capacity=4)],
    )
    candidate = SlotMatch(date="2026-09-06", course="18 Loch Tee 1", slot=schedule.slots[0], score=0.0)

    assert unplayable_reasons([candidate], [schedule], {}) == set()


def test_ranked_matches_uses_the_given_criteria_not_the_configs_own_availability():
    # Phase 4's ad hoc search screen: a typed-in one-off criteria, deliberately
    # different from whatever's saved as this config's own "availability" block --
    # ranked_matches() must actually use the criteria it's handed, not silently
    # re-derive one from config (which weekly_picks() does instead, and shouldn't
    # here).
    schedule = Schedule(
        date="2026-09-07",  # Monday
        course="18 Loch Tee 1",
        slots=[Slot(time="09:00", booked=0, capacity=4), Slot(time="18:00", booked=0, capacity=4)],
    )
    # This config's own saved default would only match the evening slot...
    config = {"availability": {"weekday_window": {"after": "17:00"}}}
    # ...but the ad hoc criteria asks for something else entirely: a morning slot.
    criteria = SearchCriteria(weekday_window=TimeWindow(after="08:00", before="12:00"))

    matches = ranked_matches([schedule], criteria, config)

    assert [m.slot.time for m in matches] == ["09:00"]


def test_weekly_picks_skips_ai_ranking_when_ai_assist_disabled():
    # No "ai_assist" block at all -- defaults to disabled, so this must never call
    # ai_assist.rank_slots() (which would otherwise need a real API key).
    schedule = Schedule(
        date="2026-09-07",  # Monday
        course="18 Loch Tee 1",
        slots=[Slot(time="18:00", booked=0, capacity=4)],
    )
    config = {"availability": {"weekday_window": {"after": "17:00"}}}

    picks = weekly_picks([schedule], config)

    assert len(picks) == 1
    assert picks[0].slot.time == "18:00"


def test_weekly_picks_uses_ai_assist_rank_slots_when_enabled(monkeypatch):
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[Slot(time="18:00", booked=0, capacity=4)],
    )
    config = {
        "availability": {"weekday_window": {"after": "17:00"}},
        "ai_assist": {"enabled": True, "model": "claude-haiku-4-5"},
    }

    calls = []

    def fake_rank_slots(candidates, context, preferences, model):
        calls.append({"candidates": candidates, "context": context, "model": model})
        for candidate in candidates:
            candidate.score = 99.0
            candidate.reasons = ["dry and empty"]
        return candidates

    import src.recommend as recommend_module

    monkeypatch.setattr(recommend_module.ai_assist, "rank_slots", fake_rank_slots)

    picks = weekly_picks([schedule], config)

    assert len(calls) == 1
    assert calls[0]["model"] == "claude-haiku-4-5"
    assert ("2026-09-07", "18 Loch Tee 1") in calls[0]["context"]["schedules"]
    assert picks[0].score == 99.0
    assert picks[0].reasons == ["dry and empty"]


def test_weekly_picks_falls_back_to_unranked_list_when_ai_assist_call_fails(monkeypatch):
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[Slot(time="18:00", booked=0, capacity=4)],
    )
    config = {
        "availability": {"weekday_window": {"after": "17:00"}},
        "ai_assist": {"enabled": True},
    }

    import src.recommend as recommend_module

    def broken_rank_slots(*args, **kwargs):
        raise RuntimeError("no API key configured")

    monkeypatch.setattr(recommend_module.ai_assist, "rank_slots", broken_rank_slots)

    picks = weekly_picks([schedule], config)

    assert len(picks) == 1
    assert picks[0].slot.time == "18:00"
    assert picks[0].score == 0.0  # untouched -- never actually ranked
