import json

from src import club_directory


# --- looks_like_club_id: the path that needs no cache and no login -------------------


def test_looks_like_club_id_normalizes_a_missing_leading_zero():
    assert club_directory.looks_like_club_id("000001") == "0000001"


def test_looks_like_club_id_accepts_the_full_seven_digit_form():
    assert club_directory.looks_like_club_id("0000001") == "0000001"


def test_looks_like_club_id_ignores_surrounding_whitespace():
    assert club_directory.looks_like_club_id("  0000001 ") == "0000001"


def test_looks_like_club_id_rejects_a_club_name():
    assert club_directory.looks_like_club_id("Musterhausen") is None


def test_looks_like_club_id_rejects_a_too_short_number():
    # Otherwise typing "18" while searching for "18 Loch" would offer a bogus club.
    assert club_directory.looks_like_club_id("18") is None


# --- the cache ----------------------------------------------------------------------


def test_load_cached_directory_returns_empty_when_never_fetched(tmp_path):
    assert club_directory.load_cached_directory(tmp_path / "nope.json") == []


def test_save_then_load_round_trips(tmp_path):
    cache = tmp_path / "sub" / "club-directory.json"  # parent doesn't exist yet
    entries = [("0000001", "Golfclub Domäne Musterhausen e.V."), ("0491605", "1. Golfclub Leipzig e.V.")]
    club_directory.save_directory(entries, cache)

    assert club_directory.load_cached_directory(cache) == entries
    assert club_directory.cached_at(cache)  # a real ISO timestamp was stamped


def test_load_cached_directory_survives_a_corrupt_cache_file(tmp_path):
    # A half-written cache is an ordinary "you haven't fetched it yet" state, not
    # something worth crashing a launch over -- the picker still has favorites and
    # direct club ids to fall back on.
    cache = tmp_path / "club-directory.json"
    cache.write_text("{not json at all")
    assert club_directory.load_cached_directory(cache) == []
    assert club_directory.cached_at(cache) is None


def test_refresh_directory_fetches_and_caches(tmp_path, monkeypatch):
    cache = tmp_path / "club-directory.json"
    entries = [("0491605", "1. Golfclub Leipzig e.V.")]
    monkeypatch.setattr(
        club_directory, "fetch_club_directory", lambda club_id, user, password: entries
    )

    assert club_directory.refresh_directory("0000001", "user@example.com", "hunter2", cache) == entries
    assert json.loads(cache.read_text())["clubs"] == [["0491605", "1. Golfclub Leipzig e.V."]]


# --- search -------------------------------------------------------------------------


_DIRECTORY = [
    ("0352001", "Golf Club Grand Ducal de Luxembourg"),
    ("0491605", "1. Golfclub Leipzig e.V."),
    ("0000001", "Golfclub Domäne Musterhausen e.V."),
]


def test_search_is_case_insensitive_substring():
    assert club_directory.search(_DIRECTORY, "leipzig") == [("0491605", "1. Golfclub Leipzig e.V.")]


def test_search_blank_query_returns_nothing():
    # The picker shows favorites instead, rather than dumping 1300+ entries.
    assert club_directory.search(_DIRECTORY, "   ") == []


def test_search_respects_its_limit():
    assert len(club_directory.search(_DIRECTORY, "golf", limit=2)) == 2


# --- any_credentials ----------------------------------------------------------------


def test_any_credentials_returns_none_without_a_usable_favorite(monkeypatch):
    monkeypatch.setattr(club_directory.club_config, "list_clubs", lambda *a, **k: [])
    assert club_directory.any_credentials() is None


def test_any_credentials_skips_a_favorite_with_no_club_id(monkeypatch):
    monkeypatch.setattr(club_directory.club_config, "list_clubs", lambda *a, **k: ["broken", "good"])
    monkeypatch.setattr(
        club_directory.club_config,
        "load_club_config",
        lambda slug, *a, **k: {} if slug == "broken" else {"club_id": "0000001"},
    )
    monkeypatch.setattr(
        club_directory.club_config, "resolve_credentials", lambda slug: ("user@example.com", "hunter2")
    )
    assert club_directory.any_credentials() == ("0000001", "user@example.com", "hunter2")


def test_any_credentials_skips_a_favorite_whose_credentials_dont_resolve(monkeypatch):
    monkeypatch.setattr(club_directory.club_config, "list_clubs", lambda *a, **k: ["nocreds"])
    monkeypatch.setattr(
        club_directory.club_config, "load_club_config", lambda slug, *a, **k: {"club_id": "0000001"}
    )
    monkeypatch.setattr(club_directory.club_config, "resolve_credentials", lambda slug: ("", ""))
    assert club_directory.any_credentials() is None
