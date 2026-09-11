from src import weather_icons


def test_icon_for_code_known_codes():
    assert weather_icons.icon_for_code(0) == "☀️"
    assert weather_icons.icon_for_code(3) == "☁️"
    assert weather_icons.icon_for_code(45) == "🌫️"
    assert weather_icons.icon_for_code(63) == "🌧️"
    assert weather_icons.icon_for_code(75) == "❄️"
    assert weather_icons.icon_for_code(95) == "⛈️"


def test_icon_for_code_missing_or_unrecognized():
    assert weather_icons.icon_for_code(None) == ""
    assert weather_icons.icon_for_code(12345) == ""


def test_worst_icon_picks_most_severe():
    # Clear morning, thunderstorm in the afternoon -- thunderstorm wins.
    assert weather_icons.worst_icon([0, 1, 2, 95]) == "⛈️"


def test_worst_icon_snow_beats_rain():
    assert weather_icons.worst_icon([61, 71]) == "❄️"


def test_worst_icon_ignores_unrecognized_and_missing():
    assert weather_icons.worst_icon([None, 99999, 2]) == "⛅"


def test_worst_icon_empty_or_all_unknown_is_blank():
    assert weather_icons.worst_icon([]) == ""
    assert weather_icons.worst_icon([None, None]) == ""
