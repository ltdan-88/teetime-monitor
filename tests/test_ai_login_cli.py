import io
import json

import pytest

from src import ai_login_cli, env_file, global_preferences


@pytest.fixture(autouse=True)
def _isolated_files(monkeypatch, tmp_path):
    # Mirrors test_login_cli.py's own fixture -- ai_login_cli reads/writes via
    # env_file's and global_preferences' module-level file constants (both resolved at
    # call time), so point both at throwaway files rather than touching the real
    # ~/.config/teetime-monitor/ files.
    monkeypatch.setattr(env_file, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(global_preferences, "PREFERENCES_FILE", tmp_path / "preferences.yaml")
    monkeypatch.setattr(ai_login_cli.paths, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ai_login_cli.paths, "MANAGED_DIRS", (tmp_path,))


def _run(monkeypatch, capsys, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    exit_code = 0
    try:
        ai_login_cli.main([])
    except SystemExit as exc:
        exit_code = exc.code
    return json.loads(capsys.readouterr().out), exit_code


def _mock_verify(monkeypatch, result):
    monkeypatch.setattr(ai_login_cli.ai_assist, "verify_api_key", lambda provider: result)


def test_missing_provider_is_rejected(monkeypatch, capsys):
    result, code = _run(monkeypatch, capsys, {"api_key": "sk-abc"})
    assert result == {"saved": False, "reason": "provider_required"}
    assert code == 1


def test_unknown_provider_is_rejected(monkeypatch, capsys):
    result, code = _run(monkeypatch, capsys, {"provider": "bing", "api_key": "sk-abc"})
    assert result == {"saved": False, "reason": "unknown_provider"}
    assert code == 1


def test_blank_key_with_no_existing_key_is_rejected(monkeypatch, capsys):
    result, code = _run(monkeypatch, capsys, {"provider": "openai", "api_key": ""})
    assert result == {"saved": False, "reason": "api_key_required"}
    assert code == 1
    assert env_file.load_env_value("OPENAI_API_KEY") is None


def test_bad_stdin_json_is_rejected(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    with pytest.raises(SystemExit) as excinfo:
        ai_login_cli.main([])
    assert excinfo.value.code == 1
    assert json.loads(capsys.readouterr().out) == {"saved": False, "reason": "bad_input"}


def test_saves_a_new_key_sets_it_as_the_active_provider_and_verifies(monkeypatch, capsys):
    _mock_verify(monkeypatch, (True, None))

    result, code = _run(monkeypatch, capsys, {"provider": "openai", "api_key": "sk-abc"})

    assert result == {"saved": True, "verified": True}
    assert code == 0
    assert env_file.load_env_value("OPENAI_API_KEY") == "sk-abc"
    assert global_preferences.load_preferences()["ai_assist"]["provider"] == "openai"


def test_rejected_key_reports_invalid_key_without_undoing_the_save(monkeypatch, capsys):
    _mock_verify(monkeypatch, (False, None))

    result, code = _run(monkeypatch, capsys, {"provider": "gemini", "api_key": "bad-key"})

    assert result == {"saved": True, "verified": False, "reason": "invalid_key"}
    assert code == 0
    # Same rule as login_cli.py: a rejected verification doesn't mean "don't write
    # what was typed."
    assert env_file.load_env_value("GEMINI_API_KEY") == "bad-key"


def test_network_hiccup_is_reported_separately_from_a_bad_key(monkeypatch, capsys):
    _mock_verify(monkeypatch, (False, "no network"))

    result, code = _run(monkeypatch, capsys, {"provider": "anthropic", "api_key": "sk-ant"})

    assert result == {
        "saved": True,
        "verified": False,
        "reason": "network_error",
        "error": "no network",
    }
    assert code == 0


def test_blank_key_with_an_existing_saved_key_switches_provider_without_rewriting_it(monkeypatch, capsys):
    env_file.set_env_values({"XAI_API_KEY": "already-saved"})
    prefs = {"ai_assist": {"enabled": True, "provider": "anthropic"}}
    global_preferences.save_preferences(prefs)
    seen_keys = []
    monkeypatch.setattr(
        ai_login_cli.ai_assist, "verify_api_key", lambda provider: (seen_keys.append(provider), (True, None))[1]
    )

    result, code = _run(monkeypatch, capsys, {"provider": "grok", "api_key": ""})

    assert result == {"saved": True, "verified": True}
    assert code == 0
    assert env_file.load_env_value("XAI_API_KEY") == "already-saved"  # untouched
    assert global_preferences.load_preferences()["ai_assist"]["provider"] == "grok"
    assert global_preferences.load_preferences()["ai_assist"]["enabled"] is True  # not clobbered
    assert seen_keys == ["grok"]


def test_effective_key_is_exported_to_the_environment_before_verifying(monkeypatch, capsys):
    # verify_api_key() builds its SDK client from os.environ, and this process never
    # loads .env itself -- a real regression this test guards against: saving a
    # brand-new key that never reaches os.environ before verification runs would
    # always look like "no key configured" to the SDK, not "verified".
    seen_env_values = []

    def fake_verify(provider):
        import os

        seen_env_values.append(os.environ.get("OPENAI_API_KEY"))
        return True, None

    monkeypatch.setattr(ai_login_cli.ai_assist, "verify_api_key", fake_verify)

    _run(monkeypatch, capsys, {"provider": "openai", "api_key": "sk-fresh"})

    assert seen_env_values == ["sk-fresh"]
