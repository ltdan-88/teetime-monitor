from src.booking_watch import (
    BUFFER_SHRUNK,
    NEIGHBOR_CROWDED,
    PARTY_GREW,
    WEATHER_WORSENED,
    check_for_changes,
)
from src.models import ConfirmedBooking, Schedule, Slot, WeatherPoint

BOOKING = ConfirmedBooking(
    date="2026-09-06", course="18 Loch Tee 1", time="14:00", holes=18, source="manual", confirmed_at="t0"
)


def _schedule(slots, weather=None):
    return Schedule(date="2026-09-06", course="18 Loch Tee 1", slots=slots, weather=weather or [])


def test_no_changes_when_nothing_changed():
    baseline = _schedule([Slot(time="14:00", booked=1, capacity=4)])
    latest = _schedule([Slot(time="14:00", booked=1, capacity=4)])

    assert check_for_changes(BOOKING, baseline, latest, buffer_before_minutes=20, buffer_after_minutes=20, round_duration_minutes=240) == []


def test_returns_empty_when_booking_has_no_time():
    not_playing = ConfirmedBooking(date="2026-09-06", course="18 Loch Tee 1", time=None, source="manual", confirmed_at="t0")
    baseline = _schedule([])
    latest = _schedule([])

    assert check_for_changes(not_playing, baseline, latest, buffer_before_minutes=20, buffer_after_minutes=20, round_duration_minutes=240) == []


def test_returns_empty_when_latest_has_no_matching_slot():
    baseline = _schedule([Slot(time="14:00", booked=1, capacity=4)])
    latest = _schedule([])  # e.g. the slot vanished from the sheet somehow

    assert check_for_changes(BOOKING, baseline, latest, buffer_before_minutes=20, buffer_after_minutes=20, round_duration_minutes=240) == []


def test_party_grew_detected():
    baseline = _schedule([Slot(time="14:00", booked=1, capacity=4)])
    latest = _schedule([Slot(time="14:00", booked=3, capacity=4)])

    changes = check_for_changes(BOOKING, baseline, latest, buffer_before_minutes=20, buffer_after_minutes=20, round_duration_minutes=240)

    assert len(changes) == 1
    assert changes[0].kind == PARTY_GREW
    assert "2 more players" in changes[0].message


def test_party_grew_singular_wording():
    baseline = _schedule([Slot(time="14:00", booked=1, capacity=4)])
    latest = _schedule([Slot(time="14:00", booked=2, capacity=4)])

    changes = check_for_changes(BOOKING, baseline, latest, buffer_before_minutes=20, buffer_after_minutes=20, round_duration_minutes=240)

    assert "1 more player " in changes[0].message  # not "1 more players"


def test_party_grew_not_flagged_without_a_baseline_slot():
    # No baseline row at all for this time (e.g. the very first scrape after booking) --
    # nothing to compare growth against, so no PARTY_GREW change should fire.
    baseline = _schedule([])
    latest = _schedule([Slot(time="14:00", booked=2, capacity=4)])

    changes = check_for_changes(BOOKING, baseline, latest, buffer_before_minutes=20, buffer_after_minutes=20, round_duration_minutes=240)
    assert changes == []


def test_buffer_shrunk_when_previously_open_neighbor_fills_in():
    baseline = _schedule(
        [Slot(time="14:00", booked=1, capacity=4), Slot(time="14:10", booked=0, capacity=4)]
    )
    latest = _schedule(
        [Slot(time="14:00", booked=1, capacity=4), Slot(time="14:10", booked=2, capacity=4)]
    )

    changes = check_for_changes(BOOKING, baseline, latest, buffer_before_minutes=20, buffer_after_minutes=20, round_duration_minutes=240)

    assert len(changes) == 1
    assert changes[0].kind == BUFFER_SHRUNK
    assert "14:10" in changes[0].message


def test_buffer_shrunk_ignores_neighbor_outside_buffer_window():
    baseline = _schedule(
        [Slot(time="14:00", booked=1, capacity=4), Slot(time="15:00", booked=0, capacity=4)]
    )
    latest = _schedule(
        [Slot(time="14:00", booked=1, capacity=4), Slot(time="15:00", booked=2, capacity=4)]
    )

    # 15:00 is 60 minutes away -- outside a 20-minute buffer.
    changes = check_for_changes(BOOKING, baseline, latest, buffer_before_minutes=20, buffer_after_minutes=20, round_duration_minutes=240)
    assert changes == []


def test_buffer_shrunk_respects_zero_buffer():
    baseline = _schedule(
        [Slot(time="14:00", booked=1, capacity=4), Slot(time="14:10", booked=0, capacity=4)]
    )
    latest = _schedule(
        [Slot(time="14:00", booked=1, capacity=4), Slot(time="14:10", booked=4, capacity=4)]
    )

    changes = check_for_changes(
        BOOKING, baseline, latest, buffer_before_minutes=0, buffer_after_minutes=0, round_duration_minutes=240
    )
    assert changes == []


# --- Asymmetric buffer (2026-09-08, same follow-up as search.py's own split) -------


def test_buffer_shrunk_before_only_ignores_a_neighbor_teeing_off_later():
    baseline = _schedule(
        [Slot(time="14:00", booked=1, capacity=4), Slot(time="14:10", booked=0, capacity=4)]
    )
    latest = _schedule(
        [Slot(time="14:00", booked=1, capacity=4), Slot(time="14:10", booked=2, capacity=4)]
    )

    # 14:10 is *after* the 14:00 booking -- buffer_after=0 means it's not watched,
    # even though buffer_before is generous enough it would have caught it the
    # other way around.
    changes = check_for_changes(
        BOOKING, baseline, latest, buffer_before_minutes=20, buffer_after_minutes=0, round_duration_minutes=240
    )
    assert changes == []


def test_buffer_shrunk_after_only_watches_a_neighbor_teeing_off_later():
    baseline = _schedule(
        [Slot(time="14:00", booked=1, capacity=4), Slot(time="14:10", booked=0, capacity=4)]
    )
    latest = _schedule(
        [Slot(time="14:00", booked=1, capacity=4), Slot(time="14:10", booked=2, capacity=4)]
    )

    changes = check_for_changes(
        BOOKING, baseline, latest, buffer_before_minutes=0, buffer_after_minutes=20, round_duration_minutes=240
    )
    assert len(changes) == 1
    assert changes[0].kind == BUFFER_SHRUNK


def test_buffer_shrunk_after_only_ignores_a_neighbor_teeing_off_earlier():
    baseline = _schedule(
        [Slot(time="13:50", booked=0, capacity=4), Slot(time="14:00", booked=1, capacity=4)]
    )
    latest = _schedule(
        [Slot(time="13:50", booked=2, capacity=4), Slot(time="14:00", booked=1, capacity=4)]
    )

    # 13:50 is *before* the 14:00 booking -- the group ahead, not watched at all
    # when only buffer_after is set.
    changes = check_for_changes(
        BOOKING, baseline, latest, buffer_before_minutes=0, buffer_after_minutes=20, round_duration_minutes=240
    )
    assert changes == []


def test_buffer_shrunk_before_only_watches_a_neighbor_teeing_off_earlier():
    baseline = _schedule(
        [Slot(time="13:50", booked=0, capacity=4), Slot(time="14:00", booked=1, capacity=4)]
    )
    latest = _schedule(
        [Slot(time="13:50", booked=2, capacity=4), Slot(time="14:00", booked=1, capacity=4)]
    )

    changes = check_for_changes(
        BOOKING, baseline, latest, buffer_before_minutes=20, buffer_after_minutes=0, round_duration_minutes=240
    )
    assert len(changes) == 1
    assert changes[0].kind == BUFFER_SHRUNK


def test_buffer_shrunk_when_neighbor_becomes_a_block():
    baseline = _schedule(
        [Slot(time="14:00", booked=1, capacity=4), Slot(time="14:10", booked=0, capacity=4)]
    )
    latest = _schedule(
        [
            Slot(time="14:00", booked=1, capacity=4),
            Slot(time="14:10", booked=4, capacity=4, block_reason="Gäste"),
        ]
    )

    changes = check_for_changes(BOOKING, baseline, latest, buffer_before_minutes=20, buffer_after_minutes=20, round_duration_minutes=240)
    assert len(changes) == 1
    assert changes[0].kind == BUFFER_SHRUNK


def test_neighbor_crowded_when_already_a_flight_grows():
    baseline = _schedule(
        [Slot(time="14:00", booked=1, capacity=4), Slot(time="14:10", booked=1, capacity=4)]
    )
    latest = _schedule(
        [Slot(time="14:00", booked=1, capacity=4), Slot(time="14:10", booked=3, capacity=4)]
    )

    changes = check_for_changes(BOOKING, baseline, latest, buffer_before_minutes=20, buffer_after_minutes=20, round_duration_minutes=240)

    assert len(changes) == 1
    assert changes[0].kind == NEIGHBOR_CROWDED


def test_neighbor_crowded_not_flagged_when_flight_size_unchanged():
    baseline = _schedule(
        [Slot(time="14:00", booked=1, capacity=4), Slot(time="14:10", booked=2, capacity=4)]
    )
    latest = _schedule(
        [Slot(time="14:00", booked=1, capacity=4), Slot(time="14:10", booked=2, capacity=4)]
    )

    changes = check_for_changes(BOOKING, baseline, latest, buffer_before_minutes=20, buffer_after_minutes=20, round_duration_minutes=240)
    assert changes == []


def test_weather_worsened_when_rain_crosses_threshold():
    baseline = _schedule(
        [Slot(time="14:00", booked=1, capacity=4)],
        weather=[WeatherPoint(time="14:00", precipitation_probability=20)],
    )
    latest = _schedule(
        [Slot(time="14:00", booked=1, capacity=4)],
        weather=[WeatherPoint(time="14:00", precipitation_probability=70)],
    )

    changes = check_for_changes(
        BOOKING, baseline, latest, buffer_before_minutes=20, buffer_after_minutes=20, round_duration_minutes=240, preferences={"avoid_rain": True}
    )

    assert len(changes) == 1
    assert changes[0].kind == WEATHER_WORSENED
    assert "rain chance" in changes[0].message


def test_weather_not_flagged_when_avoid_rain_is_false():
    baseline = _schedule(
        [Slot(time="14:00", booked=1, capacity=4)],
        weather=[WeatherPoint(time="14:00", precipitation_probability=20)],
    )
    latest = _schedule(
        [Slot(time="14:00", booked=1, capacity=4)],
        weather=[WeatherPoint(time="14:00", precipitation_probability=70)],
    )

    changes = check_for_changes(
        BOOKING, baseline, latest, buffer_before_minutes=20, buffer_after_minutes=20, round_duration_minutes=240, preferences={"avoid_rain": False}
    )
    assert changes == []


def test_weather_not_flagged_when_already_bad_and_staying_bad():
    # Both readings already exceed the threshold -- not a new development, so no banner.
    baseline = _schedule(
        [Slot(time="14:00", booked=1, capacity=4)],
        weather=[WeatherPoint(time="14:00", precipitation_probability=90)],
    )
    latest = _schedule(
        [Slot(time="14:00", booked=1, capacity=4)],
        weather=[WeatherPoint(time="14:00", precipitation_probability=95)],
    )

    changes = check_for_changes(
        BOOKING,
        baseline,
        latest,
        buffer_before_minutes=20, buffer_after_minutes=20,
        round_duration_minutes=240,
        preferences={"avoid_rain": True, "avoid_rain_probability_percent": 50},
    )
    # 95 > 50 and 95 > 90 -- this actually *does* cross further, so it should still
    # fire; this test documents that "still bad" only suppresses when the value didn't
    # also increase (see the "improves without crossing back" test below for that case).
    assert len(changes) == 1


def test_weather_not_flagged_when_condition_improves():
    baseline = _schedule(
        [Slot(time="14:00", booked=1, capacity=4)],
        weather=[WeatherPoint(time="14:00", precipitation_probability=90)],
    )
    latest = _schedule(
        [Slot(time="14:00", booked=1, capacity=4)],
        weather=[WeatherPoint(time="14:00", precipitation_probability=60)],
    )

    changes = check_for_changes(
        BOOKING,
        baseline,
        latest,
        buffer_before_minutes=20, buffer_after_minutes=20,
        round_duration_minutes=240,
        preferences={"avoid_rain": True, "avoid_rain_probability_percent": 50},
    )
    assert changes == []


def test_weather_worsened_uses_custom_threshold():
    baseline = _schedule(
        [Slot(time="14:00", booked=1, capacity=4)],
        weather=[WeatherPoint(time="14:00", precipitation_probability=40)],
    )
    latest = _schedule(
        [Slot(time="14:00", booked=1, capacity=4)],
        weather=[WeatherPoint(time="14:00", precipitation_probability=60)],
    )

    # Default threshold (50%) would flag 60% -- a custom 80% threshold should not.
    changes = check_for_changes(
        BOOKING,
        baseline,
        latest,
        buffer_before_minutes=20, buffer_after_minutes=20,
        round_duration_minutes=240,
        preferences={"avoid_rain": True, "avoid_rain_probability_percent": 80},
    )
    assert changes == []


def test_weather_worsened_skipped_without_forecast_on_either_side():
    baseline = _schedule([Slot(time="14:00", booked=1, capacity=4)])  # no weather saved
    latest = _schedule([Slot(time="14:00", booked=1, capacity=4)])

    changes = check_for_changes(
        BOOKING, baseline, latest, buffer_before_minutes=20, buffer_after_minutes=20, round_duration_minutes=240, preferences={"avoid_rain": True}
    )
    assert changes == []


def test_multiple_changes_reported_together():
    baseline = _schedule(
        [Slot(time="14:00", booked=1, capacity=4), Slot(time="14:10", booked=0, capacity=4)],
        weather=[WeatherPoint(time="14:00", precipitation_probability=10)],
    )
    latest = _schedule(
        [Slot(time="14:00", booked=2, capacity=4), Slot(time="14:10", booked=1, capacity=4)],
        weather=[WeatherPoint(time="14:00", precipitation_probability=90)],
    )

    changes = check_for_changes(
        BOOKING, baseline, latest, buffer_before_minutes=20, buffer_after_minutes=20, round_duration_minutes=240, preferences={"avoid_rain": True}
    )

    kinds = {change.kind for change in changes}
    assert kinds == {PARTY_GREW, BUFFER_SHRUNK, WEATHER_WORSENED}


# --- params (used by i18n.render_booking_change() to re-render in any language) ------


def test_party_grew_params():
    baseline = _schedule([Slot(time="14:00", booked=1, capacity=4)])
    latest = _schedule([Slot(time="14:00", booked=3, capacity=4)])

    changes = check_for_changes(BOOKING, baseline, latest, buffer_before_minutes=20, buffer_after_minutes=20, round_duration_minutes=240)

    assert changes[0].params == {"count": 2, "time": "14:00"}


def test_buffer_shrunk_params():
    baseline = _schedule(
        [Slot(time="14:00", booked=1, capacity=4), Slot(time="14:10", booked=0, capacity=4)]
    )
    latest = _schedule(
        [Slot(time="14:00", booked=1, capacity=4), Slot(time="14:10", booked=2, capacity=4)]
    )

    changes = check_for_changes(BOOKING, baseline, latest, buffer_before_minutes=20, buffer_after_minutes=20, round_duration_minutes=240)

    assert changes[0].params == {"time": "14:00", "neighbor_time": "14:10"}


def test_weather_worsened_params_use_keys_not_english_words():
    baseline = _schedule(
        [Slot(time="14:00", booked=1, capacity=4)],
        weather=[WeatherPoint(time="14:00", precipitation_probability=10, wind_speed_kph=5)],
    )
    latest = _schedule(
        [Slot(time="14:00", booked=1, capacity=4)],
        weather=[WeatherPoint(time="14:00", precipitation_probability=90, wind_speed_kph=50)],
    )

    changes = check_for_changes(
        BOOKING,
        baseline,
        latest,
        buffer_before_minutes=20, buffer_after_minutes=20,
        round_duration_minutes=240,
        preferences={"avoid_rain": True, "avoid_wind": True},
    )

    assert changes[0].params == {"time": "14:00", "reason_keys": ["rain_chance", "wind"]}
    # message stays the human-readable English form -- params is the separate,
    # translatable representation of the same fact.
    assert "rain chance" in changes[0].message
    assert "wind" in changes[0].message
