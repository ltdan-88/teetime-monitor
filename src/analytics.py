"""Local pattern-recognition over accumulated scrape history (ROADMAP.md Phase 4).

No AI/LLM calls, no external API, no cost — pure aggregation over the `scrapes` table
in storage.py. Needs a few weeks of accumulated history to be useful.

An opt-in AI-assisted mode (sending aggregated history to an LLM for natural-language
recommendations) is deliberately deferred to Phase 5 — see ROADMAP.md.

NOT YET IMPLEMENTED.
"""

from pathlib import Path

from .storage import DEFAULT_DB_PATH


def best_times_by_weekday(course: str, path: Path = DEFAULT_DB_PATH) -> dict[str, list[str]]:
    """Rank each weekday's time slots by historical average occupancy (emptiest first)."""
    raise NotImplementedError("analytics.py is a stub — see ROADMAP.md Phase 4")
