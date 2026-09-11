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
        "switcher.club_label": "Club:",
        "switcher.course_label": "Course:",
        "app.no_clubs": "No clubs saved yet — copy clubs/club.example.yaml first.",
        "app.no_club_id": "clubs/{slug}.yaml has no club_id set.",
        "app.course_fetch_failed": "Couldn't load this club's course list: {error}",
        "app.no_tee_sheet": "Club {club_id} doesn't publish an online tee sheet.",
        "picker.club_search_placeholder": "Search clubs, type a club id, or paste your club's booking link…",
        "picker.favorites_hint": "Your favorites — enter to open. Type to search all {count} clubs — 'f' favorites, 'r' refreshes the list.",
        "picker.no_favorites_hint": "No favorites yet. Type a club name to search, or a club id (e.g. 0000001). Don't know your club's id? Paste its pc caddie booking link instead — from your club's own website or a booking confirmation.",
        "picker.no_favorites_hint_with_seed": "No favorites yet. Search {count} clubs by name below, or type/paste a club id — press 'r' after logging in for the latest list.",
        "picker.match_count": "{count} matches — enter to open",
        "picker.open_by_id": "open this club",
        "picker.enter_to_open": "Press enter to open this club.",
        "picker.no_directory_yet": "No club list downloaded yet — press 'r' to fetch it, or paste/type a club id.",
        "picker.directory_needs_login": "Fetching the club list needs a login — enter your credentials.",
        "picker.directory_needs_a_club": "Your login is saved — type or paste your club's id above (a pc caddie booking link works too), then press 'r' again to check the full directory.",
        "picker.directory_refreshed": "Club list updated — {count} clubs.",
        "picker.favorited": "Saved {club_id} to favorites.",
        "picker.unfavorited": "Removed {club_id} from favorites.",
        "table.time": "Time",
        "table.occupancy": "Occupancy",
        "table.players": "Players",
        "table.no_data": "no data yet",
        "table.press_refresh": "press 'r' to scrape",
        "table.not_bookable": "not bookable",
        "table.day": "Day",
        "table.temperature": "Temperature",
        "table.precipitation": "Precipitation",
        "table.wind": "Wind",
        "table.events": "Events",
        "table.heat": "Heat 08–20",
        "table.pick": "Pick",
        "daylight.summary": "☀ Sunrise {sunrise} · Sunset {sunset}",
        "search.title": "Search this week",
        "search.button": "Search",
        "search.no_matches": "No matches for these criteria.",
        "search.table.date": "Date",
        "search.table.course": "Course",
        "search.table.notes": "Notes",
        "weekday.0": "Mon",
        "weekday.1": "Tue",
        "weekday.2": "Wed",
        "weekday.3": "Thu",
        "weekday.4": "Fri",
        "weekday.5": "Sat",
        "weekday.6": "Sun",
        "overview.today_suffix": "(today)",
        "overview.not_open_yet": "not open for booking yet",
        "overview.rain_all_day": "rain all day",
        "overview.no_dry_picks": "no dry picks",
        "overview.no_daylight_picks": "too dark to finish",
        "overview.no_playable_picks": "nothing playable",
        "overview.booked": "booked",
        "overview.no_matches": "No matches this week.",
        "overview.picks_title": "This week's picks",
        "legend.recommended": "recommended",
        "legend.rain": "rain",
        "legend.wind": "wind",
        "legend.event": "event/closure",
        "legend.too_late": "too late for sunset",
        "legend.changed": "changed since booked",
        "status.refreshed": "Refreshed.",
        "status.refresh_failed": "Refresh failed: {error}",
        "status.refreshing": "Refreshing…",
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
        "settings.group.availability": "Availability",
        "settings.group.weather": "Weather",
        "settings.group.priorities": "Priorities",
        "settings.group.ai": "AI ranking",
        "settings.group.timing": "Timing & scraping",
        "binding.refresh": "Refresh",
        "binding.confirm": "Confirm tee time",
        "binding.next_day": "Next day",
        "binding.prev_day": "Previous day",
        "binding.dismiss_banners": "Dismiss banners",
        "binding.switch": "Switch club/course",
        "binding.cancel": "Back",
        "binding.theme": "Theme",
        "binding.quit": "Quit",
        "binding.language": "Language",
        "binding.commands": "Commands",
        "binding.open": "Open",
        "binding.favorite": "Favorite",
        "binding.refresh_directory": "Refresh list",
        "binding.login": "Login",
        "binding.overview": "Overview",
        "binding.settings": "Settings",
        "binding.search": "Search",
        "command.language_title": "Language: switch to {other}",
        "command.language_description": "Currently {current} — switch the UI language",
        "settings.field.min_open_spots": "Min open spots (party size)",
        "settings.field.weekday_after": "Weekday window — after",
        "settings.field.weekday_before": "Weekday window — before",
        "settings.field.weekend_after": "Weekend window — after",
        "settings.field.weekend_before": "Weekend window — before",
        "settings.field.buffer_before_minutes": "Buffer to the group ahead (minutes)",
        "settings.field.buffer_after_minutes": "Buffer to the group behind (minutes)",
        "settings.field.avoid_rain": "Avoid rain",
        "settings.field.avoid_rain_probability": "  ...above rain probability (%)",
        "settings.field.avoid_rain_mm": "  ...above rain amount (mm)",
        "settings.field.avoid_wind": "Avoid wind",
        "settings.field.avoid_wind_kph": "  ...above wind speed (kph)",
        "settings.field.avoid_temp_below": "Avoid temperature below (°C)",
        "settings.field.avoid_temp_above": "Avoid temperature above (°C)",
        "settings.field.prioritize_friends": "Prioritize friends' slots",
        "settings.field.avoid_predicted_crowd": "Avoid predicted crowds",
        "settings.field.ai_assist_enabled": "AI-ranked recommendations",
        "settings.field.daylight_buffer": "Daylight safety buffer (minutes)",
        "settings.field.round_duration_nine": "Round duration — 9 holes (minutes)",
        "settings.field.round_duration_eighteen": "Round duration — 18 holes (minutes)",
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
        "club_picker.fetching": "Fetching pc caddie's club directory…",
        "club_picker.fetch_failed": "Couldn't fetch the club directory: {error}",
        "club_picker.no_matches": "No matches",
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
        "credentials.verifying": "Saved — checking your login…",
        "credentials.login_verified": "Saved and login verified — you're all set.",
        "credentials.login_failed": "Saved, but the login was rejected — double check your username/password.",
        "credentials.saved_unverified": "Saved, but couldn't verify the login right now ({error}) — it'll be checked again later.",
        "binding.heatmap": "Heatmap",
        "heatmap.title": "Crowd heatmap — {course}",
        "heatmap.section.by_weekday": "By weekday",
        "heatmap.section.special_days": "Special days (compared separately)",
        "heatmap.column.weekday": "Weekday",
        "heatmap.column.day_type": "Day type",
        "heatmap.column.hours_seen": "Hours w/ data",
        "heatmap.column.hours_ready": "Hours ready",
        "heatmap.column.samples": "Samples",
        "heatmap.column.status": "Status",
        "heatmap.weekday.sunday": "Sunday",
        "heatmap.weekday.monday": "Monday",
        "heatmap.weekday.tuesday": "Tuesday",
        "heatmap.weekday.wednesday": "Wednesday",
        "heatmap.weekday.thursday": "Thursday",
        "heatmap.weekday.friday": "Friday",
        "heatmap.weekday.saturday": "Saturday",
        "heatmap.day_type.tournament": "Tournament",
        "heatmap.day_type.public_holiday": "Public holiday",
        "heatmap.day_type.vacation": "Vacation",
        "heatmap.status.no_data": "No data yet",
        "heatmap.status.collecting": "Collecting (0/{seen} hours ready)",
        "heatmap.status.partial": "{ready}/{seen} hours ready",
        "heatmap.status.ready": "Ready ({ready}/{seen} hours)",
        "heatmap.threshold_note": "An hour counts as \"ready\" once it has at least {min} scrapes to average.",
        "heatmap.preview_title": "Hourly pattern (ready weekdays/day types only)",
        "heatmap.no_preview": "No weekday or day type has enough data for a preview yet.",
    },
    "de": {
        "picker.club_title": "Welcher Club?",
        "picker.course_title": "Welcher Platz?",
        "switcher.club_label": "Club:",
        "switcher.course_label": "Platz:",
        "app.no_clubs": "Noch kein Club gespeichert — zuerst clubs/club.example.yaml kopieren.",
        "app.no_club_id": "clubs/{slug}.yaml hat keine club_id.",
        "app.course_fetch_failed": "Kursliste des Clubs konnte nicht geladen werden: {error}",
        "app.no_tee_sheet": "Club {club_id} bietet keinen Online-Startzeitenplan an.",
        "picker.club_search_placeholder": "Clubs suchen, Club-ID eingeben oder Buchungslink einfügen…",
        "picker.favorites_hint": "Deine Favoriten — Enter zum Öffnen. Tippen, um alle {count} Clubs zu durchsuchen — 'f' favorisiert, 'r' aktualisiert die Liste.",
        "picker.no_favorites_hint": "Noch keine Favoriten. Clubnamen eingeben, um zu suchen, oder eine Club-ID (z. B. 0000001). Club-ID unbekannt? Stattdessen den pc caddie-Buchungslink deines Clubs einfügen — von der eigenen Website oder einer Buchungsbestätigung.",
        "picker.no_favorites_hint_with_seed": "Noch keine Favoriten. Unten nach Namen suchen ({count} Clubs), oder eine Club-ID eingeben/einfügen — nach dem Login mit 'r' die neuesten Daten abrufen.",
        "picker.match_count": "{count} Treffer — Enter zum Öffnen",
        "picker.open_by_id": "diesen Club öffnen",
        "picker.enter_to_open": "Mit Enter diesen Club öffnen.",
        "picker.no_directory_yet": "Noch keine Clubliste geladen — mit 'r' abrufen oder Club-ID einfügen/eingeben.",
        "picker.directory_needs_login": "Für die Clubliste ist ein Login nötig — bitte Zugangsdaten eingeben.",
        "picker.directory_needs_a_club": "Dein Login ist gespeichert — gib oben die Club-ID ein oder füge den Buchungslink deines Clubs ein, und drücke dann erneut 'r', um das ganze Verzeichnis zu prüfen.",
        "picker.directory_refreshed": "Clubliste aktualisiert — {count} Clubs.",
        "picker.favorited": "{club_id} zu den Favoriten hinzugefügt.",
        "picker.unfavorited": "{club_id} aus den Favoriten entfernt.",
        "table.time": "Zeit",
        "table.occupancy": "Belegung",
        "table.players": "Spieler",
        "table.no_data": "noch keine Daten",
        "table.press_refresh": "„r“ drücken zum Abrufen",
        "table.not_bookable": "nicht buchbar",
        "table.day": "Tag",
        "table.temperature": "Temperatur",
        "table.precipitation": "Niederschlag",
        "table.wind": "Wind",
        "table.events": "Termine",
        "table.heat": "Auslastung 08–20",
        "table.pick": "Empfehlung",
        "daylight.summary": "☀ Sonnenaufgang {sunrise} · Sonnenuntergang {sunset}",
        "search.title": "Diese Woche suchen",
        "search.button": "Suchen",
        "search.no_matches": "Keine Treffer für diese Kriterien.",
        "search.table.date": "Datum",
        "search.table.course": "Platz",
        "search.table.notes": "Hinweise",
        "weekday.0": "Mo",
        "weekday.1": "Di",
        "weekday.2": "Mi",
        "weekday.3": "Do",
        "weekday.4": "Fr",
        "weekday.5": "Sa",
        "weekday.6": "So",
        "overview.today_suffix": "(heute)",
        "overview.not_open_yet": "noch nicht buchbar",
        "overview.rain_all_day": "Regen den ganzen Tag",
        "overview.no_dry_picks": "keine trockenen Termine",
        "overview.no_daylight_picks": "zu dunkel zum Fertigspielen",
        "overview.no_playable_picks": "nichts Spielbares",
        "overview.booked": "gebucht",
        "overview.no_matches": "Keine Treffer diese Woche.",
        "overview.picks_title": "Empfehlungen dieser Woche",
        "legend.recommended": "empfohlen",
        "legend.rain": "Regen",
        "legend.wind": "Wind",
        "legend.event": "Termin/Sperrung",
        "legend.too_late": "zu spät für Sonnenuntergang",
        "legend.changed": "seit Buchung geändert",
        "status.refreshed": "Aktualisiert.",
        "status.refresh_failed": "Aktualisierung fehlgeschlagen: {error}",
        "status.refreshing": "Wird aktualisiert…",
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
        "settings.group.availability": "Verfügbarkeit",
        "settings.group.weather": "Wetter",
        "settings.group.priorities": "Prioritäten",
        "settings.group.ai": "KI-Bewertung",
        "settings.group.timing": "Timing & Abruf",
        "binding.refresh": "Aktualisieren",
        "binding.confirm": "Tee-Zeit bestätigen",
        "binding.next_day": "Nächster Tag",
        "binding.prev_day": "Vorheriger Tag",
        "binding.dismiss_banners": "Hinweise ausblenden",
        "binding.switch": "Club/Platz wechseln",
        "binding.cancel": "Zurück",
        "binding.theme": "Design",
        "binding.quit": "Beenden",
        "binding.open": "Öffnen",
        "binding.favorite": "Favorit",
        "binding.refresh_directory": "Liste aktualisieren",
        "binding.login": "Login",
        "binding.overview": "Übersicht",
        "binding.settings": "Einstellungen",
        "binding.search": "Suchen",
        "binding.language": "Sprache",
        "binding.commands": "Befehle",
        "command.language_title": "Sprache: zu {other} wechseln",
        "command.language_description": "Aktuell {current} — Sprache der Oberfläche wechseln",
        "settings.field.min_open_spots": "Min. freie Plätze (Gruppengröße)",
        "settings.field.weekday_after": "Wochentags-Fenster — ab",
        "settings.field.weekday_before": "Wochentags-Fenster — bis",
        "settings.field.weekend_after": "Wochenend-Fenster — ab",
        "settings.field.weekend_before": "Wochenend-Fenster — bis",
        "settings.field.buffer_before_minutes": "Abstand zur Gruppe davor (Minuten)",
        "settings.field.buffer_after_minutes": "Abstand zur Gruppe danach (Minuten)",
        "settings.field.avoid_rain": "Regen vermeiden",
        "settings.field.avoid_rain_probability": "  ...ab Regenwahrscheinlichkeit (%)",
        "settings.field.avoid_rain_mm": "  ...ab Regenmenge (mm)",
        "settings.field.avoid_wind": "Wind vermeiden",
        "settings.field.avoid_wind_kph": "  ...ab Windgeschwindigkeit (km/h)",
        "settings.field.avoid_temp_below": "Temperatur unter (°C) vermeiden",
        "settings.field.avoid_temp_above": "Temperatur über (°C) vermeiden",
        "settings.field.prioritize_friends": "Zeiten mit Freunden bevorzugen",
        "settings.field.avoid_predicted_crowd": "Vorhergesagten Andrang vermeiden",
        "settings.field.ai_assist_enabled": "KI-bewertete Empfehlungen",
        "settings.field.daylight_buffer": "Sicherheitspuffer Tageslicht (Minuten)",
        "settings.field.round_duration_nine": "Rundendauer — 9 Loch (Minuten)",
        "settings.field.round_duration_eighteen": "Rundendauer — 18 Loch (Minuten)",
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
        "club_picker.fetching": "Club-Verzeichnis von pc caddie wird abgerufen…",
        "club_picker.fetch_failed": "Club-Verzeichnis konnte nicht abgerufen werden: {error}",
        "club_picker.no_matches": "Keine Treffer",
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
        "credentials.verifying": "Gespeichert — Login wird geprüft…",
        "credentials.login_verified": "Gespeichert und Login bestätigt — alles bereit.",
        "credentials.login_failed": "Gespeichert, aber der Login wurde abgelehnt — bitte Benutzername/Passwort prüfen.",
        "credentials.saved_unverified": "Gespeichert, aber Login konnte gerade nicht geprüft werden ({error}) — wird später erneut geprüft.",
        "binding.heatmap": "Auslastung",
        "heatmap.title": "Auslastungs-Heatmap — {course}",
        "heatmap.section.by_weekday": "Nach Wochentag",
        "heatmap.section.special_days": "Besondere Tage (separat verglichen)",
        "heatmap.column.weekday": "Wochentag",
        "heatmap.column.day_type": "Tagestyp",
        "heatmap.column.hours_seen": "Std. m. Daten",
        "heatmap.column.hours_ready": "Std. bereit",
        "heatmap.column.samples": "Messwerte",
        "heatmap.column.status": "Status",
        "heatmap.weekday.sunday": "Sonntag",
        "heatmap.weekday.monday": "Montag",
        "heatmap.weekday.tuesday": "Dienstag",
        "heatmap.weekday.wednesday": "Mittwoch",
        "heatmap.weekday.thursday": "Donnerstag",
        "heatmap.weekday.friday": "Freitag",
        "heatmap.weekday.saturday": "Samstag",
        "heatmap.day_type.tournament": "Turnier",
        "heatmap.day_type.public_holiday": "Feiertag",
        "heatmap.day_type.vacation": "Ferien",
        "heatmap.status.no_data": "Noch keine Daten",
        "heatmap.status.collecting": "Sammelt Daten (0/{seen} Std. bereit)",
        "heatmap.status.partial": "{ready}/{seen} Std. bereit",
        "heatmap.status.ready": "Bereit ({ready}/{seen} Std.)",
        "heatmap.threshold_note": "Eine Stunde gilt als „bereit“, sobald mindestens {min} Messwerte vorliegen.",
        "heatmap.preview_title": "Stündliches Muster (nur bereite Wochentage/Tagestypen)",
        "heatmap.no_preview": "Noch kein Wochentag und kein Tagestyp hat genug Daten für eine Vorschau.",
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
