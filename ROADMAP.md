# Roadmap

This project started as a single-session spec ([`docs/spec-v1.md`](docs/spec-v1.md)) for a
plain tee-sheet scraper + TUI table. Before that was built out, the scope grew to include
weather, daylight-based playability, preference-driven recommendations, a multi-day
overview, and pattern-recognition analytics. This doc reflects the actual, current
phased plan — treat `docs/spec-v1.md` as historical background, not the build order.

## Phase 1 — Core scraper + storage + day-detail view
The original v1 scope, with a few changes driven by one key fact: **pc caddie doesn't let
you look up past tee times.** Once a day is gone, it's gone — there's no backfilling it
later. That makes storage and confirmed bookings a day-one concern, not something to add
once the rest of the app exists, because waiting would just mean losing whatever history
would've built up in the meantime.

- Manual login walkthrough + selector discovery first (no code) — real pc caddie CSS
  selectors are unknown until inspected by hand. See "Known risks" in the v1 spec. While
  doing this: also check whether player names for booked slots include friends (added as
  friends in the pc caddie app) distinguishably from other players, and whether
  tournaments/club events are shown on the tee sheet (confirmed: pc caddie does list
  these) — both feed later phases below.
- `scraper.py` — Playwright login + tee sheet scrape for one course/date, using a
  `SELECTORS` dict discovered above. Also captures any tournament/event note shown for
  the day, if one's on the sheet.
- `models.py` — `Slot` / `Schedule` dataclasses (as in v1 spec), `Schedule` also gets an
  `events: list[str]` field for tournament/event notes.
- `config.yaml` gains an `identity` block: your own name and a list of friends' names, as
  they appear on the tee sheet. Simple text-matching against scraped player names — no
  dependence on pc caddie having a special "friend" marker in its own HTML. Powers both
  Phase 3's friend-spotting and Phase 5's personal stats.
- `storage.py` — SQLite-backed persistence, **not just a cache**: it's the only record of
  the past that will ever exist, since pc caddie itself won't show it later. Two tables:
  - `scrapes` — every scrape logged as its own row (course, date, time, booked, capacity,
    players, scraped_at). Loading "today's schedule" is a query for the latest scrape per
    slot; this same table is what Phase 5 analytics reads from later.
  - `confirmed_bookings` — see below. Kept separate from `scrapes` because it answers a
    different question ("did *I* actually play, and when") that scraped player-name
    matching can't always answer reliably on its own (name visibility can vary, or you
    might book without your name showing).
- **A confirm-your-tee-time prompt.** We're not booking through teetime-monitor, but
  without some record of which slot was actually yours, Phase 5's stats would have
  nothing to work with. New keybinding `c` in the TUI: pick the slot you're playing today
  (or mark "not playing"), which writes a row to `confirmed_bookings`. This exists from
  Phase 1 onward, precisely because it can't be reconstructed retroactively later.
- `tui.py` — Textual app, single-day detail screen: Time | Occupancy | Players, colored
  by fill ratio. `r` = refresh, `c` = confirm your tee time, `q` = quit.
- Config via `.env` (`PCC_USER` / `PCC_PASS`) + `config.yaml` (club URL, default course,
  default date range)
- A small standalone scrape-and-store script (no TUI), runnable on a schedule (e.g. a
  daily cron/launchd job) so history keeps accumulating even on days you don't open the
  app yourself. Confirmed 2026-09-05: manual-only runs would leave permanent gaps given
  pc caddie's no-history limitation, so this is worth having from the start rather than
  bolted on later.

## Phase 2 — Weather + daylight overlay (rain, wind, sunrise/sunset, playability)
- `weather.py` — client for [Open-Meteo](https://open-meteo.com/) (free, no API key
  required). Needs the club's lat/lon in `config.yaml`. One call gets all of:
  - Hourly precipitation probability/amount, matched to each tee time slot and shown as
    an extra column or icon (e.g. a rain-drop indicator past a threshold).
  - Hourly wind speed, same treatment — windy rounds are miserable even without rain.
  - Hourly temperature — freezing or scorching rounds matter too.
  - Daily sunrise/sunset (Open-Meteo returns these directly in the same `daily` response
    — no second API needed).
- `playability.py` — pure time-arithmetic helper, no I/O: given a slot's start time, the
  day's sunset, an estimated round duration, and a safety buffer, decide whether that
  round would finish before dark. Round duration is configurable per length (9 vs 18
  holes) in `config.yaml`, since pace varies by course/player.
- This feeds a "playable" highlight (e.g. dim/strike out tee times too late to finish a
  9- or 18-hole round before sunset) surfaced in **both** the Phase 1 day-detail table and
  the Phase 4 overview — it's not just a weather footnote, it's meant to answer "is this
  tee time even usable" at a glance.

## Phase 3 — Preference-based recommendations ("pick for me")
- New: instead of just displaying occupancy/weather/playability and leaving you to scan
  the table, score each slot against your own stated preferences and highlight the best
  one per day with a star.
- `config.yaml` gains a `preferences` block, e.g. preferred time of day (morning/
  afternoon/either), solo vs with-others, how much to weight rain/wind/temperature
  comfort, and whether to boost slots where a friend (from the Phase 1 `identity` list)
  is already booked.
- `recommend.py` (new module) — combines Phase 1 occupancy, Phase 2 weather/playability,
  and (if available) friend-spotting into one score per slot, per your configured
  preferences. Pure scoring logic over already-scraped data, no new external calls.
- This is distinct from Phase 5's historical analytics: recommendations use *today's*
  data plus rules you set, not weeks of accumulated history.

## Phase 4 — Multi-day overview (home screen)
- New Textual screen: a compact 4-5 day at-a-glance grid, readable in one look — one
  column per day, condensed occupancy + rain/wind/temperature + playability summary,
  plus the Phase 3 recommended pick highlighted per day (not full per-slot detail). Days
  with a tournament/event note (from Phase 1) get their own flag, so a weird-looking
  sheet doesn't confuse you.
- This becomes the app's **default/home screen**. Drilling into one day (e.g. pressing
  Enter on a day column) opens the Phase 1 single-day detail table.
- Requires the scraper to pull multiple days in one run (loop over dates), still gated by
  the same course/config.

## Phase 5 — Local-stats analytics & personal stats
- `analytics.py` — pattern recognition over the accumulated SQLite history, no AI/LLM
  calls, no external API, no cost. E.g.: aggregate historical occupancy by weekday +
  time-of-day to answer "when is this course usually emptiest?", surfaced as a simple
  ranked list or heatmap-style view in the TUI.
- Needs a few weeks of accumulated scrapes to be useful — this phase's usefulness grows
  over time, not something to judge from day one. Complements Phase 3 (today's rules)
  with "what actually tends to be true here over time".
- Also a small personal-stats view, built primarily from Phase 1's `confirmed_bookings`
  table (the reliable source), optionally cross-checked against `identity.my_name`
  matches in scraped player names: days since you last played, total rounds logged, and
  whatever else turns out to be fun/sensible once there's real data to look at — this
  list is expected to grow once Phase 1 history actually exists, not fixed up front.

## Phase 6 — AI-assisted insights (later, opt-in)
- Explicitly deferred, not blocking Phase 5. Once local-stats analytics exists and there's
  real accumulated history, consider an opt-in mode that sends the aggregated (not raw)
  history to an LLM for natural-language recommendations ("book Tuesday afternoons, avoid
  weekend mornings") — richer than fixed local heuristics, but costs per call and means
  data leaves the machine, hence opt-in and last phase, not earlier.

## Considered and dropped
- **Spreadsheet export of history** — decided against for now (2026-09-05): not enough
  time to actually analyze it. Revisit only if that changes.
- **Jump-to-booking shortcut** (one key opens the real pc caddie booking page for a
  slot) — decided against (2026-09-05): booking always has to go through the pc caddie
  app anyway, so this wouldn't save a step.

## Known risks
- pc caddie's real CSS selectors are unverified until inspected by hand, and the tee
  sheet may sit inside an iframe (see `docs/spec-v1.md` for detail) — the original v1
  risks, still true.
- **History can't be backfilled.** pc caddie hides past tee sheets, so any day that's
  neither scraped nor confirmed via the Phase 1 prompt is a permanent gap — not
  something a later phase can go back and fix. The scheduled scrape script exists
  specifically to minimize this.

## Out of scope (all phases)
Booking/auto-booking, notifications, multi-club support, packaging/distribution, mobile
support (pc caddie's own app already covers that).
