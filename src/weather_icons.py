"""Weather condition icons — direct feedback, 2026-09-11: "I also would like icons
for when it is sunny, overcast, foggy, snowing etc." Open-Meteo's hourly
`weathercode` field (the WMO weather interpretation code scheme, the same one most
public weather APIs use) is what backs this — `weather.py`'s own
`fetch_hourly_weather()` requests it and stores it straight through on
`WeatherPoint.weather_code`; this module's only job is turning that numeric code
into something worth glancing at.

Deliberately a plain code -> icon lookup, not a full label/description table — the
existing Temperature/Precipitation/Wind columns already show the real numbers a
golfer actually plans a round around; this is a fast, at-a-glance summary sitting
next to them, not a replacement for the forecast text a real weather app would show.
Pure functions, no I/O, tested directly like units.py.
"""

# WMO code -> icon. Grouped by Open-Meteo's own published code ranges
# (https://open-meteo.com/en/docs), not by our own invented buckets.
_ICONS: dict[int, str] = {
    0: "☀️",  # Clear sky
    1: "🌤️",  # Mainly clear
    2: "⛅",  # Partly cloudy
    3: "☁️",  # Overcast
    45: "🌫️",  # Fog
    48: "🌫️",  # Depositing rime fog
    51: "🌦️",  # Drizzle: light
    53: "🌦️",  # Drizzle: moderate
    55: "🌦️",  # Drizzle: dense
    56: "🌦️",  # Freezing drizzle: light
    57: "🌦️",  # Freezing drizzle: dense
    61: "🌧️",  # Rain: slight
    63: "🌧️",  # Rain: moderate
    65: "🌧️",  # Rain: heavy
    66: "🌧️",  # Freezing rain: light
    67: "🌧️",  # Freezing rain: heavy
    71: "❄️",  # Snow fall: slight
    73: "❄️",  # Snow fall: moderate
    75: "❄️",  # Snow fall: heavy
    77: "❄️",  # Snow grains
    80: "🌧️",  # Rain showers: slight
    81: "🌧️",  # Rain showers: moderate
    82: "🌧️",  # Rain showers: violent
    85: "🌨️",  # Snow showers: slight
    86: "🌨️",  # Snow showers: heavy
    95: "⛈️",  # Thunderstorm
    96: "⛈️",  # Thunderstorm with slight hail
    99: "⛈️",  # Thunderstorm with heavy hail
}

# Worst-first, for collapsing a whole day's worth of hourly codes down to the one
# icon OverviewScreen's own day-level column shows — same "worst across the window,
# not an average" reasoning _wind_cell()'s own daily peak already uses. A code
# earlier in this list wins over one later in it.
_SEVERITY_ORDER: list[int] = [
    95, 96, 99,  # thunderstorm
    85, 86,  # snow showers
    71, 73, 75, 77,  # snow
    66, 67,  # freezing rain
    61, 63, 65, 80, 81, 82,  # rain / rain showers
    56, 57,  # freezing drizzle
    51, 53, 55,  # drizzle
    45, 48,  # fog
    3,  # overcast
    2,  # partly cloudy
    1,  # mainly clear
    0,  # clear
]


def icon_for_code(code: int | None) -> str:
    """The icon for one hourly forecast's own weather code, or "" for a missing or
    unrecognized code (no forecast at all, or a WMO code Open-Meteo adds later that
    this table doesn't know yet) — same "blank, not a guess" stance every other
    weather cell in this app already takes."""
    if code is None:
        return ""
    return _ICONS.get(code, "")


def worst_icon(codes: list[int | None]) -> str:
    """The single most severe icon among a day's worth of hourly codes — see the
    module docstring and `_SEVERITY_ORDER`. "" if none of `codes` are
    recognized/present."""
    known = [code for code in codes if code in _ICONS]
    if not known:
        return ""
    worst = min(known, key=_SEVERITY_ORDER.index)
    return _ICONS[worst]
