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
