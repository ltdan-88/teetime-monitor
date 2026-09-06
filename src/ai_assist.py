"""Claude API calls for the steps that are genuine judgment rather than exact logic
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
history) to Anthropic's API — see ROADMAP.md "Known risks". `model` is a parameter, not
hardcoded, because which model to spend on which call is a cost/quality tradeoff that's
the club config's call (`ai_assist.model` in the club's YAML) — this module doesn't
pick a cheaper model on its own.

Implemented 2026-09-06, tested against a mocked `anthropic.Anthropic` client (no real
API calls in the test suite — this genuinely costs money and needs a real key, neither
of which a unit test should depend on). `classify_booking_label()` and `rank_slots()`
use `client.messages.parse()` with a Pydantic `output_format`, validated structured
output with no hand-written response parsing; `summarize_history()` is open-ended text,
so it uses plain `client.messages.create()` instead — there's no fixed schema to hold
open-ended commentary to.
"""

import json
from typing import Literal

import anthropic
from pydantic import BaseModel

from . import weather as weather_module
from .models import SlotMatch

DEFAULT_MODEL = "claude-opus-5"


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


def classify_booking_label(text: str, model: str = DEFAULT_MODEL) -> BookingLabelClassification:
    """Classify one tee-sheet booking-cell label (see the module docstring).

    Only reached as a fallback for a genuinely novel label — see scraper.py's
    KNOWN_ANONYMIZED_LABELS and STATUS_* constants for the deterministic path that
    covers everything observed live so far.
    """
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": _CLASSIFY_PROMPT.format(text=text)}],
        output_format=BookingLabelClassification,
    )
    parsed = response.parsed_output
    if parsed is None:
        raise ValueError(f"Claude did not return a parseable classification for {text!r}")
    # raw_text is set from the actual input, not whatever Claude echoed back --
    # exact fidelity matters more here than trusting the model to reproduce it verbatim.
    return BookingLabelClassification(label=parsed.label, raw_text=text)


class _RankedSlot(BaseModel):
    """One ranked candidate, keyed back to its position in the input list — simpler
    and more robust than asking Claude to echo the date/course/time exactly."""

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
    return line


def rank_slots(
    candidates: list[SlotMatch], context: dict, preferences: dict, model: str = DEFAULT_MODEL
) -> list[SlotMatch]:
    """Rank already-hard-filtered candidates (score/reasons not yet set by search.py)
    and return them sorted best-first with `reasons` filled in.

    `context` may optionally carry `schedules` (a `{(date, course): Schedule}` dict)
    and `round_duration_minutes` to describe weather to Claude — recommend.py's
    exclude_unplayable() already filtered out anything unplayable, so this is purely
    about the nuanced trade-offs *between* candidates that all already passed that
    check (e.g. "slightly more rain but much emptier"), not a second playability pass.
    """
    if not candidates:
        return []

    descriptions = "\n".join(_describe_candidate(i, c, context) for i, c in enumerate(candidates))
    prompt = (
        "Rank these already-hard-filtered golf tee times, best first, for someone with "
        f"these preferences: {json.dumps(preferences)}. Give each a 0-100 score and 1-3 "
        "short, plain-language reasons.\n\n" + descriptions
    )

    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
        output_format=_SlotRanking,
    )
    ranking = response.parsed_output
    if ranking is None:
        return candidates  # fall back to the unranked order rather than losing results

    ranked: list[SlotMatch] = []
    for ranked_slot in sorted(ranking.ranked, key=lambda r: r.score, reverse=True):
        if 0 <= ranked_slot.index < len(candidates):
            candidate = candidates[ranked_slot.index]
            candidate.score = ranked_slot.score
            candidate.reasons = ranked_slot.reasons
            ranked.append(candidate)
    return ranked


def summarize_history(history_rows: list[dict], question: str, model: str = DEFAULT_MODEL) -> str:
    """Open-ended interpretation over analytics.py's raw aggregated rows — crowd
    prediction confidence for sparse day-types, or personal-stats commentary."""
    if not history_rows:
        return "Not enough history yet to say."

    prompt = (
        "Given this aggregated golf tee-sheet history (as JSON rows), answer the "
        f"question in plain, friendly language, 2-3 sentences.\n\nQuestion: {question}"
        f"\n\nHistory: {json.dumps(history_rows)}"
    )
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")
