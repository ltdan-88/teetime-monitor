"""Local pattern-recognition, crowd heatmap, and personal stats over accumulated scrape
history (ROADMAP.md Phase 5).

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


def crowd_heatmap(course: str, path: Path = DEFAULT_DB_PATH) -> dict:
    """Historical average occupancy, grouped by calendar_context.py's day-type tag and
    hour-of-day — e.g. {"public_holiday": {"09": 0.9, "14": 0.4, ...}, "workday": {...}}.

    Grouping by day-type rather than plain weekday is the point: a Monday during summer
    break isn't "a Monday," it's a vacation-day, and should be compared against other
    vacation-days. This is also what lets a *future* day (with no scrape history of its
    own) get a crowd estimate at all — classify it, then look up its day-type's pattern.
    """
    raise NotImplementedError("analytics.py is a stub — see ROADMAP.md Phase 5")


def predict_crowding(day_type: str, time: str, heatmap: dict) -> float | None:
    """Estimated occupancy (0-1) for a day-type + time, from a crowd_heatmap() result.

    None if there's not enough history for that day-type yet — rarer types like
    "public_holiday" will be thin for a while, and that's fine, not an error.
    """
    raise NotImplementedError("analytics.py is a stub — see ROADMAP.md Phase 5")
