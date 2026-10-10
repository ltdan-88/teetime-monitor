"""Preferences, Settings, login and AI key for the web UI (2026-10-10).

The forms are generated from the very list the terminal app's screens are built from
(`settings_screen.FIELDS`), and saved through the very same pure functions
(`config_to_widget_values()` / `widget_values_to_config()`), so a field added there shows up here
and a value means the same thing in every front end. Labels come from `i18n.py`, so they follow
the app's language. The Textual import behind `settings_screen` is loaded on first use, not at
server start.

Two screens, as everywhere: **Preferences** (what makes a tee time good for you: availability,
weather, pace, priorities) and **Settings** (how the app runs: account, display, scraping, AI).
Fields that are not a plain value get their own forms here: the login, the AI key and the club
list. The colour theme is a terminal-app notion; the browser follows the system.
"""

import os
import threading
from typing import Any

from .. import ai_assist, club_config, env_file, global_preferences, i18n, pipeline, units, user_config
from ..ai_login_cli import save_ai_key
from ..login_cli import save_login
from . import data

THEME_PATH = ("__theme__",)
# Saving reads the preferences file, changes a field and writes it back: two quick changes (a click on a
# switch, then on a menu) arrive as two requests at once, and without this the later write could carry the
# earlier value of the other field.
_SAVE_LOCK = threading.Lock()
DISPLAY_ONLY = {"field-units", "field-show_handicaps", "field-__language__"}


def _screen():
    from .. import settings_screen  # noqa: PLC0415 -- pulls in Textual; only needed for these forms

    return settings_screen


def _fields_for(groups: list[str]):
    screen = _screen()
    return [f for f in screen.FIELDS if f.group_key in groups and f.path != THEME_PATH and f.kind != "action"]


def _choices(field) -> list[dict] | None:
    if field.path == ("units",):
        return [
            {"label": i18n.t("settings.units.metric"), "value": units.METRIC},
            {"label": i18n.t("settings.units.imperial"), "value": units.IMPERIAL},
        ]
    if field.path == ("preferences", "hcp_preference"):
        return [
            {"label": i18n.t("settings.hcp_preference.off"), "value": "off"},
            {"label": i18n.t("settings.hcp_preference.similar"), "value": "similar"},
            {"label": i18n.t("settings.hcp_preference.better"), "value": "better"},
        ]
    if field.choices is not None:
        return [{"label": label, "value": value} for label, value in field.choices]
    return None


def schema(kind: str, club_id: str | None) -> dict:
    """The form for `kind` ("preferences" or "settings"): groups of fields with their current
    values, ready to render."""
    screen = _screen()
    group_order = screen.PREFERENCE_GROUP_ORDER if kind == "preferences" else screen.SETTING_GROUP_ORDER
    fields = _fields_for(group_order)
    values = screen.config_to_widget_values(global_preferences.load_preferences(), [f for f in fields if f.kind != "display"])
    groups = []
    for group_key in group_order:
        entries = []
        for field in (f for f in fields if f.group_key == group_key):
            entry: dict[str, Any] = {
                "id": screen._field_id(field),
                "label": i18n.t(field.label_key),
                "kind": field.kind,
            }
            if field.kind == "display":
                entry["value"] = field.getter(club_id)
            else:
                entry["value"] = values[entry["id"]]
                choices = _choices(field)
                if choices is not None:
                    entry["choices"] = choices
                    if entry["value"] not in {c["value"] for c in choices}:  # a hand-edited value stays selectable
                        entry["choices"] = [{"label": str(entry["value"]), "value": entry["value"]}, *choices]
            entries.append(entry)
        if entries:
            groups.append({"key": group_key, "label": i18n.t(group_key), "fields": entries})
    return {"groups": groups}


def save(kind: str, submitted: dict[str, Any]) -> dict:
    """Apply `submitted` ({field id: value}) on top of what is saved. A field that is not sent
    keeps its value. Returns `{"ok": True}` or `{"error": text}` (a number that is not one)."""
    with _SAVE_LOCK:
        return _save(kind, submitted)


def _save(kind: str, submitted: dict[str, Any]) -> dict:
    screen = _screen()
    group_order = screen.PREFERENCE_GROUP_ORDER if kind == "preferences" else screen.SETTING_GROUP_ORDER
    fields = [f for f in _fields_for(group_order) if f.kind != "display"]
    base = global_preferences.load_preferences()
    widget_values = screen.config_to_widget_values(base, fields)
    known = {screen._field_id(f) for f in fields}
    for field_id, value in submitted.items():
        if field_id in known:
            widget_values[field_id] = value
    try:
        updated = screen.widget_values_to_config(base, widget_values, fields)
    except (ValueError, TypeError) as exc:
        return {"error": i18n.t("settings.not_saved", error=exc)}
    for field in fields:
        if field.setter is None:
            continue
        new_value = widget_values[screen._field_id(field)]
        if new_value != field.getter():
            field.setter(new_value)
    global_preferences.save_preferences(updated)
    if not set(submitted) <= DISPLAY_ONLY:  # units, handicaps and language change no ranking: keep the picks
        data._OVERVIEW_CACHE.clear()  # picks depend on the preferences
    return {"ok": True}


# ---- clubs -------------------------------------------------------------------------------


def clubs_overview() -> list[dict]:
    """The saved clubs with what Settings > Clubs edits: default course and, for courses whose
    name does not say how many holes they have, the hole count."""
    screen = _screen()
    result = []
    for club in data.club_entries():
        slug, rows = screen.course_holes_rows(club["id"])
        result.append(
            {
                **{k: club[k] for k in ("slug", "id", "name", "default_course")},
                "courses": data.courses_for(club["id"]),
                "course_holes": [{"course": course, "holes": holes} for course, holes in rows],
            }
        )
    return result


def account() -> dict:
    return {
        "username": env_file.load_env_value("PCC_USER") or "",
        "has_password": bool(env_file.load_env_value("PCC_PASS")),
    }


def ai() -> dict:
    provider = (global_preferences.load_preferences().get("ai_assist") or {}).get("provider")
    if provider not in ai_assist.PROVIDERS:
        provider = "anthropic"
    return {
        "provider": provider,
        "providers": [
            {
                "id": name,
                "label": i18n.t(f"ai_credentials.provider_{name}"),
                "has_key": bool(env_file.load_env_value(ai_assist.PROVIDER_ENV_VARS[name])),
            }
            for name in ai_assist.PROVIDERS
        ],
    }


def settings_payload(club_id: str | None) -> dict:
    """Everything the Settings sheet shows."""
    return {
        **schema("settings", club_id),
        "clubs": clubs_overview(),
        "account": account(),
        "ai": ai(),
        "theme": data.saved_theme(),
    }


def set_theme(name: str) -> dict:
    """Save the colour theme (the THEME= setting the terminal and Mac apps read too)."""
    if name not in data.theme_names():
        return {"error": "unknown_theme"}
    user_config.save_value("THEME", name, user_config.CONFIG_FILE)
    return {"ok": True}


def set_default_course(slug: str, course: str) -> dict:
    config = pipeline._load_club_config_safely(slug)
    if not config.get("club_id"):
        return {"error": "unknown_club"}
    config["default_course"] = course
    club_config.save_club_config(slug, config)
    return {"ok": True}


def set_course_holes(slug: str, course: str, holes: int | None) -> dict:
    if data.club_by_slug(slug) is None:
        return {"error": "unknown_club"}
    club_config.set_course_holes(slug, course, holes)
    data._OVERVIEW_CACHE.clear()
    return {"ok": True}


# ---- credentials -------------------------------------------------------------------------


def login(username: str, password: str, club_id: str | None) -> dict:
    """Save the pc caddie login (and verify it against `club_id` when given). The saved values are
    also put into this running process' environment: `club_config.resolve_credentials()` reads
    it from there, and `.env` was read once, at start."""
    result = save_login(username, password, club_id)
    if result["saved"]:
        for name in ("PCC_USER", "PCC_PASS"):
            value = env_file.load_env_value(name)
            if value:
                os.environ[name] = value
    return result


def ai_key(provider: str, api_key: str) -> dict:
    result = save_ai_key(provider, api_key)
    if result["saved"]:
        data._OVERVIEW_CACHE.clear()
    return result
