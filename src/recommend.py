"""Score today's slots against your own preferences and pick the best one (ROADMAP.md
Phase 3).

Different from analytics.py: this scores *today's* already-scraped data against rules
you set in config.yaml (time of day, solo vs group, rain/wind tolerance, friends), not
weeks of accumulated history. Pure scoring logic, no new external calls — it consumes
Schedule (Phase 1) + WeatherPoint/playability (Phase 2).

NOT YET IMPLEMENTED.
"""

from .models import Schedule, Slot


def best_slot(schedule: Schedule, preferences: dict) -> Slot | None:
    """Return the single best-scoring slot for the day, or None if nothing qualifies."""
    raise NotImplementedError("recommend.py is a stub — see ROADMAP.md Phase 3")
