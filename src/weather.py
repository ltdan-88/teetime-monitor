"""Rain + wind + sunrise/sunset client for the weather/daylight overlay (ROADMAP.md Phase 2).

Uses Open-Meteo (https://open-meteo.com/) — free, no API key required, forecasts up to
16 days out (comfortably past this project's 5-day overview window). `timezone=auto`
tells Open-Meteo to return timestamps in the location's own local time, matching the
plain "HH:MM" used throughout (Slot.time, WeatherPoint.time, SunTimes) with no manual
timezone math needed on this end.

Club coordinates come from the active club's YAML `location` block (see ROADMAP.md
Phase 0 for multi-club config).

`fetch_hourly_weather()` and `fetch_sun_times()` are real as of 2026-09-06, each making
its own independent request (`hourly=...` / `daily=...` respectively) rather than one
combined call for both — simpler to test and reason about independently, and one
failing (e.g. a transient daily-data gap) doesn't take the other down with it. A
combined single-request version is a plausible future optimization if API call volume
ever actually matters for a personal tool scraping a handful of times a day, but isn't
worth the added complexity now. `conditions_during_round()` (below) was already
implemented and tested earlier — see its own docstring.
"""

from datetime import datetime, timedelta

import httpx

from .models import RoundConditions, SunTimes, WeatherPoint

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

_TIME_FMT = "%H:%M"


def _hhmm(iso_timestamp: str) -> str:
    """"2026-09-06T14:00" -> "14:00" (Open-Meteo's ISO 8601 hourly/daily timestamps,
    confirmed 2026-09-05 in ROADMAP.md's "Live site findings" for the daily variant)."""
    return iso_timestamp[-5:]


def fetch_hourly_weather(lat: float, lon: float, date: str) -> list[WeatherPoint]:
    """Fetch hourly precipitation (probability + amount), wind speed, temperature, and
    weather condition code for one date, one location.

    `weathercode` (added 2026-09-11, direct feedback: "I also would like icons for
    when it is sunny, overcast, foggy, snowing etc.") is Open-Meteo's own WMO code —
    see weather_icons.py for what turns it into something to actually show."""
    response = httpx.get(
        OPEN_METEO_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": date,
            "end_date": date,
            "hourly": "precipitation_probability,precipitation,wind_speed_10m,temperature_2m,weathercode",
            "timezone": "auto",
        },
        timeout=15,
    )
    response.raise_for_status()
    hourly = response.json().get("hourly", {})

    times = hourly.get("time", [])
    probabilities = hourly.get("precipitation_probability", [])
    amounts = hourly.get("precipitation", [])
    wind_speeds = hourly.get("wind_speed_10m", [])
    temperatures = hourly.get("temperature_2m", [])
    weather_codes = hourly.get("weathercode", [])

    def at(values: list, index: int):
        return values[index] if index < len(values) else None

    return [
        WeatherPoint(
            time=_hhmm(timestamp),
            precipitation_probability=at(probabilities, i),
            precipitation_mm=at(amounts, i),
            wind_speed_kph=at(wind_speeds, i),
            temperature_c=at(temperatures, i),
            weather_code=at(weather_codes, i),
        )
        for i, timestamp in enumerate(times)
    ]


def fetch_sun_times(lat: float, lon: float, date: str) -> SunTimes:
    """Fetch sunrise/sunset for one date, one location.

    Open-Meteo's `daily` response returns these as ISO 8601 timestamps
    (e.g. "2026-09-05T19:47") — convert to "HH:MM" to match SunTimes/Slot.time.
    """
    response = httpx.get(
        OPEN_METEO_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": date,
            "end_date": date,
            "daily": "sunrise,sunset",
            "timezone": "auto",
        },
        timeout=15,
    )
    response.raise_for_status()
    daily = response.json().get("daily", {})
    sunrises = daily.get("sunrise", [])
    sunsets = daily.get("sunset", [])
    return SunTimes(
        sunrise=_hhmm(sunrises[0]) if sunrises else "",
        sunset=_hhmm(sunsets[0]) if sunsets else "",
    )


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
