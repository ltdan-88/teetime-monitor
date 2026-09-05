"""Multi-club config: which clubs are saved, and how to load each one and its
credentials (ROADMAP.md Phase 0).

Each club is one YAML file under clubs/ (see clubs/club.example.yaml for the
template) — the filename without ".yaml" is the club's id, used both to pick it at
startup and to namespace its credentials in .env.

Unlike most of Phase 0/1, this module needs no pc caddie site access — just local
files and env vars — so it's implemented (and tested) now rather than stubbed.
"""

import os
from pathlib import Path

import yaml

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
