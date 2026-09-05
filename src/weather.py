"""Rain forecast client for the weather overlay (ROADMAP.md Phase 2).

Uses Open-Meteo (https://open-meteo.com/) — free, no API key required, hourly
precipitation data. Club coordinates come from config.yaml's `location` block.

NOT YET IMPLEMENTED.
"""

from .models import WeatherPoint

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def fetch_hourly_precipitation(lat: float, lon: float, date: str) -> list[WeatherPoint]:
    """Fetch hourly precipitation probability/amount for one date, one location."""
    raise NotImplementedError("weather.py is a stub — see ROADMAP.md Phase 2")
