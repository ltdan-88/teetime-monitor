"""Add Club for the web UI (2026-10-10): search the platform's club directory, save a club as a
favorite, open one without saving it, remove one.

The directory is the one `club_directory.py` documents: the live list cached from a logged-in fetch
if there is one, else the bundled snapshot, plus a typed club id (or a pasted tee-sheet URL) that
needs neither. Saving and previewing reuse `add_club_cli.add_club()` and
`preview_club_cli.preview_club()`, the same functions the Mac app's helper programs run.
"""

from .. import add_club_cli, club_config, club_directory, directory_cli, preview_club_cli
from . import data

SEARCH_LIMIT = 50


def directory_state() -> dict:
    """Which list searches run against: `live` (fetched with a login, with the time), `seed` (the
    bundled snapshot) or `none`; and whether a login is saved at all (needed to refresh)."""
    cached = club_directory.load_cached_directory()
    if cached:
        return {"source": "live", "count": len(cached), "fetched_at": club_directory.cached_at()}
    seed = club_directory.load_seed_directory()
    if seed:
        return {"source": "seed", "count": len(seed), "fetched_at": None}
    return {"source": "none", "count": 0, "fetched_at": None}


def search(query: str) -> dict:
    """Clubs whose name contains `query`, each marked when already saved. A club id or tee-sheet
    URL in the box is a result of its own (no directory needed for those)."""
    saved = {club["id"] for club in data.club_entries()}
    directory = club_directory.load_cached_directory() or club_directory.load_seed_directory()
    results = [{"id": club_id, "name": name} for club_id, name in club_directory.search(directory, query, SEARCH_LIMIT)]
    typed = club_directory.looks_like_club_id(query)
    if typed and all(r["id"] != typed for r in results):
        known = next((name for club_id, name in directory if club_id == typed), "")
        results.insert(0, {"id": typed, "name": known, "typed": True})
    for result in results:
        result["saved"] = result["id"] in saved
    return {**directory_state(), "query": query, "results": results}


def refresh_directory() -> dict:
    return directory_cli.refresh_directory_cache()


def add(club_id: str, name: str) -> dict:
    result = add_club_cli.add_club(club_id, name)
    if result["ok"]:
        data._OVERVIEW_CACHE.clear()
    return result


def remove(club_id: str) -> dict:
    slug = club_config.remove_favorite(club_id)
    if slug is None:
        return {"error": "unknown_club"}
    data._OVERVIEW_CACHE.clear()
    return {"ok": True, "slug": slug}


def preview(club_id: str, name: str) -> dict:
    """Scrape a club that is not saved (so there is something to show); blocking, run it in the
    background."""
    return preview_club_cli.preview_club(club_id, name)
