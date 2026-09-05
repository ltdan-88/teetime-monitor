"""Claude API calls for the steps that are genuine judgment rather than exact logic
(see ROADMAP.md's "AI placement" note, and Phases 1/3/4/5).

Three entry points, one per kind of judgment call:
- `extract_schedule()` (Phase 1) — messy/varying tee-sheet HTML -> structured slot
  data. Replaces hand-mapped CSS selectors for the booking table itself (the
  login/navigation selectors stay in scraper.py — that part's stable and simple, not a
  parsing problem).
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

NOT YET IMPLEMENTED. Once wired up, extract_schedule() looks roughly like:

    import anthropic
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from .env
    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        messages=[{"role": "user", "content": f"Extract the tee sheet:\\n{html}"}],
        output_format=ExtractedSchedule,
    )
    return response.parsed_output

— structured output validated directly against the Pydantic model below, no hand-written
response parsing.
"""

from pydantic import BaseModel

from .models import SlotMatch

DEFAULT_MODEL = "claude-opus-5"


class ExtractedSlot(BaseModel):
    time: str
    booked: int
    capacity: int
    players: list[str] = []


class ExtractedSchedule(BaseModel):
    """Structured-output shape for extract_schedule(); scraper.py maps this onto
    models.Schedule."""

    slots: list[ExtractedSlot] = []
    events: list[str] = []
    available_courses: list[str] = []


def extract_schedule(html: str, model: str = DEFAULT_MODEL) -> ExtractedSchedule:
    """Turn scraped tee-sheet HTML into structured slot/event/course data."""
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
