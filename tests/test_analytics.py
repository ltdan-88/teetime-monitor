from src.analytics import (
    MIN_SAMPLES_FOR_PREDICTION,
    best_times_by_weekday,
    crowd_heatmap,
    personal_stats,
    predict_crowding,
)
from src.models import ConfirmedBooking, Schedule, Slot
from src.storage import save_confirmed_booking, save_schedule


def _save(course, date, slots, events=None, path=None):
    save_schedule(Schedule(date=date, course=course, slots=slots, events=events or []), path=path)


# --- best_times_by_weekday ----------------------------------------------------------


def test_best_times_by_weekday_empty_when_never_scraped(tmp_path):
    db = tmp_path / "teetime.db"
    assert best_times_by_weekday("18 Loch Tee 1", path=db) == {}


def test_best_times_by_weekday_ranks_emptiest_first(tmp_path):
    db = tmp_path / "teetime.db"
    # Both dates are Mondays.
    _save(
        "18 Loch Tee 1",
        "2026-08-31",
        [Slot(time="09:00", booked=3, capacity=4), Slot(time="18:00", booked=0, capacity=4)],
        path=db,
    )
    _save(
        "18 Loch Tee 1",
        "2026-09-07",
        [Slot(time="09:00", booked=4, capacity=4), Slot(time="18:00", booked=1, capacity=4)],
        path=db,
    )

    result = best_times_by_weekday("18 Loch Tee 1", path=db)

    assert result["Monday"] == ["18:00", "09:00"]  # 18:00 averages emptier


def test_best_times_by_weekday_excludes_blocked_slots(tmp_path):
    db = tmp_path / "teetime.db"
    _save(
        "18 Loch Tee 1",
        "2026-09-07",  # Monday
        [Slot(time="09:00", booked=4, capacity=4, block_reason="Golf Beginner Kurs")],
        path=db,
    )

    result = best_times_by_weekday("18 Loch Tee 1", path=db)
    assert result == {}


# --- personal_stats -------------------------------------------------------------------


def test_personal_stats_empty_when_never_confirmed(tmp_path):
    db = tmp_path / "teetime.db"
    stats = personal_stats("Max", path=db)
    assert stats == {
        "rounds_logged": 0,
        "days_since_last_played": None,
        "last_played": None,
        "rounds_with_visible_name": 0,
    }


def test_personal_stats_counts_rounds_and_days_since(tmp_path):
    from datetime import date, timedelta

    db = tmp_path / "teetime.db"
    earlier = (date.today() - timedelta(days=5)).isoformat()
    latest = (date.today() - timedelta(days=2)).isoformat()

    save_confirmed_booking(
        ConfirmedBooking(date=earlier, course="18 Loch Tee 1", time="14:00", source="manual", confirmed_at="t1"),
        path=db,
    )
    save_confirmed_booking(
        ConfirmedBooking(date=latest, course="18 Loch Tee 1", time="09:00", source="my_reservations", confirmed_at="t2"),
        path=db,
    )

    stats = personal_stats("Max", path=db)

    assert stats["rounds_logged"] == 2
    assert stats["last_played"] == latest
    assert stats["days_since_last_played"] == 2


def test_personal_stats_ignores_confirmed_not_playing(tmp_path):
    db = tmp_path / "teetime.db"
    save_confirmed_booking(
        ConfirmedBooking(date="2026-09-01", course="18 Loch Tee 1", time=None, source="manual", confirmed_at="t1"),
        path=db,
    )

    stats = personal_stats("Max", path=db)
    assert stats["rounds_logged"] == 0


def test_personal_stats_counts_visible_name(tmp_path):
    db = tmp_path / "teetime.db"
    save_confirmed_booking(
        ConfirmedBooking(date="2026-09-01", course="18 Loch Tee 1", time="14:00", source="manual", confirmed_at="t1"),
        path=db,
    )
    _save(
        "18 Loch Tee 1",
        "2026-09-01",
        [Slot(time="14:00", booked=1, capacity=4, players=["Max Mustermann"])],
        path=db,
    )

    stats = personal_stats("Max Mustermann", path=db)
    assert stats["rounds_with_visible_name"] == 1


# --- crowd_heatmap / predict_crowding ------------------------------------------------


def test_crowd_heatmap_groups_by_day_type_and_hour(tmp_path):
    db = tmp_path / "teetime.db"
    _save("18 Loch Tee 1", "2026-09-07", [Slot(time="09:30", booked=2, capacity=4)], path=db)  # Monday, workday
    _save("18 Loch Tee 1", "2026-09-12", [Slot(time="09:15", booked=4, capacity=4)], path=db)  # Saturday, weekend

    heatmap = crowd_heatmap("18 Loch Tee 1", holidays=[], vacation_ranges=[], path=db)

    assert heatmap["workday"]["09"]["average"] == 0.5
    assert heatmap["workday"]["09"]["samples"] == 1
    assert heatmap["weekend"]["09"]["average"] == 1.0


def test_crowd_heatmap_tournament_takes_priority_over_weekend(tmp_path):
    db = tmp_path / "teetime.db"
    _save(
        "18 Loch Tee 1",
        "2026-09-12",  # Saturday
        [
            Slot(time="08:00", booked=4, capacity=4, block_reason="Club Championship"),
            Slot(time="09:00", booked=2, capacity=4),  # a real, bookable slot the same day
        ],
        events=["Club Championship"],
        path=db,
    )

    heatmap = crowd_heatmap("18 Loch Tee 1", holidays=[], vacation_ranges=[], path=db)

    # The whole day is tagged "tournament" (not "weekend"), and the blocked 08:00 slot
    # itself doesn't count as occupancy -- only the real 09:00 slot contributes.
    assert "tournament" in heatmap
    assert "weekend" not in heatmap
    assert "08" not in heatmap["tournament"]
    assert heatmap["tournament"]["09"]["average"] == 0.5


def test_predict_crowding_returns_none_without_enough_samples(tmp_path):
    db = tmp_path / "teetime.db"
    _save("18 Loch Tee 1", "2026-09-07", [Slot(time="09:00", booked=2, capacity=4)], path=db)

    heatmap = crowd_heatmap("18 Loch Tee 1", holidays=[], vacation_ranges=[], path=db)
    assert predict_crowding("workday", "09:15", heatmap) is None  # only 1 sample


def test_predict_crowding_returns_average_once_enough_samples(tmp_path):
    db = tmp_path / "teetime.db"
    dates = ["2026-09-07", "2026-09-14", "2026-09-21"]  # 3 Mondays
    for date in dates:
        _save("18 Loch Tee 1", date, [Slot(time="09:00", booked=2, capacity=4)], path=db)

    heatmap = crowd_heatmap("18 Loch Tee 1", holidays=[], vacation_ranges=[], path=db)
    assert MIN_SAMPLES_FOR_PREDICTION == 3
    assert predict_crowding("workday", "09:15", heatmap) == 0.5


def test_predict_crowding_returns_none_for_unknown_day_type(tmp_path):
    db = tmp_path / "teetime.db"
    assert predict_crowding("tournament", "09:00", {}) is None
