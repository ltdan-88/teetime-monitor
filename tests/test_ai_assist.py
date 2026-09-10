import pytest

from src import ai_assist
from src.ai_assist import (
    BookingLabelClassification,
    classify_booking_label,
    rank_slots,
    summarize_history,
)
from src.models import Schedule, Slot, SlotMatch, WeatherPoint

# Everything below is tested against a mocked anthropic.Anthropic client -- these calls
# genuinely cost money and need a real API key, neither of which a unit test should
# depend on.


class _FakeResponse:
    def __init__(self, parsed_output):
        self.parsed_output = parsed_output


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeCreateResponse:
    def __init__(self, text):
        self.content = [_FakeTextBlock(text)]


class _FakeMessages:
    def __init__(self, parse_result=None, create_result=None):
        self._parse_result = parse_result
        self._create_result = create_result
        self.parse_calls = []
        self.create_calls = []

    def parse(self, **kwargs):
        self.parse_calls.append(kwargs)
        return self._parse_result

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return self._create_result


class _FakeClient:
    def __init__(self, messages):
        self.messages = messages


def _candidate(date, course, time, booked=1, capacity=4, players=None):
    return SlotMatch(
        date=date,
        course=course,
        slot=Slot(time=time, booked=booked, capacity=capacity, players=players or []),
        score=0.0,
    )


# --- classify_booking_label --------------------------------------------------------


def test_classify_booking_label_returns_label_with_exact_raw_text(monkeypatch):
    # Claude might echo the text back slightly differently -- raw_text should come
    # from the actual input, not whatever it returned.
    fake_parsed = BookingLabelClassification(label="anonymized", raw_text="something else")
    messages = _FakeMessages(parse_result=_FakeResponse(fake_parsed))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda: _FakeClient(messages))

    result = classify_booking_label("Belegt")

    assert result.label == "anonymized"
    assert result.raw_text == "Belegt"


def test_classify_booking_label_raises_when_claude_returns_nothing(monkeypatch):
    messages = _FakeMessages(parse_result=_FakeResponse(None))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda: _FakeClient(messages))

    with pytest.raises(ValueError):
        classify_booking_label("some unseen text")


def test_classify_booking_label_passes_model_through(monkeypatch):
    fake_parsed = BookingLabelClassification(label="friend_name", raw_text="x")
    messages = _FakeMessages(parse_result=_FakeResponse(fake_parsed))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda: _FakeClient(messages))

    classify_booking_label("Max Mustermann", model="claude-haiku-4-5")

    assert messages.parse_calls[0]["model"] == "claude-haiku-4-5"


# --- rank_slots ---------------------------------------------------------------------


def test_rank_slots_empty_candidates_skips_the_api_call(monkeypatch):
    called = []
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda: called.append(True))

    assert rank_slots([], {}, {}) == []
    assert called == []


def test_rank_slots_orders_by_score_and_fills_reasons(monkeypatch):
    candidates = [
        _candidate("2026-09-07", "18 Loch Tee 1", "18:00"),
        _candidate("2026-09-08", "18 Loch Tee 1", "09:00"),
    ]
    ranking = ai_assist._SlotRanking(
        ranked=[
            ai_assist._RankedSlot(index=1, score=90, reasons=["dry", "empty"]),
            ai_assist._RankedSlot(index=0, score=40, reasons=["rain expected"]),
        ]
    )
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda: _FakeClient(messages))

    result = rank_slots(candidates, {}, {"avoid_rain": True})

    assert [c.slot.time for c in result] == ["09:00", "18:00"]
    assert result[0].score == 90
    assert result[0].reasons == ["dry", "empty"]


def test_rank_slots_falls_back_to_original_order_when_claude_returns_nothing(monkeypatch):
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00")]
    messages = _FakeMessages(parse_result=_FakeResponse(None))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda: _FakeClient(messages))

    result = rank_slots(candidates, {}, {})
    assert result == candidates


def test_rank_slots_ignores_an_out_of_range_index(monkeypatch):
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00")]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=5, score=90, reasons=["?"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda: _FakeClient(messages))

    result = rank_slots(candidates, {}, {})
    assert result == []


def test_rank_slots_includes_weather_when_schedule_context_given(monkeypatch):
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[],
        weather=[WeatherPoint(time="18:00", precipitation_probability=80)],
    )
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00")]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=50, reasons=["ok"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda: _FakeClient(messages))

    context = {
        "schedules": {("2026-09-07", "18 Loch Tee 1"): schedule},
        "round_duration_minutes": 240,
    }
    rank_slots(candidates, context, {})

    prompt = messages.parse_calls[0]["messages"][0]["content"]
    assert "rain up to 80%" in prompt


def test_rank_slots_omits_weather_without_schedule_context(monkeypatch):
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00")]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=50, reasons=["ok"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda: _FakeClient(messages))

    rank_slots(candidates, {}, {})

    prompt = messages.parse_calls[0]["messages"][0]["content"]
    assert "rain" not in prompt


def test_rank_slots_includes_crowd_estimate_when_given(monkeypatch):
    # Added 2026-09-10, the actual data behind `avoid_predicted_crowd` -- previously
    # that preference reached this same prompt with nothing for the model to act on
    # (recommend.py handed the flag through, but no candidate ever carried a real
    # crowd number).
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00")]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=50, reasons=["ok"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda: _FakeClient(messages))

    context = {"crowd_estimates": {("2026-09-07", "18 Loch Tee 1", "18:00"): 0.8}}
    rank_slots(candidates, context, {"avoid_predicted_crowd": True})

    prompt = messages.parse_calls[0]["messages"][0]["content"]
    assert "historically ~80% full" in prompt


def test_rank_slots_omits_crowd_estimate_without_one(monkeypatch):
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00")]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=50, reasons=["ok"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda: _FakeClient(messages))

    rank_slots(candidates, {}, {})

    prompt = messages.parse_calls[0]["messages"][0]["content"]
    assert "historically" not in prompt


# --- summarize_history ---------------------------------------------------------------


def test_summarize_history_returns_early_message_without_rows():
    assert summarize_history([], "when's it emptiest?") == "Not enough history yet to say."


def test_summarize_history_returns_claude_text(monkeypatch):
    messages = _FakeMessages(create_result=_FakeCreateResponse("Looks quietest on weekday mornings."))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda: _FakeClient(messages))

    result = summarize_history([{"day_type": "workday", "avg_occupancy": 0.2}], "when's it emptiest?")

    assert result == "Looks quietest on weekday mornings."
