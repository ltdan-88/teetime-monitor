"""Shared test fixtures.

Added 2026-09-16 during a full-project audit, which found the suite was
*time-of-day dependent*: green when run before 21:00 local, red after it.
`OverviewScreen._render_table()` drops today's own row entirely once
`tui._NOW_HHMM() > tui.TODAY_HIDDEN_AFTER_HHMM` ("21:00") — a real, wanted
feature (2026-09-11: "I would prefer that the current day disappears ...
whenever it is after 9 pm") — but ~34 tests build their fixtures around
`tui._TODAY()` and assert on a row count or a column width that silently
changes once that cutoff passes. Nothing was wrong with the app; the tests
just read the real wall clock.

Freezing `_NOW_HHMM` for every test fixes the whole class at once rather than
patching each affected test. 08:00 is deliberately early: before the cutoff,
so today's row is always present, and before any realistic tee time, so
`_initial_date()`'s own "every slot has already passed" heuristic doesn't
kick in either.

A test that genuinely cares about a *different* time of day (the "today
disappears after 9pm" tests, `_initial_date()`'s own cases) still
monkeypatches `_NOW_HHMM` itself in its own body — that runs after this
fixture and wins, so those keep testing exactly what they always did.
"""

import pytest

from src import tui

# Well before TODAY_HIDDEN_AFTER_HHMM ("21:00") and before any realistic tee
# time -- see this module's own docstring for why both matter.
FROZEN_NOW_HHMM = "08:00"


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr(tui, "_NOW_HHMM", lambda: FROZEN_NOW_HHMM)
