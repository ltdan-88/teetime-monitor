import importlib

import dotenv

from src import club_config as club_config_module
from src.club_config import (
    list_clubs,
    load_club_config,
    new_club_stub,
    resolve_credentials,
    save_club_config,
)


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


def test_is_favorite_reflects_add_and_remove(tmp_path):
    assert club_config_module.is_favorite("0000001", tmp_path) is False
    club_config_module.add_favorite("0000001", "Musterhausen", tmp_path)
    assert club_config_module.is_favorite("0000001", tmp_path) is True
    club_config_module.remove_favorite("0000001", tmp_path)
    assert club_config_module.is_favorite("0000001", tmp_path) is False


def test_slugify_folds_umlauts_and_punctuation():
    assert club_config_module.slugify("Golfclub Domäne Musterhausen e.V.") == "golfclub-domane-musterhausen-e-v"
