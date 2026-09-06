"""Two-language (English/German) UI text lookup for the TUI, added 2026-09-06
("need to make sure the TUI is at least bilingual, since it will be used in
Germany"). Deliberately not a general-purpose i18n framework — two languages, one
flat key -> template-string dict per language, plain `str.format()` with named
placeholders, and a single process-wide "current language" (module-level state, not
threaded through every Screen/Widget's constructor) since a personal two-language CLI
tool genuinely doesn't need more machinery than that.

Only covers this app's own UI chrome — labels, buttons, table headers, status/error
messages generated interactively within the TUI. Deliberately does **not** cover
`booking_watch.py`'s banner messages: those are generated once, at scrape time, by a
separate headless process (`scrape_once.py`) and stored as already-rendered plain
text in `storage.py`'s `booking_changes` table. Localizing them properly means storing
structured (kind, params) instead of prose and re-rendering at display time in
whatever language is current *then* — a real schema change, not something to fold in
quietly here. Documented as a known, deliberate scope boundary: those messages stay
English-only for now, not a gap that was missed.

Same global-preference pattern as `theme.py` (and sharing its underlying config file
via `user_config.py`): an env var beats a saved config file beats a default. Default:
German if the system's own locale looks German (`LC_ALL`/`LANG`/`LANGUAGE` starts with
"de"), English otherwise — this club's actual portal is itself German-language, so a
German-speaking user shouldn't have to know to ask for it first.
"""

import os
from pathlib import Path

from . import user_config

ENV_VAR = "TEETIME_MONITOR_LANG"
CONFIG_FILE = user_config.CONFIG_FILE  # same file as theme.py, a different KEY=

SUPPORTED_LANGUAGES = ("en", "de")
LANGUAGE_LABELS = {"en": "English", "de": "Deutsch"}

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "picker.club_title": "Which club?",
        "picker.course_title": "Which course?",
        "app.no_clubs": "No clubs saved yet — copy clubs/club.example.yaml first.",
        "app.no_club_id": "clubs/{slug}.yaml has no club_id set.",
        "table.time": "Time",
        "table.occupancy": "Occupancy",
        "table.players": "Players",
        "table.no_data": "no data yet",
        "table.press_refresh": "press 'r' to scrape",
        "status.refreshed": "Refreshed.",
        "status.refresh_failed": "Refresh failed: {error}",
        "confirm.title": "Confirm your tee time for {date}",
        "confirm.time_label": "Time (HH:MM):",
        "confirm.holes_label": "Holes (9 or 18, optional):",
        "confirm.enter_time": "Enter a time first.",
        "confirm.holes_number": "Holes must be a number.",
        "button.save": "Save",
        "button.cancel": "Cancel",
        "button.quit": "Quit",
        "settings.saved": "Saved.",
        "settings.not_saved": "Not saved — {error}",
        "binding.refresh": "Refresh",
        "binding.confirm": "Confirm tee time",
        "binding.next_day": "Next day",
        "binding.prev_day": "Previous day",
        "binding.dismiss_banners": "Dismiss banners",
        "binding.theme": "Theme",
        "binding.quit": "Quit",
        "binding.language": "Language",
        "binding.commands": "Commands",
        "command.language_title": "Language: switch to {other}",
        "command.language_description": "Currently {current} — switch the UI language",
        "settings.field.min_open_spots": "Min open spots (party size)",
        "settings.field.weekday_after": "Weekday window — after",
        "settings.field.weekday_before": "Weekday window — before",
        "settings.field.weekend_after": "Weekend window — after",
        "settings.field.weekend_before": "Weekend window — before",
        "settings.field.buffer_minutes": "Buffer from other flights (minutes)",
        "settings.field.avoid_rain": "Avoid rain",
        "settings.field.avoid_rain_probability": "  ...above rain probability (%)",
        "settings.field.avoid_rain_mm": "  ...above rain amount (mm)",
        "settings.field.avoid_wind": "Avoid wind",
        "settings.field.avoid_wind_kph": "  ...above wind speed (kph)",
        "settings.field.avoid_temp_below": "Avoid temperature below (°C)",
        "settings.field.avoid_temp_above": "Avoid temperature above (°C)",
        "settings.field.prioritize_friends": "Prioritize friends' slots",
        "settings.field.avoid_predicted_crowd": "Avoid predicted crowds",
        "settings.field.daylight_buffer": "Daylight safety buffer (minutes)",
        "settings.field.scrape_interval_normal": "Scrape interval — normal (minutes)",
        "settings.field.scrape_interval_booked": "Scrape interval — once booked (minutes)",
        "watch.party_grew.singular": "{count} more player joined your {time} tee time since you booked",
        "watch.party_grew.plural": "{count} more players joined your {time} tee time since you booked",
        "watch.buffer_shrunk": "The {neighbor_time} slot near your {time} tee time is no longer clear",
        "watch.neighbor_crowded": "The {neighbor_time} flight near your {time} tee time picked up more players",
        "watch.weather_worsened": "The forecast for your {time} tee time got worse ({reasons})",
        "watch.reason.rain_chance": "rain chance",
        "watch.reason.rain_amount": "rain amount",
        "watch.reason.wind": "wind",
        "club_picker.title": "Add a club",
        "club_picker.search_placeholder": "Search club name…",
        "club_picker.slug_placeholder": "Save as (filename)…",
        "club_picker.fetching": "Fetching pc caddie's club directory…",
        "club_picker.fetch_failed": "Couldn't fetch the club directory: {error}",
        "club_picker.no_credentials": "No PCC_USER/PCC_PASS configured yet — set them in .env first.",
        "club_picker.match_count": "{count} matches",
        "club_picker.no_matches": "No matches",
        "club_picker.select_prompt": "Type to search, then pick a club below",
        "club_picker.slug_required": "Enter a filename first.",
        "club_picker.slug_taken": "clubs/{slug}.yaml already exists — pick another name.",
        "club_picker.pick_first": "Pick a club from the list first.",
        "club_picker.saved": (
            "Saved clubs/{slug}.yaml — edit it to add location, calendar, and preferences "
            "(see club.example.yaml)."
        ),
        "credentials.title": "pc caddie login",
        "credentials.intro": (
            "One pc caddie login covers every saved club. Stored in .env, on this machine only."
        ),
        "credentials.username_label": "Username / email",
        "credentials.password_label": "Password",
        "credentials.password_hint_unset": "(not set yet)",
        "credentials.password_hint_set": "(already set — leave blank to keep it)",
        "credentials.username_required": "Enter a username first.",
        "credentials.password_required": "Enter a password first.",
        "credentials.saved": "Saved to .env.",
    },
    "de": {
        "picker.club_title": "Welcher Club?",
        "picker.course_title": "Welcher Platz?",
        "app.no_clubs": "Noch kein Club gespeichert — zuerst clubs/club.example.yaml kopieren.",
        "app.no_club_id": "clubs/{slug}.yaml hat keine club_id.",
        "table.time": "Zeit",
        "table.occupancy": "Belegung",
        "table.players": "Spieler",
        "table.no_data": "noch keine Daten",
        "table.press_refresh": "„r“ drücken zum Abrufen",
        "status.refreshed": "Aktualisiert.",
        "status.refresh_failed": "Aktualisierung fehlgeschlagen: {error}",
        "confirm.title": "Tee-Zeit bestätigen für {date}",
        "confirm.time_label": "Uhrzeit (HH:MM):",
        "confirm.holes_label": "Löcher (9 oder 18, optional):",
        "confirm.enter_time": "Bitte zuerst eine Uhrzeit eingeben.",
        "confirm.holes_number": "Löcher muss eine Zahl sein.",
        "button.save": "Speichern",
        "button.cancel": "Abbrechen",
        "button.quit": "Beenden",
        "settings.saved": "Gespeichert.",
        "settings.not_saved": "Nicht gespeichert — {error}",
        "binding.refresh": "Aktualisieren",
        "binding.confirm": "Tee-Zeit bestätigen",
        "binding.next_day": "Nächster Tag",
        "binding.prev_day": "Vorheriger Tag",
        "binding.dismiss_banners": "Hinweise ausblenden",
        "binding.theme": "Design",
        "binding.quit": "Beenden",
        "binding.language": "Sprache",
        "binding.commands": "Befehle",
        "command.language_title": "Sprache: zu {other} wechseln",
        "command.language_description": "Aktuell {current} — Sprache der Oberfläche wechseln",
        "settings.field.min_open_spots": "Min. freie Plätze (Gruppengröße)",
        "settings.field.weekday_after": "Wochentags-Fenster — ab",
        "settings.field.weekday_before": "Wochentags-Fenster — bis",
        "settings.field.weekend_after": "Wochenend-Fenster — ab",
        "settings.field.weekend_before": "Wochenend-Fenster — bis",
        "settings.field.buffer_minutes": "Abstand zu anderen Flights (Minuten)",
        "settings.field.avoid_rain": "Regen vermeiden",
        "settings.field.avoid_rain_probability": "  ...ab Regenwahrscheinlichkeit (%)",
        "settings.field.avoid_rain_mm": "  ...ab Regenmenge (mm)",
        "settings.field.avoid_wind": "Wind vermeiden",
        "settings.field.avoid_wind_kph": "  ...ab Windgeschwindigkeit (km/h)",
        "settings.field.avoid_temp_below": "Temperatur unter (°C) vermeiden",
        "settings.field.avoid_temp_above": "Temperatur über (°C) vermeiden",
        "settings.field.prioritize_friends": "Zeiten mit Freunden bevorzugen",
        "settings.field.avoid_predicted_crowd": "Vorhergesagten Andrang vermeiden",
        "settings.field.daylight_buffer": "Sicherheitspuffer Tageslicht (Minuten)",
        "settings.field.scrape_interval_normal": "Abrufintervall — normal (Minuten)",
        "settings.field.scrape_interval_booked": "Abrufintervall — nach Buchung (Minuten)",
        "watch.party_grew.singular": "{count} weiterer Spieler ist Ihrer Tee-Zeit um {time} Uhr beigetreten, seit Sie gebucht haben",
        "watch.party_grew.plural": "{count} weitere Spieler sind Ihrer Tee-Zeit um {time} Uhr beigetreten, seit Sie gebucht haben",
        "watch.buffer_shrunk": "Die Zeit {neighbor_time} in der Nähe Ihrer Tee-Zeit um {time} Uhr ist nicht mehr frei",
        "watch.neighbor_crowded": "Der Flight um {neighbor_time} in der Nähe Ihrer Tee-Zeit um {time} Uhr hat weitere Spieler bekommen",
        "watch.weather_worsened": "Die Vorhersage für Ihre Tee-Zeit um {time} Uhr hat sich verschlechtert ({reasons})",
        "watch.reason.rain_chance": "Regenwahrscheinlichkeit",
        "watch.reason.rain_amount": "Regenmenge",
        "watch.reason.wind": "Wind",
        "club_picker.title": "Club hinzufügen",
        "club_picker.search_placeholder": "Clubnamen suchen…",
        "club_picker.slug_placeholder": "Speichern als (Dateiname)…",
        "club_picker.fetching": "Club-Verzeichnis von pc caddie wird abgerufen…",
        "club_picker.fetch_failed": "Club-Verzeichnis konnte nicht abgerufen werden: {error}",
        "club_picker.no_credentials": "Noch kein PCC_USER/PCC_PASS konfiguriert — bitte zuerst in .env eintragen.",
        "club_picker.match_count": "{count} Treffer",
        "club_picker.no_matches": "Keine Treffer",
        "club_picker.select_prompt": "Suchbegriff eingeben, dann unten einen Club auswählen",
        "club_picker.slug_required": "Bitte zuerst einen Dateinamen eingeben.",
        "club_picker.slug_taken": "clubs/{slug}.yaml existiert bereits — bitte einen anderen Namen wählen.",
        "club_picker.pick_first": "Bitte zuerst einen Club aus der Liste auswählen.",
        "club_picker.saved": (
            "clubs/{slug}.yaml gespeichert — Standort, Kalender und Einstellungen bitte "
            "ergänzen (siehe club.example.yaml)."
        ),
        "credentials.title": "pc caddie Anmeldung",
        "credentials.intro": (
            "Eine pc caddie Anmeldung gilt für alle gespeicherten Clubs. Wird nur lokal in .env gespeichert."
        ),
        "credentials.username_label": "Benutzername / E-Mail",
        "credentials.password_label": "Passwort",
        "credentials.password_hint_unset": "(noch nicht gesetzt)",
        "credentials.password_hint_set": "(bereits gesetzt — leer lassen, um es zu behalten)",
        "credentials.username_required": "Bitte zuerst einen Benutzernamen eingeben.",
        "credentials.password_required": "Bitte zuerst ein Passwort eingeben.",
        "credentials.saved": "In .env gespeichert.",
    },
}

_current_language: str | None = None


def t(key: str, **kwargs: object) -> str:
    """Look up `key` in the current language. Falls back to English if the current
    language is somehow missing it (shouldn't happen — both dicts are kept in sync —
    but a missing translation shouldn't crash the app), then to the raw key itself as
    a last resort so a typo shows up as visibly wrong text rather than a crash."""
    lang = get_language()
    template = _STRINGS.get(lang, {}).get(key) or _STRINGS["en"].get(key) or key
    return template.format(**kwargs) if kwargs else template


def get_language() -> str:
    """The current language, resolving it (env var > saved config > system-locale
    default) the first time this is called in a process, then caching it — call
    set_language() to change it afterward."""
    global _current_language
    if _current_language is None:
        _current_language = resolve_language_name()
    return _current_language


def set_language(lang: str) -> None:
    """Change the current language in memory only — pair with save_language() to
    persist it. Ignored if `lang` isn't one of SUPPORTED_LANGUAGES."""
    global _current_language
    if lang in SUPPORTED_LANGUAGES:
        _current_language = lang


def other_language(lang: str) -> str:
    """The other supported language — used for the "switch to X" command label,
    since there are only two."""
    index = SUPPORTED_LANGUAGES.index(lang) if lang in SUPPORTED_LANGUAGES else 0
    return SUPPORTED_LANGUAGES[1 - index]


def save_language(lang: str, config_file: Path | None = None) -> None:
    """Persist `lang` to the config file. See theme.py's load_saved_theme() for why
    `config_file` isn't a plain `= CONFIG_FILE` default."""
    config_file = config_file if config_file is not None else CONFIG_FILE
    user_config.save_value("LANG", lang, config_file)


def load_saved_language(config_file: Path | None = None) -> str | None:
    """The persisted LANG= value, or None if never saved or not a supported language."""
    config_file = config_file if config_file is not None else CONFIG_FILE
    saved = user_config.load_value("LANG", config_file)
    return saved if saved in SUPPORTED_LANGUAGES else None


def _default_language(environ: dict) -> str:
    for var in ("LC_ALL", "LANG", "LANGUAGE"):
        value = environ.get(var, "")
        if value.lower().startswith("de"):
            return "de"
    return "en"


def resolve_language_name(env: dict | None = None, config_file: Path | None = None) -> str:
    """Env var > saved config file > system-locale-based default — the same shape as
    theme.py's resolve_theme_name(), except the default itself is locale-aware rather
    than a fixed constant (see module docstring for why)."""
    environ = os.environ if env is None else env
    env_value = environ.get(ENV_VAR)
    if env_value in SUPPORTED_LANGUAGES:
        return env_value
    saved = load_saved_language(config_file)
    if saved is not None:
        return saved
    return _default_language(environ)


def apply_language(config_file: Path | None = None) -> str:
    """Resolve and set the current language for this process, but only if nothing
    has set it yet (mirrors get_language()'s own lazy-resolve-once behavior) — calling
    this a second time, or after something already called set_language() explicitly,
    must not silently clobber that choice by re-reading disk/env state. Called once at
    TeetimeApp/SettingsScreen startup — returns the current language either way, for a
    caller that wants to display or persist it."""
    global _current_language
    if _current_language is None:
        _current_language = resolve_language_name(config_file=config_file)
    return _current_language


# kind -> the i18n key(s) needed to re-render a booking_watch.BookingChange from its
# `kind` + `params` (see that module's docstring for why `message` alone, rendered
# once at scrape time, can't be localized after the fact).
_PARTY_GREW = "party_grew"
_BUFFER_SHRUNK = "buffer_shrunk"
_NEIGHBOR_CROWDED = "neighbor_crowded"
_WEATHER_WORSENED = "weather_worsened"


def render_booking_change(kind: str, params: dict) -> str | None:
    """Re-render one booking_watch.BookingChange in the current language. Returns
    None for a `kind` this doesn't recognize, so a caller (tui.py) can fall back to
    the change's own stored English `message` rather than showing nothing."""
    if kind == _PARTY_GREW:
        count = params.get("count", 1)
        key = "watch.party_grew.singular" if count == 1 else "watch.party_grew.plural"
        return t(key, count=count, time=params.get("time", ""))
    if kind == _BUFFER_SHRUNK:
        return t("watch.buffer_shrunk", time=params.get("time", ""), neighbor_time=params.get("neighbor_time", ""))
    if kind == _NEIGHBOR_CROWDED:
        return t(
            "watch.neighbor_crowded", time=params.get("time", ""), neighbor_time=params.get("neighbor_time", "")
        )
    if kind == _WEATHER_WORSENED:
        reason_keys = params.get("reason_keys", [])
        reasons = ", ".join(t(f"watch.reason.{key}") for key in reason_keys)
        return t("watch.weather_worsened", time=params.get("time", ""), reasons=reasons)
    return None
