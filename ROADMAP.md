# Roadmap

This project started as a single-session spec ([`docs/spec-v1.md`](docs/spec-v1.md)) for a
plain tee-sheet scraper + TUI table. Before that was built out, the scope grew to include
weather, daylight-based playability, preference-driven recommendations, a multi-day
overview, multi-club/multi-course support, calendar-aware crowd prediction, and
pattern-recognition analytics. This doc reflects the actual, current phased plan — treat
`docs/spec-v1.md` as historical background, not the build order.

**Build priority (2026-09-05, user feedback, revised same day):** the actual core value
of this tool is answering "when should I book" quickly — the user explicitly named
manually scanning the tee sheet for a good slot as the time-consuming part, not just
*seeing* the tee sheet. First cut of this note said weather could wait until after a
plain availability-filtered list; the user corrected that immediately — a recommended
slot that's raining or too dark to finish isn't actually a good recommendation, so
weather and daylight belong in the *first* useful version too, not layered on later.

The real split isn't "filtering vs. weather" — it's "hard checks vs. AI ranking."
Everything below is a deterministic *filter or exclusion*, not a judgment call, so none
of it needs `ai_assist`:
- `search.py`'s hard filtering against the user's own `availability` rules (workdays
  after 17:00, weekends after 10:00, always solo, etc.) — party size and time windows
- `playability.py` (already implemented) — exclude slots that don't leave enough
  daylight to finish, using the club's sunset + round-duration config
- A rain/wind/temperature threshold from Phase 2's Open-Meteo call — but checked
  across the *whole round's duration* via `weather.conditions_during_round()`
  (implemented and tested 2026-09-05), not just the tee-off hour. Same underlying
  point as `playability.py` already gets right for daylight: a slot's conditions can't
  be judged from a single moment once the round runs 2-4+ hours.

That combination — fits your schedule, enough daylight, decent weather — is the
smallest version that's actually a *good* recommendation, and none of it requires AI.
What genuinely can wait: `ai_assist.rank_slots()`'s plain-language reasons and nuanced
multi-factor weighing (e.g. trading off "slightly more rain" against "much emptier"),
friend-boosting, and Phase 5's crowd-heatmap avoidance — real improvements on top of an
already-useful deterministic baseline, not prerequisites for one. Phase 4's polished
overview screen can also follow after the core recommendation works.

**AI placement (revised 2026-09-05):** wherever a step is genuinely fuzzy judgment —
parsing messy/varying HTML into structured data, weighing several soft signals into a
ranked list with a plain-language reason, or making a reasonable call from sparse/noisy
history — an LLM call replaces hand-rolled logic for it, pulled into the phase where
that step lives rather than bolted on as a deferred "AI mode" later. What stays plain
code: browser automation itself (login/navigation), the database, simple time
arithmetic, external API calls, and *hard* filters (party size, time windows) — none of
that benefits from a model call, and a couple (arithmetic, hard filters) get *less*
reliable if you hand them to one. This replaced an earlier plan (a stubbed
`analytics.py`/`recommend.py` doing everything in hand-written scoring code, with "AI
insights" as an opt-in Phase 6 bolted on once there was enough history to bother) —
see `ai_assist.py` below, and the per-phase notes it touches.

## Live site findings (2026-09-05)
A real walkthrough of the user's actual club (Musterhausen, pc caddie club id 0000001)
confirmed several assumptions and corrected a couple of others. Recorded once here,
referenced from the phases below rather than repeated:

- The whole booking widget on the club's marketing site is a cross-origin iframe
  pointing straight at `pccaddie.net/clubs/0000001/app.php?cat=tt_timetable_course` —
  the scraper should navigate there directly rather than dealing with the iframe.
- **The tee sheet itself needs no login** — occupancy (booked/free, per-slot capacity)
  is fully visible logged out. Login is only needed to see names and to book.
- **Course selection is a fixed 3-option picker**, not a rotating list: "18 Loch Tee 1"
  (alias `COUB`), "9 Loch Tee 1" (`COU1`), "6 Loch Platz" (`COU6`) — a 6-hole course
  neither of us knew about. The actual weekly A/B/C loop combination shows as a separate
  "Runde A+C"-style banner on the sheet, not as extra dropdown entries — much simpler
  than the rotating-dropdown risk this roadmap originally flagged.
- **Names are private by default.** A booked slot with no visible name shows as
  `Occupied — Member (16.3)` (their handicap, not identity) unless the player is on
  your pc caddie friends list, in which case their real name shows. Friends are a
  native pc caddie feature (My Account → "My friends"), not something to fake with a
  config file — see Phase 3.
- **Friend detection, refined not confirmed** (see "Confirmed pc caddie markup
  reference" below for the full technical detail): the original "any non-anonymized
  name = friend" theory turned out too naive. A systematic scan of all 5 available days
  across all 3 courses found zero real friend names, but *did* turn up several
  non-name labels sharing the same span (event names, lesson names, "Gäste" for guest
  reservations, advance-booking-window notices) that a naive "not literally 'Occupied'"
  check would have wrongly treated as friends. Positively recognizing a real name —
  not just "this text is unfamiliar" — is now the actual job, and it's a small, cheap
  classification rather than the "parse the whole table" job originally planned.
- **"My Reservations" page** (`cat=reservations`) lists your own upcoming bookings
  directly — see Phase 1's confirmed-bookings design below.
- **Tournaments/events have their own dedicated calendar page** (`cat=ts_calendar`),
  separate from the tee sheet — but also show up directly *in* the tee sheet as a
  blocked row carrying the event's name (confirmed examples: "FC 110 After Work (E)",
  "5. Best Agers"). The calendar page remains useful for looking further ahead than the
  5-day tee-sheet window reaches; the tee-sheet row is what a scrape sees in the moment.
- There's a separate lesson/course calendar too (`cat=ts_calendar_course`, "Golfkurs
  buchen") — distinct from the tournament calendar, and the source of "Golf Beginner
  Kurs"-style blocks on the tee sheet.
- **A third slot state neither of us had considered**: some "not free" slots aren't
  occupied by anyone at all — they're not yet *openable* for booking, due to an
  advance-booking-window rule (e.g. "members can book 4 days ahead, from 8pm"). Treating
  this the same as genuine crowding would be misleading for the crowd heatmap and
  recommendations — see the markup reference below.
- **"Overview Areas" page** (`cat=tt_timetable_course_alias`) shows all 3 courses side
  by side for one date, aggregate free/occupied seat icons only, no names — one
  lightweight request instead of three, and a strong fit for Phase 4's multi-day
  overview. The per-course tee sheet remains necessary for actual slot detail.
- The date picker only ever offers 5 days ahead — matches the planned `overview_days: 5`
  default exactly.
- Sunrise/sunset and a `*` holiday marker are shown on the site itself too. **Decided
  2026-09-05: don't rely on these.** Open-Meteo (already called for rain/wind/temp) and
  Nager.Date remain the actual sources for sunrise/sunset and holidays — their
  reliability as scraped values is unverified, and there's no efficiency win anyway
  since the weather call happens regardless. Could still be a nice-to-have cross-check
  later, not a replacement.

## Confirmed pc caddie markup reference (2026-09-05)
Concrete technical detail from the walkthrough above — closer to implementation notes
than roadmap prose, kept separate so the narrative above stays readable. Update this if
the site changes. See also
[`docs/pccaddie-markup-notes.md`](docs/pccaddie-markup-notes.md) for illustrative HTML
snippets to write a parser and its tests against.

**Direct URL navigation** (no form/dropdown interaction needed):
```
https://www.pccaddie.net/clubs/<club_id>/app.php?cat=tt_timetable_course&date=DAY|<YYYY-MM-DD>&alias=ALIAS|<course_code>
```
Confirmed working as a plain GET — including via same-origin `fetch()` from the page
console, meaning this is server-rendered HTML, not a JS single-page app, for at least
the anonymous view. Worth reconsidering during real Phase 1 implementation whether
Playwright is needed for anything beyond the login step itself: log in once with
Playwright to obtain session cookies, then use a lighter HTTP client (`httpx`) for the
repeated scheduled scrapes — likely faster and cheaper than a full browser per scrape.

**Per-course tee sheet** (`cat=tt_timetable_course`):
- Table: `table.pcco-tt-timetable`; one row per time, `tr.pcco-tt-time-person`.
- Time cell: `td.seats-free-N` where N (0-4) is the free-seat count, directly in the
  class name — fully deterministic, no parsing judgment needed. `tt-grau` = normal row,
  `tt-rot` = blocked for an event.
- Each of the 4 player cells: `<span class="tt-show-name tt-show-male|female">` +
  `<span class="tt-show-hcp">`. Confirmed content patterns for `tt-show-name`:
  - Literal `"Occupied"` — an anonymized member booking (not a friend); `tt-show-hcp`
    then reads "Member (H.H)".
  - An event/lesson/guest/sponsor label — the slot is blocked, not player-occupied.
    Confirmed real examples: tournament names straight from `ts_calendar` ("FC 110
    After Work (E)", "5. Best Agers", "7. Damengolf Afterwork"), lesson names from
    `ts_calendar_course` ("Golf Beginner Kurs"), "Gäste" (guest reservation), sponsor
    bookings ("Stadler Business Golf").
  - An advance-booking-window notice ("Mitglieder 4 Tage im voraus ab 20 Uhr buchbar")
    — **not occupancy at all**, just "not bookable yet." `recommend.py`/`analytics.py`
    should treat this as unknown, not as crowding — counting it as "busy" would be
    actively misleading for the heatmap and recommendations.
  - Presumably an actual friend's real name — not yet observed. A systematic scan of
    all 5 available days × all 3 courses on 2026-09-05 found only the labels above, no
    real names. This is now a narrow, cheap classification task (one short string in,
    one label out) worth an `ai_assist` call, not the "parse the whole messy table" job
    originally planned — most of the table turned out to be cleanly structured once
    actually inspected, which is exactly the kind of update the "AI placement" note
    above expects: use AI for what's genuinely ambiguous, plain code for what isn't,
    and revise the split once you actually know which is which.

**"Overview Areas" page** (`cat=tt_timetable_course_alias`): all 3 courses side by side
for one date. Aggregate seat icons only, no names: `i.fa-ban.occupied` (booked) /
`i.fa-circle-o.bookable` (free) per seat. One lightweight request covers all 3 courses
for a date — good primary source for Phase 4's overview; the per-course page above
remains necessary for real slot detail.

**Confirmed rotation mechanic**: with 3 loops (A/B/C), the 18-hole and 9-hole options
pair automatically rather than rotating independently — 18-hole "Runde A+C" shows
alongside 9-hole "Runde B" (the leftover loop) at the same time. One combo determines
the other.

**Cross-club validation (2026-09-05, same evening)**: checked 3 other real pc caddie
clubs found via public search (Golf Club Segeberg, Golf Club Schloß Klingenburg, Green
Eagle Golf Courses — different club ids, different branding) to see whether the markup
above is Musterhausen-specific or platform-wide. Confirmed: `table.pcco-tt-timetable`
and the `td.seats-free-N`/`tt-grau` pattern are byte-identical across all 4 clubs
checked — this is pc caddie *platform* markup, not something Musterhausen customized,
which is a real win for the multi-club feature: the deterministic parsing approach
should generalize to any pc caddie club, needing only a different `club_id` and course
alias codes (which do differ per club — re-derive `COURSE_ALIASES` per club, don't
assume Musterhausen's `COUB`/`COU1`/`COU6` are universal).

Differences observed between clubs (config, not platform, differences):
- Course-selector presence varies — some clubs show one combined view with a per-slot
  "9H"/"18H" tag instead of Musterhausen's separate dropdown-per-course-alias page.
- The "Daylight" display is sometimes accurate, sometimes shows placeholder "XX:XX" for
  a club that hasn't configured a location — further confirms the 2026-09-05 decision
  not to rely on this for sunrise/sunset (see "Considered and dropped").
- The `.tt-show-hcp` span isn't always a handicap — one club used it for a round-length
  tag instead. Don't assume its content is always "Member (H.H)" — another point in
  favor of `ai_assist.classify_booking_label()` handling the semantics, not a fixed
  regex.
- Anonymization has (at least) two text variants depending on login state: **"Please
  login to see names"** when not logged in at all (confirmed identical wording at every
  club checked, including Musterhausen before the user logged in earlier), vs.
  **"Occupied"** once logged in but not a friend. `classify_booking_label()` should
  treat both as `"anonymized"`.

**Implementation pass confirmed the parser against the live site (2026-09-06)**:
writing and actually running `src/scraper.py` (not just reading the markup in a
browser) surfaced a more precise, more robust picture than the walkthrough above —
`docs/pccaddie-markup-notes.md` has the full detail, summarized here:

- Each `tr.pcco-tt-time-person` carries clean `data-*` attributes — `data-time`,
  `data-status`, `data-seat_bookable` — a better source than parsing `seats-free-N`
  off the time cell's class (kept only as a fallback now).
- `data-status` has **four** values, not the two implied above: `bookable`,
  `occupied`, `block-time` (an event/lesson/guest block), and a fourth found live this
  pass, `disable-time` — the advance-booking-window notice. Both `block-time` and
  `disable-time` are handled identically (neither is real occupancy).
- Free/empty seats aren't individually rendered — they're merged into one trailing
  `<td colspan="N">` with an empty `.tt-show-name` span; skipping blank spans handles
  this with no colspan arithmetic.
- The anonymized-placeholder text has (at least) **four** confirmed variants, not two
  — German short form "Belegt" and German long form "Namensanzeige nach dem Login" (the
  server's default locale) join the two EN variants already found. "Belegt" was only
  caught via an actual end-to-end scrape (it briefly slipped through as a false-
  positive "player name" before being added).
- Verified via a full sweep of every date/course the live site offered that day (5
  dates x 3 courses, 1092 slots): zero false-positive player names, all 7 real
  block/event reasons correctly categorized. `scrape_schedule()` and
  `parse_schedule_html()` are now real, tested code (fixture-based unit tests in
  `tests/test_scraper.py`), not stubs.

**Confirmed by the user (2026-09-05)**: one pc caddie login genuinely does work across
multiple clubs — not a session-scoping quirk, an actual platform feature. They also
believe guest reservations at other clubs are possible through that same account, not
just viewing. This flips Phase 0's credential framing (see below): namespaced per-club
credentials become the edge case, not the default. It also raises an open question worth
checking once Phase 1 implementation starts, not assumed either way: does "My
Reservations" (`cat=reservations`) return bookings scoped to just the club it's viewed
from, or every club under the account? Matters for how `scrape_my_reservations()`
should be called across multiple saved clubs.

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
  security principle). Revised 2026-09-05: the user confirmed one pc caddie login
  works across multiple clubs, not just the club it was issued for — so plain
  `PCC_USER`/`PCC_PASS` is now expected to be the normal path for *every* saved club,
  not a single-club fallback. Namespaced overrides (`PCC_USER__<club-id>` /
  `PCC_PASS__<club-id>`) remain available in `resolve_credentials()` for the genuine
  edge case — a club that actually needs separate credentials — but aren't the
  expected default the way this was first designed.
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

- Manual login walkthrough first (no code) — the login form and how to navigate to the
  tee sheet are still unknown until inspected by hand. See "Known risks" in the v1 spec.
  This no longer means hand-mapping the *entire* booking table's markup, though — see
  `ai_assist.py` below.
- `scraper.py` — navigates straight to the pc caddie booking page via direct URL (see
  "Confirmed pc caddie markup reference" — no need to fight the club marketing site's
  iframe, or even simulate dropdown clicks: date/course selection is a plain query
  string). The tee sheet itself needs no login; a separate authenticated pass handles
  player names, "My Reservations," and confirms bookings. Twice-revised 2026-09-05:
  first assumed the booking table's markup was unknown and messy enough to need
  `ai_assist.extract_schedule()` for the whole thing; turned out, once actually
  inspected, that occupancy (`seats-free-N` class), time, and blocked-vs-normal
  (`tt-grau`/`tt-rot`) are all cleanly deterministic — plain code parses these directly,
  no AI involved, which is both cheaper and more reliable per the "AI placement" note's
  own logic once the real structure was known. The one piece still handed to AI is
  `ai_assist.classify_booking_label()` — telling an anonymized booking, an event/lesson/
  guest block, an advance-booking-window notice, and an actual friend's name apart,
  since new label wording could appear that hasn't been seen yet. A small `SELECTORS`
  dict remains for the login form itself (still genuinely unverified). Whether
  Playwright is needed at all beyond that login step is worth reconsidering once
  implementation starts — the pages are server-rendered HTML, not a JS app, so a
  lighter authenticated HTTP client could handle the repeated scheduled scrapes.
- `models.py` — `Slot` / `Schedule` dataclasses (as in v1 spec), `Schedule` also gets an
  `events: list[str]` field for tournament/event notes and an `available_courses:
  list[str]` field for Phase 0's course picker.
- The active club's YAML (Phase 0) gains an `identity` block: your own name, kept for
  now, plus a `friends` list that may turn out to be unnecessary — see "Live site
  findings" above. pc caddie's native friends list already makes real names visible for
  friends and anonymizes everyone else, so once the "any non-anonymized name = friend"
  theory is confirmed, this config field can likely be dropped rather than kept as a
  second, redundant source of truth.
- `storage.py` — SQLite-backed persistence, **not just a cache**: it's the only record of
  the past that will ever exist, since pc caddie itself won't show it later. Implemented
  and tested 2026-09-06 (`tests/test_storage.py`, 9 tests). Three tables, one database
  file per club rather than a `club_id` column — `path` already separates clubs:
  - `scrapes` — one row per scrape *event* (course, date, scraped_at) — a batch header.
  - `slots` and `weather_points` — each scrape's actual data, split out since weather is
    a separate axis from occupancy (`booking_watch.py` needs to diff just the weather
    side between two scrapes without caring about player names). `load_latest_schedule()`
    reconstructs a `Schedule` from the latest scrape's rows; `sun_times` and
    `available_courses` aren't persisted, left for a caller to add back if needed.
  - `confirmed_bookings` — see below.
  `last_scraped_at()` (added 2026-09-06) returns just the timestamp of the latest
  scrape for a course/date, without loading the whole `Schedule` — the mechanism behind
  the adjustable scrape interval below.
  Not yet covered: looking up a *specific* historical scrape by timestamp (only "the
  latest" exists so far) — may be needed once `scrape_once.py`/`booking_watch.py` are
  wired together for real.
- **Confirmed bookings, automatic first, manual as fallback.** Revised 2026-09-05:
  pc caddie's own "My Reservations" page (`cat=reservations`, see "Live site findings")
  lists your upcoming bookings directly, so the scraper reads that automatically on
  every run instead of requiring you to remember a keypress. Nothing extra needed to
  keep it fresh — pc caddie updates it the moment you book through their app, and our
  scraper just sees whatever's current next time it runs. The real risk is *timing*: if
  you book and play a same-day tee time between two scheduled scrapes, it could be
  missed entirely before that date becomes unrecoverable past history — the same
  no-backfill problem as the rest of Phase 1, just sharper here. Two mitigations, both
  kept: the scheduled scrape (below) should run more than once a day (e.g. morning and
  evening) to shrink that window, and the manual `c` keybinding stays as a fallback
  safety net for whatever still slips through, rather than being removed.
- **`booking_watch.py` (new module, 2026-09-06)** — a confirmed booking isn't a fire-
  and-forget event: the situation around it can change afterward, and nothing was
  watching for that. Since every scrape is kept forever, not overwritten (the whole
  reason for that design in the first place), comparing a confirmed booking's slot in
  the latest scrape against an earlier one is pure deterministic diffing — no AI, no
  new scraping. Four things it watches for: your own slot's player count going up
  (someone joined your flight), a neighboring slot that was empty at booking time
  becoming booked (your buffer eroding), general crowding nearby, and — added the same
  day, same reasoning — the weather forecast for the round itself getting worse since
  you booked (a forecast a week out is less reliable than one the day before; reuses
  `weather.conditions_during_round()` against both scrapes, no new API calls). Sunset
  doesn't need this treatment — it's astronomical fact, not a forecast that gets
  revised, so daylight cushion isn't part of this check. Runs as part of the scheduled
  scrape (below); surfaces as a plain in-app banner next time you open the TUI — **not**
  a push notification. Explicitly decided 2026-09-06: this is different from the
  "notify me of a new opportunity" alerts already ruled out earlier — it's protecting
  something you already committed to, not surfacing something new — but a passive
  banner still respects the same "no active pings" preference, so that's the version
  built. An active notification remains a possible later upgrade, not today's scope.
- `tui.py` — Textual app, single-day detail screen: Time | Occupancy | Players, colored
  by fill ratio. `r` = refresh, `c` = confirm your tee time, `q` = quit. The Home screen
  also shows a `booking_watch.py` banner when it has something to report.
- Config via `.env` (see Phase 0's namespaced credentials) + the active club's YAML
  (club URL, default course, default date range)
- A small standalone scrape-and-store script (no TUI), runnable on a schedule (e.g. a
  cron/launchd job) so history keeps accumulating even on days you don't open the app
  yourself. Confirmed 2026-09-05: manual-only runs would leave permanent gaps given
  pc caddie's no-history limitation, so this is worth having from the start rather than
  bolted on later. `scrape_once.py`'s `run()` is real as of 2026-09-06 for the login-free
  half (scrape + save via storage.py); the login-dependent half (`scrape_my_reservations`,
  then `booking_watch.check_for_changes`) degrades gracefully — caught and skipped, not
  fatal — until the real login form exists, so one club's missing login doesn't stop an
  unattended run scraping every other club/course/date it covers. `main()` loops every
  saved club and its `overview_days` window with no arguments needed — not actually
  installed as a cron/launchd job by this session, since that's a standing persistent
  change and stays the user's call.
- **Adjustable scrape interval (added 2026-09-06, after feedback that once/twice-daily
  was too infrequent, especially for a date already booked)**: the fixed "twice a day"
  cadence above is gone. Each club's YAML now has `scrape_interval_minutes` (default 6
  hours) and a shorter `scrape_interval_minutes_booked` (default 1 hour, applied once a
  confirmed booking exists for that date — freshness matters more once there's
  something to protect than for the general far-future browsing window).
  `scrape_once._should_scrape()` checks `storage.last_scraped_at()` against whichever
  interval applies before re-scraping a course/date, so the *cron job itself* can now
  fire often (e.g. every 15-30 min) and the script self-throttles per course/date,
  rather than needing the cron schedule itself tuned to match the desired interval.

## Phase 2 — Weather, daylight & calendar overlay
- `weather.py` — client for [Open-Meteo](https://open-meteo.com/) (free, no API key
  required). Needs the club's lat/lon from its YAML (Phase 0). One call gets all of:
  - Hourly precipitation probability/amount, wind speed, and temperature for the whole
    day, shown per slot in the day-detail table (e.g. a rain-drop indicator past a
    threshold) as a quick visual, but see `conditions_during_round()` below for how
    this actually feeds recommendations.
  - Daily sunrise/sunset (Open-Meteo returns these directly in the same `daily` response
    — no second API needed).
  - `conditions_during_round()` (implemented and tested, 2026-09-05) — a slot's weather
    can't be judged from its tee-off hour alone once a round runs 2-4+ hours. Given the
    day's hourly forecast, a start time, and the round duration, returns the *worst*
    reading across the whole window (max rain/wind; temperature as a min/max pair,
    since cold and heat are both bad but in opposite directions — see `RoundConditions`
    in models.py). Added after user feedback that checking only the tee-off hour misses
    rain rolling in partway through a round.
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
    boost slots where a friend is already booked, and (once Phase 5's heatmap exists)
    whether to steer away from historically/calendar-predicted crowded windows
    (`avoid_predicted_crowd`). "Friend" detection is pc caddie's own native friends list
    surfacing real names in the scraped data (see "Live site findings") — not the
    config-file matching originally planned.
- `recommend.py` (new module) — a thin wrapper: builds a `SearchCriteria` from
  `availability`, runs it via `search.py` across every day in the overview to get the
  hard-filtered candidates (deterministic — party size and time windows are exact
  checks, not judgment calls), then hands those candidates plus the `preferences`
  weights to `ai_assist.rank_slots()` for the actual ranking + reasons. Revised
  2026-09-05: weighing rain vs wind vs friends vs crowd-prediction into one score was
  originally sketched as hand-tuned scoring math (`SlotMatch.score: float`); an LLM
  given the same facts in plain language does this more naturally and produces the
  human-readable `reasons` directly, instead of a formula that needs constant retuning.
- **Build this so the filtered list alone is already useful** (see "Build priority"
  above, revised): `weekly_picks()` should apply `availability` filtering *and*
  exclude non-playable (not enough daylight) and bad-weather slots — all deterministic,
  no AI needed — sorted by something simple like earliest or emptiest among what's
  left. A recommendation that ignores weather/daylight isn't actually a good one, so
  those checks belong in this first useful version, not deferred with the AI-ranked
  upgrade. What *can* wait for `ai_assist.rank_slots()`: nuanced trade-offs between
  candidates that all already pass these checks (e.g. "slightly more rain but much
  emptier"), plain-language reasons, and friend-boosting.
- This is distinct from Phase 5's historical analytics: recommendations use *today's/
  this week's* already-scraped data plus rules you set, not weeks of accumulated history.

**Implemented 2026-09-06**: `search.py`'s `search()` and `recommend.py`'s
`default_criteria_from_config()`/`exclude_unplayable()`/`weekly_picks()` are all real
and tested (36 tests across `tests/test_search.py` and `tests/test_recommend.py`) —
the deterministic baseline this phase actually promised. `weekly_picks()` falls back to
the filtered-but-unranked list while `ai_assist.rank_slots()` is still a stub, rather
than raising, matching the "the filtered list alone is already useful" note above. One
gap found and resolved while implementing `exclude_unplayable()`: `preferences.
avoid_rain`/`avoid_wind` are booleans, with no numeric cutoff for a hard filter to
actually compare against (unlike `avoid_temp_below_c`/`above_c`, already numbers) — see
`recommend.py`'s module docstring and the new optional `avoid_rain_probability_percent`/
`avoid_rain_mm`/`avoid_wind_kph` keys in `clubs/club.example.yaml` for how that's
resolved (sensible defaults, overridable per club) pending the user's own sign-off on
the actual numbers.

## Phase 4 — Multi-day overview & search (home screen)
- New Textual screen: a compact 4-5 day at-a-glance grid, readable in one look — one
  column per day, condensed occupancy + rain/wind/temperature + playability summary,
  plus the Phase 3 recommended pick highlighted per day (not full per-slot detail). Days
  with a tournament/event get their own flag, so a weird-looking sheet doesn't confuse
  you — sourced from pc caddie's dedicated events calendar (`cat=ts_calendar`, see "Live
  site findings"), not a tee-sheet icon as originally planned; it's a cleaner source
  since it directly lists date, affected course "Runde," and holes.
- This becomes the app's **default/home screen**. Drilling into one day (e.g. pressing
  Enter on a day column) opens the Phase 1 single-day detail table.
- Requires the scraper to pull multiple days in one run. Revised 2026-09-05: pc caddie's
  "Overview Areas" page (`cat=tt_timetable_course_alias`, see "Confirmed pc caddie
  markup reference") shows all 3 courses' aggregate free/occupied counts for one date in
  a single request, rather than needing to loop over each course separately — a better
  primary source for this screen's condensed view than assembling it from the per-course
  detail pages, which are still what the Phase 1 drill-down uses.
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
  - Hard filters run as plain deterministic code (`search.py`), same as Phase 3; the
    matches are then ranked by the same `ai_assist.rank_slots()` call Phase 3 uses, with
    the typed-in criteria's candidates in place of the saved-default ones — same engine,
    different input.

## Phase 5 — Local-stats analytics, crowd heatmap & personal stats
- `analytics.py` — the *raw aggregation* stays plain SQL/code, no AI involved: it needs
  to produce actual numbers to color a heatmap grid, and grouping rows by day-type and
  hour is a simple, exact `GROUP BY`, not a judgment call. E.g.: aggregate historical
  occupancy by weekday + time-of-day to answer "when is this course usually emptiest?".
- Needs a few weeks of accumulated scrapes to be useful — this phase's usefulness grows
  over time, not something to judge from day one. Complements Phase 3 (today's rules)
  with "what actually tends to be true here over time".
- **Crowd heatmap** (2026-09-05): `crowd_heatmap()` groups historical occupancy by
  Phase 2's day-type tag (tournament / public holiday / vacation / weekend / workday) x
  hour-of-day, rather than just plain weekday x hour — a Monday during summer break
  isn't "a Monday," it's a vacation-day, and should be compared against other
  vacation-days, not typical Mondays. Rendered as a real colored heatmap screen in the
  TUI (new keybinding).
- `predict_crowding()` — this is where it stops being simple aggregation: guessing a
  *future* date's crowding means classifying its day-type (Phase 2), then judging how
  much to trust a thin or noisy historical pattern for that day-type (a handful of
  "public holiday" data points vs hundreds of "workday" ones). Revised 2026-09-05: that
  judgment call is handed to `ai_assist.summarize_history()` rather than hand-coded
  confidence rules — the raw aggregated rows go in, a trust-weighted estimate (or "not
  enough data yet") comes out. This is what `avoid_predicted_crowd` (Phase 3/4
  preferences) uses to steer the automatic weekly picks and search results.
- Personal stats, built primarily from Phase 1's `confirmed_bookings` table (the
  reliable source): days since you last played, total rounds logged, and whatever else
  turns out fun/sensible from the raw numbers. The fixed stats are plain code; anything
  more open-ended ("say something interesting about my play history") also goes through
  `ai_assist.summarize_history()` rather than growing into a longer and longer list of
  bespoke queries by hand.

*(An earlier version of this roadmap had a separate, deferred "Phase 6 — AI-assisted
insights, opt-in, later" here. Revised 2026-09-05: once AI is the mechanism for
ranking/parsing/interpretation from Phase 1 onward, there's nothing left to defer — see
the "AI placement" note at the top of this doc.)*

## `ai_assist.py` (new module, spans Phases 1/3/4/5)
One shared module wrapping the Claude API (Anthropic SDK), used by whichever phase
needs a judgment call rather than exact logic:
- `classify_booking_label()` (Phase 1) — classifies one booking cell's text as
  anonymized / event-or-lesson-block / guest-block / advance-booking-window-notice /
  friend-name (structured output). Narrower than originally planned — see "Confirmed pc
  caddie markup reference": most of the tee sheet turned out deterministic once
  actually inspected, so plain code in scraper.py handles occupancy/time/blocking
  directly, and this is the one piece still genuinely ambiguous.
- `rank_slots()` (Phases 3/4) — ranks already-hard-filtered candidate slots and writes
  the plain-language `SlotMatch.reasons`
- `summarize_history()` (Phase 5) — crowd-prediction confidence for sparse day-types,
  and open-ended personal-stats commentary
- Each club's YAML gets a small `ai_assist` block (`enabled`, `model`) — off by default
  isn't the plan here (this is the actual implementation mechanism, not a bonus mode),
  but which model to spend on which call is a cost/quality tradeoff that's yours to set,
  not something to hardcode. `ANTHROPIC_API_KEY` goes in `.env` (global, not
  per-club — one Anthropic account covers every saved club).
- Worth being upfront about, same as the retired Phase 6 already noted: every call
  costs money and sends the relevant data (tee-sheet contents, your preferences,
  aggregated history) to Anthropic's API. That trade now starts from Phase 1 instead of
  being deferred — a deliberate choice, not an oversight.

## Considered and dropped
- **Spreadsheet export of history** — decided against for now (2026-09-05): not enough
  time to actually analyze it. Revisit only if that changes.
- **Jump-to-booking shortcut** (one key opens the real pc caddie booking page for a
  slot) — decided against (2026-09-05): booking always has to go through the pc caddie
  app anyway, so this wouldn't save a step.
- **Sourcing sunrise/sunset and holidays from the site's own scraped display**, instead
  of Open-Meteo/Nager.Date — decided against (2026-09-05): reliability as scraped values
  is unverified, and there's no efficiency win since the Open-Meteo call is already
  needed for rain/wind/temperature regardless. See "Live site findings."

## Known risks
- pc caddie's real login form is unverified until inspected by hand, and the tee sheet
  may sit inside an iframe (see `docs/spec-v1.md` for detail) — the original v1 risks,
  much narrower now that table parsing itself turned out deterministic (see "Confirmed
  pc caddie markup reference") rather than needing a hand-mapped selector set, but the
  login form itself is still genuinely unverified.
  Resolved 2026-09-05: the tee sheet itself is a *separate*, non-iframed pc caddie page
  reachable directly, and needs no login at all — see "Live site findings."
- **AI calls cost money and send data to Anthropic's API, starting from Phase 1** —
  not deferred/opt-in the way an earlier draft of this roadmap had it. Tee-sheet
  contents (including other members' names, if visible), your availability/preference
  settings, and aggregated history all pass through `ai_assist.py` calls. Model choice
  per call is configurable specifically so cost is a dial you control, not a decision
  made for you.
- **History can't be backfilled.** pc caddie hides past tee sheets, so any day that's
  neither scraped nor confirmed via the Phase 1 prompt is a permanent gap — not
  something a later phase can go back and fix. The scheduled scrape script exists
  specifically to minimize this, and per the confirmed-bookings revision above, needs
  to run more than once a day to also catch same-day bookings before they're gone.
- **Public-holiday API coverage varies by country**, and there's no universal free
  school-vacation API at all — `calendar.country_code` and `vacation_ranges` may need
  more manual upkeep than the rest of the config, depending on the club's region.
- **Advance-booking-window notices could get miscounted as crowding if not handled.**
  See "Confirmed pc caddie markup reference" — a slot that's just not open for booking
  yet reads identically to a genuinely full slot unless the scraper specifically checks
  for this label. Getting this wrong would quietly bias the crowd heatmap and
  recommendations toward avoiding perfectly good, simply-not-yet-bookable times.
- **Still unconfirmed: what an actual friend's booking looks like.** See "Confirmed pc
  caddie markup reference" — a systematic scan across every available day/course found
  the anonymized pattern and several non-name system labels, but no real name, since
  none of this account's friends had a booking during the walkthrough. The
  classification approach (positively recognize a name, don't just flag "unfamiliar
  text") should hold up, but is unverified against the actual case it exists for.

~~How the 27-hole rotation is actually presented on the site is unverified~~ — resolved
2026-09-05, see "Live site findings": it's a fixed 3-option course picker plus a
separate "Runde X+Y" banner, simpler than the rotating-dropdown risk this used to be.

## Out of scope (all phases)
Booking/auto-booking, notifications, packaging/distribution, mobile support (pc
caddie's own app already covers that). Multi-club support was on this list originally;
reversed 2026-09-05 — see Phase 0.
