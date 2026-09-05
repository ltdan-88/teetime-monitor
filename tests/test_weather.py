from src.models import WeatherPoint
from src.weather import conditions_during_round


def _points():
    # A typical afternoon: dry and calm at tee-off, rain rolls in later, cools off too.
    return [
        WeatherPoint(time="15:00", precipitation_probability=5, wind_speed_kph=10, temperature_c=22),
        WeatherPoint(time="16:00", precipitation_probability=10, wind_speed_kph=12, temperature_c=21),
        WeatherPoint(time="17:00", precipitation_probability=70, wind_speed_kph=25, temperature_c=18),
        WeatherPoint(time="18:00", precipitation_probability=80, wind_speed_kph=30, temperature_c=16),
        WeatherPoint(time="19:00", precipitation_probability=20, wind_speed_kph=15, temperature_c=15),
    ]


def test_catches_rain_that_rolls_in_after_tee_off():
    # Tee off at 15:00 looks dry, but a 4-hour round runs until ~19:00 and hits rain.
    result = conditions_during_round(_points(), start_time="15:00", duration_minutes=240)
    assert result.max_precipitation_probability == 80
    assert result.max_wind_speed_kph == 30


def test_temperature_is_a_range_not_a_single_worst_value():
    result = conditions_during_round(_points(), start_time="15:00", duration_minutes=240)
    assert result.min_temperature_c == 15
    assert result.max_temperature_c == 22


def test_short_round_only_sees_its_own_window():
    # A 1-hour round at 15:00 shouldn't be penalized for rain that arrives at 17:00.
    result = conditions_during_round(_points(), start_time="15:00", duration_minutes=60)
    assert result.max_precipitation_probability == 10


def test_returns_none_when_forecast_does_not_cover_the_window():
    result = conditions_during_round(_points(), start_time="23:00", duration_minutes=240)
    assert result is None
