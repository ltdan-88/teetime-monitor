import re

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


@pytest.mark.parametrize("ui_is_german, expected", [(True, "de"), (False, "en")])
def test_windows_default_follows_the_os_ui_language(tmp_path, monkeypatch, ui_is_german, expected):
    """Windows shells export no LANG/LC_ALL, so German Windows used to get English."""
    monkeypatch.setattr(i18n.sys, "platform", "win32")
    monkeypatch.setattr(i18n, "_windows_ui_language_is_german", lambda: ui_is_german)
    assert i18n.resolve_language_name(env={}, config_file=tmp_path / "config") == expected


def test_windows_default_still_honours_an_explicit_lang(tmp_path, monkeypatch):
    # Git Bash / MSYS set LANG; that wins over the OS language, same as elsewhere.
    monkeypatch.setattr(i18n.sys, "platform", "win32")
    monkeypatch.setattr(i18n, "_windows_ui_language_is_german", lambda: True)
    env = {"LANG": "en_US.UTF-8"}
    assert i18n.resolve_language_name(env=env, config_file=tmp_path / "config") == "en"


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


# --- render_booking_change() ----------------------------------------------------------


def test_render_booking_change_party_grew_singular_english():
    i18n.set_language("en")
    text = i18n.render_booking_change("party_grew", {"count": 1, "time": "14:00"})
    assert text == "1 more player joined your 14:00 tee time since you booked"


def test_render_booking_change_party_grew_plural_english():
    i18n.set_language("en")
    text = i18n.render_booking_change("party_grew", {"count": 2, "time": "14:00"})
    assert text == "2 more players joined your 14:00 tee time since you booked"


def test_render_booking_change_party_grew_german_uses_correct_plural_form():
    # The point is German subject-verb agreement (ist/sind), which is exactly why
    # party_grew has two separate keys rather than one templated string. Wording
    # rephrased 2026-09-16 (audit: the banners were the app's only formal "Sie"
    # strings, everything else already addressed the user as "du") -- the
    # agreement this guards is unchanged, so only the surrounding words moved.
    i18n.set_language("de")
    singular = i18n.render_booking_change("party_grew", {"count": 1, "time": "14:00"})
    plural = i18n.render_booking_change("party_grew", {"count": 2, "time": "14:00"})
    assert "ist 1 Spieler" in singular
    assert "sind 2 Spieler" in plural
    # ...and neither form slipped back into the formal register.
    assert "Ihrer" not in singular and "Ihrer" not in plural


def test_render_booking_change_buffer_shrunk():
    i18n.set_language("en")
    text = i18n.render_booking_change("buffer_shrunk", {"time": "14:00", "neighbor_time": "14:10"})
    assert text == "The 14:10 slot near your 14:00 tee time is no longer clear"


def test_render_booking_change_neighbor_crowded():
    i18n.set_language("en")
    text = i18n.render_booking_change("neighbor_crowded", {"time": "14:00", "neighbor_time": "14:10"})
    assert text == "The 14:10 flight near your 14:00 tee time picked up more players"


def test_render_booking_change_weather_worsened_translates_each_reason():
    i18n.set_language("en")
    text = i18n.render_booking_change("weather_worsened", {"time": "14:00", "reason_keys": ["rain_chance", "wind"]})
    assert text == "The forecast for your 14:00 tee time got worse (rain chance, wind)"


def test_render_booking_change_weather_worsened_german_reasons():
    i18n.set_language("de")
    text = i18n.render_booking_change("weather_worsened", {"time": "14:00", "reason_keys": ["wind"]})
    assert "Wind" in text
    assert "Vorhersage" in text


def test_render_booking_change_returns_none_for_unknown_kind():
    assert i18n.render_booking_change("something_new", {}) is None


def test_german_ui_never_mixes_formal_sie_with_informal_du():
    """Found in the 2026-09-16 full-project audit: the five booking-watch banners
    addressed the user formally ("...ist Ihrer Tee-Zeit beigetreten, seit Sie
    gebucht haben") while every club-picker hint in the same app already used "du"
    ("Deine Favoriten", "Dein Login ist gespeichert"). A German speaker notices
    that instantly; it reads as two different products stitched together. The app
    is now consistently informal, and this guards that -- a single formal pronoun
    slipping back into any German string fails here rather than shipping.

    Matches whole words only: "Sie" as a pronoun, not the "sie"/"Sie" inside
    ordinary words, and not the capitalised-at-sentence-start false positives an
    unanchored substring search would produce.
    """
    formal = re.compile(r"\b(Sie|Ihre[rnms]?|Ihnen)\b")
    offenders = {
        key: value
        for key, value in i18n._STRINGS["de"].items()
        if isinstance(value, str) and formal.search(value)
    }
    assert offenders == {}, f"formal 'Sie/Ihr' found in German UI strings: {offenders}"


def test_render_booking_change_reservations_sync_failed_login():
    i18n.set_language("en")
    text = i18n.render_booking_change("reservations_sync_failed", {"reason": "login"})
    assert "login failed" in text


def test_render_booking_change_reservations_sync_failed_parsing_german():
    i18n.set_language("de")
    text = i18n.render_booking_change("reservations_sync_failed", {"reason": "parsing"})
    assert "geändert" in text


def test_scrape_health_strings_match_the_gui_word_for_word():
    # 2026-10-05: the health line must read the same in both apps (same keys, same
    # text), so this parses macos/Sources/I18n.swift's two tables directly rather than
    # trusting that someone remembered to copy an edit across.
    from pathlib import Path

    swift = (Path(__file__).resolve().parent.parent / "macos" / "Sources" / "I18n.swift").read_text(encoding="utf-8")
    english, german = swift.split("private let germanStrings", 1)
    entry = re.compile(r'^\s*"(health\.[^"]+)":\s*"((?:[^"\\]|\\.)*)",?\s*$', re.MULTILINE)
    for lang, table in (("en", english), ("de", german)):
        swift_health = dict(entry.findall(table))
        python_health = {k: v for k, v in i18n._STRINGS[lang].items() if k.startswith("health.")}
        assert python_health, "no health.* keys in i18n.py"
        assert swift_health == python_health, lang


def test_shorter_round_strings_match_the_gui_word_for_word():
    # 2026-10-05: the "★ 16:10 · 9H" cell, its #row-detail sentence (the GUI's
    # tooltip) and the hint's course list must read the same in both apps.
    from pathlib import Path

    swift = (Path(__file__).resolve().parent.parent / "macos" / "Sources" / "I18n.swift").read_text(encoding="utf-8")
    english, german = swift.split("private let germanStrings", 1)
    keys = ("overview.pick_holes", "overview.pick_alternative", "overview.hint_alternative")
    entry = re.compile(r'^\s*"([^"]+)":\s*"((?:[^"\\]|\\.)*)",?\s*$', re.MULTILINE)
    for lang, table in (("en", english), ("de", german)):
        swift_strings = dict(entry.findall(table))
        for key in keys:
            assert swift_strings[key] == i18n._STRINGS[lang][key], (lang, key)


def test_quality_reason_strings_match_the_gui_word_for_word():
    # 2026-10-05: the Pick's "why" (#row-detail here, the badge tooltip in the GUI) is
    # composed from the same strings in both apps, so parse I18n.swift's tables directly.
    from pathlib import Path

    from src import quality

    swift = (Path(__file__).resolve().parent.parent / "macos" / "Sources" / "I18n.swift").read_text(encoding="utf-8")
    english, german = swift.split("private let germanStrings", 1)
    keys = ("overview.pick_reasons", *(f"quality.reason.{key}" for key in quality.REASON_KEYS))
    entry = re.compile(r'^\s*"([^"]+)":\s*"((?:[^"\\]|\\.)*)",?\s*$', re.MULTILINE)
    for lang, table in (("en", english), ("de", german)):
        swift_strings = dict(entry.findall(table))
        for key in keys:
            assert swift_strings[key] == i18n._STRINGS[lang][key], (lang, key)


# --- booking-window lock strings (2026-10-05) ---------------------------------------------

LOCK_KEYS = (
    "lock.today",
    "lock.opens_at",
    "lock.opens_at_date",
    "legend.locked",
    "lock.date",
    *(f"lock.month.{month}" for month in range(1, 13)),
)


def test_lock_strings_exist_in_both_languages_with_matching_placeholders():
    for key in LOCK_KEYS:
        en, de = i18n._STRINGS["en"][key], i18n._STRINGS["de"][key]
        assert en and de
        assert set(re.findall(r"{(\w+)}", en)) == set(re.findall(r"{(\w+)}", de)), key
    for key in ("lock.opens_at", "lock.opens_at_date"):
        assert "{when}" in i18n._STRINGS["en"][key] and "{when}" in i18n._STRINGS["de"][key]


def test_lock_sentences_render_in_both_languages():
    i18n.set_language("en")
    assert i18n.t("lock.opens_at", when="Wed 21:00") == "Booking opens Wed 21:00"
    assert i18n.t("lock.opens_at_date", when="Tue") == "Booking opens Tue (the club gives no time)"
    i18n.set_language("de")
    assert i18n.t("lock.opens_at", when="Mi 21:00") == "Buchbar ab Mi 21:00"
    assert i18n.t("lock.today") == "heute"


def test_lock_date_wording_is_natural_in_each_language():
    month = i18n.t("lock.month.10")
    assert i18n.t("lock.date", month=month, day=14) == "Oct 14"
    i18n.set_language("de")
    assert i18n.t("lock.date", month=i18n.t("lock.month.10"), day=14) == "14. Okt"
    assert i18n.t("lock.month.3") == "Mär"
