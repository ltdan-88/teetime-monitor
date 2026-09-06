"""Read/write `.env` KEY=value pairs without disturbing anything else in the file —
comments, blank lines, unrelated keys (namespaced per-club credentials,
`ANTHROPIC_API_KEY`, etc.). Added 2026-09-07 for `credentials_screen.py`, direct
follow-up to the club picker: "I want to setup credentials from UI. It should be user
friendly" — hand-editing `.env` in a text editor was the only path before this.

Deliberately not a general `.env` parser/writer library — just enough to update a
handful of known keys in place, or append them if the file doesn't have them yet
(starting from `.env.example`'s own structure and comments if `.env` doesn't exist at
all). This module never logs, prints, or otherwise surfaces a value it reads or
writes — see `credentials_screen.py` for how the password field itself stays masked
end to end (the value only ever moves from the user's own keystrokes into this file,
same as if they'd typed it into a text editor themselves).

`path`/`template_path` default to `None` and get resolved to the module-level
`ENV_FILE`/`ENV_EXAMPLE_FILE` at call time, not bound as literal defaults — the same
gotcha already caught twice elsewhere in this project (theme.py, user_config.py's own
docstring): a plain `path: Path = ENV_FILE` default freezes at import time, so
monkeypatching `env_file.ENV_FILE` in a test wouldn't reach a call that omits the
argument.
"""

from pathlib import Path

ENV_FILE = Path(".env")
ENV_EXAMPLE_FILE = Path(".env.example")


def load_env_value(key: str, path: Path | None = None) -> str | None:
    """The current value of `key` in `path` (defaults to ENV_FILE, resolved at call
    time), or None if the file doesn't exist, the key isn't set, or it's set but
    blank (blank and "not set" are the same thing for every caller here)."""
    path = path if path is not None else ENV_FILE
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        found_key, _, value = stripped.partition("=")
        if found_key.strip() == key:
            return value.strip() or None
    return None


def set_env_values(
    values: dict[str, str], path: Path | None = None, template_path: Path | None = None
) -> None:
    """Update (or append) each key in `values`, preserving every other line as-is.
    Starts from `path` if it exists, otherwise from `template_path` (so a first-ever
    save keeps `.env.example`'s own explanatory comments) — an empty starting point if
    neither exists. Blank values in `values` are skipped entirely (a caller leaving a
    field blank means "don't change this one," not "set it to empty" — see
    credentials_screen.py's docstring for why, especially for the password field)."""
    path = path if path is not None else ENV_FILE
    template_path = template_path if template_path is not None else ENV_EXAMPLE_FILE
    values = {key: value for key, value in values.items() if value}
    if not values:
        return

    if path.exists():
        lines = path.read_text().splitlines()
    elif template_path.exists():
        lines = template_path.read_text().splitlines()
    else:
        lines = []

    remaining = dict(values)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        found_key, _, _ = stripped.partition("=")
        found_key = found_key.strip()
        if found_key in remaining:
            lines[i] = f"{found_key}={remaining.pop(found_key)}"

    for key, value in remaining.items():
        lines.append(f"{key}={value}")

    path.write_text("\n".join(lines) + "\n")
