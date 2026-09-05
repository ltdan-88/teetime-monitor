"""Rain + wind + sunrise/sunset client for the weather/daylight overlay (ROADMAP.md Phase 2).

Uses Open-Meteo (https://open-meteo.com/) — free, no API key required. A single forecast
call covers everything here: `hourly=precipitation_probability,precipitation,
wind_speed_10m,temperature_2m` for the rain/wind/temperature overlay, and
`daily=sunrise,sunset` for playability (see playability.py) — no second API/service
needed for sunrise/sunset.

Club coordinates come from the active club's YAML `location` block (see ROADMAP.md
Phase 0 for multi-club config).

NOT YET IMPLEMENTED, except `conditions_during_round()` — see its docstring.
"""

from datetime import datetime, timedelta

from .models import RoundConditions, SunTimes, WeatherPoint

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

_TIME_FMT = "%H:%M"


def fetch_hourly_weather(lat: float, lon: float, date: str) -> list[WeatherPoint]:
    """Fetch hourly precipitation + wind speed for one date, one location."""
    raise NotImplementedError("weather.py is a stub — see ROADMAP.md Phase 2")


def fetch_sun_times(lat: float, lon: float, date: str) -> SunTimes:
    """Fetch sunrise/sunset for one date, one location.

    Open-Meteo's `daily` response returns these as ISO 8601 timestamps
    (e.g. "2026-09-05T19:47") — convert to "HH:MM" to match SunTimes/Slot.time.
    """
    raise NotImplementedError("weather.py is a stub — see ROADMAP.md Phase 2")


def conditions_during_round(
    weather_points: list[WeatherPoint], start_time: str, duration_minutes: int
) -> RoundConditions | None:
    """Worst-case conditions across the *whole* round, not just the tee-off hour.

    Added 2026-09-05 after user feedback: weather changes over the course of a round,
    so checking only the tee-off hour misses rain rolling in at hour 3 of a 4-hour
    round. Filters `weather_points` (a full day's hourly forecast, as returned by
    fetch_hourly_weather) to the ones overlapping [start_time, start_time +
    duration_minutes], and returns a RoundConditions summarizing the *worst* reading
    per field across that window — a round interrupted partway through by rain is
    still a bad round, so "worst across the window" is the right aggregation, not an
    average. See RoundConditions for why temperature is min/max rather than one number.

    Pure function, no I/O — implemented (and tested) now like playability.py, since it
    doesn't need to wait on the actual Open-Meteo call to exist. Returns None if no
    weather points overlap the window at all (e.g. forecast doesn't reach that far) —
    callers should treat that as "unknown," not "assume it's fine."
    """
    start = datetime.strptime(start_time, _TIME_FMT)
    end = start + timedelta(minutes=duration_minutes)

    def in_window(point: WeatherPoint) -> bool:
        point_time = datetime.strptime(point.time, _TIME_FMT)
        # An hourly point covers the hour starting at its own timestamp, so a point
        # just before `start` can still overlap the round's first minutes.
        return start <= point_time <= end or point_time <= start < point_time + timedelta(hours=1)

    window = [p for p in weather_points if in_window(p)]
    if not window:
        return None

    def highest(values: list[float | None]) -> float | None:
        present = [v for v in values if v is not None]
        return max(present) if present else None

    def lowest(values: list[float | None]) -> float | None:
        present = [v for v in values if v is not None]
        return min(present) if present else None

    return RoundConditions(
        max_precipitation_probability=highest([p.precipitation_probability for p in window]),
        max_precipitation_mm=highest([p.precipitation_mm for p in window]),
        max_wind_speed_kph=highest([p.wind_speed_kph for p in window]),
        min_temperature_c=lowest([p.temperature_c for p in window]),
        max_temperature_c=highest([p.temperature_c for p in window]),
    )
