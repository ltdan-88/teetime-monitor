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

NOT YET IMPLEMENTED.
"""

from dataclasses import dataclass

from . import weather as weather_module
from .models import ConfirmedBooking, Schedule

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


def check_for_changes(
    booking: ConfirmedBooking,
    baseline: Schedule,
    latest: Schedule,
    buffer_minutes: int,
    round_duration_minutes: int,
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
    raise NotImplementedError("booking_watch.py is a stub — see ROADMAP.md Phase 1")
