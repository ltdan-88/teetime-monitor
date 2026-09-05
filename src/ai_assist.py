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

NOT YET IMPLEMENTED. Once wired up, classify_booking_label() looks roughly like:

    import anthropic
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from .env
    response = client.messages.parse(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": f"Classify this tee-sheet booking label:\\n{text}"}],
        output_format=BookingLabelClassification,
    )
    return response.parsed_output

— structured output validated directly against the Pydantic model below, no hand-written
response parsing.
"""

from typing import Literal

from pydantic import BaseModel

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


def classify_booking_label(text: str, model: str = DEFAULT_MODEL) -> BookingLabelClassification:
    """Classify one tee-sheet booking-cell label (see the module docstring)."""
    raise NotImplementedError("ai_assist.py is a stub — see ROADMAP.md Phase 1")


def rank_slots(
    candidates: list[SlotMatch], context: dict, preferences: dict, model: str = DEFAULT_MODEL
) -> list[SlotMatch]:
    """Rank already-hard-filtered candidates (score/reasons not yet set by search.py)
    and return them sorted best-first with `reasons` filled in."""
    raise NotImplementedError("ai_assist.py is a stub — see ROADMAP.md Phases 3/4")


def summarize_history(history_rows: list[dict], question: str, model: str = DEFAULT_MODEL) -> str:
    """Open-ended interpretation over analytics.py's raw aggregated rows — crowd
    prediction confidence for sparse day-types, or personal-stats commentary."""
    raise NotImplementedError("ai_assist.py is a stub — see ROADMAP.md Phase 5")
