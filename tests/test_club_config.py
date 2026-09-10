import importlib

import dotenv
import pytest

from src import club_config as club_config_module
from src.club_config import (
    list_clubs,
    load_club_config,
    new_club_stub,
    resolve_credentials,
    save_club_config,
)


@pytest.fixture(autouse=True)
def _no_real_geocoding_by_default(monkeypatch):
    """`add_favorite()` (via `new_club_stub_with_location()`, added 2026-09-08) calls
    `geocode.find_club_location()` on every save -- every test here that calls
    `add_favorite()` with a real name would otherwise make a real network request to
    the live Nominatim service, same test-isolation gap already caught and fixed in
    test_club_picker.py. Defaults to "nothing found" (`None`) -- a test exercising
    the "location found" path overrides this locally."""
    monkeypatch.setattr(club_config_module.geocode, "find_club_location", lambda name: None)


def test_list_clubs_excludes_example_template(tmp_path):
    (tmp_path / "club.example.yaml").write_text("club_url: example\n")
    (tmp_path / "home-club.yaml").write_text("club_url: home\n")
    (tmp_path / "guest-club.yaml").write_text("club_url: guest\n")

    assert list_clubs(tmp_path) == ["guest-club", "home-club"]


def test_list_clubs_on_missing_dir_returns_empty():
    from pathlib import Path

    assert list_clubs(Path("/nonexistent/does/not/exist")) == []


def test_load_club_config_reads_yaml(tmp_path):
    (tmp_path / "home-club.yaml").write_text("club_url: 'https://example.test'\n")
    config = load_club_config("home-club", tmp_path)
    assert config["club_url"] == "https://example.test"


def test_list_clubs_load_club_config_and_save_club_config_honor_a_patched_clubs_dir(tmp_path, monkeypatch):
    # Regression test (2026-09-10, dedicated bug hunt): these three functions used to
    # take `clubs_dir: Path = CLUBS_DIR` -- a literal default frozen at import time --
    # while every other function in this file (slug_for_club_id, is_favorite,
    # add_favorite, remove_favorite) already resolved it at call time instead.
    # Monkeypatching the module's own CLUBS_DIR constant silently failed to reach any
    # of these three when called with no explicit clubs_dir, exactly the frozen-default
    # gotcha this project has been bitten by more than once elsewhere. Calling each
    # with no clubs_dir argument at all, after only patching CLUBS_DIR, is what
    # actually exercises the fix -- passing tmp_path explicitly (as every other test in
    # this file does) would pass even with the old buggy signatures.
    monkeypatch.setattr(club_config_module, "CLUBS_DIR", tmp_path)
    save_club_config("home-club", {"club_id": "0000001"})
    assert list_clubs() == ["home-club"]
    assert load_club_config("home-club")["club_id"] == "0000001"


def test_resolve_credentials_prefers_namespaced_over_plain(monkeypatch):
    monkeypatch.setenv("PCC_USER", "plain-user")
    monkeypatch.setenv("PCC_PASS", "plain-pass")
    monkeypatch.setenv("PCC_USER__home-club", "namespaced-user")
    monkeypatch.setenv("PCC_PASS__home-club", "namespaced-pass")

    assert resolve_credentials("home-club") == ("namespaced-user", "namespaced-pass")


def test_resolve_credentials_falls_back_to_plain(monkeypatch):
    monkeypatch.delenv("PCC_USER__guest-club", raising=False)
    monkeypatch.delenv("PCC_PASS__guest-club", raising=False)
    monkeypatch.setenv("PCC_USER", "plain-user")
    monkeypatch.setenv("PCC_PASS", "plain-pass")

    assert resolve_credentials("guest-club") == ("plain-user", "plain-pass")


def test_save_club_config_round_trips(tmp_path):
    config = {
        "club_id": "0000001",
        "availability": {"min_open_spots": 1, "buffer_minutes": 20},
        "preferences": {"avoid_rain": True, "avoid_temp_below_c": 5},
    }

    save_club_config("home-club", config, tmp_path)
    loaded = load_club_config("home-club", tmp_path)

    assert loaded == config


def test_save_club_config_overwrites_existing_file(tmp_path):
    save_club_config("home-club", {"club_id": "old"}, tmp_path)
    save_club_config("home-club", {"club_id": "new"}, tmp_path)

    assert load_club_config("home-club", tmp_path) == {"club_id": "new"}


def test_new_club_stub_fills_only_club_id():
    stub = new_club_stub("0000001")
    assert stub["club_id"] == "0000001"
    assert stub["default_course"] == ""
    assert stub["default_date"] == "today"


def test_new_club_stub_is_saveable_and_loadable(tmp_path):
    save_club_config("guest-club", new_club_stub("0352001"), tmp_path)
    assert load_club_config("guest-club", tmp_path)["club_id"] == "0352001"


def test_module_import_loads_dotenv(monkeypatch):
    # Regression test for a real bug found 2026-09-07: python-dotenv was a listed
    # dependency from day one, but nothing ever actually called load_dotenv() -- a
    # .env file only ever did anything if something else had already loaded it into
    # the environment first. Fixed by calling it at module import time (see
    # club_config.py's module docstring for why import time, not lazily inside
    # resolve_credentials()). Verified here by monkeypatching the underlying
    # dotenv.load_dotenv (not club_config's own reference to it, which gets rebound
    # by the `from dotenv import load_dotenv` line every reload) and reloading the
    # module -- a real call happening at import is what this regression actually is.
    calls = []
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: calls.append((a, k)))
    importlib.reload(club_config_module)
    assert len(calls) == 1


def test_module_import_resolves_dotenv_path_via_cwd(monkeypatch):
    # Regression test for a second, deeper instance of the exact gap the test above
    # already covers, found live 2026-09-10: plain load_dotenv() with no path
    # argument searches upward from the *calling frame's own file location*, not the
    # process's working directory -- for a real installed package (Homebrew, any pip
    # install), that frame is this very module, sitting deep in site-packages, and
    # walking up from there never reaches anywhere near a user's real .env. Invisible
    # in every bit of dev-repo testing this project ever did (pytest, a bare
    # `python -c`), since both fall back to (or coincidentally walk up through) a
    # directory that happens to have its own .env -- neither resembles how the real
    # installed binary actually runs. Confirmed live: the real Homebrew-installed
    # app, launched from a real user's home directory with real working credentials
    # already sitting in ~/.env, showed the credentials screen on every single
    # launch regardless -- os.environ never actually saw them. `find_dotenv
    # (usecwd=True)` searches from the process's actual cwd instead -- verified here
    # by checking find_dotenv() is actually asked for usecwd=True, and that its
    # result (not some other path) is what gets handed to load_dotenv().
    find_dotenv_calls = []
    monkeypatch.setattr(dotenv, "find_dotenv", lambda *a, **k: find_dotenv_calls.append(k) or "/fake/.env")
    load_dotenv_calls = []
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: load_dotenv_calls.append((a, k)))
    importlib.reload(club_config_module)
    assert find_dotenv_calls == [{"usecwd": True}]
    assert load_dotenv_calls == [(("/fake/.env",), {})]


# --- Favorites (2026-09-07): "saving clubs makes only sense in the sense of
# Favorites" -- a club is now reached by its numeric id, and a clubs/*.yaml is
# optional extra settings, not a precondition for looking at the club ----------------


def test_slug_for_club_id_finds_a_saved_club(tmp_path):
    (tmp_path / "home.yaml").write_text("club_id: '0000001'\n")
    assert club_config_module.slug_for_club_id("0000001", tmp_path) == "home"


def test_slug_for_club_id_returns_none_for_an_unsaved_club(tmp_path):
    # A club being visited without saving it -- a normal state now, not an error.
    (tmp_path / "home.yaml").write_text("club_id: '0000001'\n")
    assert club_config_module.slug_for_club_id("0352002", tmp_path) is None


def test_slug_for_club_id_ignores_an_unreadable_favorite(tmp_path):
    (tmp_path / "broken.yaml").write_text("club_id: [unclosed\n")
    (tmp_path / "home.yaml").write_text("club_id: '0000001'\n")
    assert club_config_module.slug_for_club_id("0000001", tmp_path) == "home"


def test_add_favorite_writes_a_stub_named_after_the_club(tmp_path):
    slug = club_config_module.add_favorite("0000001", "Golfclub Domäne Musterhausen e.V.", tmp_path)
    assert slug == "golfclub-domane-musterhausen-e-v"
    assert club_config_module.load_club_config(slug, tmp_path)["club_id"] == "0000001"


def test_add_favorite_is_idempotent(tmp_path):
    first = club_config_module.add_favorite("0000001", "Musterhausen", tmp_path)
    second = club_config_module.add_favorite("0000001", "Musterhausen", tmp_path)
    assert first == second
    assert club_config_module.list_clubs(tmp_path) == [first]  # no duplicate file


def test_add_favorite_falls_back_to_the_club_id_without_a_name(tmp_path):
    assert club_config_module.add_favorite("0000001", clubs_dir=tmp_path) == "club-0000001"


def test_add_favorite_avoids_clobbering_a_same_named_file(tmp_path):
    (tmp_path / "musterhausen.yaml").write_text("club_id: '0111111'\n")
    slug = club_config_module.add_favorite("0000001", "Musterhausen", tmp_path)
    assert slug == "musterhausen-2"
    assert club_config_module.load_club_config("musterhausen", tmp_path)["club_id"] == "0111111"


def test_remove_favorite_deletes_the_file_and_returns_the_slug(tmp_path):
    club_config_module.add_favorite("0000001", "Musterhausen", tmp_path)
    assert club_config_module.remove_favorite("0000001", tmp_path) == "musterhausen"
    assert club_config_module.list_clubs(tmp_path) == []


def test_remove_favorite_returns_none_for_an_unsaved_club(tmp_path):
    assert club_config_module.remove_favorite("0352002", tmp_path) is None


def test_add_favorite_fills_in_a_location_when_the_geocoder_finds_one(monkeypatch, tmp_path):
    # Real gap found and fixed 2026-09-08: this is the path tui.py's `f`-to-favorite
    # actually calls -- the app's everyday, one-keypress way to save a club -- which
    # originally built its own plain new_club_stub() and skipped the location lookup
    # entirely, even though club_picker.py's separate "search the whole directory"
    # screen already had it. Caught live: re-adding a club through `f` still showed
    # no weather forecast.
    monkeypatch.setattr(
        club_config_module.geocode, "find_club_location", lambda name: (50.1234567, 8.1234567)
    )
    slug = club_config_module.add_favorite("0000002", "Golf Club Sonnenberg e.V.", tmp_path)
    assert club_config_module.load_club_config(slug, tmp_path)["location"] == {
        "lat": 50.1234567,
        "lon": 8.1234567,
    }


def test_add_favorite_passes_the_clubs_own_name_to_the_geocoder(monkeypatch, tmp_path):
    seen_names = []
    monkeypatch.setattr(
        club_config_module.geocode, "find_club_location", lambda name: seen_names.append(name) or None
    )
    club_config_module.add_favorite("0000002", "Golf Club Sonnenberg e.V.", tmp_path)
    assert seen_names == ["Golf Club Sonnenberg e.V."]


def test_add_favorite_skips_geocoding_without_a_name(monkeypatch, tmp_path):
    # A club favorited by typed-in id alone (never seen in a directory search) has
    # no name to geocode with -- must not even attempt a lookup.
    def fail_if_called(name):
        raise AssertionError("should never be called without a name")

    monkeypatch.setattr(club_config_module.geocode, "find_club_location", fail_if_called)
    slug = club_config_module.add_favorite("0000002", clubs_dir=tmp_path)
    assert "location" not in club_config_module.load_club_config(slug, tmp_path)


def test_is_favorite_reflects_add_and_remove(tmp_path):
    assert club_config_module.is_favorite("0000001", tmp_path) is False
    club_config_module.add_favorite("0000001", "Musterhausen", tmp_path)
    assert club_config_module.is_favorite("0000001", tmp_path) is True
    club_config_module.remove_favorite("0000001", tmp_path)
    assert club_config_module.is_favorite("0000001", tmp_path) is False


def test_slugify_folds_umlauts_and_punctuation():
    assert club_config_module.slugify("Golfclub Domäne Musterhausen e.V.") == "golfclub-domane-musterhausen-e-v"
