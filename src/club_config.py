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
`credentials_screen.py`) already imports this module before doing anything else, including
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
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv

from . import geocode

load_dotenv()

CLUBS_DIR = Path("clubs")
EXAMPLE_FILENAME = "club.example.yaml"

_SLUG_INVALID_CHARS = re.compile(r"[^a-z0-9]+")
_UMLAUT_FOLDS = {"ä": "a", "ö": "o", "ü": "u", "ß": "ss"}


def slugify(name: str) -> str:
    """A reasonable filename slug from a club's display name — e.g. "Golfclub Domäne
    Musterhausen e.V." -> "golfclub-domane-musterhausen-e-v". Not guaranteed unique and
    not a real transliteration; good enough as a filename and as a default the user can
    edit. Moved here 2026-09-07 from the now-deleted club_picker.py so the favorites
    helpers below and that screen's own search flow shared one implementation rather
    than drifting apart."""
    normalized = name.lower()
    for umlaut, plain in _UMLAUT_FOLDS.items():
        normalized = normalized.replace(umlaut, plain)
    slug = _SLUG_INVALID_CHARS.sub("-", normalized).strip("-")
    return slug or "club"


def list_clubs(clubs_dir: Path | None = None) -> list[str]:
    """Club ids available to pick from (every clubs/*.yaml except the example template).

    `clubs_dir` defaults to `None`, resolved to the module-level `CLUBS_DIR` at call
    time rather than bound as a literal default (2026-09-10, found in a dedicated bug
    hunt: this and the two functions below were the last holdouts of the frozen-
    default gotcha already fixed everywhere else in this file -- slug_for_club_id(),
    is_favorite(), add_favorite(), and remove_favorite() already used this exact
    pattern. A plain `clubs_dir: Path = CLUBS_DIR` default freezes at import time, so
    `monkeypatch.setattr(club_config, "CLUBS_DIR", ...)` silently fails to reach any
    call that omits the argument -- the same mistake this project's own ad hoc test
    sandboxes have hit more than once by reaching for the obvious-looking constant
    instead of the functions themselves)."""
    directory = clubs_dir if clubs_dir is not None else CLUBS_DIR
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.yaml") if p.name != EXAMPLE_FILENAME)


def load_club_config(club_id: str, clubs_dir: Path | None = None) -> dict:
    """Load one club's YAML config as a plain dict. See list_clubs() above for why
    `clubs_dir` resolves at call time rather than as a bound default."""
    directory = clubs_dir if clubs_dir is not None else CLUBS_DIR
    path = directory / f"{club_id}.yaml"
    with path.open() as f:
        return yaml.safe_load(f) or {}


def save_club_config(club_id: str, config: dict, clubs_dir: Path | None = None) -> None:
    """Write a club's config back to its YAML file — the mechanism behind the
    settings_screen.py TUI (added 2026-09-06, per direct feedback that preferences
    needed to be editable from the UI, not just by hand-editing YAML). See
    list_clubs() above for why `clubs_dir` resolves at call time rather than as a
    bound default.

    Known limitation: this rewrites the whole file via `yaml.safe_dump`, so any
    comments in the existing file (including every explanatory comment copied over
    from club.example.yaml when the file was first created) are lost on save. Accepted
    for now rather than pulling in a round-trip-preserving YAML library — the
    checked-in `club.example.yaml` template stays fully commented as the reference
    either way, and this only affects a club's own gitignored copy."""
    directory = clubs_dir if clubs_dir is not None else CLUBS_DIR
    path = directory / f"{club_id}.yaml"
    with path.open("w") as f:
        yaml.safe_dump(config, f, sort_keys=False)


def new_club_stub(club_id: str, name: str = "") -> dict:
    """A minimal starting config for a club just picked from `tui.py`'s
    `ClubBrowserScreen` directory search — only
    `club_id` comes from pc caddie's own directory; every other field (location,
    calendar, availability, preferences, ...) is a personal fact the picker has no way
    to know, and stays whatever each consumer already falls back to when it's missing
    (see e.g. scrape_once.py's DEFAULT_SCRAPE_INTERVAL_MINUTES, recommend.py's
    DEFAULT_AVOID_RAIN_*) until filled in by hand or via settings_screen.py. See
    clubs/club.example.yaml for the fully annotated reference of what's available.

    `name` (added 2026-09-08) is the club's real display name, persisted as `name`
    when known — a real bug found live: `tui.ClubBrowserScreen._favorites()` used to
    hand the file *slug* (lowercase, hyphenated, umlauts folded away, "e.V."
    mangled into "-e-v") to `add_favorite()` as if it were the name, for any club
    reached from the plain favorites list (the default view, an empty search box)
    rather than a live directory search — silently correct-looking in most places
    (a slug reads close enough to a name at a glance) but a real, confirmed dead end
    for `geocode.find_club_location()`, which needs the actual name to have any
    chance of matching. Persisting the real name once it's genuinely known (via a
    directory search) means a later un/re-favorite from the plain list can find it
    again here instead of falling back to the slug."""
    stub = {"club_id": club_id, "default_course": "", "default_date": "today"}
    if name:
        stub["name"] = name
    return stub


def slug_for_club_id(club_id: str, clubs_dir: Path | None = None) -> str | None:
    """The saved slug for a club's numeric pc caddie id, if it's a favorite.

    Added 2026-09-07 with the "favorites, not required setup" rework: the TUI now
    reaches a club by its numeric id (picked from the directory, or typed in), and only
    afterwards asks whether that club happens to be saved — the reverse of the old flow,
    where a slug was the only way in and every club had to be saved first. Returns None
    for a club being visited without saving it, which is a normal state now, not an
    error."""
    directory = clubs_dir if clubs_dir is not None else CLUBS_DIR
    wanted = str(club_id).strip()
    for slug in list_clubs(directory):
        try:
            config = load_club_config(slug, directory)
        except (OSError, yaml.YAMLError):
            continue  # an unreadable/malformed favorite shouldn't break club lookup
        if str(config.get("club_id", "")).strip() == wanted:
            return slug
    return None


def is_favorite(club_id: str, clubs_dir: Path | None = None) -> bool:
    """Whether this club is saved. "Favorite" and "has a clubs/*.yaml" are the same
    thing — the file is still where a club's own settings live, it's just no longer a
    precondition for looking at the club at all."""
    return slug_for_club_id(club_id, clubs_dir) is not None


def new_club_stub_with_location(club_id: str, name: str = "") -> dict:
    """`new_club_stub()` plus a best-effort geocoded `location` if `name` is given
    and something was found (2026-09-08 — see `geocode.py`'s module docstring for
    what this lookup can and can't do). Factored out so both ways of adding a club
    get the same treatment: `add_favorite()` below (`tui.py`'s `f`-to-favorite, the
    app's everyday one-keypress way to save a club) and `ClubBrowserScreen`'s own
    "search the whole directory, save as a new file" flow. `name` is blank
    whenever the caller has no name to geocode with (e.g. a club favorited by
    typed-in id alone, never seen in a directory search) — skipped in that case,
    same as a blank name is skipped anywhere else in this project."""
    stub = new_club_stub(club_id, name)
    location = geocode.find_club_location(name) if name else None
    if location is not None:
        lat, lon = location
        stub["location"] = {"lat": lat, "lon": lon}
    return stub


def add_favorite(club_id: str, name: str = "", clubs_dir: Path | None = None) -> str:
    """Save a club as a favorite and return its slug. A no-op returning the existing
    slug if it's already saved, so toggling twice can't create a duplicate file (the
    exact mistake made by hand during the first real end-to-end test on 2026-09-06,
    when the club picker saved a second copy of the home club).

    Real gap found and fixed 2026-09-08: the automatic weather-location lookup
    (`new_club_stub_with_location()` above) originally only lived in
    `club_picker.py`'s own save flow — this function, the one `tui.py`'s
    `f`-to-favorite actually calls (the app's more commonly used, one-keypress way
    to save a club), built its own plain `new_club_stub()` directly and skipped it
    entirely. Caught live: re-adding a club through `f` still showed no weather
    forecast, the exact symptom the lookup was built to fix."""
    directory = clubs_dir if clubs_dir is not None else CLUBS_DIR
    existing = slug_for_club_id(club_id, directory)
    if existing is not None:
        return existing
    base = slugify(name) if name else f"club-{club_id}"
    slug, n = base, 2
    while (directory / f"{slug}.yaml").exists():
        slug, n = f"{base}-{n}", n + 1
    directory.mkdir(parents=True, exist_ok=True)
    save_club_config(slug, new_club_stub_with_location(club_id, name), directory)
    return slug


def remove_favorite(club_id: str, clubs_dir: Path | None = None) -> str | None:
    """Un-favorite a club, returning the slug removed (or None if it wasn't saved).

    Deletes that club's `clubs/*.yaml` and with it any preferences stored in it —
    scraped history in `data/<club_id>.db` is keyed by club id, not slug, and is
    deliberately left alone, so re-favoriting the club later still has its history."""
    directory = clubs_dir if clubs_dir is not None else CLUBS_DIR
    slug = slug_for_club_id(club_id, directory)
    if slug is None:
        return None
    (directory / f"{slug}.yaml").unlink(missing_ok=True)
    return slug


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
