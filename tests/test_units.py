from src import units


def test_celsius_to_fahrenheit():
    assert units.celsius_to_fahrenheit(0) == 32
    assert units.celsius_to_fahrenheit(100) == 212
    assert round(units.celsius_to_fahrenheit(20), 1) == 68.0


def test_kph_to_mph():
    assert round(units.kph_to_mph(100), 2) == 62.14


def test_mm_to_inches():
    assert round(units.mm_to_inches(25.4), 2) == 1.0


def test_display_temperature_metric_is_unchanged():
    assert units.display_temperature(16, units="metric") == 16


def test_display_temperature_imperial_converts():
    assert round(units.display_temperature(0, units="imperial"), 1) == 32.0


def test_display_wind_speed_metric_is_unchanged():
    assert units.display_wind_speed(10, units="metric") == 10


def test_display_wind_speed_imperial_converts():
    assert round(units.display_wind_speed(100, units="imperial"), 2) == 62.14


def test_display_precipitation_mm_metric_is_unchanged():
    assert units.display_precipitation_mm(5, units="metric") == 5


def test_display_precipitation_mm_imperial_converts():
    assert round(units.display_precipitation_mm(25.4, units="imperial"), 2) == 1.0


def test_wind_unit_label():
    assert units.wind_unit_label("metric") == "km/h"
    assert units.wind_unit_label("imperial") == "mph"


def test_precipitation_amount_label():
    assert units.precipitation_amount_label("metric") == "mm"
    assert units.precipitation_amount_label("imperial") == "in"


def test_defaults_to_metric_when_units_omitted():
    assert units.display_temperature(16) == 16
    assert units.display_wind_speed(10) == 10
    assert units.display_precipitation_mm(5) == 5
    assert units.wind_unit_label() == "km/h"
    assert units.precipitation_amount_label() == "mm"
