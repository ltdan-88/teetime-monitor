import io
import json

import pytest

from src import search_cli
from src.models import Schedule, Slot
from src.storage import save_schedule


def _run(monkeypatch, capsys, payload, argv):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    exit_code = 0
    try:
        search_cli.main(argv)
    except SystemExit as exc:
        exit_code = exc.code
    return json.loads(capsys.readouterr().out), exit_code


def test_finds_an_open_slot_matching_the_typed_criteria(tmp_path, monkeypatch, capsys):
    db = tmp_path / "club.db"
    # 2026-09-20 is a Sunday -- a weekend_window is what search()'s own
    # _window_for_date() needs; an omitted window for a day type means "skip that
    # day type entirely" (see SearchCriteria's own docstring), not "no restriction."
    save_schedule(Schedule(date="2026-09-20", course="18 Loch Tee 1", slots=[
        Slot(time="09:10", booked=0, capacity=4),
        Slot(time="18:00", booked=4, capacity=4),  # full -- shouldn't match
    ]), path=db)

    result, code = _run(
        monkeypatch, capsys,
        {"min_open_spots": 1, "weekend_window": {"after": None, "before": None}},
        ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-09-20", "--days", "1"],
    )

    assert code == 0
    assert len(result) == 1
    assert result[0]["date"] == "2026-09-20"
    assert result[0]["time"] == "09:10"
    assert result[0]["booked"] == 0
    assert result[0]["capacity"] == 4


def test_respects_min_open_spots(tmp_path, monkeypatch, capsys):
    db = tmp_path / "club.db"
    save_schedule(Schedule(date="2026-09-20", course="18 Loch Tee 1", slots=[
        Slot(time="09:10", booked=3, capacity=4),  # only 1 open spot
    ]), path=db)

    result, code = _run(
        monkeypatch, capsys,
        {"min_open_spots": 2, "weekend_window": {"after": None, "before": None}},
        ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-09-20", "--days", "1"],
    )

    assert code == 0
    assert result == []


def test_respects_weekday_window(tmp_path, monkeypatch, capsys):
    db = tmp_path / "club.db"
    # 2026-09-21 is a Monday.
    save_schedule(Schedule(date="2026-09-21", course="18 Loch Tee 1", slots=[
        Slot(time="09:10", booked=0, capacity=4),
        Slot(time="18:00", booked=0, capacity=4),
    ]), path=db)

    result, code = _run(
        monkeypatch, capsys, {"min_open_spots": 1, "weekday_window": {"after": "17:00", "before": None}},
        ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-09-21", "--days", "1"],
    )

    assert code == 0
    assert [m["time"] for m in result] == ["18:00"]


def test_skips_dates_with_nothing_scraped_yet(tmp_path, monkeypatch, capsys):
    db = tmp_path / "club.db"
    save_schedule(Schedule(date="2026-09-20", course="18 Loch Tee 1", slots=[
        Slot(time="09:10", booked=0, capacity=4),
    ]), path=db)

    result, code = _run(
        monkeypatch, capsys,
        {"min_open_spots": 1, "weekend_window": {"after": None, "before": None}},
        # 2026-09-21/22 have no scrape at all -- shouldn't error, just contribute nothing.
        ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-09-20", "--days", "3"],
    )

    assert code == 0
    assert len(result) == 1


def test_no_matches_is_a_valid_empty_result_not_an_error(tmp_path, monkeypatch, capsys):
    db = tmp_path / "club.db"
    save_schedule(Schedule(date="2026-09-20", course="18 Loch Tee 1", slots=[]), path=db)

    result, code = _run(
        monkeypatch, capsys, {"min_open_spots": 1},
        ["--db-path", str(db), "--course", "18 Loch Tee 1", "--from", "2026-09-20", "--days", "1"],
    )

    assert code == 0
    assert result == []


def test_missing_db_path_is_rejected(monkeypatch, capsys):
    result, code = _run(monkeypatch, capsys, {"min_open_spots": 1}, ["--course", "18 Loch Tee 1"])
    assert code == 1
    assert result == {"error": "missing --db-path or --course"}


def test_bad_stdin_json_is_rejected(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    with pytest.raises(SystemExit) as excinfo:
        search_cli.main(["--db-path", str(tmp_path / "club.db"), "--course", "18 Loch Tee 1"])
    assert excinfo.value.code == 1
    assert json.loads(capsys.readouterr().out) == {"error": "bad_input"}


def test_defaults_to_todays_date_and_six_days_when_omitted(tmp_path, monkeypatch, capsys):
    from datetime import date

    import src.search_cli as module

    captured_dates = []
    real_load = module.storage.load_latest_schedule

    def spy(course, one_date, path):
        captured_dates.append(one_date)
        return real_load(course, one_date, path=path)

    monkeypatch.setattr(module.storage, "load_latest_schedule", spy)
    db = tmp_path / "club.db"
    save_schedule(Schedule(date=date.today().isoformat(), course="18 Loch Tee 1", slots=[]), path=db)

    _run(monkeypatch, capsys, {"min_open_spots": 1}, ["--db-path", str(db), "--course", "18 Loch Tee 1"])

    assert len(captured_dates) == 6
    assert captured_dates[0] == date.today().isoformat()
