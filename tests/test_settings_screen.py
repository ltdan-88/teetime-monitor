import asyncio

import pytest
from textual.app import App

from src import global_preferences, i18n
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


class _HostApp(App):
    """SettingsScreen became a plain Screen (2026-09-08, once tui.py needed to push
    it directly) rather than a standalone App — this stands in for the real host app
    so it can still be tested in isolation, same pattern used for every other pushed
    screen in this project."""

    def __init__(self, screen):
        super().__init__()
        self._screen_to_push = screen

    def on_mount(self):
        self.push_screen(self._screen_to_push)


# --- config_to_widget_values ------------------------------------------------


def test_config_to_widget_values_uses_defaults_on_empty_config():
    values = config_to_widget_values({})
    assert values[_id("availability", "min_open_spots")] == "1"
    assert values[_id("availability", "buffer_before_minutes")] == "0"
    assert values[_id("availability", "buffer_after_minutes")] == "0"
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


def test_config_to_widget_values_falls_back_to_the_old_single_buffer_key():
    # A config saved before the 2026-09-08 before/after split -- what this screen
    # shows must match what the app actually does (search.resolve_buffer_minutes()'s
    # same fallback), not just literally what's under the new keys yet.
    config = {"availability": {"buffer_minutes": 15}}
    values = config_to_widget_values(config)
    assert values[_id("availability", "buffer_before_minutes")] == "15"
    assert values[_id("availability", "buffer_after_minutes")] == "15"


def test_config_to_widget_values_prefers_the_new_split_keys_when_present():
    config = {"availability": {"buffer_minutes": 15, "buffer_before_minutes": 5, "buffer_after_minutes": 25}}
    values = config_to_widget_values(config)
    assert values[_id("availability", "buffer_before_minutes")] == "5"
    assert values[_id("availability", "buffer_after_minutes")] == "25"


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


def test_widget_values_to_config_drops_the_old_single_buffer_key_once_saved():
    # A config saved before the 2026-09-08 before/after split -- once the new keys
    # are written (every save does, since they're ordinary "int" fields), the old
    # single key would just be dead, confusing weight left in the file.
    config = {"availability": {"buffer_minutes": 15}}
    values = config_to_widget_values(config)
    updated = widget_values_to_config(config, values)
    assert "buffer_minutes" not in updated["availability"]
    assert updated["availability"]["buffer_before_minutes"] == 15
    assert updated["availability"]["buffer_after_minutes"] == 15


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
    preferences_file = tmp_path / "preferences.yaml"
    preferences_file.write_text("availability:\n  min_open_spots: 3\n")

    async def scenario():
        app = _HostApp(SettingsScreen(preferences_file))
        async with app.run_test():
            widget = app.screen.query_one(f"#{_id('availability', 'min_open_spots')}")
            assert widget.value == "3"

    asyncio.run(scenario())


def test_settings_screen_fields_fill_the_window_instead_of_the_button_row(tmp_path):
    # Direct feedback, a real screenshot (2026-09-08): "the settings menu doesn't
    # fill out vertical space from my window". Root cause: Textual's own Horizontal
    # container (used for #buttons) defaults to height: 1fr, same as VerticalScroll
    # (#fields) -- with nothing overriding it, the two-button row was claiming an
    # equal fractional share of the screen as the entire scrollable fields list,
    # leaving most of a tall terminal as dead space below a stub of visible fields.
    # Asserts the actual resolved sizes in a tall terminal, not just that the CSS
    # text contains the right words.
    preferences_file = tmp_path / "preferences.yaml"

    async def scenario():
        app = _HostApp(SettingsScreen(preferences_file))
        async with app.run_test(size=(80, 50)):
            fields = app.screen.query_one("#fields")
            buttons = app.screen.query_one("#buttons")
            # #buttons should be sized to its own two buttons, not sharing an equal
            # fractional split of the screen with #fields -- a generous upper bound
            # (a button row is a handful of rows, nowhere near half a 50-row screen).
            assert buttons.size.height < 10
            # #fields should claim essentially everything else, not be squeezed down
            # to the same size as the two-line button row it was splitting space with.
            assert fields.size.height > 30

    asyncio.run(scenario())


def test_settings_screen_save_writes_edited_value_to_disk(tmp_path):
    preferences_file = tmp_path / "preferences.yaml"
    preferences_file.write_text(
        "availability:\n  min_open_spots: 1\npreferences:\n  avoid_rain: true\n"
    )

    async def scenario():
        app = _HostApp(SettingsScreen(preferences_file))
        async with app.run_test() as pilot:
            widget = app.screen.query_one(f"#{_id('availability', 'min_open_spots')}")
            widget.value = "3"
            await pilot.click("#save")
            await pilot.pause()

    asyncio.run(scenario())

    saved = global_preferences.load_preferences(preferences_file)
    assert saved["availability"]["min_open_spots"] == 3
    assert saved["preferences"]["avoid_rain"] is True  # untouched fields survive the save


def test_settings_screen_save_calls_on_saved_callback(tmp_path):
    preferences_file = tmp_path / "preferences.yaml"
    seen = []

    async def scenario():
        app = _HostApp(SettingsScreen(preferences_file, on_saved=seen.append))
        async with app.run_test() as pilot:
            await pilot.click("#save")
            await pilot.pause()

    asyncio.run(scenario())

    assert len(seen) == 1
    assert seen[0]["availability"]["min_open_spots"] == 1  # the default, since nothing was edited


def test_settings_screen_invalid_input_does_not_crash_or_save(tmp_path):
    # min_open_spots (used here before 2026-09-08) and buffer_minutes (used here
    # before the same-day before/after split) both became Select dropdowns and can
    # no longer even hold an invalid string -- this now targets avoid_wind_kph, one
    # of the fields that stayed free text (see FIELDS' "choices" split in the
    # module docstring).
    preferences_file = tmp_path / "preferences.yaml"
    preferences_file.write_text("preferences:\n  avoid_wind_kph: 25\n")

    async def scenario():
        app = _HostApp(SettingsScreen(preferences_file))
        async with app.run_test() as pilot:
            widget = app.screen.query_one(f"#{_id('preferences', 'avoid_wind_kph')}")
            widget.value = "not a number"
            await pilot.click("#save")
            await pilot.pause()

    asyncio.run(scenario())

    # Unsaved -- the on-disk file still has the original value.
    saved = global_preferences.load_preferences(preferences_file)
    assert saved["preferences"]["avoid_wind_kph"] == 25


# --- Language (bilingual UI) ----------------------------------------------------------


def test_every_field_label_key_has_a_translation():
    for field in FIELDS:
        assert i18n.t(field.label_key) != field.label_key, f"missing translation for {field.label_key!r}"


def test_settings_screen_renders_german_labels_and_buttons(tmp_path):
    preferences_file = tmp_path / "preferences.yaml"
    i18n.set_language("de")

    async def scenario():
        from textual.widgets import Button, Label

        app = _HostApp(SettingsScreen(preferences_file))
        async with app.run_test() as pilot:
            await pilot.pause()
            labels = {str(label.content) for label in app.screen.query(Label)}
            assert "Min. freie Plätze (Gruppengröße)" in labels
            assert "Regen vermeiden" in labels
            assert str(app.screen.query_one("#save", Button).label) == "Speichern"
            assert str(app.screen.query_one("#quit", Button).label) == "Beenden"

    asyncio.run(scenario())


def test_settings_screen_german_status_messages(tmp_path):
    preferences_file = tmp_path / "preferences.yaml"
    preferences_file.write_text("availability:\n  min_open_spots: 1\n")
    i18n.set_language("de")

    async def scenario():
        from textual.widgets import Static

        app = _HostApp(SettingsScreen(preferences_file))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#save")
            await pilot.pause()
            assert str(app.screen.query_one("#status", Static).content) == "Gespeichert."

    asyncio.run(scenario())


# --- 2026-09-08 UI/UX pass (6-point direct feedback) -------------------------------


def test_settings_screen_buttons_are_right_aligned_quit_then_save(tmp_path):
    # Point 1: "buttons at the bottom of window need to follow common layout
    # conventions regarding placement (iirc usually those buttons are aligned to
    # the right)". Checks actual resolved positions, not just that the CSS mentions
    # "right" -- and that Quit (secondary) sits left of Save (primary), matching the
    # ordinary OS-dialog "Cancel ... Save" convention.
    preferences_file = tmp_path / "preferences.yaml"

    async def scenario():
        app = _HostApp(SettingsScreen(preferences_file))
        async with app.run_test(size=(80, 50)) as pilot:
            await pilot.pause()
            quit_button = app.screen.query_one("#quit")
            save_button = app.screen.query_one("#save")
            assert quit_button.region.x < save_button.region.x
            # The row hugs the right edge of an 80-column screen, not the left.
            assert save_button.region.right > 60

    asyncio.run(scenario())


def test_settings_screen_field_rows_are_one_row_tall(tmp_path):
    # Point 2: "the settings entries take too much vertical space (seems to be two
    # rows currently)" -- was actually three (Input's default border), against a
    # one-row Label, which is also what caused the label/field misalignment.
    preferences_file = tmp_path / "preferences.yaml"

    async def scenario():
        app = _HostApp(SettingsScreen(preferences_file))
        async with app.run_test(size=(80, 50)) as pilot:
            await pilot.pause()
            row = app.screen.query_one(f"#{_id('preferences', 'avoid_wind_kph')}").parent
            assert row.size.height == 1

    asyncio.run(scenario())


def test_settings_screen_limited_fields_render_as_dropdowns(tmp_path):
    # Point 3: "many of the entry fields could be dropdowns since the selection
    # options are mostly limited". min_open_spots (1-4), the daylight buffer, and
    # both scrape intervals qualify; genuine ranges (weather thresholds, time
    # windows) stay free text -- see the module docstring for why (no range-slider
    # widget exists in Textual, and a dropdown wouldn't clearly beat typing a number
    # for those).
    from textual.widgets import Select

    preferences_file = tmp_path / "preferences.yaml"

    async def scenario():
        app = _HostApp(SettingsScreen(preferences_file))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen.query_one(f"#{_id('availability', 'min_open_spots')}"), Select)
            assert isinstance(app.screen.query_one(f"#{_id('daylight_buffer_minutes')}"), Select)
            # The 2026-09-08 before/after buffer split -- also 10-minute-step dropdowns.
            assert isinstance(app.screen.query_one(f"#{_id('availability', 'buffer_before_minutes')}"), Select)
            assert isinstance(app.screen.query_one(f"#{_id('availability', 'buffer_after_minutes')}"), Select)
            # A genuine range stays free text.
            from textual.widgets import Input

            assert isinstance(
                app.screen.query_one(f"#{_id('preferences', 'avoid_wind_kph')}"), Input
            )

    asyncio.run(scenario())


def test_settings_screen_dropdown_keeps_a_stored_value_outside_the_presets(tmp_path):
    # A value saved before these presets existed (or hand-edited to something
    # unusual) must still load and remain selectable rather than crashing the
    # screen or silently getting discarded on the next save.
    preferences_file = tmp_path / "preferences.yaml"
    preferences_file.write_text("scrape_interval_minutes: 7\n")

    async def scenario():
        app = _HostApp(SettingsScreen(preferences_file))
        async with app.run_test() as pilot:
            await pilot.pause()
            widget = app.screen.query_one(f"#{_id('scrape_interval_minutes')}")
            assert widget.value == "7"
            await pilot.click("#save")
            await pilot.pause()

    asyncio.run(scenario())

    saved = global_preferences.load_preferences(preferences_file)
    assert saved["scrape_interval_minutes"] == 7


def test_settings_screen_groups_fields_into_labeled_sections(tmp_path):
    # Point 4: "entries in settings could be grouped into categories, to make it
    # more user friendly."
    from textual.widgets import Collapsible

    preferences_file = tmp_path / "preferences.yaml"

    async def scenario():
        app = _HostApp(SettingsScreen(preferences_file))
        async with app.run_test() as pilot:
            await pilot.pause()
            titles = {str(c.title) for c in app.screen.query(Collapsible)}
            assert titles == {"Availability", "Weather", "Priorities", "Timing & scraping"}
            # Expanded by default -- these are settings you're here to look at.
            assert all(not c.collapsed for c in app.screen.query(Collapsible))
            # A field genuinely lives inside its labeled group, not just anywhere.
            availability_group = next(c for c in app.screen.query(Collapsible) if str(c.title) == "Availability")
            assert availability_group.query_one(f"#{_id('availability', 'min_open_spots')}")

    asyncio.run(scenario())


def test_settings_screen_stacks_label_above_field_in_a_narrow_window(tmp_path):
    # Direct follow-up, same day: "I'd like that made more flexible too" -- the
    # side-by-side label/field layout needs roughly 70 columns and had nowhere to
    # shrink to below that, clipping the field clean off screen. Below the
    # threshold, the row switches to label-above-field (both full width) instead.
    preferences_file = tmp_path / "preferences.yaml"

    async def scenario():
        app = _HostApp(SettingsScreen(preferences_file))
        async with app.run_test(size=(80, 50)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert not screen.has_class("-narrow")
            row = screen.query_one(f"#{_id('preferences', 'avoid_wind_kph')}").parent
            # Side by side at a comfortable width -- one row.
            assert row.size.height == 1

            await pilot.resize_terminal(50, 50)
            await pilot.pause()
            assert screen.has_class("-narrow")
            # Label-above-field now -- the row genuinely grew taller, not just a
            # class name flipping with nothing visibly different.
            assert row.size.height > 1

            # And it un-narrows again once there's room, rather than getting stuck.
            await pilot.resize_terminal(80, 50)
            await pilot.pause()
            assert not screen.has_class("-narrow")
            assert row.size.height == 1

    asyncio.run(scenario())


def test_settings_screen_narrow_layout_never_clips_a_field_off_screen(tmp_path):
    preferences_file = tmp_path / "preferences.yaml"

    async def scenario():
        app = _HostApp(SettingsScreen(preferences_file))
        async with app.run_test(size=(50, 50)) as pilot:
            await pilot.pause()
            widget = app.screen.query_one(f"#{_id('preferences', 'avoid_wind_kph')}")
            # Fully inside the 50-column screen -- not pushed past its right edge,
            # which is what the fixed 42+20-column layout used to do below ~70
            # columns.
            assert widget.region.right <= 50

    asyncio.run(scenario())


def test_settings_screen_time_fields_split_into_hour_and_minute_dropdowns(tmp_path):
    # Direct follow-up, same day: "can you at least split the input boxes for the
    # time ranges into something like hh:mm?"
    from textual.widgets import Input, Select

    preferences_file = tmp_path / "preferences.yaml"
    preferences_file.write_text("availability:\n  weekday_window: {after: '17:00'}\n")

    async def scenario():
        app = _HostApp(SettingsScreen(preferences_file))
        async with app.run_test() as pilot:
            await pilot.pause()
            base = _id("availability", "weekday_window", "after")
            # No more single free-text time field...
            assert not app.screen.query(f"#{base}")
            # ...it's two dropdowns instead, pre-filled from the saved "17:00".
            hour = app.screen.query_one(f"#{base}-hh", Select)
            minute = app.screen.query_one(f"#{base}-mm", Select)
            assert hour.value == "17"
            assert minute.value == "00"
            # A field that's never been split (a genuine range) still isn't one.
            assert isinstance(app.screen.query_one(f"#{_id('preferences', 'avoid_wind_kph')}"), Input)

    asyncio.run(scenario())


def test_settings_screen_time_field_round_trips_through_hour_and_minute(tmp_path):
    preferences_file = tmp_path / "preferences.yaml"

    async def scenario():
        app = _HostApp(SettingsScreen(preferences_file))
        async with app.run_test() as pilot:
            await pilot.pause()
            base = _id("availability", "weekday_window", "after")
            app.screen.query_one(f"#{base}-hh").value = "09"
            app.screen.query_one(f"#{base}-mm").value = "30"
            await pilot.click("#save")
            await pilot.pause()

    asyncio.run(scenario())

    saved = global_preferences.load_preferences(preferences_file)
    assert saved["availability"]["weekday_window"]["after"] == "09:30"


def test_settings_screen_time_field_blank_hour_means_not_set(tmp_path):
    preferences_file = tmp_path / "preferences.yaml"
    preferences_file.write_text("availability:\n  weekday_window: {after: '17:00'}\n")

    async def scenario():
        app = _HostApp(SettingsScreen(preferences_file))
        async with app.run_test() as pilot:
            await pilot.pause()
            base = _id("availability", "weekday_window", "after")
            app.screen.query_one(f"#{base}-hh").value = ""
            await pilot.click("#save")
            await pilot.pause()

    asyncio.run(scenario())

    saved = global_preferences.load_preferences(preferences_file)
    # "before" was never set either, so the whole window collapses to nothing --
    # same "day type not configured -> skipped entirely" rule widget_values_to_config
    # already applies (see its own docstring), not new behavior from this change.
    assert "weekday_window" not in saved.get("availability", {})


def test_settings_screen_time_field_keeps_a_stored_minute_outside_the_presets(tmp_path):
    # A value saved before the quarter-hour presets existed (or hand-edited) must
    # still load and stay selectable rather than crashing the screen.
    preferences_file = tmp_path / "preferences.yaml"
    preferences_file.write_text("availability:\n  weekday_window: {after: '17:05'}\n")

    async def scenario():
        app = _HostApp(SettingsScreen(preferences_file))
        async with app.run_test() as pilot:
            await pilot.pause()
            base = _id("availability", "weekday_window", "after")
            assert app.screen.query_one(f"#{base}-hh").value == "17"
            assert app.screen.query_one(f"#{base}-mm").value == "05"
            await pilot.click("#save")
            await pilot.pause()

    asyncio.run(scenario())

    saved = global_preferences.load_preferences(preferences_file)
    assert saved["availability"]["weekday_window"]["after"] == "17:05"


def test_settings_screen_hour_dropdown_excludes_implausible_hours(tmp_path):
    # Direct follow-up, same day: "can you please remove hours that don't make
    # sense from the dropdown menus?" -- no golf club is open at 2am.
    from src.settings_screen import EARLIEST_TEE_HOUR, LATEST_TEE_HOUR

    preferences_file = tmp_path / "preferences.yaml"

    async def scenario():
        from textual.widgets import Select

        app = _HostApp(SettingsScreen(preferences_file))
        async with app.run_test() as pilot:
            await pilot.pause()
            base = _id("availability", "weekday_window", "after")
            hour_select = app.screen.query_one(f"#{base}-hh", Select)
            offered_hours = hour_select._legal_values - {""}
            assert "02" not in offered_hours
            assert "23" not in offered_hours
            assert f"{EARLIEST_TEE_HOUR:02d}" in offered_hours
            assert f"{LATEST_TEE_HOUR:02d}" in offered_hours

    asyncio.run(scenario())


def test_settings_screen_time_field_keeps_a_stored_hour_outside_the_restricted_range(tmp_path):
    # A value saved before this restriction existed (or hand-edited to something
    # implausible) must still load and stay selectable rather than crashing the
    # screen or silently getting discarded on the next save -- same generic
    # "current value stays selectable" handling every other dropdown here uses,
    # not new migration logic (see the memory note: this project skips that while
    # still in development).
    preferences_file = tmp_path / "preferences.yaml"
    preferences_file.write_text("availability:\n  weekday_window: {after: '23:00'}\n")

    async def scenario():
        app = _HostApp(SettingsScreen(preferences_file))
        async with app.run_test() as pilot:
            await pilot.pause()
            base = _id("availability", "weekday_window", "after")
            assert app.screen.query_one(f"#{base}-hh").value == "23"
            await pilot.click("#save")
            await pilot.pause()

    asyncio.run(scenario())

    saved = global_preferences.load_preferences(preferences_file)
    assert saved["availability"]["weekday_window"]["after"] == "23:00"


def test_settings_screen_footer_renders_translated_hint(tmp_path):
    preferences_file = tmp_path / "preferences.yaml"
    i18n.set_language("de")

    async def scenario():
        from src.settings_screen import TranslatedFooter

        app = _HostApp(SettingsScreen(preferences_file))
        async with app.run_test() as pilot:
            await pilot.pause()
            footer = app.screen.query_one(TranslatedFooter)
            assert "Beenden" in footer.render()

    asyncio.run(scenario())
