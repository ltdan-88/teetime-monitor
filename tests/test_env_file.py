import sys

import pytest

from src.env_file import load_env_value, set_env_values


def test_load_env_value_reads_existing_key(tmp_path):
    path = tmp_path / ".env"
    path.write_text("PCC_USER=someone@example.com\nPCC_PASS=hunter2\n")
    assert load_env_value("PCC_USER", path) == "someone@example.com"


def test_load_env_value_missing_file_returns_none(tmp_path):
    assert load_env_value("PCC_USER", tmp_path / "does-not-exist.env") is None


def test_load_env_value_missing_key_returns_none(tmp_path):
    path = tmp_path / ".env"
    path.write_text("PCC_USER=someone@example.com\n")
    assert load_env_value("PCC_PASS", path) is None


def test_load_env_value_ignores_commented_out_lines(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# PCC_USER=commented@example.com\nPCC_USER=real@example.com\n")
    assert load_env_value("PCC_USER", path) == "real@example.com"


def test_load_env_value_blank_value_treated_as_unset(tmp_path):
    path = tmp_path / ".env"
    path.write_text("PCC_USER=\n")
    assert load_env_value("PCC_USER", path) is None


def test_set_env_values_creates_file_from_template(tmp_path):
    path = tmp_path / ".env"
    template = tmp_path / ".env.example"
    template.write_text("# a helpful comment\nPCC_USER=\nPCC_PASS=\nANTHROPIC_API_KEY=\n")

    set_env_values({"PCC_USER": "someone@example.com", "PCC_PASS": "hunter2"}, path, template)

    content = path.read_text()
    assert "# a helpful comment" in content  # template comments survive
    assert "PCC_USER=someone@example.com" in content
    assert "PCC_PASS=hunter2" in content
    assert "ANTHROPIC_API_KEY=" in content  # untouched key stays, still blank


def test_set_env_values_updates_existing_file_in_place(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# my own note\nPCC_USER=old@example.com\nPCC_PASS=oldpass\nANTHROPIC_API_KEY=sk-real\n")

    set_env_values({"PCC_USER": "new@example.com"}, path)

    content = path.read_text()
    assert "# my own note" in content  # unrelated comment untouched
    assert "PCC_USER=new@example.com" in content
    assert "PCC_PASS=oldpass" in content  # untouched key survives
    assert "ANTHROPIC_API_KEY=sk-real" in content  # untouched key survives


def test_set_env_values_appends_key_not_already_present(tmp_path):
    path = tmp_path / ".env"
    path.write_text("PCC_USER=someone@example.com\n")

    set_env_values({"PCC_PASS": "hunter2"}, path)

    content = path.read_text()
    assert "PCC_USER=someone@example.com" in content
    assert "PCC_PASS=hunter2" in content


def test_set_env_values_skips_blank_values_leaving_existing_value_untouched(tmp_path):
    path = tmp_path / ".env"
    path.write_text("PCC_USER=someone@example.com\nPCC_PASS=hunter2\n")

    set_env_values({"PCC_USER": "someone@example.com", "PCC_PASS": ""}, path)

    assert load_env_value("PCC_PASS", path) == "hunter2"


def test_set_env_values_all_blank_is_a_no_op_on_missing_file(tmp_path):
    path = tmp_path / ".env"
    set_env_values({"PCC_USER": "", "PCC_PASS": ""}, path)
    assert not path.exists()


@pytest.mark.parametrize(
    "password",
    ["golf #1", "'quoted'", '"double"', "pa$${HOME}x", " spaced ", "back\\slash", "it's", "plain#hash", "sk-ant-abc"],
)
def test_saved_values_reach_load_dotenv_unchanged(tmp_path, password):
    """The login is verified against load_env_value(), but every later process gets
    its password from club_config's load_dotenv() -- both must see the exact string
    that was typed, or a verified login fails on the next scrape."""
    from dotenv import dotenv_values

    path = tmp_path / ".env"
    set_env_values({"PCC_USER": "me@example.com", "PCC_PASS": password}, path)

    assert load_env_value("PCC_PASS", path) == password
    assert dotenv_values(path, interpolate=False)["PCC_PASS"] == password
    assert "PCC_USER=me@example.com" in path.read_text()  # plain values stay bare for the GUI


def test_set_env_values_rejects_a_line_break_instead_of_injecting_a_key(tmp_path):
    path = tmp_path / ".env"
    with pytest.raises(ValueError):
        set_env_values({"PCC_PASS": "x\nHTTPS_PROXY=http://evil:8080"}, path)
    assert not path.exists()


@pytest.mark.parametrize("separator", ["\x0b", "\x0c", "\x1c", "\x85", " ", " "])
def test_set_env_values_rejects_other_line_separators(tmp_path, separator):
    """The file is re-read with str.splitlines() on the next save, which would split
    such a value across two lines -- reject it up front like a plain newline."""
    path = tmp_path / ".env"
    with pytest.raises(ValueError):
        set_env_values({"PCC_PASS": f"a{separator}b"}, path)
    assert not path.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no POSIX permission bits")
def test_set_env_values_keeps_credentials_private(tmp_path):
    path = tmp_path / ".env"
    set_env_values({"PCC_PASS": "hunter2"}, path)
    assert path.stat().st_mode & 0o777 == 0o600

    path.chmod(0o644)  # an older save, or a hand-made file
    set_env_values({"PCC_PASS": "hunter3"}, path)
    assert path.stat().st_mode & 0o777 == 0o600


def test_first_save_ignores_a_template_in_the_working_directory(tmp_path, monkeypatch):
    """The template used to be `./.env.example`, so a stray one wherever the command
    ran (a cloned repo, Downloads) was merged into the real credentials file."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.example").write_text("HTTPS_PROXY=http://attacker:8080\nPCC_USER=\n")
    path = tmp_path / "config" / ".env"
    path.parent.mkdir()

    set_env_values({"PCC_USER": "me@example.com"}, path)

    content = path.read_text()
    assert "HTTPS_PROXY" not in content
    assert "PCC_USER=me@example.com" in content
    assert "ANTHROPIC_API_KEY=" in content  # the built-in template's own keys
