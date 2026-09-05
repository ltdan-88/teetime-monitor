"""Rain + sunrise/sunset client for the weather/daylight overlay (ROADMAP.md Phase 2).

Uses Open-Meteo (https://open-meteo.com/) — free, no API key required. A single forecast
call covers both needs here: `hourly=precipitation_probability,precipitation` for the
rain overlay, and `daily=sunrise,sunset` for playability (see playability.py) — no
second API/service needed for sunrise/sunset.

Club coordinates come from config.yaml's `location` block.

NOT YET IMPLEMENTED.
"""

from .models import SunTimes, WeatherPoint

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def fetch_hourly_precipitation(lat: float, lon: float, date: str) -> list[WeatherPoint]:
    """Fetch hourly precipitation probability/amount for one date, one location."""
    raise NotImplementedError("weather.py is a stub — see ROADMAP.md Phase 2")


def fetch_sun_times(lat: float, lon: float, date: str) -> SunTimes:
    """Fetch sunrise/sunset for one date, one location.

    Open-Meteo's `daily` response returns these as ISO 8601 timestamps
    (e.g. "2026-09-05T19:47") — convert to "HH:MM" to match SunTimes/Slot.time.
    """
    raise NotImplementedError("weather.py is a stub — see ROADMAP.md Phase 2")
