import pytest

from src import i18n


@pytest.fixture(autouse=True)
def _reset_current_language():
    """i18n's "current language" is deliberate module-level global state (see its
    docstring) — reset it around every test so one test's set_language() call can't
    leak into the next."""
    i18n._current_language = None
    yield
    i18n._current_language = None


# --- t() ------------------------------------------------------------------------------


def test_t_returns_english_by_default(monkeypatch):
    monkeypatch.delenv(i18n.ENV_VAR, raising=False)
    i18n.set_language("en")
    assert i18n.t("table.time") == "Time"


def test_t_returns_german_when_set():
    i18n.set_language("de")
    assert i18n.t("table.time") == "Zeit"


def test_t_formats_placeholders():
    i18n.set_language("en")
    assert i18n.t("app.no_club_id", slug="home-club") == "clubs/home-club.yaml has no club_id set."


def test_t_falls_back_to_the_raw_key_for_an_unknown_key():
    i18n.set_language("en")
    assert i18n.t("not.a.real.key") == "not.a.real.key"


def test_every_english_key_has_a_german_translation():
    # Keeps the two dictionaries honestly in sync -- t()'s English fallback exists for
    # safety, not as a license to leave German half-finished.
    en_keys = set(i18n._STRINGS["en"])
    de_keys = set(i18n._STRINGS["de"])
    assert en_keys == de_keys


# --- get_language / set_language / other_language -----------------------------------


def test_set_language_ignores_unsupported_value():
    i18n.set_language("en")
    i18n.set_language("fr")  # not supported -- should be a no-op
    assert i18n.get_language() == "en"


def test_other_language_toggles():
    assert i18n.other_language("en") == "de"
    assert i18n.other_language("de") == "en"


# --- persistence ------------------------------------------------------------------------


def test_load_saved_language_returns_none_when_never_saved(tmp_path):
    assert i18n.load_saved_language(tmp_path / "config") is None


def test_save_and_load_language_round_trips(tmp_path):
    config_file = tmp_path / "config"
    i18n.save_language("de", config_file)
    assert i18n.load_saved_language(config_file) == "de"


def test_load_saved_language_ignores_unsupported_saved_value(tmp_path):
    config_file = tmp_path / "config"
    from src import user_config

    user_config.save_value("LANG", "fr", config_file)
    assert i18n.load_saved_language(config_file) is None


def test_theme_and_language_share_the_same_config_file(tmp_path):
    from src import theme

    config_file = tmp_path / "config"
    theme.save_theme("nord", config_file)
    i18n.save_language("de", config_file)

    assert theme.load_saved_theme(config_file) == "nord"
    assert i18n.load_saved_language(config_file) == "de"


# --- resolution order --------------------------------------------------------------------


def test_resolve_language_name_defaults_to_english_for_a_non_german_locale(tmp_path):
    config_file = tmp_path / "config"
    env = {"LANG": "en_US.UTF-8"}
    assert i18n.resolve_language_name(env=env, config_file=config_file) == "en"


def test_resolve_language_name_defaults_to_german_for_a_german_locale(tmp_path):
    config_file = tmp_path / "config"
    env = {"LANG": "de_DE.UTF-8"}
    assert i18n.resolve_language_name(env=env, config_file=config_file) == "de"


def test_resolve_language_name_saved_config_wins_over_locale_default(tmp_path):
    config_file = tmp_path / "config"
    i18n.save_language("en", config_file)
    env = {"LANG": "de_DE.UTF-8"}  # would default to German, but a saved choice wins
    assert i18n.resolve_language_name(env=env, config_file=config_file) == "en"


def test_resolve_language_name_env_var_wins_over_everything(tmp_path):
    config_file = tmp_path / "config"
    i18n.save_language("en", config_file)
    env = {i18n.ENV_VAR: "de", "LANG": "en_US.UTF-8"}
    assert i18n.resolve_language_name(env=env, config_file=config_file) == "de"


def test_apply_language_resolves_and_sets_current_language(tmp_path):
    config_file = tmp_path / "config"
    i18n.save_language("de", config_file)
    applied = i18n.apply_language(config_file=config_file)
    assert applied == "de"
    assert i18n.get_language() == "de"
