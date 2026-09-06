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

CONFIG_DIR = Path.home() / ".config" / "teetime-monitor"
CONFIG_FILE = CONFIG_DIR / "config"


def load_value(key: str, config_file: Path) -> str | None:
    """The value of `KEY=...` in `config_file`, or None if the file or the key
    doesn't exist."""
    if not config_file.exists():
        return None
    prefix = f"{key}="
    for line in config_file.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            value = stripped[len(prefix) :].strip()
            return value or None
    return None


def save_value(key: str, value: str, config_file: Path) -> None:
    """Persist `KEY=value` to `config_file`, rewriting an existing `KEY=` line in
    place rather than duplicating it, and leaving every other line untouched."""
    config_file.parent.mkdir(parents=True, exist_ok=True)
    prefix = f"{key}="
    lines: list[str] = []
    replaced = False
    if config_file.exists():
        for line in config_file.read_text().splitlines():
            if line.strip().startswith(prefix):
                lines.append(f"{key}={value}")
                replaced = True
            else:
                lines.append(line)
    if not replaced:
        lines.append(f"{key}={value}")
    config_file.write_text("\n".join(lines) + "\n")
