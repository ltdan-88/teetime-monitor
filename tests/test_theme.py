import asyncio

from textual.app import App

from src import theme


def _run(coro):
    asyncio.run(coro)


# --- name mapping ---------------------------------------------------------------------


def test_to_textual_theme_name_maps_known_brew_launcher_names():
    assert theme.to_textual_theme_name("catppuccin") == "catppuccin-mocha"
    assert theme.to_textual_theme_name("tokyonight") == "tokyo-night"
    assert theme.to_textual_theme_name("nord") == "nord"


def test_to_textual_theme_name_passes_through_custom_and_unknown_names():
    assert theme.to_textual_theme_name("green") == "green"
    assert theme.to_textual_theme_name("monokai") == "monokai"


def test_to_logical_name_reverses_the_builtin_map():
    assert theme.to_logical_name("catppuccin-mocha") == "catppuccin"
    assert theme.to_logical_name("tokyo-night") == "tokyonight"


def test_to_logical_name_passes_through_names_with_no_brew_launcher_equivalent():
    assert theme.to_logical_name("monokai") == "monokai"
    assert theme.to_logical_name("green") == "green"


def test_all_theme_names_covers_all_ten():
    assert len(theme.ALL_THEME_NAMES) == 10
    assert set(theme.ALL_THEME_NAMES) == {
        "catppuccin",
        "gruvbox",
        "tokyonight",
        "nord",
        "dracula",
        "solarized-dark",
        "solarized-light",
        "green",
        "amber",
        "red-sands",
    }


# --- persistence ------------------------------------------------------------------------


def test_load_saved_theme_returns_none_when_never_saved(tmp_path):
    config_file = tmp_path / "config"
    assert theme.load_saved_theme(config_file) is None


def test_save_and_load_theme_round_trips(tmp_path):
    config_file = tmp_path / "config"
    theme.save_theme("nord", config_file)
    assert theme.load_saved_theme(config_file) == "nord"


def test_save_theme_overwrites_in_place_not_duplicated(tmp_path):
    config_file = tmp_path / "config"
    theme.save_theme("nord", config_file)
    theme.save_theme("dracula", config_file)

    content = config_file.read_text()
    assert content.count("THEME=") == 1
    assert theme.load_saved_theme(config_file) == "dracula"


def test_save_theme_preserves_other_config_lines(tmp_path):
    config_file = tmp_path / "config"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("SOME_OTHER_SETTING=value\n")

    theme.save_theme("gruvbox", config_file)

    content = config_file.read_text()
    assert "SOME_OTHER_SETTING=value" in content
    assert "THEME=gruvbox" in content


# --- resolution order --------------------------------------------------------------------


def test_resolve_theme_name_defaults_when_nothing_set(tmp_path):
    config_file = tmp_path / "config"
    assert theme.resolve_theme_name(env={}, config_file=config_file) == theme.DEFAULT_THEME


def test_resolve_theme_name_uses_saved_config_over_default(tmp_path):
    config_file = tmp_path / "config"
    theme.save_theme("amber", config_file)
    assert theme.resolve_theme_name(env={}, config_file=config_file) == "amber"


def test_resolve_theme_name_env_var_wins_over_saved_config(tmp_path):
    config_file = tmp_path / "config"
    theme.save_theme("amber", config_file)
    env = {theme.ENV_VAR: "red-sands"}
    assert theme.resolve_theme_name(env=env, config_file=config_file) == "red-sands"


# --- applying to a real App --------------------------------------------------------------


def test_apply_theme_registers_customs_and_sets_builtin_equivalent(tmp_path):
    config_file = tmp_path / "config"

    async def scenario():
        app = App()
        async with app.run_test():
            applied = theme.apply_theme(app, name="catppuccin", config_file=config_file)
            assert applied == "catppuccin"
            assert app.theme == "catppuccin-mocha"

    _run(scenario())


def test_apply_theme_applies_a_custom_theme(tmp_path):
    config_file = tmp_path / "config"

    async def scenario():
        app = App()
        async with app.run_test():
            theme.apply_theme(app, name="green", config_file=config_file)
            assert app.theme == "green"
            assert "green" in app.available_themes

    _run(scenario())


def test_apply_theme_falls_back_to_default_for_unknown_name(tmp_path):
    config_file = tmp_path / "config"

    async def scenario():
        app = App()
        async with app.run_test():
            applied = theme.apply_theme(app, name="not-a-real-theme", config_file=config_file)
            assert applied == theme.DEFAULT_THEME
            assert app.theme == theme.to_textual_theme_name(theme.DEFAULT_THEME)

    _run(scenario())


def test_apply_theme_uses_resolve_order_when_no_name_given(tmp_path):
    config_file = tmp_path / "config"
    theme.save_theme("dracula", config_file)

    async def scenario():
        app = App()
        async with app.run_test():
            applied = theme.apply_theme(app, config_file=config_file)
            assert applied == "dracula"
            assert app.theme == "dracula"

    _run(scenario())
