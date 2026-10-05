"""The one clock seam (2026-10-05): `tui.py` and `pipeline.py` both read "now" through
these three functions, always as `clock.today()` (never `from .clock import today`),
so a test patching `clock.today` reaches every caller at once. Before this, the
three lambdas lived in `tui.py` (`_TODAY`/`_NOW_HHMM`/`_NOW_UTC`) and moved pipeline
code could not have seen a patch made there.

Local wall-clock for the date and HH:MM (the same "today" the person sees); UTC for the
booking-window lock, which compares against an absolute opening instant.
"""

from datetime import UTC, datetime
from datetime import date as date_cls


def today() -> str:
    """Today's local date, ISO ("YYYY-MM-DD")."""
    return date_cls.today().isoformat()


def now_hhmm() -> str:
    """The local time of day, "HH:MM" -- for `_initial_date()`, today's past-slot
    dimming and the "today disappears after 21:00" cutoff."""
    return datetime.now().strftime("%H:%M")


def now_utc() -> datetime:
    """The current instant, timezone-aware UTC -- for the booking-window lock."""
    return datetime.now(UTC)
