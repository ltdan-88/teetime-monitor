from src import calendar_context as calendar_module
from src.calendar_context import classify_day, fetch_public_holidays
from src.models import DateRange


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_public_holidays_parses_nager_date_response(monkeypatch):
    payload = [
        {"date": "2026-01-01", "localName": "Neujahr"},
        {"date": "2026-12-25", "localName": "Weihnachten"},
    ]

    captured_url = {}

    def fake_get(url, timeout):
        captured_url["url"] = url
        return _FakeResponse(payload)

    monkeypatch.setattr(calendar_module.httpx, "get", fake_get)

    holidays = fetch_public_holidays("AT", 2026)

    assert holidays == ["2026-01-01", "2026-12-25"]
    assert captured_url["url"] == "https://date.nager.at/api/v3/PublicHolidays/2026/AT"


def test_classify_day_tournament_takes_priority_over_everything():
    # A tournament on what would otherwise be a public holiday is still "tournament".
    result = classify_day(
        "2026-12-25", holidays=["2026-12-25"], vacation_ranges=[], has_tournament=True
    )
    assert result == "tournament"


def test_classify_day_public_holiday():
    result = classify_day("2026-12-25", holidays=["2026-12-25"], vacation_ranges=[], has_tournament=False)
    assert result == "public_holiday"


def test_classify_day_vacation_range():
    ranges = [DateRange(start="2026-07-04", end="2026-09-15", label="summer break")]
    result = classify_day("2026-08-01", holidays=[], vacation_ranges=ranges, has_tournament=False)
    assert result == "vacation"


def test_classify_day_vacation_range_boundaries_inclusive():
    ranges = [DateRange(start="2026-07-04", end="2026-09-15", label="summer break")]
    assert classify_day("2026-07-04", [], ranges, False) == "vacation"
    assert classify_day("2026-09-15", [], ranges, False) == "vacation"
    assert classify_day("2026-09-16", [], ranges, False) == "workday"  # 2026-09-16 is a Wed


def test_classify_day_weekend():
    # 2026-09-12 is a Saturday.
    result = classify_day("2026-09-12", holidays=[], vacation_ranges=[], has_tournament=False)
    assert result == "weekend"


def test_classify_day_workday():
    # 2026-09-07 is a Monday.
    result = classify_day("2026-09-07", holidays=[], vacation_ranges=[], has_tournament=False)
    assert result == "workday"


def test_classify_day_holiday_takes_priority_over_weekend():
    # A Saturday that's also a public holiday should classify as the holiday.
    result = classify_day("2026-09-12", holidays=["2026-09-12"], vacation_ranges=[], has_tournament=False)
    assert result == "public_holiday"


# --- review fixes (2026-10-04) --------------------------------------------------------

_DE_2026 = [
    {"date": "2026-01-01", "localName": "Neujahr", "global": True, "counties": None},
    {"date": "2026-06-04", "localName": "Fronleichnam", "global": False, "counties": ["DE-BW", "DE-BY"]},
    {"date": "2026-10-31", "localName": "Reformationstag", "global": False, "counties": ["DE-BB", "DE-SN"]},
]


def test_fetch_public_holidays_drops_state_only_holidays_without_a_region(monkeypatch):
    monkeypatch.setattr(calendar_module.httpx, "get", lambda url, timeout: _FakeResponse(_DE_2026))

    assert fetch_public_holidays("DE", 2026) == ["2026-01-01"]


def test_fetch_public_holidays_keeps_the_regions_own_state_holidays(monkeypatch):
    monkeypatch.setattr(calendar_module.httpx, "get", lambda url, timeout: _FakeResponse(_DE_2026))

    # Fronleichnam is a holiday in Baden-Württemberg; Reformationstag is not.
    assert fetch_public_holidays("DE", 2026, region="DE-BW") == ["2026-01-01", "2026-06-04"]


def test_classify_day_accepts_unquoted_yaml_vacation_dates():
    # PyYAML loads an unquoted `start: 2026-07-04` as datetime.date, not a string.
    from src import yaml_util

    raw = yaml_util.safe_load("- {start: 2026-07-04, end: 2026-09-15}\n")[0]
    ranges = [DateRange(start=raw["start"], end=raw["end"])]

    assert classify_day("2026-08-01", [], ranges, False) == "vacation"
    assert classify_day("2026-09-16", [], ranges, False) == "workday"


def _slots(blocked_by, blocked, total):
    from src.models import Slot

    return [
        Slot(time=f"{8 + i // 6:02d}:{(i % 6) * 10:02d}", booked=0, capacity=4,
             block_reason=blocked_by if i < blocked else None)
        for i in range(total)
    ]


def test_is_tournament_day_ignores_routine_group_and_lesson_blocks():
    assert not calendar_module.is_tournament_day([], _slots(None, 0, 10))
    assert not calendar_module.is_tournament_day(["Dienstag-Ladies"], _slots("Dienstag-Ladies", 11, 85))
    assert not calendar_module.is_tournament_day(["Grundkurs", "Marco"], _slots("Grundkurs", 2, 60))
    assert not calendar_module.is_tournament_day(["Gäste"], _slots("Gäste", 4, 60))


def test_is_tournament_day_recognises_competition_names():
    for name in ["HP Golf Cup", "Vierer-Clubmeisterschaften", "Matchplay", "Club Championship", "Herbstturnier"]:
        assert calendar_module.is_tournament_day([name], _slots(name, 1, 60)), name


def test_is_tournament_day_counts_an_unnamed_event_that_takes_over_the_course():
    assert calendar_module.is_tournament_day(["Nippenburg Quick 9"], _slots("Nippenburg Quick 9", 30, 60))
    # An advance-booking notice also sets block_reason but is never an event.
    slots = _slots("4 Tage im Voraus buchbar", 50, 60)
    assert not calendar_module.is_tournament_day(["Montagsgolfer"], slots)
