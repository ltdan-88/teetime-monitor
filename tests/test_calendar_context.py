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
