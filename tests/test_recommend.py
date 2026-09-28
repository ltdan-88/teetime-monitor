from src import recommend
from src.models import Schedule, Slot, SlotMatch, SunTimes, TimeWindow, WeatherPoint
from src.recommend import (
    _round_duration_minutes,
    default_criteria_from_config,
    diversify_by_day,
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


# --- prioritize_friends deterministic boost (2026-09-27) ---------------------------


def test_ranked_matches_sorts_a_friends_slot_first_when_prioritize_friends_is_on():
    schedule = Schedule(
        date="2026-09-07",  # Monday
        course="18 Loch Tee 1",
        slots=[
            Slot(time="09:00", booked=1, capacity=4, players=["A Stranger"]),
            Slot(time="18:00", booked=1, capacity=4, players=["Erika Mustermann"]),
        ],
    )
    config = {
        "availability": {"weekday_window": {"after": "08:00"}},
        "preferences": {"prioritize_friends": True},
    }

    matches = ranked_matches([schedule], default_criteria_from_config(config), config, friend_names={"Erika Mustermann"})

    assert [m.slot.time for m in matches] == ["18:00", "09:00"]


def test_ranked_matches_does_not_sort_when_prioritize_friends_is_off():
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[
            Slot(time="09:00", booked=1, capacity=4, players=["A Stranger"]),
            Slot(time="18:00", booked=1, capacity=4, players=["Erika Mustermann"]),
        ],
    )
    config = {"availability": {"weekday_window": {"after": "08:00"}}}  # prioritize_friends unset

    matches = ranked_matches([schedule], default_criteria_from_config(config), config, friend_names={"Erika Mustermann"})

    assert [m.slot.time for m in matches] == ["09:00", "18:00"]  # original, chronological order


def test_ranked_matches_does_not_sort_without_any_friend_names_given():
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[
            Slot(time="09:00", booked=1, capacity=4, players=["A Stranger"]),
            Slot(time="18:00", booked=1, capacity=4, players=["Erika Mustermann"]),
        ],
    )
    config = {
        "availability": {"weekday_window": {"after": "08:00"}},
        "preferences": {"prioritize_friends": True},
    }

    matches = ranked_matches([schedule], default_criteria_from_config(config), config, friend_names=None)

    assert [m.slot.time for m in matches] == ["09:00", "18:00"]


def test_ranked_matches_friend_sort_is_stable_among_non_friend_slots():
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[
            Slot(time="08:00", booked=1, capacity=4, players=["Stranger A"]),
            Slot(time="09:00", booked=1, capacity=4, players=["Erika Mustermann"]),
            Slot(time="10:00", booked=1, capacity=4, players=["Stranger B"]),
        ],
    )
    config = {
        "availability": {"weekday_window": {"after": "07:00"}},
        "preferences": {"prioritize_friends": True},
    }

    matches = ranked_matches([schedule], default_criteria_from_config(config), config, friend_names={"Erika Mustermann"})

    # The friend's slot moves to the front; the two non-friend slots keep their
    # original relative order behind it (stable sort), rather than an arbitrary one.
    assert [m.slot.time for m in matches] == ["09:00", "08:00", "10:00"]


# --- hcp_preference deterministic boost (2026-09-27, direct follow-up: "would it
# make sense to have the option to choose to play with similar HCP or with better
# HCP for better pace?") -------------------------------------------------------------


def _hcp_schedule() -> Schedule:
    return Schedule(
        date="2026-09-07",  # Monday
        course="18 Loch Tee 1",
        slots=[
            Slot(time="09:00", booked=1, capacity=4, players=["Low Hcp"]),  # 10.0
            Slot(time="10:00", booked=1, capacity=4, players=["Mid Hcp"]),  # 24.0 -- closest to my_handicap below
            Slot(time="11:00", booked=1, capacity=4, players=["High Hcp"]),  # 40.0
            Slot(time="12:00", booked=0, capacity=4),  # empty -- no field to judge at all
        ],
    )


_HCP_MAP = {"Low Hcp": 10.0, "Mid Hcp": 24.0, "High Hcp": 40.0}


def test_ranked_matches_similar_hcp_prefers_the_closest_field_to_your_own():
    config = {
        "availability": {"weekday_window": {"after": "08:00"}},
        "preferences": {"hcp_preference": "similar"},
    }

    matches = ranked_matches(
        [_hcp_schedule()], default_criteria_from_config(config), config,
        known_handicaps=_HCP_MAP, my_handicap=25.0,
    )

    # 24.0 is closest to 25.0, then 10.0, then 40.0; the empty slot (no known field)
    # sorts last regardless.
    assert [m.slot.time for m in matches] == ["10:00", "09:00", "11:00", "12:00"]


def test_ranked_matches_better_hcp_prefers_the_lowest_average_field():
    config = {
        "availability": {"weekday_window": {"after": "08:00"}},
        "preferences": {"hcp_preference": "better"},
    }

    matches = ranked_matches(
        [_hcp_schedule()], default_criteria_from_config(config), config, known_handicaps=_HCP_MAP,
    )

    assert [m.slot.time for m in matches] == ["09:00", "10:00", "11:00", "12:00"]


def test_ranked_matches_does_not_sort_by_hcp_when_preference_is_off():
    config = {"availability": {"weekday_window": {"after": "08:00"}}}  # hcp_preference unset

    matches = ranked_matches(
        [_hcp_schedule()], default_criteria_from_config(config), config,
        known_handicaps=_HCP_MAP, my_handicap=25.0,
    )

    assert [m.slot.time for m in matches] == ["09:00", "10:00", "11:00", "12:00"]  # chronological


def test_ranked_matches_does_not_sort_by_hcp_without_any_known_handicaps_given():
    config = {
        "availability": {"weekday_window": {"after": "08:00"}},
        "preferences": {"hcp_preference": "better"},
    }

    matches = ranked_matches(
        [_hcp_schedule()], default_criteria_from_config(config), config, known_handicaps=None,
    )

    assert [m.slot.time for m in matches] == ["09:00", "10:00", "11:00", "12:00"]  # chronological


def test_ranked_matches_friends_take_priority_over_hcp_preference():
    # Direct design decision, see ranked_matches()'s own docstring: friends stay
    # the stronger signal, HCP only breaks ties within each friend/non-friend group.
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[
            Slot(time="09:00", booked=1, capacity=4, players=["Low Hcp"]),  # 10.0, not a friend
            Slot(time="10:00", booked=1, capacity=4, players=["A Friend"]),  # 40.0, a friend
        ],
    )
    config = {
        "availability": {"weekday_window": {"after": "08:00"}},
        "preferences": {"hcp_preference": "better", "prioritize_friends": True},
    }

    matches = ranked_matches(
        [schedule], default_criteria_from_config(config), config,
        friend_names={"A Friend"}, known_handicaps={"Low Hcp": 10.0, "A Friend": 40.0},
    )

    # The friend's own slot wins despite its much worse (higher) handicap.
    assert [m.slot.time for m in matches] == ["10:00", "09:00"]


def test_ranked_matches_feeds_avg_field_hcp_and_my_handicap_to_ai_never_names(monkeypatch):
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[Slot(time="09:00", booked=2, capacity=4, players=["Low Hcp", "High Hcp"])],  # avg 25.0
    )
    config = {
        "availability": {"weekday_window": {"after": "08:00"}},
        "ai_assist": {"enabled": True},
    }
    captured = {}

    def fake_rank_slots(candidates, context, preferences, provider, model, language):
        captured["description"] = recommend.ai_assist._describe_candidate(0, candidates[0], context)
        captured["preferences"] = preferences
        return candidates

    monkeypatch.setattr(recommend.ai_assist, "rank_slots", fake_rank_slots)

    ranked_matches(
        [schedule], default_criteria_from_config(config), config,
        known_handicaps={"Low Hcp": 10.0, "High Hcp": 40.0}, my_handicap=25.0,
    )

    assert "avg field HCP 25.0" in captured["description"]
    assert "Low Hcp" not in captured["description"]
    assert "High Hcp" not in captured["description"]
    assert captured["preferences"]["my_handicap"] == 25.0


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

    def fake_rank_slots(candidates, context, preferences, provider, model, language):
        calls.append({"candidates": candidates, "context": context, "provider": provider, "model": model})
        for candidate in candidates:
            candidate.score = 99.0
            candidate.reasons = ["dry and empty"]
        return candidates

    import src.recommend as recommend_module

    monkeypatch.setattr(recommend_module.ai_assist, "rank_slots", fake_rank_slots)

    picks = weekly_picks([schedule], config)

    assert len(calls) == 1
    assert calls[0]["model"] == "claude-haiku-4-5"
    assert calls[0]["provider"] == "anthropic"  # default when config["ai_assist"] sets no provider
    assert ("2026-09-07", "18 Loch Tee 1") in calls[0]["context"]["schedules"]
    assert picks[0].score == 99.0
    assert picks[0].reasons == ["dry and empty"]


def test_ranked_matches_threads_the_current_ui_language_through_to_rank_slots(monkeypatch):
    from src import i18n

    schedule = Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="18:00", booked=0, capacity=4)])
    config = {"availability": {"weekday_window": {"after": "17:00"}}, "ai_assist": {"enabled": True}}
    criteria = default_criteria_from_config(config)

    calls = []

    def fake_rank_slots(candidates, context, preferences, provider, model, language):
        calls.append(language)
        return candidates

    import src.recommend as recommend_module

    monkeypatch.setattr(recommend_module.ai_assist, "rank_slots", fake_rank_slots)

    i18n.set_language("de")
    try:
        ranked_matches([schedule], criteria, config)
    finally:
        i18n.set_language("en")

    assert calls == ["de"]


def test_weekly_picks_threads_a_configured_provider_through_to_rank_slots(monkeypatch):
    schedule = Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="18:00", booked=0, capacity=4)])
    config = {
        "availability": {"weekday_window": {"after": "17:00"}},
        "ai_assist": {"enabled": True, "provider": "gemini"},
    }

    calls = []

    def fake_rank_slots(candidates, context, preferences, provider, model, language):
        calls.append(provider)
        return candidates

    import src.recommend as recommend_module

    monkeypatch.setattr(recommend_module.ai_assist, "rank_slots", fake_rank_slots)

    weekly_picks([schedule], config)

    assert calls == ["gemini"]


def test_ranked_matches_merges_avoid_predicted_crowd_into_preferences(monkeypatch):
    # avoid_predicted_crowd moved from config["preferences"] to config["ai_assist"]
    # 2026-09-10 ("make avoid crowds a child of AI option") -- ai_assist.rank_slots()
    # still needs it in the `preferences` dict it hands to Claude's prompt, since
    # that's the only place the model actually sees it.
    schedule = Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="18:00", booked=0, capacity=4)])
    config = {
        "availability": {"weekday_window": {"after": "17:00"}},
        "ai_assist": {"enabled": True, "avoid_predicted_crowd": True},
        "preferences": {"prioritize_friends": True},
    }
    criteria = default_criteria_from_config(config)

    calls = []

    def fake_rank_slots(candidates, context, preferences, provider, model, language):
        calls.append(preferences)
        return candidates

    import src.recommend as recommend_module

    monkeypatch.setattr(recommend_module.ai_assist, "rank_slots", fake_rank_slots)

    ranked_matches([schedule], criteria, config)

    assert calls[0] == {"prioritize_friends": True, "avoid_predicted_crowd": True}


def test_ranked_matches_threads_crowd_estimates_into_context(monkeypatch):
    schedule = Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="18:00", booked=0, capacity=4)])
    config = {"availability": {"weekday_window": {"after": "17:00"}}, "ai_assist": {"enabled": True}}
    criteria = default_criteria_from_config(config)

    calls = []

    def fake_rank_slots(candidates, context, preferences, provider, model, language):
        calls.append(context)
        return candidates

    import src.recommend as recommend_module

    monkeypatch.setattr(recommend_module.ai_assist, "rank_slots", fake_rank_slots)

    estimates = {("2026-09-07", "18 Loch Tee 1", "18:00"): 0.8}
    ranked_matches([schedule], criteria, config, crowd_estimates=estimates)

    assert calls[0]["crowd_estimates"] == estimates


def test_ranked_matches_omits_crowd_estimates_from_context_when_none_given(monkeypatch):
    schedule = Schedule(date="2026-09-07", course="18 Loch Tee 1", slots=[Slot(time="18:00", booked=0, capacity=4)])
    config = {"availability": {"weekday_window": {"after": "17:00"}}, "ai_assist": {"enabled": True}}
    criteria = default_criteria_from_config(config)

    calls = []

    def fake_rank_slots(candidates, context, preferences, provider, model, language):
        calls.append(context)
        return candidates

    import src.recommend as recommend_module

    monkeypatch.setattr(recommend_module.ai_assist, "rank_slots", fake_rank_slots)

    ranked_matches([schedule], criteria, config)

    assert "crowd_estimates" not in calls[0]


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


# diversify_by_day() -- added 2026-09-08, direct feedback on a real overview
# screenshot: "why does it only recommend tee times on Tuesday?" -- a day with enough
# open slots to fill the whole displayed list was crowding out the rest of the week.


def _match(date, time):
    return SlotMatch(date=date, course="18 Loch Tee 1", slot=Slot(time=time, booked=0, capacity=4), score=0.0)


def test_diversify_by_day_keeps_only_the_first_pick_per_date():
    picks = [_match("2026-09-08", "16:00"), _match("2026-09-08", "16:10"), _match("2026-09-09", "17:00")]

    result = diversify_by_day(picks, max_count=5)

    assert [(p.date, p.slot.time) for p in result] == [("2026-09-08", "16:00"), ("2026-09-09", "17:00")]


def test_diversify_by_day_stops_at_max_count_distinct_days():
    picks = [_match(f"2026-09-{8 + i:02d}", "16:00") for i in range(10)]  # 10 different days

    result = diversify_by_day(picks, max_count=3)

    assert len(result) == 3
    assert [p.date for p in result] == ["2026-09-08", "2026-09-09", "2026-09-10"]


def test_diversify_by_day_preserves_input_order():
    # Order matters -- it's what AI ranking (or the plain chronological fallback)
    # already decided is "best first"; diversify_by_day() must not re-sort it.
    picks = [_match("2026-09-09", "17:00"), _match("2026-09-08", "16:00")]

    result = diversify_by_day(picks, max_count=5)

    assert [p.date for p in result] == ["2026-09-09", "2026-09-08"]


def test_diversify_by_day_empty_input():
    assert diversify_by_day([], max_count=5) == []


# --- window_for_date / latest_start / window_too_late_hint (2026-09-27, bundle C) ---


def _sunny_schedule(day: str, sunset: str = "19:10") -> Schedule:
    return Schedule(
        date=day, course="18 Loch Tee 1",
        slots=[Slot(time="16:00", booked=0, capacity=4)],
        sun_times=SunTimes(sunrise="07:20", sunset=sunset),
    )


def test_window_for_date_picks_the_weekday_or_weekend_window():
    config = {"availability": {"weekday_window": {"after": "16:00"}, "weekend_window": {"after": "10:00"}}}
    assert recommend.window_for_date("2026-09-28", config).after == "16:00"  # Monday
    assert recommend.window_for_date("2026-09-27", config).after == "10:00"  # Sunday
    assert recommend.window_for_date("2026-09-28", {}) is None


def test_latest_start_is_sunset_minus_round_and_buffer():
    config = {"daylight_buffer_minutes": 30}
    assert recommend.latest_start(_sunny_schedule("2026-09-28"), config) == "14:40"  # 19:10 - 4h - 30min
    assert recommend.latest_start(Schedule(date="2026-09-28", course="18 Loch Tee 1"), config) is None


def test_window_too_late_hint_needs_two_days_whose_window_opens_after_the_latest_start():
    config = {"availability": {"weekday_window": {"after": "16:00"}}, "daylight_buffer_minutes": 30}
    one_day = [_sunny_schedule("2026-09-28")]
    assert recommend.window_too_late_hint(one_day, config) is None  # one odd day isn't a pattern
    two_days = [_sunny_schedule("2026-09-28"), _sunny_schedule("2026-09-29", sunset="19:08")]
    assert recommend.window_too_late_hint(two_days, config) == {
        "window_after": "16:00", "latest_start": "14:40", "sunset": "19:10", "round_minutes": 240, "days": 2,
    }
    early = {"availability": {"weekday_window": {"after": "13:00"}}, "daylight_buffer_minutes": 30}
    assert recommend.window_too_late_hint(two_days, early) is None  # the window still fits


# --- only_with_friend / only_with_player (2026-09-28, "implement players or friends into the search") ---


def _match_with_players(date, time, players):
    return SlotMatch(date=date, course="18 Loch Tee 1", slot=Slot(time=time, booked=len(players), capacity=4, players=players), score=0.0)


def test_only_with_friend_keeps_only_slots_with_a_marked_friend():
    matches = [
        _match_with_players("2026-09-28", "09:00", ["Anna Bauer"]),
        _match_with_players("2026-09-28", "10:00", ["Someone Else"]),
        _match_with_players("2026-09-28", "11:00", []),
    ]
    result = recommend.only_with_friend(matches, {"Anna Bauer"})
    assert [m.slot.time for m in result] == ["09:00"]


def test_only_with_friend_no_friends_at_all_means_no_matches():
    matches = [_match_with_players("2026-09-28", "09:00", ["Anna Bauer"])]
    assert recommend.only_with_friend(matches, set()) == []


def test_only_with_player_keeps_only_slots_with_that_exact_name():
    matches = [
        _match_with_players("2026-09-28", "09:00", ["Anna Bauer"]),
        _match_with_players("2026-09-28", "10:00", ["Anna Bauer-Klein"]),  # not a substring match
        _match_with_players("2026-09-28", "11:00", ["Max Mustermann", "Anna Bauer"]),
    ]
    result = recommend.only_with_player(matches, "Anna Bauer")
    assert [m.slot.time for m in result] == ["09:00", "11:00"]


def test_only_with_player_nobody_by_that_name_means_no_matches():
    matches = [_match_with_players("2026-09-28", "09:00", ["Anna Bauer"])]
    assert recommend.only_with_player(matches, "Someone Else") == []
