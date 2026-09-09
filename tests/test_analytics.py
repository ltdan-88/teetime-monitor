from src.analytics import (
    MIN_SAMPLES_FOR_PREDICTION,
    best_times_by_weekday,
    crowd_heatmap,
    heatmap_readiness,
    personal_stats,
    predict_crowding,
)
from src.calendar_context import SPECIAL_DAY_TYPES, WEEKDAYS
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
# Reworked 2026-09-09 to group by actual weekday (plus a separate special-days panel)
# rather than calendar_context.DAY_TYPES on one axis -- see analytics.py's module
# docstring for the mockup mismatch this fixes.


def test_crowd_heatmap_groups_ordinary_days_by_weekday_and_hour(tmp_path):
    db = tmp_path / "teetime.db"
    _save("18 Loch Tee 1", "2026-09-07", [Slot(time="09:30", booked=2, capacity=4)], path=db)  # Monday, workday
    _save("18 Loch Tee 1", "2026-09-12", [Slot(time="09:15", booked=4, capacity=4)], path=db)  # Saturday, weekend

    heatmap = crowd_heatmap("18 Loch Tee 1", holidays=[], vacation_ranges=[], path=db)

    # Grouped by actual weekday, not a coarse workday/weekend split.
    assert heatmap["by_weekday"]["Monday"]["09"]["average"] == 0.5
    assert heatmap["by_weekday"]["Monday"]["09"]["samples"] == 1
    assert heatmap["by_weekday"]["Saturday"]["09"]["average"] == 1.0
    assert heatmap["special_days"] == {}


def test_crowd_heatmap_tournament_day_goes_to_special_days_not_its_weekday(tmp_path):
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

    # The whole day counts as "tournament" (in special_days), not as a Saturday --
    # and the blocked 08:00 slot itself doesn't count as occupancy, only 09:00 does.
    assert "tournament" in heatmap["special_days"]
    assert heatmap["by_weekday"] == {}
    assert "08" not in heatmap["special_days"]["tournament"]
    assert heatmap["special_days"]["tournament"]["09"]["average"] == 0.5


def test_predict_crowding_returns_none_without_enough_samples(tmp_path):
    db = tmp_path / "teetime.db"
    _save("18 Loch Tee 1", "2026-09-07", [Slot(time="09:00", booked=2, capacity=4)], path=db)  # Monday

    heatmap = crowd_heatmap("18 Loch Tee 1", holidays=[], vacation_ranges=[], path=db)
    assert predict_crowding("Monday", "09:15", heatmap) is None  # only 1 sample


def test_predict_crowding_returns_average_once_enough_samples(tmp_path):
    db = tmp_path / "teetime.db"
    dates = ["2026-09-07", "2026-09-14", "2026-09-21"]  # 3 Mondays
    for date in dates:
        _save("18 Loch Tee 1", date, [Slot(time="09:00", booked=2, capacity=4)], path=db)

    heatmap = crowd_heatmap("18 Loch Tee 1", holidays=[], vacation_ranges=[], path=db)
    assert MIN_SAMPLES_FOR_PREDICTION == 3
    assert predict_crowding("Monday", "09:15", heatmap) == 0.5


def test_predict_crowding_checks_special_days_too(tmp_path):
    db = tmp_path / "teetime.db"
    for date in ["2026-01-01", "2026-05-01", "2026-12-25"]:  # 3 public holidays
        _save("18 Loch Tee 1", date, [Slot(time="09:00", booked=2, capacity=4)], path=db)

    heatmap = crowd_heatmap("18 Loch Tee 1", holidays=["2026-01-01", "2026-05-01", "2026-12-25"], vacation_ranges=[], path=db)
    assert predict_crowding("public_holiday", "09:15", heatmap) == 0.5


def test_predict_crowding_returns_none_for_unknown_key(tmp_path):
    assert predict_crowding("tournament", "09:00", {}) is None
    assert predict_crowding("Monday", "09:00", {}) is None


# --- heatmap_readiness ---------------------------------------------------------------
# Added 2026-09-08, direct request ("a menu to track how much data has been collected,
# and how much is still needed to be functional") ahead of building the heatmap screen.
# Reworked 2026-09-09 alongside crowd_heatmap() to report weekday/special-days
# readiness separately.


def test_heatmap_readiness_every_weekday_and_special_day_present_with_no_data_at_all():
    readiness = heatmap_readiness({})
    assert set(readiness) == {"by_weekday", "special_days"}
    assert set(readiness["by_weekday"]) == set(WEEKDAYS)
    assert set(readiness["special_days"]) == set(SPECIAL_DAY_TYPES)
    for stats in {**readiness["by_weekday"], **readiness["special_days"]}.values():
        assert stats == {"hours_seen": 0, "hours_ready": 0, "total_samples": 0}


def test_heatmap_readiness_counts_seen_vs_ready_hours():
    assert MIN_SAMPLES_FOR_PREDICTION == 3
    heatmap = {
        "by_weekday": {
            "Monday": {
                "09": {"average": 0.5, "samples": 3},  # ready
                "14": {"average": 0.2, "samples": 1},  # seen, not ready yet
            }
        },
        "special_days": {},
    }
    readiness = heatmap_readiness(heatmap)
    assert readiness["by_weekday"]["Monday"] == {"hours_seen": 2, "hours_ready": 1, "total_samples": 4}
    assert readiness["by_weekday"]["Tuesday"] == {"hours_seen": 0, "hours_ready": 0, "total_samples": 0}


def test_heatmap_readiness_fully_ready_special_day():
    heatmap = {
        "by_weekday": {},
        "special_days": {"tournament": {"10": {"average": 0.9, "samples": 5}, "11": {"average": 0.8, "samples": 4}}},
    }
    readiness = heatmap_readiness(heatmap)
    assert readiness["special_days"]["tournament"] == {"hours_seen": 2, "hours_ready": 2, "total_samples": 9}
