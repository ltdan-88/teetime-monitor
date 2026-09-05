# Roadmap

This project started as a single-session spec ([`docs/spec-v1.md`](docs/spec-v1.md)) for a
plain tee-sheet scraper + TUI table. Before that was built out, the scope grew to include
weather, a multi-day overview, and pattern-recognition analytics. This doc reflects the
actual, current phased plan — treat `docs/spec-v1.md` as historical background, not the
build order.

## Phase 1 — Core scraper + storage + day-detail view
The original v1 scope, with one change: storage is **SQLite from the start**, not a flat
JSON cache. Phase 4 analytics needs history to accumulate across scrapes, and starting
with JSON would just mean migrating later for no benefit.

- Manual login walkthrough + selector discovery first (no code) — real pc caddie CSS
  selectors are unknown until inspected by hand. See "Known risks" in the v1 spec.
- `scraper.py` — Playwright login + tee sheet scrape for one course/date, using a
  `SELECTORS` dict discovered above
- `models.py` — `Slot` / `Schedule` dataclasses (as in v1 spec)
- `storage.py` — SQLite-backed persistence. One `scrapes` table logging every scrape
  (course, date, time, booked, capacity, players, scraped_at). Loading "today's schedule"
  is a query for the latest scrape per slot; this same table is what Phase 4 analytics
  reads from later.
- `tui.py` — Textual app, single-day detail screen: Time | Occupancy | Players, colored
  by fill ratio. `r` = refresh, `q` = quit.
- Config via `.env` (`PCC_USER` / `PCC_PASS`) + `config.yaml` (club URL, default course,
  default date range)

## Phase 2 — Weather overlay (rain focus)
- `weather.py` — client for [Open-Meteo](https://open-meteo.com/) (free, no API key
  required, good hourly precipitation data). Needs the club's lat/lon in `config.yaml`.
- Fetch hourly precipitation probability/amount for the scraped date, match to each tee
  time slot, surface as an extra column or icon in the day-detail table (e.g. a rain-drop
  indicator when precipitation probability crosses a threshold).

## Phase 3 — Multi-day overview (home screen)
- New Textual screen: a compact 4-5 day at-a-glance grid, readable in one look — one
  column per day, condensed occupancy + rain summary per day (not full per-slot detail).
- This becomes the app's **default/home screen**. Drilling into one day (e.g. pressing
  Enter on a day column) opens the Phase 1 single-day detail table.
- Requires the scraper to pull multiple days in one run (loop over dates), still gated by
  the same course/config.

## Phase 4 — Local-stats analytics ("best tee times")
- `analytics.py` — pattern recognition over the accumulated SQLite history, no AI/LLM
  calls, no external API, no cost. E.g.: aggregate historical occupancy by weekday +
  time-of-day to answer "when is this course usually emptiest?", surfaced as a simple
  ranked list or heatmap-style view in the TUI.
- Needs a few weeks of accumulated scrapes to be useful — this phase's usefulness grows
  over time, not something to judge from day one.

## Phase 5 — AI-assisted insights (later, opt-in)
- Explicitly deferred, not blocking Phase 4. Once local-stats analytics exists and there's
  real accumulated history, consider an opt-in mode that sends the aggregated (not raw)
  history to an LLM for natural-language recommendations ("book Tuesday afternoons, avoid
  weekend mornings") — richer than fixed local heuristics, but costs per call and means
  data leaves the machine, hence opt-in and Phase 5, not Phase 4.

## Out of scope (all phases)
Booking/auto-booking, notifications, multi-club support, packaging/distribution, mobile
support (pc caddie's own app already covers that).
