"""One shared `availability`/`preferences`/scrape-interval settings file, used across
every saved club — not a per-club fact any more. Direct feedback (2026-09-08, right
after the settings screen became reachable from the running app): "i also want the
settings/preferences to be global and not tied to a specific club."

That request is correct about what these actually are: your own standing availability
("workdays after 17:00, weekends after 10:00, always solo") and weather comfort
thresholds are facts about *you*, not about any one club — the old design required
re-entering the same rules into every club's own YAML, which only ever meant "the same
answer, typed in twice" for a second club, never a genuinely different one. `location`,
`calendar`, `overview_days`, `default_course`, and `identity` stay in `clubs/*.yaml` —
each of those *is* a real per-club fact (coordinates, course lineup) — only the fields
`settings_screen.py`'s own form edits move here: `availability`, `preferences`,
`ai_assist`, `round_duration_minutes`, `daylight_buffer_minutes`,
`scrape_interval_minutes`, `scrape_interval_minutes_booked`.

`ai_assist` joined this list the same day, direct follow-up right after discussing
turning AI ranking on for the first time: "the ai feature should be an option in the
settings menu." Originally kept per-club on the theory that model choice is a
cost/quality tradeoff that varies by club — in practice nothing about wanting AI
ranking on or off actually does, and the request itself was for one switch, not a
per-club dial. A club's own `ai_assist` block in `clubs/*.yaml` (if one predates this)
still works as a fallback via `_resolved_config()`'s shallow merge — it just no longer
wins once this file has actually set one.

`round_duration_minutes` followed the next day, same shape of request ("make pace
speed adjustable in settings") right after explaining its existing 120/240-minute
defaults — it had been kept per-club on the theory that pace genuinely varies by
course, but the actual ask was for one adjustable pair of settings, not a per-club
dial. Same fallback story: a club's own `round_duration_minutes` still works if set,
just no longer wins once this file has one.

Stored at `~/.config/teetime-monitor/preferences.yaml` — the same directory
`user_config.py` already uses for the equally-global theme/language choice, just its
own file rather than reusing that flat `KEY=value` format: this data is nested
(`availability.weekday_window.after`), which a flat format can't represent, so it's
plain YAML via the same `yaml.safe_load`/`safe_dump` `club_config.py` already uses for
`clubs/*.yaml` — same shape, different file, no per-club directory involved.

Callers merge this on top of whatever a specific club's own config has (see
`tui.py`'s `_resolved_config()` and `scrape_once.py`'s own merge in `run()`/
`scrape_due_for_club()`) — a shallow merge is exactly right here, since the fields
this file owns and the fields a club's own YAML still owns don't overlap.
"""

from pathlib import Path

import yaml

from . import user_config

CONFIG_DIR = user_config.CONFIG_DIR
PREFERENCES_FILE = CONFIG_DIR / "preferences.yaml"


def load_preferences(path: Path | None = None) -> dict:
    """The shared settings, or `{}` if none have been saved yet — same "missing means
    empty, not an error" stance `club_config.load_club_config()` doesn't get to have
    (a club file is expected to exist once saved), since this file may genuinely never
    have been created on a fresh install."""
    resolved = path if path is not None else PREFERENCES_FILE
    if not resolved.exists():
        return {}
    with resolved.open() as f:
        return yaml.safe_load(f) or {}


def save_preferences(config: dict, path: Path | None = None) -> None:
    """Write the shared settings back, creating `~/.config/teetime-monitor/` if this
    is the first save on a fresh install (same reasoning as `club_directory.py`'s own
    `save_directory()` — the first write anywhere under that directory can't assume
    it already exists)."""
    resolved = path if path is not None else PREFERENCES_FILE
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("w") as f:
        yaml.safe_dump(config, f, sort_keys=False)


def load_last_active_club(config_file: Path | None = None) -> dict | None:
    """The `{"club_id", "slug", "course"}` last successfully opened, or `None` if
    never set (a genuinely fresh install, or incomplete data). Added 2026-09-10,
    direct feedback: "when you launch teetime-monitor you are greeted with which
    club to select, then which course. I think this is redundant since you can now
    select club and courses from the overview." Once `OverviewScreen`'s own inline
    switcher (2026-09-09) could change either one in place, forcing the same
    two-screen picker flow at *every* launch stopped making sense — this is what
    lets `TeetimeApp._start()` jump straight back into the last-used club/course
    instead, falling back to the full picker flow only when this is missing or
    turns out to be stale (see `_resume_last_active()`'s own docstring).

    Deliberately *not* stored in `PREFERENCES_FILE` alongside actual user-edited
    preferences, despite otherwise fitting this module's own theme (global, not
    per-club, small): a real bug found live while building this very feature —
    `_resolved_config()` merges `load_preferences()`'s *entire* dict wholesale on
    top of a club's own settings, with no filtering of which keys are genuine
    preferences, so a `last_active` key living there would leak into every
    resolved club config anywhere in the app (recommend.py, scrape_once.py, ...),
    not just the one place that actually needs it. Uses `user_config`'s own flat
    `KEY=value` file instead — the same one `theme.py`/`i18n.py` already use for
    exactly this kind of "global app state, never part of a resolved club config"
    data — three flat keys (`LAST_CLUB_ID`/`LAST_CLUB_SLUG`/`LAST_COURSE`) rather
    than the nested shape this module's own YAML file holds."""
    resolved = config_file if config_file is not None else user_config.CONFIG_FILE
    club_id = user_config.load_value("LAST_CLUB_ID", resolved)
    course = user_config.load_value("LAST_COURSE", resolved)
    if not club_id or not course:
        return None
    return {"club_id": club_id, "slug": user_config.load_value("LAST_CLUB_SLUG", resolved), "course": course}


def save_last_active_club(club_id: str, slug: str | None, course: str, config_file: Path | None = None) -> None:
    """Remember the club/course a later launch should resume straight into — see
    `load_last_active_club()`'s own docstring for the full detail, including why
    this deliberately isn't stored in `PREFERENCES_FILE`. Called every time a
    club/course open or inline switch actually succeeds (`TeetimeApp._open_club()`,
    which also backs the explicit `s`-to-switch flow; `OverviewScreen.
    _switch_club()`/`_switch_course()`), not just once at startup, so switching
    mid-session updates what a later relaunch resumes into rather than freezing on
    whatever was first opened."""
    resolved = config_file if config_file is not None else user_config.CONFIG_FILE
    user_config.save_value("LAST_CLUB_ID", club_id, resolved)
    user_config.save_value("LAST_CLUB_SLUG", slug or "", resolved)
    user_config.save_value("LAST_COURSE", course, resolved)
