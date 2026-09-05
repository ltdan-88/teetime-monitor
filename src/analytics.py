"""Local pattern-recognition, crowd heatmap, and personal stats over accumulated scrape
history (ROADMAP.md Phase 5).

Raw aggregation (`crowd_heatmap`, `best_times_by_weekday`, the fixed personal-stats
numbers) is plain SQL/code, no AI involved — grouping rows by day-type and hour is an
exact `GROUP BY`, not a judgment call, and it needs to produce real numbers to color a
heatmap grid. Interpreting *sparse or noisy* results (how much to trust a handful of
"public holiday" data points, or open-ended personal-stats commentary) goes through
`ai_assist.summarize_history()` instead — see ROADMAP.md's "AI placement" note.

Needs a few weeks of accumulated history to be useful.

NOT YET IMPLEMENTED.
"""

from pathlib import Path

from . import ai_assist
from .storage import DEFAULT_DB_PATH


def best_times_by_weekday(course: str, path: Path = DEFAULT_DB_PATH) -> dict[str, list[str]]:
    """Rank each weekday's time slots by historical average occupancy (emptiest first)."""
    raise NotImplementedError("analytics.py is a stub — see ROADMAP.md Phase 5")


def personal_stats(my_name: str, path: Path = DEFAULT_DB_PATH) -> dict:
    """Fun/useful numbers about your own play, spotted via `my_name` in scraped players.

    Fixed numbers (days since you last played, total rounds logged) are plain queries.
    Anything more open-ended — "say something interesting about my play history" — goes
    through ai_assist.summarize_history() on the raw rows, rather than growing this into
    an ever-longer list of hand-written queries.
    """
    raise NotImplementedError("analytics.py is a stub — see ROADMAP.md Phase 5")


def crowd_heatmap(course: str, path: Path = DEFAULT_DB_PATH) -> dict:
    """Historical average occupancy, grouped by calendar_context.py's day-type tag and
    hour-of-day — e.g. {"public_holiday": {"09": 0.9, "14": 0.4, ...}, "workday": {...}}.

    Grouping by day-type rather than plain weekday is the point: a Monday during summer
    break isn't "a Monday," it's a vacation-day, and should be compared against other
    vacation-days. This is also what lets a *future* day (with no scrape history of its
    own) get a crowd estimate at all — classify it, then look up its day-type's pattern.
    Plain aggregation — no AI here, just exact grouping/averaging.
    """
    raise NotImplementedError("analytics.py is a stub — see ROADMAP.md Phase 5")


def predict_crowding(day_type: str, time: str, heatmap: dict) -> float | None:
    """Estimated occupancy (0-1) for a day-type + time, from a crowd_heatmap() result.

    This is where it stops being simple aggregation: judging how much to trust a thin
    or noisy pattern for a rarer day-type (a handful of "public_holiday" rows vs
    hundreds of "workday" ones) is handed to ai_assist.summarize_history() rather than
    hand-coded confidence thresholds. Returns None only if summarize_history judges
    there's not enough history to say anything useful yet.
    """
    raise NotImplementedError("analytics.py is a stub — see ROADMAP.md Phase 5")
