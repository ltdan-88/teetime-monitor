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


@pytest.fixture(autouse=True)
def _fake_xai_key(monkeypatch):
    """`_client_for("grok")` refuses to build a client without XAI_API_KEY (the
    openai SDK would otherwise fall back to OPENAI_API_KEY). The fake clients
    below never use it."""
    monkeypatch.setenv("XAI_API_KEY", "test-xai-key")


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
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    result = classify_booking_label("Belegt")

    assert result.label == "anonymized"
    assert result.raw_text == "Belegt"


def test_classify_booking_label_raises_when_claude_returns_nothing(monkeypatch):
    messages = _FakeMessages(parse_result=_FakeResponse(None))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    with pytest.raises(ValueError):
        classify_booking_label("some unseen text")


def test_classify_booking_label_passes_model_through(monkeypatch):
    fake_parsed = BookingLabelClassification(label="friend_name", raw_text="x")
    messages = _FakeMessages(parse_result=_FakeResponse(fake_parsed))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

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
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    result = rank_slots(candidates, {}, {"avoid_rain": True})

    assert [c.slot.time for c in result] == ["09:00", "18:00"]
    assert result[0].score == 90
    assert result[0].reasons == ["dry", "empty"]


def test_rank_slots_falls_back_to_original_order_when_claude_returns_nothing(monkeypatch):
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00")]
    messages = _FakeMessages(parse_result=_FakeResponse(None))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    result = rank_slots(candidates, {}, {})
    assert result == candidates


def test_rank_slots_still_shows_a_candidate_behind_an_out_of_range_index(monkeypatch):
    # Regression test (2026-09-10, dedicated bug hunt): this used to assert
    # result == [] -- an out-of-range index used to make the one real, already
    # hard-filtered candidate vanish from the result entirely, rather than still
    # showing it (unranked) the way a candidate Claude never mentions at all now is.
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00")]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=5, score=90, reasons=["?"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    result = rank_slots(candidates, {}, {})
    assert result == candidates
    assert result[0].score == 0.0
    assert result[0].reasons == []


def test_rank_slots_appends_a_candidate_claude_never_mentioned(monkeypatch):
    # A candidate Claude's ranking simply omits (an incomplete response -- plausible
    # once the candidate list is long enough to brush against max_tokens, or just an
    # ordinary model omission) is still shown, appended after the ones it did rank,
    # rather than silently dropped.
    candidates = [
        _candidate("2026-09-07", "18 Loch Tee 1", "18:00"),
        _candidate("2026-09-08", "18 Loch Tee 1", "09:00"),
    ]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=90, reasons=["dry"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    result = rank_slots(candidates, {}, {})
    assert [c.slot.time for c in result] == ["18:00", "09:00"]
    assert result[0].score == 90
    assert result[1].score == 0.0
    assert result[1].reasons == []


def test_rank_slots_ignores_a_duplicate_index(monkeypatch):
    # A structured-output schema doesn't stop Claude from mentioning the same index
    # twice -- the second mention shouldn't add a duplicate reference to the result.
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00")]
    ranking = ai_assist._SlotRanking(
        ranked=[
            ai_assist._RankedSlot(index=0, score=90, reasons=["dry"]),
            ai_assist._RankedSlot(index=0, score=10, reasons=["wet"]),
        ]
    )
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    result = rank_slots(candidates, {}, {})
    assert len(result) == 1
    assert result[0].score == 90


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
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    context = {
        "schedules": {("2026-09-07", "18 Loch Tee 1"): schedule},
        "round_duration_minutes": 240,
    }
    rank_slots(candidates, context, {})

    prompt = messages.parse_calls[0]["messages"][0]["content"]
    assert "rain up to 80%" in prompt


def test_rank_slots_never_sends_player_names_to_the_ai_provider(monkeypatch):
    # Regression test (2026-09-27): scraper.py can now populate Slot.players with
    # real, authenticated-scrape names of other club members -- confirmed live the
    # same day. Sending that to whichever AI provider is configured would mean a real
    # third party's name leaving this machine without their knowledge, so
    # _describe_candidate() must never read slot.players into the prompt text.
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00", players=["Erika Mustermann", "Max Mustermann"])]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=50, reasons=["ok"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    rank_slots(candidates, {}, {})

    prompt = messages.parse_calls[0]["messages"][0]["content"]
    assert "Erika Mustermann" not in prompt
    assert "Max Mustermann" not in prompt
    assert "friends" not in prompt.lower()


def test_rank_slots_includes_a_friend_count_but_never_a_name(monkeypatch):
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00", players=["Erika Mustermann", "A Stranger"])]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=50, reasons=["ok"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    rank_slots(candidates, {"friend_names": {"Erika Mustermann"}}, {})

    prompt = messages.parse_calls[0]["messages"][0]["content"]
    assert "1 friend(s) already booked" in prompt
    assert "Erika Mustermann" not in prompt
    assert "A Stranger" not in prompt


def test_rank_slots_omits_the_friend_count_line_when_no_friend_is_in_the_slot(monkeypatch):
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00", players=["A Stranger"])]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=50, reasons=["ok"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    rank_slots(candidates, {"friend_names": {"Erika Mustermann"}}, {})

    prompt = messages.parse_calls[0]["messages"][0]["content"]
    assert "friend" not in prompt.lower()


def test_rank_slots_includes_avg_field_hcp_but_never_a_name(monkeypatch):
    # 2026-09-27, direct follow-up: "would it make sense to have the option to
    # choose to play with similar HCP or with better HCP" -- same "a number, never
    # a name" contract test_rank_slots_includes_a_friend_count_but_never_a_name
    # above already pins for friends.
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00", players=["Low Hcp", "High Hcp"])]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=50, reasons=["ok"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    rank_slots(candidates, {"known_handicaps": {"Low Hcp": 10.0, "High Hcp": 40.0}}, {})

    prompt = messages.parse_calls[0]["messages"][0]["content"]
    assert "avg field HCP 25.0" in prompt
    assert "Low Hcp" not in prompt
    assert "High Hcp" not in prompt


def test_rank_slots_omits_the_hcp_line_for_a_player_with_no_known_handicap(monkeypatch):
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00", players=["A Stranger"])]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=50, reasons=["ok"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    rank_slots(candidates, {"known_handicaps": {"Low Hcp": 10.0}}, {})

    prompt = messages.parse_calls[0]["messages"][0]["content"]
    assert "HCP" not in prompt


def test_rank_slots_omits_weather_without_schedule_context(monkeypatch):
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00")]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=50, reasons=["ok"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

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
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    context = {"crowd_estimates": {("2026-09-07", "18 Loch Tee 1", "18:00"): 0.8}}
    rank_slots(candidates, context, {"avoid_predicted_crowd": True})

    prompt = messages.parse_calls[0]["messages"][0]["content"]
    assert "historically ~80% full" in prompt


def test_rank_slots_omits_crowd_estimate_without_one(monkeypatch):
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00")]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=50, reasons=["ok"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    rank_slots(candidates, {}, {})

    prompt = messages.parse_calls[0]["messages"][0]["content"]
    assert "historically" not in prompt


# --- summarize_history ---------------------------------------------------------------


def test_rank_slots_asks_for_the_requested_language_in_the_prompt(monkeypatch):
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00")]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=50, reasons=["ok"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    rank_slots(candidates, {}, {}, language="de")

    prompt = messages.parse_calls[0]["messages"][0]["content"]
    assert "Respond in German." in prompt


def test_rank_slots_defaults_to_english_when_no_language_given(monkeypatch):
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00")]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=50, reasons=["ok"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    rank_slots(candidates, {}, {})

    prompt = messages.parse_calls[0]["messages"][0]["content"]
    assert "Respond in English." in prompt


def test_summarize_history_asks_for_the_requested_language_in_the_prompt(monkeypatch):
    messages = _FakeMessages(create_result=_FakeCreateResponse("Ruhig an Wochentagvormittagen."))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    summarize_history([{"day_type": "workday"}], "wann ist es am leersten?", language="de")

    prompt = messages.create_calls[0]["messages"][0]["content"]
    assert "Respond in German." in prompt


def test_summarize_history_returns_early_message_without_rows():
    assert summarize_history([], "when's it emptiest?") == "Not enough history yet to say."


def test_summarize_history_returns_claude_text(monkeypatch):
    messages = _FakeMessages(create_result=_FakeCreateResponse("Looks quietest on weekday mornings."))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    result = summarize_history([{"day_type": "workday", "avg_occupancy": 0.2}], "when's it emptiest?")

    assert result == "Looks quietest on weekday mornings."


# --- multi-provider (2026-09-26) -----------------------------------------------------
# OpenAI and Grok share one code path (_structured/_text's "openai"/"grok" branch --
# Grok is just the openai package pointed at xAI's OpenAI-compatible endpoint), so one
# parametrized fake client covers both rather than duplicating every case per provider.


class _FakeParsedMessage:
    def __init__(self, parsed):
        self.parsed = parsed
        self.content = None


class _FakeChoice:
    def __init__(self, message):
        self.message = message


class _FakeChatCompletionResponse:
    def __init__(self, message):
        self.choices = [_FakeChoice(message)]


class _FakeChatCompletions:
    def __init__(self, parse_result=None, create_content=None):
        self._parse_result = parse_result
        self._create_content = create_content
        self.parse_calls = []
        self.create_calls = []

    def parse(self, **kwargs):
        self.parse_calls.append(kwargs)
        return _FakeChatCompletionResponse(_FakeParsedMessage(self._parse_result))

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        message = _FakeParsedMessage(None)
        message.content = self._create_content
        return _FakeChatCompletionResponse(message)


class _FakeOpenAIClient:
    def __init__(self, chat):
        self.chat = _Namespace(completions=chat)


class _Namespace:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeGeminiResponse:
    def __init__(self, parsed=None, text=None):
        self.parsed = parsed
        self.text = text


class _FakeGeminiModels:
    def __init__(self, generate_result=None):
        self._generate_result = generate_result
        self.generate_calls = []

    def generate_content(self, **kwargs):
        self.generate_calls.append(kwargs)
        return self._generate_result


class _FakeGeminiClient:
    def __init__(self, models):
        self.models = models


@pytest.mark.parametrize("provider", ["openai", "grok"])
def test_classify_booking_label_openai_compatible_providers(monkeypatch, provider):
    fake_parsed = BookingLabelClassification(label="anonymized", raw_text="something else")
    chat = _FakeChatCompletions(parse_result=fake_parsed)
    monkeypatch.setattr(ai_assist.openai, "OpenAI", lambda **kwargs: _FakeOpenAIClient(chat))

    result = classify_booking_label("Belegt", provider=provider)

    assert result.label == "anonymized"
    assert result.raw_text == "Belegt"


def test_classify_booking_label_gemini(monkeypatch):
    fake_parsed = BookingLabelClassification(label="friend_name", raw_text="x")
    models = _FakeGeminiModels(generate_result=_FakeGeminiResponse(parsed=fake_parsed))
    monkeypatch.setattr(ai_assist.genai, "Client", lambda **kwargs: _FakeGeminiClient(models))

    result = classify_booking_label("Max Mustermann", provider="gemini")

    assert result.label == "friend_name"
    assert result.raw_text == "Max Mustermann"


@pytest.mark.parametrize("provider", ["openai", "grok"])
def test_rank_slots_openai_compatible_providers(monkeypatch, provider):
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00")]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=90, reasons=["dry"])])
    chat = _FakeChatCompletions(parse_result=ranking)
    monkeypatch.setattr(ai_assist.openai, "OpenAI", lambda **kwargs: _FakeOpenAIClient(chat))

    result = rank_slots(candidates, {}, {}, provider=provider)

    assert result[0].score == 90
    assert result[0].reasons == ["dry"]


def test_rank_slots_gemini(monkeypatch):
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00")]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=70, reasons=["ok"])])
    models = _FakeGeminiModels(generate_result=_FakeGeminiResponse(parsed=ranking))
    monkeypatch.setattr(ai_assist.genai, "Client", lambda **kwargs: _FakeGeminiClient(models))

    result = rank_slots(candidates, {}, {}, provider="gemini")

    assert result[0].score == 70


@pytest.mark.parametrize("provider", ["openai", "grok"])
def test_summarize_history_openai_compatible_providers(monkeypatch, provider):
    chat = _FakeChatCompletions(create_content="Quiet on weekday mornings.")
    monkeypatch.setattr(ai_assist.openai, "OpenAI", lambda **kwargs: _FakeOpenAIClient(chat))

    result = summarize_history([{"day_type": "workday"}], "when's it emptiest?", provider=provider)

    assert result == "Quiet on weekday mornings."


def test_summarize_history_gemini(monkeypatch):
    models = _FakeGeminiModels(generate_result=_FakeGeminiResponse(text="Quiet on weekday mornings."))
    monkeypatch.setattr(ai_assist.genai, "Client", lambda **kwargs: _FakeGeminiClient(models))

    result = summarize_history([{"day_type": "workday"}], "when's it emptiest?", provider="gemini")

    assert result == "Quiet on weekday mornings."


def test_model_for_unknown_provider_raises(monkeypatch):
    with pytest.raises(ValueError):
        ai_assist._model_for("bing", None)


# --- verify_api_key -------------------------------------------------------------------


class _FakeModelsListOK:
    def list(self):
        return ["a-model"]


class _FakeModelsListRaises:
    def __init__(self, exc):
        self._exc = exc

    def list(self):
        raise self._exc


@pytest.mark.parametrize("provider,attr", [("anthropic", "anthropic"), ("openai", "openai"), ("grok", "openai")])
def test_verify_api_key_ok(monkeypatch, provider, attr):
    fake_client = _Namespace(models=_FakeModelsListOK())
    module = getattr(ai_assist, attr)
    ctor = "Anthropic" if attr == "anthropic" else "OpenAI"
    monkeypatch.setattr(module, ctor, lambda **kwargs: fake_client)

    ok, error = ai_assist.verify_api_key(provider)

    assert ok is True
    assert error is None


def _fake_auth_error(module):
    # Both anthropic.AuthenticationError and openai.AuthenticationError are real
    # httpx-status-code-carrying exceptions, not plain str-message ones -- need a real
    # (fake) httpx.Response to construct one at all.
    import httpx

    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(401, request=request)
    return module.AuthenticationError("nope", response=response, body=None)


@pytest.mark.parametrize("provider,attr", [("anthropic", "anthropic"), ("openai", "openai"), ("grok", "openai")])
def test_verify_api_key_rejected(monkeypatch, provider, attr):
    module = getattr(ai_assist, attr)
    fake_client = _Namespace(models=_FakeModelsListRaises(_fake_auth_error(module)))
    ctor = "Anthropic" if attr == "anthropic" else "OpenAI"
    monkeypatch.setattr(module, ctor, lambda **kwargs: fake_client)

    ok, error = ai_assist.verify_api_key(provider)

    assert ok is False
    assert error is None


def test_verify_api_key_network_error_is_not_treated_as_a_bad_key(monkeypatch):
    fake_client = _Namespace(models=_FakeModelsListRaises(ConnectionError("timed out")))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: fake_client)

    ok, error = ai_assist.verify_api_key("anthropic")

    assert ok is False
    assert error == "timed out"


def test_verify_api_key_gemini_ok(monkeypatch):
    models = _Namespace(list=lambda: iter(["a-model"]))
    monkeypatch.setattr(ai_assist.genai, "Client", lambda **kwargs: _Namespace(models=models))

    ok, error = ai_assist.verify_api_key("gemini")

    assert ok is True
    assert error is None


# --- _with_retry -----------------------------------------------------------------


def test_with_retry_succeeds_on_the_second_attempt_after_a_transient_error(monkeypatch):
    monkeypatch.setattr(ai_assist.time, "sleep", lambda seconds: None)
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise ai_assist.genai.errors.ServerError(503, {"error": {"message": "busy"}})
        return "ok"

    result = ai_assist._with_retry("gemini", flaky)

    assert result == "ok"
    assert len(calls) == 2


def test_with_retry_does_not_retry_an_auth_error(monkeypatch):
    module = ai_assist.openai
    calls = []

    def always_fails():
        calls.append(1)
        raise _fake_auth_error(module)

    with pytest.raises(module.AuthenticationError):
        ai_assist._with_retry("openai", always_fails)
    assert len(calls) == 1  # no retry -- a bad key fails identically every time


def test_with_retry_raises_after_the_second_attempt_also_fails(monkeypatch):
    monkeypatch.setattr(ai_assist.time, "sleep", lambda seconds: None)
    calls = []

    def always_fails():
        calls.append(1)
        raise ai_assist.genai.errors.ServerError(503, {"error": {"message": "busy"}})

    with pytest.raises(ai_assist.genai.errors.ServerError):
        ai_assist._with_retry("gemini", always_fails)
    assert len(calls) == 2  # one real attempt, one retry, then give up


def test_rank_slots_recovers_from_one_transient_gemini_error(monkeypatch):
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00")]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=70, reasons=["ok"])])
    calls = []

    def flaky(**kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise ai_assist.genai.errors.ServerError(503, {"error": {"message": "busy"}})
        return _FakeGeminiResponse(parsed=ranking)

    models = _Namespace(generate_content=flaky)
    monkeypatch.setattr(ai_assist.genai, "Client", lambda **kwargs: _FakeGeminiClient(models))
    monkeypatch.setattr(ai_assist.time, "sleep", lambda seconds: None)

    result = rank_slots(candidates, {}, {}, provider="gemini")

    assert result[0].score == 70
    assert len(calls) == 2


def test_verify_api_key_gemini_rejected(monkeypatch):
    def raise_client_error():
        raise ai_assist.genai.errors.ClientError(401, {"error": {"message": "bad key"}})
        yield  # pragma: no cover -- makes this a generator, matching the real pager shape

    models = _Namespace(list=raise_client_error)
    monkeypatch.setattr(ai_assist.genai, "Client", lambda **kwargs: _Namespace(models=models))

    ok, error = ai_assist.verify_api_key("gemini")

    assert ok is False
    assert error is None


def test_verify_api_key_gemini_quota_exceeded_is_not_treated_as_a_bad_key(monkeypatch):
    # Regression test (2026-09-27, found live against a real free-tier key): a 429
    # RESOURCE_EXHAUSTED quota error is also a google.genai.errors.ClientError, same
    # as a 401/403 rejected key -- treating the whole class as "bad key" used to
    # mean a real quota error was reported identically to a wrong key, and (via
    # _with_retry) never even retried despite the API's own response saying to.
    def raise_quota_error():
        raise ai_assist.genai.errors.ClientError(429, {"error": {"message": "quota exceeded"}})
        yield  # pragma: no cover -- makes this a generator, matching the real pager shape

    models = _Namespace(list=raise_quota_error)
    monkeypatch.setattr(ai_assist.genai, "Client", lambda **kwargs: _Namespace(models=models))

    ok, error = ai_assist.verify_api_key("gemini")

    assert ok is False
    assert error is not None  # reported as a real error, not silently "key rejected"


def test_with_retry_retries_a_gemini_quota_error_not_just_503s(monkeypatch):
    monkeypatch.setattr(ai_assist.time, "sleep", lambda seconds: None)
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise ai_assist.genai.errors.ClientError(429, {"error": {"message": "quota exceeded"}})
        return "ok"

    result = ai_assist._with_retry("gemini", flaky)

    assert result == "ok"
    assert len(calls) == 2


# --- review fixes (2026-10-04) --------------------------------------------------------


def test_verify_api_key_gemini_invalid_key_400_is_treated_as_rejected(monkeypatch):
    # Gemini answers a mistyped key with 400 INVALID_ARGUMENT / API_KEY_INVALID, not
    # 401/403 -- it must read as "rejected", not as a network error.
    def raise_invalid_key():
        raise ai_assist.genai.errors.ClientError(
            400,
            {
                "error": {
                    "code": 400,
                    "message": "API key not valid. Please pass a valid API key.",
                    "status": "INVALID_ARGUMENT",
                    "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}],
                }
            },
        )
        yield  # pragma: no cover -- makes this a generator, matching the real pager shape

    models = _Namespace(list=raise_invalid_key)
    monkeypatch.setattr(ai_assist.genai, "Client", lambda **kwargs: _Namespace(models=models))

    assert ai_assist.verify_api_key("gemini") == (False, None)


def test_with_retry_still_retries_an_unrelated_gemini_400(monkeypatch):
    monkeypatch.setattr(ai_assist.time, "sleep", lambda seconds: None)
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise ai_assist.genai.errors.ClientError(400, {"error": {"message": "bad request"}})
        return "ok"

    assert ai_assist._with_retry("gemini", flaky) == "ok"
    assert len(calls) == 2


def test_with_retry_does_not_retry_a_timeout(monkeypatch):
    import httpx

    monkeypatch.setattr(ai_assist.time, "sleep", lambda seconds: None)
    calls = []

    def times_out():
        calls.append(1)
        raise httpx.ReadTimeout("stalled")

    with pytest.raises(httpx.ReadTimeout):
        ai_assist._with_retry("gemini", times_out)
    assert len(calls) == 1


def test_clients_are_built_with_an_explicit_timeout(monkeypatch):
    seen = {}
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: seen.setdefault("anthropic", kwargs))
    monkeypatch.setattr(ai_assist.openai, "OpenAI", lambda **kwargs: seen.setdefault("openai", kwargs))
    monkeypatch.setattr(ai_assist.genai, "Client", lambda **kwargs: seen.setdefault("gemini", kwargs))

    ai_assist._client_for("anthropic")
    ai_assist._client_for("openai")
    ai_assist._client_for("gemini")

    assert seen["anthropic"]["timeout"] == ai_assist.REQUEST_TIMEOUT_SECONDS
    assert seen["openai"]["timeout"] == ai_assist.REQUEST_TIMEOUT_SECONDS
    assert seen["gemini"]["http_options"].timeout == ai_assist.REQUEST_TIMEOUT_SECONDS * 1000


def test_grok_without_its_own_key_never_falls_back_to_the_openai_key(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-secret")
    built = []
    monkeypatch.setattr(ai_assist.openai, "OpenAI", lambda **kwargs: built.append(kwargs))

    with pytest.raises(ValueError, match="XAI_API_KEY"):
        ai_assist._client_for("grok")
    assert built == []  # no client (and so no request to api.x.ai) at all


def test_rank_slots_uses_the_per_course_round_duration(monkeypatch):
    # Rain at 18:00 is after a 2-hour round starting 15:00, so it must not reach the
    # prompt when the context says this course's round is 120 minutes.
    schedule = Schedule(
        date="2026-09-07",
        course="9 Loch Tee 1",
        slots=[],
        weather=[
            WeatherPoint(time="15:00", precipitation_probability=10),
            WeatherPoint(time="18:00", precipitation_probability=80),
        ],
    )
    candidates = [_candidate("2026-09-07", "9 Loch Tee 1", "15:00")]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=50, reasons=["ok"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    context = {
        "schedules": {("2026-09-07", "9 Loch Tee 1"): schedule},
        "round_duration_minutes": {"9 Loch Tee 1": 120},
    }
    rank_slots(candidates, context, {})

    prompt = messages.parse_calls[0]["messages"][0]["content"]
    assert "rain up to 10%" in prompt
    assert "80%" not in prompt


def test_rank_slots_leaves_out_weather_metrics_the_forecast_lacks(monkeypatch):
    schedule = Schedule(
        date="2026-09-07",
        course="18 Loch Tee 1",
        slots=[],
        weather=[WeatherPoint(time="18:00", precipitation_probability=30)],
    )
    candidates = [_candidate("2026-09-07", "18 Loch Tee 1", "18:00")]
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=50, reasons=["ok"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    rank_slots(candidates, {"schedules": {("2026-09-07", "18 Loch Tee 1"): schedule}}, {})

    prompt = messages.parse_calls[0]["messages"][0]["content"]
    assert "rain up to 30% during the round" in prompt
    assert "None" not in prompt


def test_rank_slots_reuses_a_cached_ranking_for_an_identical_prompt(monkeypatch):
    # The TUI re-ranks on every refresh and picks_cli runs as a fresh process per GUI
    # reload; an unchanged prompt must not reach the provider a second time.
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=70, reasons=["quiet"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    first = rank_slots([_candidate("2026-09-07", "18 Loch Tee 1", "18:00")], {}, {})
    second = rank_slots([_candidate("2026-09-07", "18 Loch Tee 1", "18:00")], {}, {})

    assert len(messages.parse_calls) == 1
    assert ai_assist._rank_cache_path().exists()
    assert first[0].reasons == second[0].reasons == ["quiet"]
    assert second[0].score == 70


def test_rank_slots_calls_the_provider_again_once_the_prompt_changes(monkeypatch):
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=70, reasons=["quiet"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    rank_slots([_candidate("2026-09-07", "18 Loch Tee 1", "18:00", booked=1)], {}, {})
    rank_slots([_candidate("2026-09-07", "18 Loch Tee 1", "18:00", booked=2)], {}, {})  # one spot fewer

    assert len(messages.parse_calls) == 2


def test_rank_slots_survives_a_corrupt_cache_file(monkeypatch):
    ai_assist._rank_cache_path().parent.mkdir(parents=True, exist_ok=True)
    ai_assist._rank_cache_path().write_text("{not json", encoding="utf-8")
    ranking = ai_assist._SlotRanking(ranked=[ai_assist._RankedSlot(index=0, score=70, reasons=["quiet"])])
    messages = _FakeMessages(parse_result=_FakeResponse(ranking))
    monkeypatch.setattr(ai_assist.anthropic, "Anthropic", lambda **kwargs: _FakeClient(messages))

    result = rank_slots([_candidate("2026-09-07", "18 Loch Tee 1", "18:00")], {}, {})

    assert result[0].reasons == ["quiet"]
    assert len(messages.parse_calls) == 1
