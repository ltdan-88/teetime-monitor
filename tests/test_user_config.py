from src.user_config import load_value, save_value


def test_load_value_returns_none_when_file_missing(tmp_path):
    assert load_value("THEME", tmp_path / "config") is None


def test_load_value_returns_none_when_key_missing(tmp_path):
    config_file = tmp_path / "config"
    config_file.write_text("OTHER=value\n")
    assert load_value("THEME", config_file) is None


def test_save_and_load_round_trips(tmp_path):
    config_file = tmp_path / "config"
    save_value("THEME", "nord", config_file)
    assert load_value("THEME", config_file) == "nord"


def test_save_value_overwrites_in_place_not_duplicated(tmp_path):
    config_file = tmp_path / "config"
    save_value("THEME", "nord", config_file)
    save_value("THEME", "dracula", config_file)

    content = config_file.read_text()
    assert content.count("THEME=") == 1
    assert load_value("THEME", config_file) == "dracula"


def test_save_value_preserves_other_keys(tmp_path):
    config_file = tmp_path / "config"
    save_value("THEME", "nord", config_file)
    save_value("LANG", "de", config_file)

    assert load_value("THEME", config_file) == "nord"
    assert load_value("LANG", config_file) == "de"


def test_save_value_creates_parent_directory(tmp_path):
    config_file = tmp_path / "nested" / "dir" / "config"
    save_value("THEME", "gruvbox", config_file)
    assert load_value("THEME", config_file) == "gruvbox"
