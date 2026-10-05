"""Tiny flat `KEY=value` config file reader/writer, shared by `theme.py` (`THEME=`)
and `i18n.py` (`LANG=`) — both are global "how do I want this to look" preferences,
not per-club facts, so they share one file (`~/.config/teetime-monitor/config`)
separate from `clubs/*.yaml`, in the same spirit and with the same "never sourced as
code" safety property as brew-launcher's own config file. Factored out here once a
second module (`i18n.py`) needed the identical "read/write one KEY=value line,
preserve every other line untouched" logic `theme.py` already had.

Each caller still resolves its own `config_file` default at call time, not as a bound
parameter default — a plain `config_file: Path = CONFIG_FILE` default is frozen at
import time and would silently ignore a test's `monkeypatch.setattr(module,
"CONFIG_FILE", ...)`, a real gotcha already caught twice this session (once in
club_config.save_club_config(), once in this module's own predecessor inside
theme.py) — so the functions here take a required, already-resolved `config_file`
rather than defaulting it themselves.
"""

from pathlib import Path

from . import paths

CONFIG_DIR = paths.CONFIG_DIR
CONFIG_FILE = CONFIG_DIR / "config"


def load_value(key: str, config_file: Path) -> str | None:
    """The value of `KEY=...` in `config_file`, or None if the file or the key
    doesn't exist."""
    if not config_file.exists():
        return None
    prefix = f"{key}="
    for line in config_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            value = stripped[len(prefix) :].strip()
            return value or None
    return None


def save_value(key: str, value: str, config_file: Path) -> None:
    """Persist `KEY=value` to `config_file`, rewriting an existing `KEY=` line in
    place rather than duplicating it, and leaving every other line untouched."""
    save_values({key: value}, config_file)


def save_values(values: dict[str, str], config_file: Path) -> None:
    """`save_value()` for several keys in one atomic write -- the file is shared with
    the GUI and the background scrape, so it's never seen truncated or half-updated."""
    lines: list[str] = []
    replaced: set[str] = set()
    if config_file.exists():
        for line in config_file.read_text(encoding="utf-8").splitlines():
            key = next((k for k in values if line.strip().startswith(f"{k}=")), None)
            if key is None:
                lines.append(line)
            else:
                lines.append(f"{key}={values[key]}")
                replaced.add(key)
    lines.extend(f"{key}={value}" for key, value in values.items() if key not in replaced)
    paths.atomic_write_text(config_file, "\n".join(lines) + "\n")
