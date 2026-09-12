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


def test_ordered_icons_is_calm_first_the_reverse_of_severity_order():
    # Added 2026-09-15 for tui.py's own CONDITION_LEGEND -- direct question:
    # "how are the weather icons arranged/ordered?" Calm-first is the exact
    # reverse of _SEVERITY_ORDER (worst-first, the same list worst_icon()
    # already uses), confirmed against that same ordering's own already-tested
    # judgment calls above (test_worst_icon_snow_beats_rain: snow ranks worse
    # than plain rain, so "rain" must come before "snow" here).
    ordered = weather_icons.ordered_icons()
    assert ordered[0] == "☀️"  # clear -- calmest
    assert ordered[-1] == "⛈️"  # thunderstorm -- most severe
    assert ordered.index("🌧️") < ordered.index("❄️")  # rain calmer than snow
    assert ordered.index("❄️") < ordered.index("🌨️")  # snow calmer than snow showers


def test_ordered_icons_has_no_duplicates():
    # Several WMO codes share one icon (every drizzle severity, every rain/rain-
    # shower/freezing-rain variant, etc.) -- each icon appears exactly once.
    ordered = weather_icons.ordered_icons()
    assert len(ordered) == len(set(ordered))
