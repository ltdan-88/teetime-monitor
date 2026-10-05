# Architecture

How the Python side is layered (2026-10-05). The macOS app shells out to the CLIs
below; the terminal app is `tui.py`.

- `src/tui.py` -- screens only: Textual widgets, Rich markup, key bindings, layout.
  Imports the headless logic it needs from `pipeline.py` under its old private names.
- `src/pipeline.py` -- headless logic, no Textual/Rich imports: `_resolved_config()`
  (club YAML + global preferences), `_availability_pipeline()` (the Pick column and
  the ★ markers), `_shorter_round_alternative()`, `_crowd_estimates()` with its
  holiday/vacation/heatmap caches, `_too_late_for_daylight()`.
- `src/quality.py` -- the free, deterministic, explainable slot score behind the day's Pick
  (2026-10-05): `score_matches()` weighs weather margin over the real round, room around the
  group, predicted crowd and daylight cushion, and names up to three reason keys ("dry",
  "room_around", ...). `recommend.ranked_matches(rank_by_quality=True)` sorts by it (friend and
  handicap tiers above, chronological on a tie); `_availability_pipeline()` is its one caller.
  Reason keys are localised only at the edges (`i18n.py`, `I18n.swift`), never in this module.
- `src/clock.py` -- the one time seam: `today()`, `now_hhmm()`, `now_utc()`. Call them
  as `clock.today()` (never `from .clock import today`) so a single test patch reaches
  `tui.py` and `pipeline.py` alike.
- `src/picks_cli.py`, `search_cli.py`, `preview_club_cli.py` (and the other `*_cli.py`)
  depend only on `pipeline.py` and the leaf modules (`recommend`, `storage`,
  `scrape_once`, ...), never on `tui.py`, so a GUI subprocess does not import Textual.
  `tests/test_import_hygiene.py` enforces this.

Rules of thumb: logic that a CLI needs goes in `pipeline.py` (or a leaf module); markup
and widgets stay in `tui.py`. Tests patch moved state where it now lives, e.g.
`pipeline._HOLIDAY_CACHE`, `pipeline._resolved_config`, `clock.today`.
