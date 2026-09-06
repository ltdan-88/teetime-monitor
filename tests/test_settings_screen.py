import asyncio

import pytest

from src import i18n
from src.club_config import load_club_config
from src.recommend import DEFAULT_AVOID_RAIN_PROBABILITY_PERCENT
from src.scrape_once import DEFAULT_SCRAPE_INTERVAL_MINUTES
from src.settings_screen import (
    FIELDS,
    SettingsScreen,
    config_to_widget_values,
    widget_values_to_config,
)


@pytest.fixture(autouse=True)
def _english_ui(monkeypatch, tmp_path):
    # Same reasoning as tui.py's identical fixture -- i18n's current language is
    # module-level global state that would otherwise leak between tests.
    monkeypatch.setattr(i18n, "CONFIG_FILE", tmp_path / "not-used-unless-a-test-wants-it")
    i18n.set_language("en")
    yield
    i18n._current_language = None


def _id(*path):
    return "field-" + "-".join(path)


# --- config_to_widget_values ------------------------------------------------


def test_config_to_widget_values_uses_defaults_on_empty_config():
    values = config_to_widget_values({})
    assert values[_id("availability", "min_open_spots")] == "1"
    assert values[_id("availability", "buffer_minutes")] == "0"
    assert values[_id("preferences", "avoid_rain")] is False
    assert values[_id("preferences", "avoid_rain_probability_percent")] == str(
        DEFAULT_AVOID_RAIN_PROBABILITY_PERCENT
    )
    assert values[_id("scrape_interval_minutes")] == str(DEFAULT_SCRAPE_INTERVAL_MINUTES)
    assert values[_id("availability", "weekday_window", "after")] == ""


def test_config_to_widget_values_reflects_existing_config():
    config = {
        "availability": {"min_open_spots": 3, "weekday_window": {"after": "17:00"}},
        "preferences": {"avoid_rain": True, "avoid_rain_probability_percent": 80},
    }
    values = config_to_widget_values(config)
    assert values[_id("availability", "min_open_spots")] == "3"
    assert values[_id("availability", "weekday_window", "after")] == "17:00"
    assert values[_id("availability", "weekday_window", "before")] == ""
    assert values[_id("preferences", "avoid_rain")] is True
    assert values[_id("preferences", "avoid_rain_probability_percent")] == "80"


# --- widget_values_to_config -------------------------------------------------


def test_widget_values_to_config_round_trips_defaults():
    values = config_to_widget_values({})
    updated = widget_values_to_config({}, values)
    assert updated["availability"]["min_open_spots"] == 1
    assert updated["preferences"]["avoid_rain"] is False
    assert updated["scrape_interval_minutes"] == DEFAULT_SCRAPE_INTERVAL_MINUTES


def test_widget_values_to_config_parses_edited_int():
    values = config_to_widget_values({})
    values[_id("availability", "min_open_spots")] = "4"
    updated = widget_values_to_config({}, values)
    assert updated["availability"]["min_open_spots"] == 4


def test_widget_values_to_config_parses_edited_bool():
    values = config_to_widget_values({})
    values[_id("preferences", "avoid_rain")] = True
    updated = widget_values_to_config({}, values)
    assert updated["preferences"]["avoid_rain"] is True


def test_widget_values_to_config_optional_float_blank_means_none():
    values = config_to_widget_values({"preferences": {"avoid_temp_below_c": 5}})
    values[_id("preferences", "avoid_temp_below_c")] = ""
    updated = widget_values_to_config({}, values)
    assert updated["preferences"]["avoid_temp_below_c"] is None


def test_widget_values_to_config_drops_fully_empty_time_window():
    # Neither after nor before set for the weekday window -- should collapse to no
    # weekday_window key at all, matching "day type not configured -> skipped
    # entirely" (see search.py's SearchCriteria docstring), not an empty {} dict.
    values = config_to_widget_values({})
    updated = widget_values_to_config({}, values)
    assert "weekday_window" not in updated.get("availability", {})


def test_widget_values_to_config_keeps_partial_time_window():
    values = config_to_widget_values({})
    values[_id("availability", "weekday_window", "after")] = "17:00"
    updated = widget_values_to_config({}, values)
    assert updated["availability"]["weekday_window"] == {"after": "17:00", "before": None}


def test_widget_values_to_config_raises_on_invalid_number():
    values = config_to_widget_values({})
    values[_id("availability", "min_open_spots")] = "not a number"
    try:
        widget_values_to_config({}, values)
        assert False, "expected ValueError"
    except ValueError:
        pass


# --- SettingsScreen (real Textual app, run headlessly via Textual's test harness) --


def test_settings_screen_loads_config_into_widgets(tmp_path):
    (tmp_path / "home-club.yaml").write_text(
        "club_id: '0000001'\navailability:\n  min_open_spots: 3\n"
    )

    async def scenario():
        app = SettingsScreen("home-club", clubs_dir=tmp_path)
        async with app.run_test():
            widget = app.query_one(f"#{_id('availability', 'min_open_spots')}")
            assert widget.value == "3"

    asyncio.run(scenario())


def test_settings_screen_save_writes_edited_value_to_disk(tmp_path):
    (tmp_path / "home-club.yaml").write_text(
        "club_id: '0000001'\navailability:\n  min_open_spots: 1\n"
    )

    async def scenario():
        app = SettingsScreen("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            widget = app.query_one(f"#{_id('availability', 'min_open_spots')}")
            widget.value = "3"
            await pilot.click("#save")
            await pilot.pause()

    asyncio.run(scenario())

    saved = load_club_config("home-club", tmp_path)
    assert saved["availability"]["min_open_spots"] == 3
    assert saved["club_id"] == "0000001"  # untouched fields survive the save


def test_settings_screen_save_calls_on_saved_callback(tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    seen = []

    async def scenario():
        app = SettingsScreen("home-club", clubs_dir=tmp_path, on_saved=seen.append)
        async with app.run_test() as pilot:
            await pilot.click("#save")
            await pilot.pause()

    asyncio.run(scenario())

    assert len(seen) == 1
    assert seen[0]["club_id"] == "0000001"


def test_settings_screen_invalid_input_does_not_crash_or_save(tmp_path):
    (tmp_path / "home-club.yaml").write_text(
        "club_id: '0000001'\navailability:\n  min_open_spots: 1\n"
    )

    async def scenario():
        app = SettingsScreen("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            widget = app.query_one(f"#{_id('availability', 'min_open_spots')}")
            widget.value = "not a number"
            await pilot.click("#save")
            await pilot.pause()

    asyncio.run(scenario())

    # Unsaved -- the on-disk file still has the original value.
    saved = load_club_config("home-club", tmp_path)
    assert saved["availability"]["min_open_spots"] == 1


# --- Language (bilingual UI) ----------------------------------------------------------


def test_every_field_label_key_has_a_translation():
    for field in FIELDS:
        assert i18n.t(field.label_key) != field.label_key, f"missing translation for {field.label_key!r}"


def test_settings_screen_renders_german_labels_and_buttons(tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    i18n.set_language("de")

    async def scenario():
        from textual.widgets import Button, Label

        app = SettingsScreen("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            labels = {str(label.content) for label in app.query(Label)}
            assert "Min. freie Plätze (Gruppengröße)" in labels
            assert "Regen vermeiden" in labels
            assert str(app.query_one("#save", Button).label) == "Speichern"
            assert str(app.query_one("#quit", Button).label) == "Beenden"

    asyncio.run(scenario())


def test_settings_screen_german_status_messages(tmp_path):
    (tmp_path / "home-club.yaml").write_text(
        "club_id: '0000001'\navailability:\n  min_open_spots: 1\n"
    )
    i18n.set_language("de")

    async def scenario():
        from textual.widgets import Static

        app = SettingsScreen("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#save")
            await pilot.pause()
            assert str(app.query_one("#status", Static).content) == "Gespeichert."

    asyncio.run(scenario())


def test_settings_screen_footer_renders_translated_hint(tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_id: '0000001'\n")
    i18n.set_language("de")

    async def scenario():
        from src.settings_screen import TranslatedFooter

        app = SettingsScreen("home-club", clubs_dir=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            footer = app.query_one(TranslatedFooter)
            assert "Beenden" in footer.render()

    asyncio.run(scenario())
