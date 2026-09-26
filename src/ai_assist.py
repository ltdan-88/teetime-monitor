"""AI-provider calls for the steps that are genuine judgment rather than exact logic
(see ROADMAP.md's "AI placement" note, and Phases 1/3/4/5).

Three entry points, one per kind of judgment call:
- `classify_booking_label()` (Phase 1) — one short string from a tee-sheet cell, in;
  one of a handful of categories, out. Revised 2026-09-05, replacing a much bigger
  `extract_schedule()` concept: a real walkthrough (see ROADMAP.md "Confirmed pc
  caddie markup reference") found that occupancy, time, and blocked-vs-normal are all
  cleanly deterministic CSS classes — plain code in scraper.py parses those directly,
  no AI involved. The one genuinely ambiguous piece left is telling an anonymized
  booking, an event/lesson/guest/sponsor block, an advance-booking-window notice, and
  an actual friend's real name apart, since new label wording could appear that hasn't
  been seen yet. A small, cheap classification, not a whole-page parse.
- `rank_slots()` (Phases 3/4) — ranks already-hard-filtered candidates (party size and
  time windows are exact checks done in search.py, not here) and writes the
  plain-language `SlotMatch.reasons`.
- `summarize_history()` (Phase 5) — crowd-prediction confidence for sparse day-types,
  and open-ended personal-stats commentary, over analytics.py's raw aggregated rows.

Every call here costs money and sends data (tee-sheet contents, preferences, aggregated
history) to whichever provider is configured — see ROADMAP.md "Known risks". `model`
remains a parameter on each function (a caller can still hand it a different model),
but each provider's entry in `_DEFAULT_MODELS` is no longer meant to imply "the safe,
general-purpose choice" — see `DEFAULT_MODEL`'s own comment below for why
`rank_slots()`'s actual task doesn't call for more than that.

**Multi-provider (2026-09-26)** — direct follow-up to shipping the credentials screen
(see `ai_credentials_screen.py`/`ai_login_cli.py`): originally Anthropic-only, since
that's what this whole app is built with, but a user setting up the credentials screen
naturally wants a real choice, not just a key field for one vendor. `provider` is now a
parameter on all three public functions, defaulting to `"anthropic"` so every existing
caller/test keeps working unchanged. Structured output (`classify_booking_label`,
`rank_slots`) and open-ended text (`summarize_history`) are each implemented once per
*provider shape*, not once per function: OpenAI and Grok share the exact same code path
(`_openai_compatible_structured`/`_openai_compatible_text`) since xAI's API is
OpenAI-compatible — Grok needs no SDK of its own, just the `openai` package pointed at
`base_url="https://api.x.ai/v1"` with its own `XAI_API_KEY`.

Implemented 2026-09-06 (Anthropic-only), tested against a mocked `anthropic.Anthropic`
client (no real API calls in the test suite — this genuinely costs money and needs a
real key, neither of which a unit test should depend on); extended 2026-09-26 to mock
`openai.OpenAI`/`google.genai.Client` the same way. `classify_booking_label()` and
`rank_slots()` use each provider's own structured-output mechanism (Anthropic:
`client.messages.parse()`; OpenAI/Grok: `client.chat.completions.parse()`; Gemini:
`client.models.generate_content()` with a `response_schema`) with no hand-written
response parsing; `summarize_history()` is open-ended text, so it uses each provider's
plain completion call instead — there's no fixed schema to hold open-ended commentary
to.
"""

import json
import os
import time
from typing import Literal

from pydantic import BaseModel

from . import weather as weather_module
from .models import SlotMatch


def _anthropic_module():
    """The `anthropic` package, imported on first real use rather than at import time.

    Measured 2026-09-17 while profiling startup: importing `anthropic` eagerly here cost
    **~200ms of a ~310ms `import src.tui`** — around two thirds of the app's entire
    import budget — and `src.recommend` imports this module unconditionally, so every
    launch paid it. AI ranking is off by default (`ai_assist.enabled`, see
    `settings_screen.py`), so the overwhelmingly common case was paying that cost in
    full for a library never called once.

    Deferring it means a default launch never imports `anthropic` at all, while the
    first actual call that needs it pays the import once and caches the module in this
    module's own globals for every call after it. `_openai_module()`/`_genai_module()`
    below (2026-09-26) follow the exact same shape for the same reason — three heavy
    SDKs now, not one, and a default launch (AI off, or AI on with Anthropic, the
    original and still most common case) shouldn't pay for the other two at all.

    A module-level `__getattr__` (below) keeps `ai_assist.anthropic` working as an
    attribute for anything that reaches for it that way — the test suite patches
    `ai_assist.anthropic.Anthropic` in exactly that style, and resolving it through
    here hands back the very same module object those patches land on."""
    global anthropic
    if "anthropic" not in globals():
        import anthropic  # noqa: PLC0415 -- deliberately deferred, see docstring
    return anthropic


def _openai_module():
    """The `openai` package — see `_anthropic_module()`'s docstring for why this is
    deferred the same way. Also backs Grok (`_client_for("grok")` below): xAI's API is
    OpenAI-compatible, so there's no separate xAI SDK to import."""
    global openai
    if "openai" not in globals():
        import openai  # noqa: PLC0415 -- deliberately deferred, see _anthropic_module()
    return openai


def _genai_module():
    """The `google.genai` package (Gemini) — see `_anthropic_module()`'s docstring for
    why this is deferred the same way."""
    global genai
    if "genai" not in globals():
        from google import genai  # noqa: PLC0415 -- deliberately deferred
    return genai


def __getattr__(name):
    """PEP 562 module-level attribute hook — see `_anthropic_module()` for why none of
    the three provider SDKs are plain module-level imports. Only ever fires for a name
    this module doesn't already define, so it costs nothing on the normal path."""
    if name == "anthropic":
        return _anthropic_module()
    if name == "openai":
        return _openai_module()
    if name == "genai":
        return _genai_module()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Changed from "claude-opus-5" to Haiku, 2026-09-09, direct feedback while wiring
# ai_assist.enabled into the settings screen: "Are you sure haiku is not good enough
# for this to work?" It's more than enough -- by the time rank_slots() ever runs,
# search.py/exclude_unplayable() have already thrown out every candidate that fails
# party size, time window, weather, and daylight; all that's left for the model is
# picking the best of an already-short, already-valid list and writing one short
# plain-language reason per pick. A small, structured, low-stakes task, not one that
# calls for a slower/pricier model -- opus-5 was never a deliberate quality
# requirement here, just an arbitrary starting default from this module's very first
# implementation, before there was a real cost-conscious user to weigh in. Direct
# follow-up once that was laid out plainly: "I would not even offer the other
# options, since they seem overkill" -- so settings_screen.py no longer exposes a
# model choice at all (see that module's own docstring for what was removed); `model`
# stays a parameter here for a caller that really wants something else, but nothing
# in this app hands it anything but each provider's own default any more.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# One cheap/fast default per provider (2026-09-26) -- same "small, low-stakes task"
# reasoning as DEFAULT_MODEL above, just picked once per vendor rather than assuming
# everyone wants Anthropic. Model names move fast and this project has no way to track
# every vendor's own lineup -- `model=` stays an override on every public function
# below (and `ai_assist.model` in preferences.yaml, same as always) for exactly the
# case where one of these goes stale before this comment does.
#
# Gemini uses "gemini-flash-latest" (2026-09-27 fix), not a pinned dated model, after
# a real user's first live test hit this directly: "gemini-2.5-flash" (this constant's
# original value) returned a 404 -- "no longer available to new users" -- confirmed
# against the real API the same day. A pinned snapshot name is exactly the kind of
# thing this comment already warned would go stale; the "-latest" alias exists
# specifically so this constant doesn't have to be hand-updated every time Google
# retires one. Confirmed live: classify_booking_label(), rank_slots(), and
# summarize_history() all returned real, valid results against a real (free-tier) key
# with this model.
_DEFAULT_MODELS = {
    "anthropic": DEFAULT_MODEL,
    "openai": "gpt-4.1-mini",
    "gemini": "gemini-flash-latest",
    "grok": "grok-4-fast",
}

# Which .env key each provider's credential lives under -- see ai_login_cli.py and
# ai_credentials_screen.py, both of which import this rather than hardcoding the
# mapping a second time.
PROVIDER_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "grok": "XAI_API_KEY",
}

PROVIDERS = tuple(PROVIDER_ENV_VARS)  # ("anthropic", "openai", "gemini", "grok")

# Names the model is asked to reply in -- kept separate from i18n.LANGUAGE_LABELS
# (that dict names the *UI's own* language picker in whatever language is currently
# selected, e.g. "Deutsch" while German is active, not a stable English name a prompt
# can rely on) even though the *codes* are the same set this app already supports.
_LANGUAGE_NAMES = {"en": "English", "de": "German"}


def _language_instruction(language: str) -> str:
    """One line appended to a prompt whose response is free-language prose shown
    directly to the user (`rank_slots`'s `reasons`, `summarize_history`'s answer) --
    added 2026-09-27, direct report right after AI ranking's first real end-to-end
    test: the UI is bilingual (English/German) but every prompt was hardcoded English
    with no instruction otherwise, so a German-language session still got English
    reasons back, unconditionally, regardless of `i18n.get_language()`. Not applied to
    `classify_booking_label()` -- its only outputs are a fixed English enum value and
    the verbatim input text, neither of which is prose generated for a person to read."""
    name = _LANGUAGE_NAMES.get(language, _LANGUAGE_NAMES["en"])
    return f"\n\nRespond in {name}."


def _client_for(provider: str):
    """Construct the right SDK client for `provider`. Grok is the `openai` package
    pointed at xAI's OpenAI-compatible endpoint with its own key -- not a separate SDK
    (see module docstring)."""
    if provider == "anthropic":
        return _anthropic_module().Anthropic()
    if provider == "openai":
        return _openai_module().OpenAI()
    if provider == "grok":
        return _openai_module().OpenAI(
            api_key=os.environ.get("XAI_API_KEY"), base_url="https://api.x.ai/v1"
        )
    if provider == "gemini":
        return _genai_module().Client(api_key=os.environ.get("GEMINI_API_KEY"))
    raise ValueError(f"unknown ai_assist provider: {provider!r}")


def _model_for(provider: str, model: str | None) -> str:
    if model is not None:
        return model
    try:
        return _DEFAULT_MODELS[provider]
    except KeyError:
        raise ValueError(f"unknown ai_assist provider: {provider!r}") from None


# Each SDK's own "the key itself was rejected" exception -- narrower than a bare
# `except Exception`, same reasoning login_cli.py separates scraper.LoginError (wrong
# credentials) from a generic network exception (transient, not proof the key is bad).
# Grok reuses openai's exception class since it's the same SDK. Resolved lazily inside
# verify_api_key() itself (not at import time) since it needs whichever module(s)
# _client_for() already imported for this provider.
#
# Gemini is the one provider where this needs a status-code check, not just a class
# check (2026-09-27 fix, found live): `google.genai.errors.ClientError` covers every
# 4xx response, 401/403 (a genuinely bad key) and 429 (a rate limit / quota) alike --
# unlike anthropic/openai, where `AuthenticationError` is already its own narrow class
# distinct from `RateLimitError`. Treating the whole `ClientError` class as
# "don't retry" was itself a bug: a real quota-exceeded 429 (confirmed live against a
# free-tier Gemini key -- "Please retry in 31s") was being treated exactly like a
# rejected key and never retried at all, even though the API's own response says
# retrying is the right move.
def _is_auth_failure(provider: str, exc: Exception) -> bool:
    if provider == "anthropic":
        return isinstance(exc, _anthropic_module().AuthenticationError)
    if provider in ("openai", "grok"):
        return isinstance(exc, _openai_module().AuthenticationError)
    if provider == "gemini":
        client_error = _genai_module().errors.ClientError
        return isinstance(exc, client_error) and getattr(exc, "code", None) in (401, 403)
    raise ValueError(f"unknown ai_assist provider: {provider!r}")


def _with_retry(provider: str, call):
    """Retry `call()` once, after a short pause, for anything except a genuine
    auth failure for `provider` -- added 2026-09-27, found live while building the
    GUI's Overview pick feature: Gemini's free tier returned a real `503 UNAVAILABLE`
    ("high demand") on roughly half of a real run of consecutive live calls, and
    this module had no retry anywhere, so one transient overload fell straight
    through to `recommend.ranked_matches()`'s own outer fallback (no reasons shown
    at all) even though the very next attempt, moments later, usually succeeded. A
    bad key fails identically no matter how many times it's retried, so that one
    case is excluded -- everything else (a busy server, a rate limit, a network
    hiccup) gets exactly one more try before this module gives up and lets the
    caller's own fallback take over. Note this can't help a genuinely exhausted
    *daily* quota (confirmed live the same day: a free-tier Gemini key's 20-request
    daily cap for one model) -- a 1.5s retry is only ever going to help a transient
    or short-lived limit, not one that only resets tomorrow."""
    try:
        return call()
    except Exception as exc:
        if _is_auth_failure(provider, exc):
            raise
        time.sleep(1.5)
        return call()


def _structured(client, provider: str, model: str, prompt: str, schema_cls: type[BaseModel]):
    """Provider-specific structured output, returning a validated `schema_cls`
    instance (or `None` if the provider genuinely returned nothing parseable) -- see
    module docstring for why OpenAI and Grok share one branch."""

    def call():
        if provider == "anthropic":
            response = client.messages.parse(
                model=model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema_cls,
            )
            return response.parsed_output
        if provider in ("openai", "grok"):
            response = client.chat.completions.parse(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format=schema_cls,
            )
            return response.choices[0].message.parsed
        if provider == "gemini":
            genai = _genai_module()
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    response_mime_type="application/json", response_schema=schema_cls
                ),
            )
            return response.parsed
        raise ValueError(f"unknown ai_assist provider: {provider!r}")

    return _with_retry(provider, call)


def _text(client, provider: str, model: str, prompt: str, max_tokens: int) -> str:
    """Provider-specific open-ended text completion -- see module docstring for why
    OpenAI and Grok share one branch."""

    def call():
        if provider == "anthropic":
            response = client.messages.create(
                model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}]
            )
            return "".join(block.text for block in response.content if block.type == "text")
        if provider in ("openai", "grok"):
            response = client.chat.completions.create(
                model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message.content or ""
        if provider == "gemini":
            response = client.models.generate_content(model=model, contents=prompt)
            return response.text or ""
        raise ValueError(f"unknown ai_assist provider: {provider!r}")

    return _with_retry(provider, call)


def verify_api_key(provider: str) -> tuple[bool, str | None]:
    """Validate `provider`'s currently-saved key with a live but free call --
    `models.list()` (Gemini: the same, just a lazy pager that needs one item pulled to
    actually hit the network) rather than a generation call, so saving a key on the
    credentials screen never itself costs money. Returns `(True, None)` on success,
    `(False, None)` if the key was rejected, or `(False, error)` for anything else
    (network hiccup, etc.) -- mirrors `login_cli.py`'s own three-way
    verified/rejected/network_error split."""
    try:
        client = _client_for(provider)
        if provider == "gemini":
            next(iter(client.models.list()), None)
        else:
            client.models.list()
    except Exception as exc:  # noqa: BLE001 -- a network hiccup isn't proof the key is bad
        if _is_auth_failure(provider, exc):
            return False, None
        return False, str(exc)
    return True, None


class BookingLabelClassification(BaseModel):
    """Structured-output shape for classify_booking_label().

    "anonymized" covers both confirmed anonymized-state texts: "Occupied" (logged in,
    not a friend) and "Please login to see names" (not logged in at all) — both mean a
    member booking, name withheld, confirmed identical wording across every pc caddie
    club checked. "advance_booking_window" means the slot isn't real occupancy at all —
    just not open for booking yet (see ROADMAP.md "Known risks") — scraper.py should
    set Slot.block_reason, not count it toward `booked`. "event_or_lesson_block" and
    "guest_block" also set block_reason, using `raw_text` as the reason. "friend_name"
    means `raw_text` is an actual person's name — goes into Slot.players.
    """

    label: Literal[
        "anonymized",
        "advance_booking_window",
        "event_or_lesson_block",
        "guest_block",
        "friend_name",
    ]
    raw_text: str


_CLASSIFY_PROMPT = """You classify one short text label taken from a golf club's tee-sheet booking table. Categories:
- anonymized: a placeholder shown instead of a real name because the site hides names (e.g. "Occupied", "Belegt", "Namensanzeige nach dem Login", "Please login to see names")
- advance_booking_window: a notice that the slot isn't bookable yet because it's too far in advance (e.g. "4 Tage im Voraus ab 20 Uhr buchbar")
- event_or_lesson_block: an event, tournament, or lesson name occupying the slot (e.g. "Golf Beginner Kurs", "FC 110 After Work (E)")
- guest_block: a slot reserved for guests (e.g. "Gäste")
- friend_name: an actual person's real name, not matching any of the above

Classify this label: {text!r}"""


def classify_booking_label(text: str, provider: str = "anthropic", model: str | None = None) -> BookingLabelClassification:
    """Classify one tee-sheet booking-cell label (see the module docstring).

    Only reached as a fallback for a genuinely novel label — see scraper.py's
    KNOWN_ANONYMIZED_LABELS and STATUS_* constants for the deterministic path that
    covers everything observed live so far.
    """
    client = _client_for(provider)
    parsed = _structured(client, provider, _model_for(provider, model), _CLASSIFY_PROMPT.format(text=text), BookingLabelClassification)
    if parsed is None:
        raise ValueError(f"{provider} did not return a parseable classification for {text!r}")
    # raw_text is set from the actual input, not whatever the model echoed back --
    # exact fidelity matters more here than trusting it to reproduce it verbatim.
    return BookingLabelClassification(label=parsed.label, raw_text=text)


class _RankedSlot(BaseModel):
    """One ranked candidate, keyed back to its position in the input list — simpler
    and more robust than asking the model to echo the date/course/time exactly."""

    index: int
    score: float  # 0-100, higher is better
    reasons: list[str]


class _SlotRanking(BaseModel):
    ranked: list[_RankedSlot]


def _describe_candidate(index: int, candidate: SlotMatch, context: dict) -> str:
    slot = candidate.slot
    open_spots = slot.capacity - slot.booked
    friends = ", ".join(slot.players) if slot.players else "none"
    line = (
        f"[{index}] {candidate.date} {candidate.course} at {slot.time} — "
        f"{open_spots} open spot(s) of {slot.capacity}, friends already booked: {friends}"
    )

    schedule = context.get("schedules", {}).get((candidate.date, candidate.course))
    if schedule is not None:
        duration = context.get("round_duration_minutes", 240)
        conditions = weather_module.conditions_during_round(schedule.weather, slot.time, duration)
        if conditions is not None:
            line += (
                f", rain up to {conditions.max_precipitation_probability}% / "
                f"{conditions.max_precipitation_mm}mm, wind up to {conditions.max_wind_speed_kph}kph, "
                f"{conditions.min_temperature_c}-{conditions.max_temperature_c}°C during the round"
            )

    # Only present at all once `ai_assist.avoid_predicted_crowd` is on (recommend.py
    # skips the analytics.crowd_heatmap() work entirely otherwise -- see
    # ranked_matches()'s own `crowd_estimates` docstring) -- added 2026-09-10, the
    # actual data behind that preference, which previously reached this prompt with
    # nothing for the model to act on.
    estimate = context.get("crowd_estimates", {}).get((candidate.date, candidate.course, slot.time))
    if estimate is not None:
        line += f", historically ~{estimate:.0%} full at this time"
    return line


def rank_slots(
    candidates: list[SlotMatch],
    context: dict,
    preferences: dict,
    provider: str = "anthropic",
    model: str | None = None,
    language: str = "en",
) -> list[SlotMatch]:
    """Rank already-hard-filtered candidates (score/reasons not yet set by search.py)
    and return them sorted best-first with `reasons` filled in.

    `context` may optionally carry `schedules` (a `{(date, course): Schedule}` dict)
    and `round_duration_minutes` to describe weather to the model — recommend.py's
    exclude_unplayable() already filtered out anything unplayable, so this is purely
    about the nuanced trade-offs *between* candidates that all already passed that
    check (e.g. "slightly more rain but much emptier"), not a second playability pass.

    `language` (2026-09-27) is an `i18n.py` language code -- see
    `_language_instruction()`'s own docstring for why `reasons` needs this at all.
    """
    if not candidates:
        return []

    descriptions = "\n".join(_describe_candidate(i, c, context) for i, c in enumerate(candidates))
    prompt = (
        "Rank these already-hard-filtered golf tee times, best first, for someone with "
        f"these preferences: {json.dumps(preferences)}. Give each a 0-100 score and 1-3 "
        "short, plain-language reasons.\n\n" + descriptions + _language_instruction(language)
    )

    client = _client_for(provider)
    ranking = _structured(client, provider, _model_for(provider, model), prompt, _SlotRanking)
    if ranking is None:
        return candidates  # fall back to the unranked order rather than losing results

    ranked: list[SlotMatch] = []
    seen_indices: set[int] = set()
    for ranked_slot in sorted(ranking.ranked, key=lambda r: r.score, reverse=True):
        # Out-of-range and duplicate indices are both possible, real model mistakes --
        # a structured-output schema doesn't stop the model from mentioning the same
        # index twice, or one that doesn't exist. Both are just skipped here rather
        # than raising or letting a duplicate reference into the result twice.
        if 0 <= ranked_slot.index < len(candidates) and ranked_slot.index not in seen_indices:
            candidate = candidates[ranked_slot.index]
            candidate.score = ranked_slot.score
            candidate.reasons = ranked_slot.reasons
            ranked.append(candidate)
            seen_indices.add(ranked_slot.index)

    # Any candidate the response simply never mentioned -- found live 2026-09-10, a
    # dedicated bug hunt: an incomplete ranking (plausible once the candidate list is
    # long enough to brush against a token limit, or just an ordinary model omission)
    # used to make that candidate vanish from the result entirely, even though it
    # already passed every hard filter (party size, time window, weather, daylight)
    # before ever reaching this function. Appended here instead, unranked (score 0.0,
    # no reasons) but still visible -- matches recommend.exclude_unplayable()'s own
    # stated stance: silently dropping a candidate is a worse failure mode than
    # showing an unranked one.
    for index, candidate in enumerate(candidates):
        if index not in seen_indices:
            ranked.append(candidate)
    return ranked


def summarize_history(
    history_rows: list[dict],
    question: str,
    provider: str = "anthropic",
    model: str | None = None,
    language: str = "en",
) -> str:
    """Open-ended interpretation over analytics.py's raw aggregated rows — crowd
    prediction confidence for sparse day-types, or personal-stats commentary.

    `language` (2026-09-27) is an `i18n.py` language code -- see
    `_language_instruction()`'s own docstring for why this needs it."""
    if not history_rows:
        return "Not enough history yet to say."

    prompt = (
        "Given this aggregated golf tee-sheet history (as JSON rows), answer the "
        f"question in plain, friendly language, 2-3 sentences.\n\nQuestion: {question}"
        f"\n\nHistory: {json.dumps(history_rows)}" + _language_instruction(language)
    )
    client = _client_for(provider)
    return _text(client, provider, _model_for(provider, model), prompt, max_tokens=512)
