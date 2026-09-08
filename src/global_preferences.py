"""One shared `availability`/`preferences`/scrape-interval settings file, used across
every saved club — not a per-club fact any more. Direct feedback (2026-09-08, right
after the settings screen became reachable from the running app): "i also want the
settings/preferences to be global and not tied to a specific club."

That request is correct about what these actually are: your own standing availability
("workdays after 17:00, weekends after 10:00, always solo") and weather comfort
thresholds are facts about *you*, not about any one club — the old design required
re-entering the same rules into every club's own YAML, which only ever meant "the same
answer, typed in twice" for a second club, never a genuinely different one. `location`,
`calendar`, `overview_days`, `default_course`, `identity`, and `round_duration_minutes`
stay in `clubs/*.yaml` — each of those *is* a real per-club fact (coordinates, course
lineup) — only the fields `settings_screen.py`'s own form edits move here:
`availability`, `preferences`, `ai_assist`, `daylight_buffer_minutes`,
`scrape_interval_minutes`, `scrape_interval_minutes_booked`.

`ai_assist` joined this list the same day, direct follow-up right after discussing
turning AI ranking on for the first time: "the ai feature should be an option in the
settings menu." Originally kept per-club on the theory that model choice is a
cost/quality tradeoff that varies by club — in practice nothing about wanting AI
ranking on or off actually does, and the request itself was for one switch, not a
per-club dial. A club's own `ai_assist` block in `clubs/*.yaml` (if one predates this)
still works as a fallback via `_resolved_config()`'s shallow merge — it just no longer
wins once this file has actually set one.

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
