"""Multi-club config: which clubs are saved, and how to load each one and its
credentials (ROADMAP.md Phase 0).

Each club is one YAML file under clubs/ (see clubs/club.example.yaml for the
template) — the filename without ".yaml" is the club's id, used both to pick it at
startup and to namespace its credentials in .env.

Unlike most of Phase 0/1, this module needs no pc caddie site access — just local
files and env vars — so it's implemented (and tested) now rather than stubbed.

Found and fixed 2026-09-07, while wiring up credentials_screen.py: `python-dotenv`
has been a listed dependency since the very first commit, but nothing in this
codebase ever actually called `load_dotenv()` — a `.env` file sitting next to the
project only ever did anything if something *else* (a shell profile, `direnv`,
manually running `export $(cat .env)`) had already loaded it into the environment
first. Silent and easy to miss, since `resolve_credentials()` degrading to `("", "")`
looks identical whether `.env` is missing, misspelled, or just never loaded —
genuinely surfaced only once a screen existed whose entire point is "fill in `.env`
and have it work right away."

Fixed at import time, here, rather than lazily inside `resolve_credentials()` itself:
every real entry point (`tui.py`, `scrape_once.py`, `settings_screen.py`,
`club_picker.py`) already imports this module before doing anything else, including
before `ai_assist.py` ever constructs an `anthropic.Anthropic()` client (which reads
`ANTHROPIC_API_KEY` from the environment internally, on its own, with no call into
this module at all) — an import-time call is what actually guarantees `.env` is
loaded before *any* of that runs, regardless of which function happens to be called
first. `load_dotenv()`'s own default behavior of never overriding an already-set
environment variable is exactly right here, so an env var set some other way still
wins; its default upward directory search from this file's own location finds the
project root's `.env` regardless of the caller's current working directory.
"""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

CLUBS_DIR = Path("clubs")
EXAMPLE_FILENAME = "club.example.yaml"


def list_clubs(clubs_dir: Path = CLUBS_DIR) -> list[str]:
    """Club ids available to pick from (every clubs/*.yaml except the example template)."""
    if not clubs_dir.exists():
        return []
    return sorted(p.stem for p in clubs_dir.glob("*.yaml") if p.name != EXAMPLE_FILENAME)


def load_club_config(club_id: str, clubs_dir: Path = CLUBS_DIR) -> dict:
    """Load one club's YAML config as a plain dict."""
    path = clubs_dir / f"{club_id}.yaml"
    with path.open() as f:
        return yaml.safe_load(f) or {}


def save_club_config(club_id: str, config: dict, clubs_dir: Path = CLUBS_DIR) -> None:
    """Write a club's config back to its YAML file — the mechanism behind the
    settings_screen.py TUI (added 2026-09-06, per direct feedback that preferences
    needed to be editable from the UI, not just by hand-editing YAML).

    Known limitation: this rewrites the whole file via `yaml.safe_dump`, so any
    comments in the existing file (including every explanatory comment copied over
    from club.example.yaml when the file was first created) are lost on save. Accepted
    for now rather than pulling in a round-trip-preserving YAML library — the
    checked-in `club.example.yaml` template stays fully commented as the reference
    either way, and this only affects a club's own gitignored copy."""
    path = clubs_dir / f"{club_id}.yaml"
    with path.open("w") as f:
        yaml.safe_dump(config, f, sort_keys=False)


def new_club_stub(club_id: str) -> dict:
    """A minimal starting config for a club just picked via club_picker.py — only
    `club_id` comes from pc caddie's own directory; every other field (location,
    calendar, availability, preferences, ...) is a personal fact the picker has no way
    to know, and stays whatever each consumer already falls back to when it's missing
    (see e.g. scrape_once.py's DEFAULT_SCRAPE_INTERVAL_MINUTES, recommend.py's
    DEFAULT_AVOID_RAIN_*) until filled in by hand or via settings_screen.py. See
    clubs/club.example.yaml for the fully annotated reference of what's available."""
    return {"club_id": club_id, "default_course": "", "default_date": "today"}


def resolve_credentials(club_id: str) -> tuple[str, str]:
    """(username, password) for a club.

    Confirmed 2026-09-05: one pc caddie login works across multiple clubs under the
    same account, so plain PCC_USER/PCC_PASS is the expected path even with several
    clubs saved — not just a single-club shortcut. Namespaced env vars
    (PCC_USER__<club_id> / PCC_PASS__<club_id>), checked first, exist only for the
    genuine edge case: a specific club that actually needs different credentials.
    """
    user = os.environ.get(f"PCC_USER__{club_id}") or os.environ.get("PCC_USER", "")
    password = os.environ.get(f"PCC_PASS__{club_id}") or os.environ.get("PCC_PASS", "")
    return user, password
