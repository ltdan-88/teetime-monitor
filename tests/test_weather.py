from src import weather as weather_module
from src.models import WeatherPoint
from src.weather import conditions_during_round, fetch_hourly_weather, fetch_sun_times


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


# --- fetch_hourly_weather / fetch_sun_times (real httpx calls, mocked) -------------


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_hourly_weather_parses_open_meteo_response(monkeypatch):
    payload = {
        "hourly": {
            "time": ["2026-09-06T14:00", "2026-09-06T15:00"],
            "precipitation_probability": [10, 80],
            "precipitation": [0.0, 2.5],
            "wind_speed_10m": [12.0, 25.0],
            "temperature_2m": [22.0, 20.0],
        }
    }
    monkeypatch.setattr(weather_module.httpx, "get", lambda url, params, timeout: _FakeResponse(payload))

    points = fetch_hourly_weather(47.0, 11.0, "2026-09-06")

    assert points == [
        WeatherPoint(time="14:00", precipitation_probability=10, precipitation_mm=0.0, wind_speed_kph=12.0, temperature_c=22.0),
        WeatherPoint(time="15:00", precipitation_probability=80, precipitation_mm=2.5, wind_speed_kph=25.0, temperature_c=20.0),
    ]


def test_fetch_hourly_weather_passes_coordinates_and_date_as_params(monkeypatch):
    captured = {}

    def fake_get(url, params, timeout):
        captured.update(params)
        return _FakeResponse({"hourly": {"time": []}})

    monkeypatch.setattr(weather_module.httpx, "get", fake_get)

    fetch_hourly_weather(47.5, 11.5, "2026-09-06")

    assert captured["latitude"] == 47.5
    assert captured["longitude"] == 11.5
    assert captured["start_date"] == "2026-09-06"
    assert captured["end_date"] == "2026-09-06"
    assert captured["timezone"] == "auto"


def test_fetch_hourly_weather_handles_missing_fields_as_none(monkeypatch):
    # A real response always has all four arrays, but tolerate a short/missing one
    # rather than crashing.
    payload = {"hourly": {"time": ["2026-09-06T14:00"]}}
    monkeypatch.setattr(weather_module.httpx, "get", lambda url, params, timeout: _FakeResponse(payload))

    points = fetch_hourly_weather(47.0, 11.0, "2026-09-06")

    assert points == [
        WeatherPoint(time="14:00", precipitation_probability=None, precipitation_mm=None, wind_speed_kph=None, temperature_c=None)
    ]


def test_fetch_sun_times_parses_open_meteo_response(monkeypatch):
    payload = {"daily": {"sunrise": ["2026-09-06T06:32"], "sunset": ["2026-09-06T19:47"]}}
    monkeypatch.setattr(weather_module.httpx, "get", lambda url, params, timeout: _FakeResponse(payload))

    sun_times = fetch_sun_times(47.0, 11.0, "2026-09-06")

    assert sun_times.sunrise == "06:32"
    assert sun_times.sunset == "19:47"


def test_fetch_sun_times_empty_response(monkeypatch):
    monkeypatch.setattr(weather_module.httpx, "get", lambda url, params, timeout: _FakeResponse({"daily": {}}))

    sun_times = fetch_sun_times(47.0, 11.0, "2026-09-06")

    assert sun_times.sunrise == ""
    assert sun_times.sunset == ""
