import json

import pytest

from src import global_preferences, picks_cli
from src.models import Schedule, Slot
from src.storage import save_schedule


@pytest.fixture(autouse=True)
def _isolated_preferences(monkeypatch, tmp_path):
    monkeypatch.setattr(global_preferences, "PREFERENCES_FILE", tmp_path / "preferences.yaml")


def _run(capsys, argv):
    exit_code = 0
    try:
        picks_cli.main(argv)
    except SystemExit as exc:
        exit_code = exc.code
    return json.loads(capsys.readouterr().out), exit_code


def test_missing_db_path_or_course_is_rejected(capsys):
    result, code = _run(capsys, ["--course", "18 Loch Tee 1"])
    assert result == {"error": "missing --db-path or --course"}
    assert code == 1


def test_every_date_is_null_when_no_availability_is_configured(tmp_path, capsys):
    db = tmp_path / "club.db"
    save_schedule(Schedule(date="2026-09-27", course="18 Loch Tee 1", slots=[
        Slot(time="09:10", booked=0, capacity=4),
    ]), path=db)

    result, code = _run(
        capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-09-27", "--days", "2"]
    )

    assert code == 0
    assert result == {"2026-09-27": None, "2026-09-28": None}


def test_picks_the_best_playable_slot_for_each_date(tmp_path, capsys):
    global_preferences.save_preferences({"availability": {"weekend_window": {"after": None, "before": None}}})
    db = tmp_path / "club.db"
    # 2026-09-27 is a Sunday
    save_schedule(Schedule(date="2026-09-27", course="18 Loch Tee 1", slots=[
        Slot(time="09:10", booked=0, capacity=4),
        Slot(time="18:00", booked=4, capacity=4),  # full -- shouldn't be picked
    ]), path=db)

    result, code = _run(
        capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-09-27", "--days", "1"]
    )

    assert code == 0
    assert result["2026-09-27"]["time"] == "09:10"
    assert result["2026-09-27"]["reasons"] == []  # ai_assist.enabled defaults to off


def test_null_for_a_date_with_no_schedule_scraped_yet(tmp_path, capsys):
    global_preferences.save_preferences({"availability": {"weekend_window": {"after": None, "before": None}}})
    db = tmp_path / "club.db"

    result, code = _run(
        capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-09-27", "--days", "1"]
    )

    assert code == 0
    assert result == {"2026-09-27": None}


def test_null_when_nothing_is_playable(tmp_path, capsys):
    global_preferences.save_preferences({"availability": {"weekend_window": {"after": None, "before": None}}})
    db = tmp_path / "club.db"
    save_schedule(Schedule(date="2026-09-27", course="18 Loch Tee 1", slots=[
        Slot(time="09:10", booked=4, capacity=4),  # full
    ]), path=db)

    result, code = _run(
        capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-09-27", "--days", "1"]
    )

    assert code == 0
    assert result == {"2026-09-27": None}


def test_ai_ranked_pick_includes_real_reasons_when_enabled(tmp_path, monkeypatch, capsys):
    global_preferences.save_preferences({
        "availability": {"weekend_window": {"after": None, "before": None}},
        "ai_assist": {"enabled": True},
    })
    db = tmp_path / "club.db"
    save_schedule(Schedule(date="2026-09-27", course="18 Loch Tee 1", slots=[
        Slot(time="09:10", booked=0, capacity=4),
    ]), path=db)

    from src import tui as tui_module

    def fake_rank_slots(candidates, context, preferences, provider, model, language):
        for c in candidates:
            c.score = 90.0
            c.reasons = ["dry", "calm"]
        return candidates

    monkeypatch.setattr(tui_module.recommend.ai_assist, "rank_slots", fake_rank_slots)

    result, code = _run(
        capsys, ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-09-27", "--days", "1"]
    )

    assert code == 0
    assert result["2026-09-27"] == {"time": "09:10", "score": 90.0, "reasons": ["dry", "calm"]}
