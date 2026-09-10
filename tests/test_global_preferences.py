from src import global_preferences


def test_load_preferences_returns_empty_when_never_saved(tmp_path):
    assert global_preferences.load_preferences(tmp_path / "nope.yaml") == {}


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "sub" / "preferences.yaml"  # parent doesn't exist yet
    config = {"availability": {"min_open_spots": 3}, "preferences": {"avoid_rain": True}}

    global_preferences.save_preferences(config, path)

    assert global_preferences.load_preferences(path) == config


def test_save_preferences_overwrites_existing_file(tmp_path):
    path = tmp_path / "preferences.yaml"
    global_preferences.save_preferences({"availability": {"min_open_spots": 1}}, path)
    global_preferences.save_preferences({"availability": {"min_open_spots": 5}}, path)

    assert global_preferences.load_preferences(path)["availability"]["min_open_spots"] == 5


def test_load_preferences_treats_an_empty_file_as_no_settings(tmp_path):
    path = tmp_path / "preferences.yaml"
    path.write_text("")
    assert global_preferences.load_preferences(path) == {}


# --- last active club -- added 2026-09-10, direct feedback: "when you launch
# teetime-monitor you are greeted with which club to select, then which course.
# I think this is redundant since you can now select club and courses from the
# overview." -------------------------------------------------------------------


def test_load_last_active_club_returns_none_when_never_saved(tmp_path):
    assert global_preferences.load_last_active_club(tmp_path / "user-config") is None


def test_save_then_load_last_active_club_round_trips(tmp_path):
    config_file = tmp_path / "user-config"
    global_preferences.save_last_active_club("0497758", "golfclub-domane-niederreutin-e-v", "18 Loch Tee 1", config_file)

    assert global_preferences.load_last_active_club(config_file) == {
        "club_id": "0497758",
        "slug": "golfclub-domane-niederreutin-e-v",
        "course": "18 Loch Tee 1",
    }


def test_save_last_active_club_with_no_slug_round_trips_to_none(tmp_path):
    # A club visited without ever being favorited -- slug is genuinely None, not
    # an empty string leaking back out as a falsy-but-not-None value.
    config_file = tmp_path / "user-config"
    global_preferences.save_last_active_club("0000002", None, "9 Loch Tee 1", config_file)

    result = global_preferences.load_last_active_club(config_file)
    assert result["slug"] is None
    assert result["club_id"] == "0000002"


def test_last_active_club_does_not_pollute_resolved_config_via_preferences_file(tmp_path):
    # Regression test for a real bug found live while building this exact feature:
    # last_active used to be stored inside PREFERENCES_FILE itself, which
    # _resolved_config() merges wholesale into every club's own config -- meaning
    # every resolved config anywhere in the app (recommend.py, scrape_once.py, ...)
    # would have silently picked up an irrelevant last_active key. Saving a last
    # active club must never touch (or appear in) the ordinary preferences file at
    # all.
    preferences_path = tmp_path / "preferences.yaml"
    user_config_path = tmp_path / "user-config"
    global_preferences.save_preferences({"availability": {"min_open_spots": 2}}, preferences_path)

    global_preferences.save_last_active_club("0497758", "home-club", "18 Loch Tee 1", user_config_path)

    assert global_preferences.load_preferences(preferences_path) == {"availability": {"min_open_spots": 2}}
    assert "last_active" not in global_preferences.load_preferences(preferences_path)
