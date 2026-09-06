"""Detects when a confirmed booking's situation has changed since you booked it
(ROADMAP.md Phase 1, added 2026-09-06, extended same day).

A confirmed booking isn't fire-and-forget — someone can join your flight, a
neighboring slot that was empty at booking time can fill in and erode your buffer, or
the weather forecast itself can simply have gotten worse since you booked (a forecast
made a week out is less reliable than one made the day before). Since every scrape is
kept forever, not overwritten (the whole reason for that design choice — see
storage.py), comparing a booking's slot — and its forecast — in the latest scrape
against an earlier one is pure deterministic diffing. No AI, no new scraping, no new
API calls: `weather.conditions_during_round()` already exists and just gets called
against two different Schedules instead of one.

Runs as part of the scheduled scrape (scrape_once.py); the TUI's home screen shows the
result as a plain banner next time you open the app — **not** a push notification.
Explicitly decided 2026-09-06: different from the "notify me of a new opportunity"
alerts already ruled out — this protects something you already committed to — but a
passive in-app banner still respects the same "no active pings" preference. An active
notification (e.g. a Mac notification) remains a possible later upgrade, not this.

Implemented 2026-09-06. `preferences` (a club's `preferences` YAML block) is an
optional parameter, not required — the rain/wind thresholds it drives are the same
ones `recommend.exclude_unplayable()` already resolves (booleans gating whether to
check at all, numeric cutoffs with the same defaults) — see that module's docstring
for why those cutoffs exist and aren't just the plain avoid_rain/avoid_wind booleans.
"""

from dataclasses import dataclass
from datetime import datetime

from . import weather as weather_module
from .models import ConfirmedBooking, Schedule, Slot
from .recommend import (
    DEFAULT_AVOID_RAIN_MM,
    DEFAULT_AVOID_RAIN_PROBABILITY_PERCENT,
    DEFAULT_AVOID_WIND_KPH,
)

_TIME_FMT = "%H:%M"

# Kinds of change this watches for.
PARTY_GREW = "party_grew"  # your own slot's player count went up
BUFFER_SHRUNK = "buffer_shrunk"  # a neighboring slot that was open is now booked
NEIGHBOR_CROWDED = "neighbor_crowded"  # general crowding nearby, not just the buffer edge
WEATHER_WORSENED = "weather_worsened"  # rain/wind across the round's duration got worse


@dataclass
class BookingChange:
    """One detected change for a confirmed booking, ready to show as an in-app banner."""

    booking: ConfirmedBooking
    kind: str  # one of the constants above
    message: str  # plain language, e.g. "1 more player joined your 14:00 since you booked"


def _find_slot(schedule: Schedule, time: str) -> Slot | None:
    return next((slot for slot in schedule.slots if slot.time == time), None)


def _is_another_flight(slot: Slot | None) -> bool:
    """Same definition search.py's buffer check uses — real players booked, or a block
    (event/lesson/guest) both count; a fully open (or missing) slot doesn't."""
    return slot is not None and (slot.booked > 0 or slot.block_reason is not None)


def _party_grew_change(booking: ConfirmedBooking, baseline_slot: Slot | None, latest_slot: Slot) -> BookingChange | None:
    if baseline_slot is None or latest_slot.booked <= baseline_slot.booked:
        return None
    joined = latest_slot.booked - baseline_slot.booked
    plural = "s" if joined != 1 else ""
    return BookingChange(
        booking=booking,
        kind=PARTY_GREW,
        message=f"{joined} more player{plural} joined your {booking.time} tee time since you booked",
    )


def _neighbor_changes(booking: ConfirmedBooking, baseline: Schedule, latest: Schedule, buffer_minutes: int) -> list[BookingChange]:
    changes: list[BookingChange] = []
    booking_time = datetime.strptime(booking.time, _TIME_FMT)
    baseline_by_time = {slot.time: slot for slot in baseline.slots}

    for latest_slot in latest.slots:
        if latest_slot.time == booking.time:
            continue  # your own slot -- handled by _party_grew_change instead
        if buffer_minutes <= 0:
            continue
        slot_time = datetime.strptime(latest_slot.time, _TIME_FMT)
        gap_minutes = abs((slot_time - booking_time).total_seconds()) / 60
        if gap_minutes >= buffer_minutes:
            continue  # outside the buffer window -- not relevant to this booking

        baseline_slot = baseline_by_time.get(latest_slot.time)
        was_flight = _is_another_flight(baseline_slot)
        is_flight = _is_another_flight(latest_slot)

        if not was_flight and is_flight:
            changes.append(
                BookingChange(
                    booking=booking,
                    kind=BUFFER_SHRUNK,
                    message=(
                        f"The {latest_slot.time} slot near your {booking.time} tee time "
                        "is no longer clear"
                    ),
                )
            )
        elif was_flight and is_flight and latest_slot.booked > baseline_slot.booked:
            changes.append(
                BookingChange(
                    booking=booking,
                    kind=NEIGHBOR_CROWDED,
                    message=(
                        f"The {latest_slot.time} flight near your {booking.time} tee time "
                        "picked up more players"
                    ),
                )
            )

    return changes


def _crossed_threshold(baseline_value: float | None, latest_value: float | None, limit: float) -> bool:
    """"A rise ... past the club's threshold" — must now exceed the limit AND have
    actually gone up, not just already have been bad and stayed that way (already
    known, not a new development worth a banner for)."""
    if baseline_value is None or latest_value is None:
        return False
    return latest_value > limit and latest_value > baseline_value


def _weather_change(
    booking: ConfirmedBooking, baseline: Schedule, latest: Schedule, round_duration_minutes: int, preferences: dict
) -> BookingChange | None:
    baseline_conditions = weather_module.conditions_during_round(baseline.weather, booking.time, round_duration_minutes)
    latest_conditions = weather_module.conditions_during_round(latest.weather, booking.time, round_duration_minutes)
    if baseline_conditions is None or latest_conditions is None:
        return None  # no forecast to compare on one side or the other

    reasons = []

    if preferences.get("avoid_rain"):
        prob_limit = preferences.get("avoid_rain_probability_percent", DEFAULT_AVOID_RAIN_PROBABILITY_PERCENT)
        mm_limit = preferences.get("avoid_rain_mm", DEFAULT_AVOID_RAIN_MM)
        if _crossed_threshold(
            baseline_conditions.max_precipitation_probability, latest_conditions.max_precipitation_probability, prob_limit
        ):
            reasons.append("rain chance")
        if _crossed_threshold(baseline_conditions.max_precipitation_mm, latest_conditions.max_precipitation_mm, mm_limit):
            reasons.append("rain amount")

    if preferences.get("avoid_wind"):
        wind_limit = preferences.get("avoid_wind_kph", DEFAULT_AVOID_WIND_KPH)
        if _crossed_threshold(baseline_conditions.max_wind_speed_kph, latest_conditions.max_wind_speed_kph, wind_limit):
            reasons.append("wind")

    if not reasons:
        return None

    return BookingChange(
        booking=booking,
        kind=WEATHER_WORSENED,
        message=f"The forecast for your {booking.time} tee time got worse ({', '.join(reasons)})",
    )


def check_for_changes(
    booking: ConfirmedBooking,
    baseline: Schedule,
    latest: Schedule,
    buffer_minutes: int,
    round_duration_minutes: int,
    preferences: dict | None = None,
) -> list[BookingChange]:
    """Compare `baseline` (the schedule as scraped around when `booking` was confirmed,
    or as of the last check) against `latest`, and report anything that changed for the
    worse. Only ever compares two already-scraped Schedules — no live site access here.

    Weather specifically: call weather.conditions_during_round() on both baseline.weather
    and latest.weather for booking.time, and compare the two RoundConditions — a rise in
    max_precipitation_probability/mm past the club's avoid_rain threshold, or in
    max_wind_speed_kph past avoid_wind, is a WEATHER_WORSENED change. (Sunset itself
    doesn't need this treatment — it's an astronomical fact, not a forecast that gets
    revised, so the daylight cushion doesn't need re-checking the same way rain/wind do.)
    """
    preferences = preferences or {}
    if booking.time is None:
        return []  # "confirmed not playing" -- nothing to watch

    latest_slot = _find_slot(latest, booking.time)
    if latest_slot is None:
        return []  # can't compare without a matching slot in the latest scrape

    baseline_slot = _find_slot(baseline, booking.time)

    changes: list[BookingChange] = []
    party_grew = _party_grew_change(booking, baseline_slot, latest_slot)
    if party_grew is not None:
        changes.append(party_grew)

    changes.extend(_neighbor_changes(booking, baseline, latest, buffer_minutes))

    weather_change = _weather_change(booking, baseline, latest, round_duration_minutes, preferences)
    if weather_change is not None:
        changes.append(weather_change)

    return changes
