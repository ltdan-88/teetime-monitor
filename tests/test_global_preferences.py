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
