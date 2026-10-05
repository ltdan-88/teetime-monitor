"""Read/write `.env` KEY=value pairs without disturbing anything else in the file —
comments, blank lines, unrelated keys (namespaced per-club credentials,
`ANTHROPIC_API_KEY`, etc.). Added 2026-09-07 for `credentials_screen.py`, direct
follow-up to the club picker: "I want to setup credentials from UI. It should be user
friendly" — hand-editing `.env` in a text editor was the only path before this.

Deliberately not a general `.env` parser/writer library — just enough to update a
handful of known keys in place, or append them if the file doesn't have them yet
(starting from the built-in `ENV_TEMPLATE`'s structure and comments if `.env` doesn't
exist at all). Values are written so python-dotenv reads them back unchanged. This module never logs, prints, or otherwise surfaces a value it reads or
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

from dotenv import dotenv_values

from . import paths

ENV_FILE = paths.ENV_FILE  # ~/.config/teetime-monitor/.env -- see paths.py

# What a first-ever save starts from. Built in rather than read from `.env.example`
# in the working directory: that resolved against wherever the command ran, so a
# stray file there (any cloned repo) was merged into the real credentials file and
# its keys -- HTTPS_PROXY, say -- loaded into every later run.
ENV_TEMPLATE = """\
# One pc caddie login covers every club under the same account. These two are
# usually all you need, even with several clubs saved.
PCC_USER=
PCC_PASS=

# Only for a specific club that requires separate credentials. Namespaced per club
# id (the filename in clubs/, without ".yaml"); overrides the pair above for it:
# PCC_USER__guest-club=
# PCC_PASS__guest-club=

# Powers ai_assist.py (AI ranking and summaries). One key covers every saved club.
ANTHROPIC_API_KEY=
"""
# None means ENV_TEMPLATE. Callers and tests can still point this at a real file.
ENV_EXAMPLE_FILE: Path | None = None

# Characters python-dotenv would treat specially in an unquoted value: whitespace
# before `#` starts a comment, a leading quote starts a quoted value, and outer
# whitespace is stripped. A value containing any of them is written single-quoted.
_NEEDS_QUOTES = set("#'\"")


def _format_value(value: str) -> str:
    """`value` as python-dotenv will read it back unchanged. Plain values stay bare
    (the GUI reads PCC_USER raw); anything else is single-quoted, where dotenv only
    decodes `\\\\` and `\\'`. Interpolation of `${...}` is off at load time (see
    club_config.py), so `$` needs nothing."""
    # splitlines() also breaks on \x0b, \x0c, \x1c-\x1e, \x85 and U+2028/9 -- and
    # set_env_values() re-reads the file that way, so the next save would split it.
    if value.splitlines() != [value]:
        raise ValueError("a .env value can't contain a line break")
    if value == value.strip() and not any(c.isspace() or c in _NEEDS_QUOTES for c in value):
        return value
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def load_env_value(key: str, path: Path | None = None) -> str | None:
    """The current value of `key` in `path` (defaults to ENV_FILE, resolved at call
    time), or None if the file doesn't exist, the key isn't set, or it's set but
    blank (blank and "not set" are the same thing for every caller here).

    Parsed by python-dotenv itself, with the same settings as club_config's
    `load_dotenv()`, so a login verified against this value is the same string
    every later process logs in with."""
    path = path if path is not None else ENV_FILE
    if not path.exists():
        return None
    value = dotenv_values(path, interpolate=False, encoding="utf-8").get(key)
    return value if value and value.strip() else None


def set_env_values(
    values: dict[str, str], path: Path | None = None, template_path: Path | None = None
) -> None:
    """Update (or append) each key in `values`, preserving every other line as-is.
    Starts from `path` if it exists, otherwise from `template_path` (so a first-ever
    save keeps the template's explanatory comments; `ENV_TEMPLATE` when it's None) —
    an empty starting point if a given template file doesn't exist. Raises ValueError
    for a value with a line break, which could otherwise inject extra keys. Blank values in `values` are skipped entirely (a caller leaving a
    field blank means "don't change this one," not "set it to empty" — see
    credentials_screen.py's docstring for why, especially for the password field)."""
    path = path if path is not None else ENV_FILE
    template_path = template_path if template_path is not None else ENV_EXAMPLE_FILE
    values = {key: _format_value(value) for key, value in values.items() if value}
    if not values:
        return

    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    elif template_path is None:
        lines = ENV_TEMPLATE.splitlines()
    elif template_path.exists():
        lines = template_path.read_text(encoding="utf-8").splitlines()
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

    # Atomic, and 0600 on every save: this file holds the password and API key.
    paths.atomic_write_text(path, "\n".join(lines) + "\n", mode=0o600)
