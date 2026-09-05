# Roadmap

This project started as a single-session spec ([`docs/spec-v1.md`](docs/spec-v1.md)) for a
plain tee-sheet scraper + TUI table. Before that was built out, the scope grew to include
weather, daylight-based playability, preference-driven recommendations, a multi-day
overview, multi-club/multi-course support, calendar-aware crowd prediction, and
pattern-recognition analytics. This doc reflects the actual, current phased plan — treat
`docs/spec-v1.md` as historical background, not the build order.

## Phase 0 — Club & course setup
Added 2026-09-05, and deliberately numbered *before* Phase 1: which club and which
course you're even looking at has to be settled before any scraping happens, and the
user's club plays 27 holes with the 9-hole loops rotating which pair makes up "the
18-hole course" week to week — so this isn't a detail to bolt on later, it changes what
"the tee sheet" even means from one week to the next.

- Multi-club config: each club is one YAML file under `clubs/` (see
  `clubs/club.example.yaml` for the template) — its filename (without `.yaml`) is the
  club's id. Was explicitly out of scope in the original spec; reversed 2026-09-05 once
  the user asked to save more than one.
- On startup, the TUI lists club ids found in `clubs/` and lets you pick one — skipped
  automatically if only one exists. In the spirit of `brew-launcher`'s fzf-style
  pickers, given this project's stated inspiration.
- Credentials stay out of the YAML files (kept in `.env`, per the original spec's
  security principle), namespaced per club id: `PCC_USER__<club-id>` /
  `PCC_PASS__<club-id>`, falling back to plain `PCC_USER`/`PCC_PASS` for the common
  single-club case so that setup doesn't get more complicated than it needs to.
- `club_config.py` (new module) — `list_clubs`, `load_club_config`,
  `resolve_credentials`. Pure local file/env I/O, no site access needed, so unlike most
  of Phase 1 this is genuinely implementable (and tested) now rather than stubbed.
- **Course selection**: because the 9/18-hole combination rotates weekly, a hardcoded
  course name in config would go stale. Add "does the site expose a course-selector
  dropdown, and what does it list" to Phase 1's manual selector-discovery walkthrough —
  the scraper should read the *currently available* course options live each run
  (`Schedule.available_courses`) rather than trusting a static list. The TUI offers a
  picker over whatever comes back, remembering your last pick per club as a convenience
  default (`default_course` in the club's YAML), switchable anytime.

## Phase 1 — Core scraper + storage + day-detail view
The original v1 scope, with a few changes driven by one key fact: **pc caddie doesn't let
you look up past tee times.** Once a day is gone, it's gone — there's no backfilling it
later. That makes storage and confirmed bookings a day-one concern, not something to add
once the rest of the app exists, because waiting would just mean losing whatever history
would've built up in the meantime.

- Manual login walkthrough + selector discovery first (no code) — real pc caddie CSS
  selectors are unknown until inspected by hand. See "Known risks" in the v1 spec. While
  doing this: also check whether player names for booked slots include friends (added as
  friends in the pc caddie app) distinguishably from other players, whether
  tournaments/club events are shown on the tee sheet (confirmed: pc caddie does list
  these), and — per Phase 0 — whether/how the site exposes a course-selector for the
  27-hole rotation.
- `scraper.py` — Playwright login + tee sheet scrape for one course/date, using a
  `SELECTORS` dict discovered above. Also captures any tournament/event note shown for
  the day, and the list of currently-available courses (Phase 0), if one's on the sheet.
- `models.py` — `Slot` / `Schedule` dataclasses (as in v1 spec), `Schedule` also gets an
  `events: list[str]` field for tournament/event notes and an `available_courses:
  list[str]` field for Phase 0's course picker.
- The active club's YAML (Phase 0) gains an `identity` block: your own name and a list
  of friends' names, as they appear on the tee sheet. Simple text-matching against
  scraped player names — no dependence on pc caddie having a special "friend" marker in
  its own HTML. Powers both Phase 3's friend-spotting and Phase 5's personal stats.
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
- Config via `.env` (see Phase 0's namespaced credentials) + the active club's YAML
  (club URL, default course, default date range)
- A small standalone scrape-and-store script (no TUI), runnable on a schedule (e.g. a
  daily cron/launchd job) so history keeps accumulating even on days you don't open the
  app yourself. Confirmed 2026-09-05: manual-only runs would leave permanent gaps given
  pc caddie's no-history limitation, so this is worth having from the start rather than
  bolted on later.

## Phase 2 — Weather, daylight & calendar overlay
- `weather.py` — client for [Open-Meteo](https://open-meteo.com/) (free, no API key
  required). Needs the club's lat/lon from its YAML (Phase 0). One call gets all of:
  - Hourly precipitation probability/amount, matched to each tee time slot and shown as
    an extra column or icon (e.g. a rain-drop indicator past a threshold).
  - Hourly wind speed, same treatment — windy rounds are miserable even without rain.
  - Hourly temperature — freezing or scorching rounds matter too.
  - Daily sunrise/sunset (Open-Meteo returns these directly in the same `daily` response
    — no second API needed).
- `playability.py` — pure time-arithmetic helper, no I/O: given a slot's start time, the
  day's sunset, an estimated round duration, and a safety buffer, decide whether that
  round would finish before dark. Round duration is configurable per length (9 vs 18
  holes) in the club's YAML, since pace varies by course/player.
- This feeds a "playable" highlight (e.g. dim/strike out tee times too late to finish a
  9- or 18-hole round before sunset) surfaced in **both** the Phase 1 day-detail table and
  the Phase 4 overview — it's not just a weather footnote, it's meant to answer "is this
  tee time even usable" at a glance.
- `calendar_context.py` (new module, 2026-09-05) — public holidays and school-vacation
  periods, since both tend to mean a busier course:
  - Public holidays fetched automatically via the free
    [Nager.Date](https://date.nager.at/) API, no key needed, keyed by the club's
    `calendar.country_code`.
  - School/regional vacation periods have no reliable universal free API, so those come
    straight from the club's YAML (`calendar.vacation_ranges`, entered by hand).
  - `classify_day()` folds holidays, vacation ranges, and Phase 1's scraped tournament
    notes into one day-type tag per date (tournament > public holiday > vacation >
    weekend > workday) — this is what Phase 5's crowd heatmap groups history by, and
    what lets a *future* day (with no scrape history of its own yet) get a crowd
    estimate at all.

## Phase 3 — Default availability & recommendations ("pick for me")
- New: instead of just displaying occupancy/weather/playability and leaving you to scan
  the table, score each slot against your own standing rules and highlight the best
  match per day with a star, automatically, no typing required.
- One shared engine with Phase 4's search, `search.py`'s `SearchCriteria` (see below) —
  Phase 3 is just that same shape, saved as your defaults and run automatically instead
  of typed in on demand. Revised 2026-09-05 from an earlier, flatter "time of
  day"/"solo vs group" idea once it became clear the two features are the same thing.
- The active club's YAML gains two blocks:
  - `availability` — your standing hard rules, e.g. "workdays only after 17:00,
    weekends only after 10:00, always solo, need 20 minutes clear of other flights."
    Different windows for workdays vs weekends, since that's genuinely how availability
    tends to work.
  - `preferences` — soft scoring weights layered on top of whatever passes the hard
    availability filter: how much to weight rain/wind/temperature comfort, whether to
    boost slots where a friend (from the Phase 1 `identity` list) is already booked, and
    (once Phase 5's heatmap exists) whether to steer away from historically/
    calendar-predicted crowded windows (`avoid_predicted_crowd`).
- `recommend.py` (new module) — a thin wrapper: builds a `SearchCriteria` from
  `availability`, runs it via `search.py` across every day in the overview, ranks
  results using the `preferences` weights. Pure logic over already-scraped data, no new
  external calls.
- This is distinct from Phase 5's historical analytics: recommendations use *today's/
  this week's* already-scraped data plus rules you set, not weeks of accumulated history.

## Phase 4 — Multi-day overview & search (home screen)
- New Textual screen: a compact 4-5 day at-a-glance grid, readable in one look — one
  column per day, condensed occupancy + rain/wind/temperature + playability summary,
  plus the Phase 3 recommended pick highlighted per day (not full per-slot detail). Days
  with a tournament/event note (from Phase 1) get their own flag, so a weird-looking
  sheet doesn't confuse you.
- This becomes the app's **default/home screen**. Drilling into one day (e.g. pressing
  Enter on a day column) opens the Phase 1 single-day detail table.
- Requires the scraper to pull multiple days in one run (loop over dates), still gated by
  the same course/config.
- **Search**: for the one-off cases that don't match your saved `availability` defaults
  — e.g. "just this once, 3 players, weekdays only, after 15:00, 20 minutes clear of any
  other flight." New keybinding opens a small form; `search.py`'s `SearchCriteria`
  covers:
  - **Party size** (`min_open_spots`) — enough open spots in the slot for your group
  - **Separate workday/weekend time windows** (`weekday_window` / `weekend_window`) —
    a day type with no window set is skipped entirely, so leaving one out means "only
    the other day type"
  - **Buffer from other flights** (`buffer_minutes`) — a minimum gap to the nearest
    other booked flight, both before and after, so your group isn't squeezed between
    two other groups
  - Results are ranked using the same `preferences` scoring weights as Phase 3's
    automatic weekly picks (dry, calm, safely before sunset first) — same engine, just
    typed-in criteria instead of saved defaults.

## Phase 5 — Local-stats analytics, crowd heatmap & personal stats
- `analytics.py` — pattern recognition over the accumulated SQLite history, no AI/LLM
  calls, no external API, no cost. E.g.: aggregate historical occupancy by weekday +
  time-of-day to answer "when is this course usually emptiest?", surfaced as a simple
  ranked list or heatmap-style view in the TUI.
- Needs a few weeks of accumulated scrapes to be useful — this phase's usefulness grows
  over time, not something to judge from day one. Complements Phase 3 (today's rules)
  with "what actually tends to be true here over time".
- **Crowd heatmap** (2026-09-05): `crowd_heatmap()` groups historical occupancy by
  Phase 2's day-type tag (tournament / public holiday / vacation / weekend / workday) x
  hour-of-day, rather than just plain weekday x hour — a Monday during summer break
  isn't "a Monday," it's a vacation-day, and should be compared against other
  vacation-days, not typical Mondays. Rendered as a real colored heatmap screen in the
  TUI (new keybinding), and also read by `predict_crowding()` to estimate expected
  occupancy for a *future* date it hasn't scraped yet: classify the date's day-type
  (Phase 2), look up that day-type's historical pattern. This is what
  `avoid_predicted_crowd` (Phase 3/4 preferences) actually uses to steer the automatic
  weekly picks and search results away from likely-overbooked windows.
- Like the rest of this phase, the heatmap starts out thin (little/no history for rarer
  day-types like "public holiday") and gets more useful the longer Phase 1's scraping
  and confirmed-bookings have been running.
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
- **How the 27-hole rotation is actually presented on the site is unverified.** Whether
  it's a simple dropdown, separate URLs per course combo, or something else determines
  how much of Phase 0's course-detection is realistic to automate vs needing a manual
  fallback (e.g. you just tell it which combo is live this week). Check during the
  Phase 1 walkthrough.
- **Public-holiday API coverage varies by country**, and there's no universal free
  school-vacation API at all — `calendar.country_code` and `vacation_ranges` may need
  more manual upkeep than the rest of the config, depending on the club's region.

## Out of scope (all phases)
Booking/auto-booking, notifications, packaging/distribution, mobile support (pc
caddie's own app already covers that). Multi-club support was on this list originally;
reversed 2026-09-05 — see Phase 0.
