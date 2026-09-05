"""Local pattern-recognition + personal stats over accumulated scrape history
(ROADMAP.md Phase 5).

No AI/LLM calls, no external API, no cost — pure aggregation over the `scrapes` table
in storage.py. Needs a few weeks of accumulated history to be useful.

An opt-in AI-assisted mode (sending aggregated history to an LLM for natural-language
recommendations) is deliberately deferred to Phase 6 — see ROADMAP.md.

NOT YET IMPLEMENTED.
"""

from pathlib import Path

from .storage import DEFAULT_DB_PATH


def best_times_by_weekday(course: str, path: Path = DEFAULT_DB_PATH) -> dict[str, list[str]]:
    """Rank each weekday's time slots by historical average occupancy (emptiest first)."""
    raise NotImplementedError("analytics.py is a stub — see ROADMAP.md Phase 5")


def personal_stats(my_name: str, path: Path = DEFAULT_DB_PATH) -> dict:
    """Fun/useful numbers about your own play, spotted via `my_name` in scraped players.

    Starting point: days since you last played, total rounds logged. Expected to grow
    once there's real history to look at — see ROADMAP.md Phase 5.
    """
    raise NotImplementedError("analytics.py is a stub — see ROADMAP.md Phase 5")
