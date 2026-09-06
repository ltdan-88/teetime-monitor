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
