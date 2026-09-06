"""Color themes for the TUI, in the spirit of brew-launcher's own theme system
(the sister project this tool is modeled on) — same 10 named themes, same hex
values, same env-var-then-config-file-then-default resolution order, added
2026-09-06 on direct request ("I'd like color themes like in brew launcher").

Textual already ships several of brew-launcher's palettes as built-in themes, sourced
from the same published specs (Catppuccin, Gruvbox, Tokyo Night, Nord, Dracula,
Solarized) — `BUILTIN_THEME_MAP` below just points brew-launcher's names at Textual's
own equivalents rather than redefining colors Textual already has correct. Only the
three brew-launcher has that Textual doesn't — the monochrome CRT-phosphor `green`/
`amber` palettes and `red-sands` (from the iTerm2-Color-Schemes collection) — are
registered here as custom `Theme` objects, using the exact hex values from
brew-launcher's own `bin/brew-launcher` (its fzf `--color` case statement), mapped
onto Textual's semantic Theme fields (primary/secondary/accent/foreground/background/
surface/panel/boost/success/warning/error) rather than fzf's own 15-key vocabulary
(fg/bg/fg+/bg+/hl/hl+/info/prompt/pointer/marker/spinner/header/border/label/query) —
the two don't line up 1:1, so each custom theme below documents its own mapping.

One deliberate improvement over brew-launcher's own version: that tool requires a full
process relaunch for a theme change to take effect (fzf's colors are baked in at
subprocess-spawn time); this app's theme applies live, and Textual's own command
palette (`ctrl+p`, or the `t` binding on the day-detail screen) already gives a
searchable, live-preview picker across every registered theme for free — no
hand-built ThemePickerScreen needed, unlike this project's other pickers.

Persistence is a flat `KEY=value` text file, `~/.config/teetime-monitor/config` —
same shape and the same "never sourced as code" safety property as brew-launcher's
own `~/.config/brew-launcher/config` — but a separate mechanism from `clubs/*.yaml`,
since a color preference is a "how do I like my terminal to look" choice, not a
per-club fact. The actual file read/write lives in `user_config.py`, shared with
`i18n.py`'s `LANG=` line in that same file.
"""

import os
from pathlib import Path

from textual.app import App
from textual.theme import Theme

from . import user_config

DEFAULT_THEME = "catppuccin"

ENV_VAR = "TEETIME_MONITOR_THEME"
CONFIG_DIR = user_config.CONFIG_DIR
CONFIG_FILE = user_config.CONFIG_FILE

# brew-launcher name -> Textual's own built-in equivalent (same published palette).
BUILTIN_THEME_MAP = {
    "catppuccin": "catppuccin-mocha",
    "gruvbox": "gruvbox",
    "tokyonight": "tokyo-night",
    "nord": "nord",
    "dracula": "dracula",
    "solarized-dark": "solarized-dark",
    "solarized-light": "solarized-light",
}
_REVERSE_BUILTIN_MAP = {textual_name: brew_name for brew_name, textual_name in BUILTIN_THEME_MAP.items()}

# The three brew-launcher palettes Textual doesn't ship — exact hex values from
# bin/brew-launcher's own fzf --color case statement, mapped onto Textual's Theme
# fields (see each comment for the fzf-key -> Theme-field mapping used).
CUSTOM_THEMES: dict[str, Theme] = {
    "green": Theme(
        # A real green-phosphor CRT could only show one hue at varying brightness —
        # brightness does the work color does in the other themes, same reasoning
        # brew-launcher's own comment gives. hl->primary, info->secondary,
        # hl+->accent, fg->foreground, bg->background, border->surface/panel,
        # bg+->boost, marker->success, spinner->warning, pointer->error.
        name="green",
        primary="#33ff66",
        secondary="#1f8f42",
        accent="#ccffdd",
        foreground="#33ff66",
        background="#000000",
        surface="#114422",
        panel="#114422",
        boost="#003311",
        success="#33ff66",
        warning="#33ff66",
        error="#ccffdd",
        dark=True,
    ),
    "amber": Theme(
        # Same reasoning as green — one hue (amber-phosphor, Hercules-style), varied
        # by intensity. Same fzf-key -> Theme-field mapping as green above.
        name="amber",
        primary="#ffbf00",
        secondary="#996f00",
        accent="#ffe699",
        foreground="#ffbf00",
        background="#000000",
        surface="#4d3800",
        panel="#4d3800",
        boost="#332200",
        success="#ffbf00",
        warning="#ffbf00",
        error="#ffe699",
        dark=True,
    ),
    "red-sands": Theme(
        # From iTerm2-Color-Schemes — a genuinely red *background*, not just a red
        # accent among several. A classic 16-color ANSI scheme, not a from-scratch UI
        # palette, so (like brew-launcher's own comment notes) info/border have no
        # official equivalent — reused the same bright-black ANSI entry for both, as
        # brew-launcher does. hl->primary, info/border->secondary, pointer->accent,
        # fg->foreground, bg->background, bg+->boost, marker->success,
        # spinner->warning (its own blue ANSI entry — no separate warning hue
        # published), pointer->error (no separate error hue published either).
        name="red-sands",
        primary="#e7b000",
        secondary="#6e6e6e",
        accent="#00bbbb",
        foreground="#d7c9a7",
        background="#7a251e",
        surface="#6e6e6e",
        panel="#6e6e6e",
        boost="#a4a390",
        success="#00bb00",
        warning="#0072ff",
        error="#00bbbb",
        dark=True,
    ),
}

ALL_THEME_NAMES = list(BUILTIN_THEME_MAP) + list(CUSTOM_THEMES)


def register_custom_themes(app: App) -> None:
    """Register the three custom palettes with `app` — idempotent, safe to call every
    startup. The seven brew-launcher names Textual already ships need no registration."""
    for custom_theme in CUSTOM_THEMES.values():
        app.register_theme(custom_theme)


def to_textual_theme_name(name: str) -> str:
    """A brew-launcher-style name (or an already-Textual-native one, e.g. one the
    user picked straight from the command palette) -> the actual name to assign to
    `app.theme`."""
    return BUILTIN_THEME_MAP.get(name, name)


def to_logical_name(textual_theme_name: str) -> str:
    """The reverse of to_textual_theme_name() — used when persisting, so the saved
    config file uses brew-launcher's own naming for a theme that has one, and the raw
    Textual name unchanged for anything else (e.g. a native Textual theme with no
    brew-launcher equivalent, like "monokai" or "rose-pine")."""
    return _REVERSE_BUILTIN_MAP.get(textual_theme_name, textual_theme_name)


def load_saved_theme(config_file: Path | None = None) -> str | None:
    """The persisted THEME= value, or None if never saved.

    `config_file` defaults to the module-level `CONFIG_FILE` looked up at call time
    (not bound as the parameter's default value) so tests can monkeypatch
    `theme.CONFIG_FILE` and have every caller here actually see the replacement —
    a plain `config_file: Path = CONFIG_FILE` default is frozen at import time and
    would silently ignore a monkeypatch, the same gotcha already caught once this
    session in club_config.py. The actual read/write lives in user_config.py, shared
    with i18n.py's identically-shaped LANG= line in the same file."""
    config_file = config_file if config_file is not None else CONFIG_FILE
    return user_config.load_value("THEME", config_file)


def save_theme(name: str, config_file: Path | None = None) -> None:
    """Persist `name` (a logical/brew-launcher-style name where one exists) to the
    config file. See load_saved_theme() for why `config_file` isn't a plain
    `= CONFIG_FILE` default."""
    config_file = config_file if config_file is not None else CONFIG_FILE
    user_config.save_value("THEME", name, config_file)


def resolve_theme_name(env: dict | None = None, config_file: Path | None = None) -> str:
    """Env var > saved config file > default — the same resolution order
    brew-launcher's own THEME_NAME uses."""
    environ = os.environ if env is None else env
    env_value = environ.get(ENV_VAR)
    if env_value:
        return env_value
    saved = load_saved_theme(config_file)
    if saved:
        return saved
    return DEFAULT_THEME


def apply_theme(app: App, name: str | None = None, config_file: Path | None = None) -> str:
    """Register the custom themes and set `app.theme` to the resolved name (env var >
    saved config > default, unless `name` is given explicitly). Returns the logical
    name that was applied, for a caller that wants to display or persist it."""
    register_custom_themes(app)
    chosen = name or resolve_theme_name(config_file=config_file)
    textual_name = to_textual_theme_name(chosen)
    if textual_name not in app.available_themes:
        textual_name = to_textual_theme_name(DEFAULT_THEME)
        chosen = DEFAULT_THEME
    app.theme = textual_name
    return chosen
