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

## Phase 2 — Weather + daylight overlay (rain, sunrise/sunset, playability)
- `weather.py` — client for [Open-Meteo](https://open-meteo.com/) (free, no API key
  required). Needs the club's lat/lon in `config.yaml`. One call gets both:
  - Hourly precipitation probability/amount, matched to each tee time slot and shown as
    an extra column or icon (e.g. a rain-drop indicator past a threshold).
  - Daily sunrise/sunset (Open-Meteo returns these directly in the same `daily` response
    — no second API needed).
- `playability.py` — pure time-arithmetic helper, no I/O: given a slot's start time, the
  day's sunset, an estimated round duration, and a safety buffer, decide whether that
  round would finish before dark. Round duration is configurable per length (9 vs 18
  holes) in `config.yaml`, since pace varies by course/player.
- This feeds a "playable" highlight (e.g. dim/strike out tee times too late to finish a
  9- or 18-hole round before sunset) surfaced in **both** the Phase 1 day-detail table and
  the Phase 3 overview — it's not just a weather footnote, it's meant to answer "is this
  tee time even usable" at a glance.

## Phase 3 — Multi-day overview (home screen)
- New Textual screen: a compact 4-5 day at-a-glance grid, readable in one look — one
  column per day, condensed occupancy + rain + playability summary per day (not full
  per-slot detail). Tee times that can't finish before sunset (see Phase 2) are visually
  de-emphasized so the readable-at-a-glance view isn't cluttered with slots that don't
  matter.
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
