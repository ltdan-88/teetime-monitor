"""Metric/imperial display conversion — direct feedback, 2026-09-13: "Can we
adjust format (metric/imperial) in settings?" (the second of two related remarks,
the first being "can we integrate units into header," which shipped first as a
purely cosmetic change — bare numbers stayed in whatever unit pc caddie/Open-Meteo
already hand back, just labelled in the header. This module is what makes the
*numbers themselves* actually change too.

Pure functions, no I/O, same reasoning `playability.py` already gives for being
implemented ahead of its own real dependency: nothing here needs a live fetch to
exist or be tested.

Deliberately narrow in scope: only the three physical quantities this app ever
displays (temperature, wind speed, precipitation amount) convert. A percentage
(rain probability, occupancy) is already unit-agnostic and never touches this
module. `settings_screen.py`'s own threshold fields (`avoid_temp_below_c`,
`avoid_wind_kph`, `avoid_rain_mm`) are deliberately NOT converted here — those are
stored, compared, and edited in one fixed unit regardless of this display
preference, same as pc caddie's own site always reports occupancy as a plain
fraction regardless of language. Converting stored thresholds bidirectionally
(so an edit in "imperial mode" round-trips correctly) is a real, separate feature,
not implied by "show me the numbers I already see in units I understand."
"""

METRIC = "metric"
IMPERIAL = "imperial"
DEFAULT_UNITS = METRIC

# (label suffix, symbol) shown in a table's own column header -- see tui.py's
# _column_header(). Precipitation pairs a unit-agnostic percentage with an amount,
# hence the "%/mm" vs "%/in" shape rather than a bare unit.
SYMBOLS = {
    METRIC: {"temperature": "°C", "wind": "km/h", "precipitation": "%/mm"},
    IMPERIAL: {"temperature": "°F", "wind": "mph", "precipitation": "%/in"},
}


def celsius_to_fahrenheit(celsius: float) -> float:
    return celsius * 9 / 5 + 32


def kph_to_mph(kph: float) -> float:
    return kph * 0.621371


def mm_to_inches(mm: float) -> float:
    return mm * 0.0393701


def display_temperature(celsius: float, units: str = DEFAULT_UNITS) -> float:
    """`celsius`, converted for display if `units` is imperial -- otherwise
    returned unchanged. Callers still do their own `:.0f`-style rounding at
    format time, same as before this module existed."""
    return celsius_to_fahrenheit(celsius) if units == IMPERIAL else celsius


def display_wind_speed(kph: float, units: str = DEFAULT_UNITS) -> float:
    return kph_to_mph(kph) if units == IMPERIAL else kph


def display_precipitation_mm(mm: float, units: str = DEFAULT_UNITS) -> float:
    return mm_to_inches(mm) if units == IMPERIAL else mm


def precipitation_amount_label(units: str = DEFAULT_UNITS) -> str:
    """The only remaining per-cell unit label (2026-09-13, direct follow-up:
    "since the units are now in the headers, we don't need the units in the
    rows, right?") -- temperature/wind cells dropped their own "°"/"km/h"
    suffixes once the column header started stating the unit (a
    `wind_unit_label()` counterpart used to live here too), but a
    precipitation cell packs two different numbers together ("70%/1.5mm"), so
    this one still earns its keep: it's what tells the second number apart
    from the first, not just a repeat of the header."""
    return "in" if units == IMPERIAL else "mm"
