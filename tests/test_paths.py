"""State now lives in fixed locations rather than the working directory (2026-09-17).

The move exists because a GUI front end launched from Finder gets `cwd = "/"` and so
can never find CWD-relative state -- see paths.py's own module docstring.
"""

import pytest

from src import paths


@pytest.fixture
def fixed_dirs(monkeypatch, tmp_path):
    """Point the module's own constants at a temporary pair of directories. Patching
    `paths.*` directly is right here (unlike in conftest.py, which patches consumers)
    because these tests exercise paths.py itself."""
    config, data = tmp_path / "config", tmp_path / "data"
    monkeypatch.setattr(paths, "CONFIG_DIR", config)
    monkeypatch.setattr(paths, "DATA_DIR", data)
    monkeypatch.setattr(paths, "CLUBS_DIR", config / "clubs")
    monkeypatch.setattr(paths, "ENV_FILE", config / ".env")
    monkeypatch.setattr(paths, "MANAGED_DIRS", (config, config / "clubs", data))
    return config, data


def _legacy_install(root):
    """A pre-move layout: clubs/, data/ and .env in one directory."""
    (root / "clubs").mkdir(parents=True)
    (root / "clubs" / "my-club.yaml").write_text("club_id: '0497758'\n")
    (root / "clubs" / "club.example.yaml").write_text("club_id: '<club_id>'\n")
    (root / "data").mkdir()
    (root / "data" / "0497758.db").write_bytes(b"sqlite-ish")
    (root / "data" / "club_directory.json").write_text("[]")
    (root / ".env").write_text("PCC_USER=me\n")
    return root


# --- resolution ---------------------------------------------------------------------


def test_every_state_path_is_absolute():
    # The whole point: nothing may depend on where the process was started.
    for path in (paths.CONFIG_DIR, paths.DATA_DIR, paths.CLUBS_DIR, paths.ENV_FILE):
        assert path.is_absolute()


def test_env_vars_override_both_directories(monkeypatch, tmp_path):
    import importlib

    monkeypatch.setenv("TEETIME_MONITOR_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("TEETIME_MONITOR_DATA_DIR", str(tmp_path / "dat"))
    reloaded = importlib.reload(paths)
    try:
        assert reloaded.CONFIG_DIR == tmp_path / "cfg"
        assert reloaded.DATA_DIR == tmp_path / "dat"
        assert reloaded.CLUBS_DIR == tmp_path / "cfg" / "clubs"
    finally:
        monkeypatch.undo()
        importlib.reload(paths)


def test_env_var_expands_a_tilde(monkeypatch):
    import importlib

    monkeypatch.setenv("TEETIME_MONITOR_DATA_DIR", "~/somewhere")
    reloaded = importlib.reload(paths)
    try:
        assert "~" not in str(reloaded.DATA_DIR)
        assert reloaded.DATA_DIR.is_absolute()
    finally:
        monkeypatch.undo()
        importlib.reload(paths)


# --- migration ----------------------------------------------------------------------


def test_needs_migration_only_when_there_is_old_state(fixed_dirs, tmp_path):
    empty = tmp_path / "unrelated"
    empty.mkdir()
    assert not paths.needs_migration(cwd=empty)
    assert paths.needs_migration(cwd=_legacy_install(tmp_path / "old"))


def test_needs_migration_is_false_once_clubs_are_already_set_up(fixed_dirs, tmp_path):
    config, _ = fixed_dirs
    (config / "clubs").mkdir(parents=True)
    (config / "clubs" / "existing.yaml").write_text("club_id: '1'\n")
    # Old state still present, but the new location is live -- must not fire again.
    assert not paths.needs_migration(cwd=_legacy_install(tmp_path / "old"))


def test_migration_copies_clubs_databases_and_credentials(fixed_dirs, tmp_path):
    config, data = fixed_dirs
    old = _legacy_install(tmp_path / "old")

    moved = paths.migrate_from(cwd=old)

    assert (config / "clubs" / "my-club.yaml").read_text() == "club_id: '0497758'\n"
    assert (data / "0497758.db").read_bytes() == b"sqlite-ish"
    assert (data / "club_directory.json").exists()
    assert (config / ".env").read_text() == "PCC_USER=me\n"
    assert any("my-club" in m for m in moved)
    assert any("credentials" in m for m in moved)


def test_migration_skips_the_bundled_example_club(fixed_dirs, tmp_path):
    config, _ = fixed_dirs
    paths.migrate_from(cwd=_legacy_install(tmp_path / "old"))
    # club.example.yaml is a repo template, not anyone's saved club -- copying it
    # would show up as a bogus favorite named "club.example".
    assert not (config / "clubs" / "club.example.yaml").exists()


def test_migration_copies_rather_than_moves(fixed_dirs, tmp_path):
    """The originals must survive -- a database here is the only copy of scrape
    history that pc caddie itself can no longer reproduce."""
    old = _legacy_install(tmp_path / "old")
    paths.migrate_from(cwd=old)
    assert (old / "data" / "0497758.db").exists()
    assert (old / "clubs" / "my-club.yaml").exists()
    assert (old / ".env").exists()


def test_migration_never_overwrites_an_existing_destination(fixed_dirs, tmp_path):
    config, data = fixed_dirs
    paths.ensure_dirs()
    (data / "0497758.db").write_bytes(b"newer-real-data")
    (config / ".env").write_text("PCC_USER=current\n")

    paths.migrate_from(cwd=_legacy_install(tmp_path / "old"))

    assert (data / "0497758.db").read_bytes() == b"newer-real-data"
    assert (config / ".env").read_text() == "PCC_USER=current\n"


def test_migration_is_idempotent(fixed_dirs, tmp_path):
    old = _legacy_install(tmp_path / "old")
    first = paths.migrate_from(cwd=old)
    second = paths.migrate_from(cwd=old)
    assert first  # something happened the first time
    assert second == []  # and nothing the second


def test_migrated_credentials_are_not_world_readable(fixed_dirs, tmp_path):
    config, _ = fixed_dirs
    old = _legacy_install(tmp_path / "old")
    (old / ".env").chmod(0o644)  # the old layout didn't enforce anything

    paths.migrate_from(cwd=old)

    assert (config / ".env").stat().st_mode & 0o077 == 0


def test_migration_ignores_files_that_are_not_real_state(fixed_dirs, tmp_path):
    _, data = fixed_dirs
    old = _legacy_install(tmp_path / "old")
    (old / "data" / "0497758.db-wal").write_bytes(b"journal")
    (old / "data" / "notes.txt").write_text("scratch")

    paths.migrate_from(cwd=old)

    assert not (data / "0497758.db-wal").exists()
    assert not (data / "notes.txt").exists()


def test_ensure_dirs_is_safe_to_call_twice(fixed_dirs):
    paths.ensure_dirs()
    paths.ensure_dirs()
    for directory in paths.MANAGED_DIRS:
        assert directory.is_dir()
