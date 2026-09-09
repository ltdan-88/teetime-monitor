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

**Course-alias re-derivation, actually implemented (2026-09-07)**: the "don't assume
Musterhausen's are universal" warning above sat unimplemented until a second real club
("Golf Club Sonnenberg e.V.", club_id `0000002`) got added and genuinely broke — see
"Known risks" for the fix. Its confirmed real `<select id="timetable_selection_alias">`
options: `ALIAS|A001` "18-Loch Schleife", `ALIAS|1810` "18-Loch Schleife (nur erste
9-Loch)", `ALIAS|1811` "18-Loch-Schleife (nur zweite 9-Loch)", `ALIAS|0901` "9-Loch
Schleife", `ALIAS|0601` "Kurzplatz" — five options, sharing no code or naming pattern
with Musterhausen's `COUB`/`COU1`/`COU6`. Its date window is also narrower than
Musterhausen's: `#timetable_selection_date` currently lists only 4 bookable days out,
not 5 (see the new "booking-date window" risk entry — this part is still unmitigated).
One further difference worth a closer look later, not yet analyzed: occupied-slot
player labels on Sonnenberg carry a trailing hole-count suffix not seen on Musterhausen
(e.g. "Occupied / Member (H.H) - 9H") — unconfirmed whether this could ever affect the
`KNOWN_ANONYMIZED_LABELS`/`_parse_slot_row` matching logic, since every case observed
so far still matched the existing anonymized pattern regardless.

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

**Login form + "My Reservations" markup, confirmed live 2026-09-06/07** (the user
logged in themselves each time — Claude only ever inspected the resulting page
structure, never entered or saw the real password): the login form is a plain HTML
`<form>`, no JavaScript, no CSRF token — `POST .../app.php?cat=start` with
`service=login&rq[login]=<username>&rq[password]=<password>`; a failed attempt
re-renders a page still containing the `rq[password]` field, a clean way to detect
failure without guessing at error-message text/language. "My Reservations"
(`cat=reservations`) shows `table.meine-buchungen`, one `<tr>` per booking with
`<td>`s for Details/Persons/Actions. Confirmed against a real demo booking made
2026-09-06 (see `docs/pccaddie-markup-notes.md`): the Details cell's text (its `<br>`s
splitting it into lines) is, in order, a "day, date, time" line, the club name, then
the course name last — the course name is always exactly one of `COURSE_ALIASES`'s own
keys (e.g. "6 Loch Platz"), letting the hole count be derived from its leading digit
rather than needing a separate lookup. Confirmed in both languages: English "Mon,
2026-09-07, 19:50 o'clock" (already ISO date order) and German "Mo, 07.09.2026, 19:50
Uhr" (`DD.MM.YYYY`, needs reordering to `YYYY-MM-DD`). The Persons cell lists
"Lastname, Firstname" per booked person (a trailing "*" on one of them, apparently
marking the account's own booking) — not parsed into `ConfirmedBooking`, which has no
players field.

**Club directory + searchable club picker (2026-09-07)**: prompted directly — the
user described pc caddie's own "Anlagenauswahl" (Facility Selection) feature (real
mobile-app screenshots showing "Zuletzt besucht"/Recently visited and "Alle
Clubs"/All Clubs tabs) and asked for the same searchable dropdown in this TUI, since
they've saved a few visited courses beyond their home club in the real app already.
Investigated live on "My Golf" (`cat=golf`, the web version's equivalent field):
confirmed via `read_network_requests` that nothing fires per keystroke — the entire
platform directory (1300+ clubs at inspection time) sits in one plain `<select
id="user_association_club">`, `<option value="club_id">[club_id] Name</option>` per
club, and whatever search box sits on top is just a client-side filter over it (see
`scraper.py`'s `fetch_club_directory()`/`_parse_club_directory_html()`). New
`club_picker.py` (standalone Textual screen, same convention as `settings_screen.py`)
fetches this once via an already-configured club's credentials, lets the user search
(plain case-insensitive substring on name — a deliberate, friendlier deviation from
pc caddie's own exact-substring, umlaut-sensitive matching, confirmed live
2026-09-06), and saves a new `clubs/*.yaml` stub (`club_config.new_club_stub()`) with
just `club_id` filled in. Can't bootstrap a first club (there'd be no club_id yet to
log in with) — that one still needs manual setup per `club.example.yaml`; this is for
the ones after it. 21 new tests (4 in `test_scraper.py`, 2 in `test_club_config.py`,
15 in `test_club_picker.py`, the latter a real headless Textual `run_test()` app same
as `test_settings_screen.py`) — 276 tests passing (was 255).

**Credentials setup screen, same day, direct follow-up ("I want to setup credentials
from UI. It should be user friendly")**: new `credentials_screen.py` — a Textual
`Screen[bool]`, not its own standalone `App` like the others, specifically so
`club_picker.py` can *push* it the moment it discovers no PCC_USER/PCC_PASS are
configured, let the user fill them in without leaving the picker, and retry the
directory fetch automatically once saved (still runnable on its own too, via a thin
`CredentialsApp` wrapper: `python -m src.credentials_screen`). Username field
pre-fills from the current `.env`; password field uses Textual's own masked input and
is never pre-filled — leaving it blank on save means "keep the existing one," so
there's never a reason to display or retype a password that already works. New
`env_file.py` reads/writes `.env` KEY=value pairs in place, preserving every other
line (comments, unrelated keys, per-club overrides) — starts from `.env.example`'s
own structure if `.env` doesn't exist yet at all.

Real, previously-unnoticed bug found and fixed while wiring this up:
`python-dotenv` has been a listed dependency since the very first commit, but
nothing anywhere in this codebase ever actually called `load_dotenv()` — a `.env`
file sitting next to the project only ever did anything if something *else* (a shell
profile, `direnv`, manually exporting it) had already loaded it into the
environment first. Completely silent, since `resolve_credentials()` degrading to
`("", "")` looks identical whether `.env` is missing, misspelled, or just never
loaded — every "fill in `.env`" instruction in this README up to today only ever
worked by accident, if it worked at all. Fixed at `club_config.py`'s import time
(every real entry point already imports it before doing anything else, including
before `ai_assist.py` constructs its own `anthropic.Anthropic()` client, which reads
`ANTHROPIC_API_KEY` from the environment with no call into this module at all) —
see that module's own docstring for why import time, not lazily inside
`resolve_credentials()` itself.

Also factored the small `TranslatedFooter` widget (previously duplicated three times
across `tui.py`/`settings_screen.py`/`club_picker.py`) into its own
`translated_footer.py`, once this 4th screen needed the identical thing — each
module now re-exports it (`from .translated_footer import TranslatedFooter`) so
existing imports/tests keep working unchanged. 21 more new tests (9 in
`test_credentials_screen.py`, 10 in `test_env_file.py`, 2 more in `test_club_picker.py`
for the auto-push/retry flow, 1 more in `test_club_config.py` regression-testing the
dotenv fix) — 297 tests passing (was 276).

## Phase 0 — Club & course setup
Added 2026-09-05, and deliberately numbered *before* Phase 1: which club and which
course you're even looking at has to be settled before any scraping happens, and the
user's club plays 27 holes with the 9-hole loops rotating which pair makes up "the
18-hole course" week to week — so this isn't a detail to bolt on later, it changes what
"the tee sheet" even means from one week to the next.

- Multi-club config: each club is one YAML file under `clubs/` (see
  `clubs/club.example.yaml` for the template) — its filename (without `.yaml`) is the
  club's id. Was explicitly out of scope in the original spec; reversed 2026-09-05 once
  the user asked to save more than one. Beyond your first club, `club_picker.py`
  (2026-09-07, see "Confirmed pc caddie markup reference" above) adds one by
  searching pc caddie's own directory instead of hand-typing its numeric id.
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
  `ai_assist.py` below. **Done 2026-09-06** — see the login note further down.
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
  since new label wording could appear that hasn't been seen yet.

**Login implemented 2026-09-06**, once the user logged into the real site themselves
and Claude inspected the resulting form's HTML directly (never entering or seeing the
actual password — see "Instruction source boundary" for why that's a hard rule
regardless of authorization). The real form turned out to be a plain HTML `POST`, no
JavaScript, no CSRF token: `POST .../app.php?cat=start` with `service=login&
rq[login]=<username>&rq[password]=<password>` sets a session cookie. So the
"Playwright vs. lighter HTTP client" question above is answered the same way
`scrape_schedule()` already answered it — a plain `httpx.Client` (its cookie jar
carries the session) is all login needs too; no browser automation anywhere in the
shipped tool. `scraper.login()` returns that authenticated client;
`scrape_my_reservations()` uses it to read "My Reservations" — first implemented for
just the confirmed empty state ("No bookings found"), then fully confirmed 2026-09-07
against a real demo booking: each row's Details cell holds date/time/club/course as
plain text lines (`<br>`-separated), the course name always matching one of
`COURSE_ALIASES`'s own keys, confirmed in both English ("Mon, 2026-09-07, 19:50
o'clock") and German ("Mo, 07.09.2026, 19:50 Uhr") date/time formats. Still raises
`NotImplementedError` for anything that doesn't match this confirmed shape, rather
than guessing at unseen markup. `scrape_once.run()` calls this via
`_sync_my_reservations()`, resolving `PCC_USER`/`PCC_PASS` via
`club_config.resolve_credentials()` and treating every failure mode (no slug, no
credentials configured, wrong credentials, or genuinely unrecognized markup) as
best-effort, not fatal — matching the same "one club's login trouble shouldn't stop an
unattended run" principle already used for weather.
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
  **Implemented and tested 2026-09-06** (19 tests, `tests/test_booking_watch.py`):
  `NEIGHBOR_CROWDED` vs. `BUFFER_SHRUNK` turned out to be the same underlying check —
  a neighbor within `buffer_minutes` that flips from "not another flight" to "is one"
  is `BUFFER_SHRUNK`; one that was already a flight and just got bigger is
  `NEIGHBOR_CROWDED` — rather than two independent checks. `WEATHER_WORSENED` takes an
  optional `preferences` dict (the same `avoid_rain`/`avoid_wind` block and thresholds
  `recommend.exclude_unplayable()` already resolves) and only fires on a value that's
  both past the threshold *and* risen since the baseline — already-bad-and-staying-bad
  isn't a new development worth a banner for. `scrape_once.run()` now passes the
  club's real `preferences` through instead of the check being a no-op.
- `tui.py` — Textual app, single-day detail screen: Time | Occupancy | Players, colored
  by fill ratio. `r` = refresh, `c` = confirm your tee time, `q` = quit. The Home screen
  also shows a `booking_watch.py` banner when it has something to report.
  **Implemented 2026-09-06** (14 tests, `tests/test_tui.py`, run headlessly via
  Textual's own `run_test()`/pilot harness — no real terminal window needed — plus a
  live smoke test in a headless tmux session against real seeded data): club picker
  (skipped if only one club is saved), course picker (skipped if the club's YAML sets a
  valid `default_course` or there's only one option), then `DayDetailScreen`. Also adds
  `n`/`p` to move a day forward/back within already-scraped data — not in the original
  bullet list above, but a near-free addition once `load_latest_schedule()` already
  takes a date. `r`'s live re-scrape is wrapped so a real network failure shows a
  status message instead of crashing the whole app. Any
  `storage.load_unacknowledged_booking_changes()` rows show as banners on open, with
  `x` to dismiss them — this is what actually delivers the "warn me if my booking's
  situation changes" feature end to end (see the new `booking_changes` table in
  `storage.py`'s Phase 1 note above). Deliberately stops here rather than also building
  the Phase 4 multi-day overview / search / Phase 5 heatmap screens in the same pass —
  those depend on `scraper.scrape_overview_areas()` and `ai_assist.rank_slots()` /
  `analytics.crowd_heatmap()` being wired into an actual layout, not just unit-tested
  in isolation, and are worth checking against the already-agreed mockups before
  building further rather than guessing blind at three more screens' worth of layout.

**Color themes, added 2026-09-06 ("I'd like color themes like in brew launcher").**
New `src/theme.py`: the same 10 named themes as `brew-launcher`'s own theme system —
catppuccin (default), gruvbox, tokyonight, nord, dracula, green, amber, solarized-dark,
solarized-light, red-sands — resolved the same way (`TEETIME_MONITOR_THEME` env var >
a saved config file > default), persisted the same way (a flat `KEY=value` text file,
`~/.config/teetime-monitor/config`, never sourced as code — the same safety property
brew-launcher's own config file has, just a separate file since a color preference
isn't a per-club fact). Seven of the ten are Textual's own built-in themes (sourced
from the same published palettes brew-launcher's own comments cite — Catppuccin,
Gruvbox, Tokyo Night, Nord, Dracula, Solarized) rather than redefined from scratch;
only the three brew-launcher has that Textual doesn't — the monochrome green/amber
CRT-phosphor palettes and Red Sands (from iTerm2-Color-Schemes) — are registered as
custom `Theme` objects, using brew-launcher's own exact hex values mapped onto
Textual's semantic fields (primary/secondary/accent/foreground/background/etc.),
documented per-theme in `theme.py` since fzf's 15-key vocabulary and Textual's don't
line up 1:1.

Deliberately *not* a hand-built theme-picker screen, unlike this project's other
pickers: Textual's own command palette (`ctrl+p`, or `t` on the day-detail screen)
already provides a searchable, live-preview theme picker covering every registered
theme for free, and applies changes immediately — a genuine improvement over
brew-launcher's own version, which needs a full process relaunch since fzf's colors
are baked in at subprocess-spawn time. `TeetimeApp.watch_theme()` persists whatever
gets picked, including a native Textual theme with no brew-launcher name (e.g.
"monokai") — stored under its own raw name in that case, not forced into the 10.

One real gotcha caught while wiring this up, the same one already caught once this
session in `club_config.save_club_config()`: `theme.py`'s functions originally took
`config_file: Path = CONFIG_FILE` as a plain default — frozen at import time, so
monkeypatching `theme.CONFIG_FILE` in a test would have silently done nothing, and a
test instantiating the real `TeetimeApp` would write straight to the developer's
actual `~/.config/teetime-monitor/config` — confirmed happening before the fix (a
stray `THEME=catppuccin` line briefly appeared on disk from a test run, cleaned up
once caught). Fixed by resolving `config_file` at call time (`config_file or CONFIG_FILE`
inside the function body) instead of a bound default, and verified live in a headless
tmux session end to end: picked "green" via the command palette, confirmed it applied
immediately, confirmed the exact RGB(51,255,102) = #33ff66 hex value in the raw
terminal output, quit, relaunched, and confirmed it came back up already green.

**Bilingual UI (English/German), added 2026-09-06 ("need to make sure the TUI is at
least bilingual, since it will be used in Germany").** New `src/i18n.py`: a flat
key -> template-string dict per language, `str.format()` with named placeholders, one
process-wide current language — same global-preference shape as `theme.py`, sharing
its config file (a `LANG=` line alongside `THEME=`) via a new `src/user_config.py`
factored out of `theme.py`'s original read/write logic once a second module needed the
identical "read/write one `KEY=value` line, preserve the rest" behavior. Default:
German if the system locale (`LC_ALL`/`LANG`/`LANGUAGE`) looks German, English
otherwise — this club's own portal is itself German-language, so a German-speaking
user shouldn't have to ask for it first. Switching is a command-palette entry
("Language: switch to Deutsch"/"...to English", alongside "Theme"), which also
rebuilds the current `DayDetailScreen` in place so every visible label/header/status
message updates immediately, not just on next launch.

Covers every label, button, table header, and status/error message across
`tui.py` and `settings_screen.py` — both club/course pickers, the confirm-booking
form, the day-detail table (including the "no data yet" placeholder), and every
settings-screen field label.

Caught one real bug while wiring this up, not just a test artifact: `apply_language()`
originally re-resolved (env var > saved config > default) and overwrote the current
language on *every* call, including a second call in the same process — meaning
`SettingsScreen.on_mount()` calling it would silently clobber a language someone had
already explicitly set that same process. Fixed to only resolve if nothing has set it
yet, mirroring `get_language()`'s own lazy-resolve-once behavior — found by a test
that set German explicitly, then saw the save confirmation come back in English.

Verified live in a headless tmux session with `LANG=de_DE.UTF-8`: the app came up
already in German without any explicit setting, confirmed every screen's text (table
headers, confirm-booking form, the language-switch command's own two labels), switched
back to English live via the command palette, and confirmed both `THEME=` and `LANG=`
persisted correctly side by side in the same config file. 28 new tests across
`tests/test_user_config.py`, `tests/test_i18n.py`, and additions to
`tests/test_tui.py`/`tests/test_settings_screen.py`.

**Two remaining gaps closed the same day, once the user actually saw a screenshot**
(the Footer key hints and the booking-watch banner were still English — flagged
directly, not left unnoticed):
- **Footer key hints**: Textual's built-in `Footer` derives its text from each
  Screen's `BINDINGS` (a class-level attribute fixed at import time), and no public
  API was found to override a binding's displayed description at render time —
  confirmed empirically (`Screen.bind()` isn't exposed in this Textual version, and
  the only paths that worked touched private internals like `_bindings`). Fixed with
  `TranslatedFooter`, a small custom widget (duplicated once, in `tui.py` and
  `settings_screen.py`, rather than cross-importing and pulling `tui.py`'s much
  heavier dependency chain into the standalone settings screen) that renders its own
  key hints from `i18n.py` — `BINDINGS` itself is untouched and still drives actual key
  dispatch, only the *displayed* text changed.
- **`booking_watch.py`'s banner messages**: previously English-only because they're
  rendered once, at scrape time, by a separate headless process, and stored as
  already-rendered prose. Resolved with the schema change flagged (not silently
  skipped) when this was first built: `BookingChange` now carries `params` (the plain
  values used to build `message`) alongside the English `message` itself; a new
  `params` column on `storage.py`'s `booking_changes` table persists it (JSON-encoded,
  defaulting to `{}` for old rows); and `i18n.render_booking_change(kind, params)`
  re-renders the same change fresh in whatever language is current *when the TUI
  displays it* — falling back to the stored English `message` for a kind it doesn't
  recognize or an old row with no `params`. Weather reasons are keyed
  (`"rain_chance"`/`"rain_amount"`/`"wind"`) rather than stored as English words, so
  they translate too. `message` itself is kept, unchanged, for any non-TUI consumer
  and for the existing tests that already checked it.

One disclosed gap remains, out of scope for this round: Textual's own built-in
command-palette entries ("Theme"/"Quit"/"Keys"/"Screenshot"/"Maximize", from
`App.get_system_commands()`'s base implementation) stay in whatever language Textual
itself ships them in. Overriding those means re-implementing that base method's own
logic to swap in translated strings — not covered here since the user's own report was
specifically about the footer and the banner text, not the command palette's built-in
entries. Verified live again after both fixes: the same `LANG=de_DE.UTF-8` tmux
session now shows a fully German footer and a fully German banner together. 16 more
new tests: 8 in `tests/test_i18n.py` for `render_booking_change()`, 3 in
`tests/test_booking_watch.py` for `params`, 3 in `tests/test_tui.py` (the translated
footer, and the banner rendering from real params), 1 in
`tests/test_settings_screen.py` (its own footer), 1 in `tests/test_storage.py` (the
new `params` column round-tripping). 240 tests passing (was 224).

- Config via `.env` (see Phase 0's namespaced credentials) + the active club's YAML
  (club URL, default course, default date range)
- A small standalone scrape-and-store script (no TUI), runnable on a schedule (e.g. a
  cron/launchd job) so history keeps accumulating even on days you don't open the app
  yourself. Confirmed 2026-09-05: manual-only runs would leave permanent gaps given
  pc caddie's no-history limitation, so this is worth having from the start rather than
  bolted on later. `scrape_once.py`'s `run()` is real as of 2026-09-06 for the login-free
  half (scrape + save via storage.py); the login-dependent half now actually logs in
  too (`_sync_my_reservations()`, once `scraper.login()` was implemented the same day)
  and still degrades gracefully — no slug/credentials configured, a `LoginError`, or
  a `NotImplementedError` from genuinely unrecognized reservations markup are
  all caught and skipped, not fatal, so one club's login trouble doesn't stop an
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
- **Don't open on "today" once it's already over (added 2026-09-07)**: the first real
  end-to-end run (user's own screenshot) — opening the app in the evening landed on
  today's date, where the course had effectively closed and every remaining slot was
  already history. New `tui._initial_date()`: opens on tomorrow instead if today's
  own cached schedule (`storage.load_latest_schedule()`, no live scrape triggered —
  opening the app stays instant) shows every slot's time has already passed; falls
  back to today if nothing's cached yet to check against. Deliberately keyed off the
  schedule's own last real slot rather than a fixed clock cutoff, since course hours
  vary by club and season. 4 new tests, 302 tests passing (was 298).
- **TUI auto-refresh (added 2026-09-07, direct feedback: "can we make autorefresh for
  the maximum timeframe, whenever you run the TUI and at the defined time intervals?
  I think hitting 'r' makes only sense as a manual override")**: a cron job was never
  the *only* way to trigger a scrape — `main()`'s own per-club loop is now
  `scrape_once.scrape_due_for_club(slug, config)`, extracted specifically so
  `tui.py` can call it too. `TeetimeApp` now runs it once right after opening and
  again every 15 minutes while it keeps running, covering the active club's *whole*
  `overview_days` window (matching "maximum timeframe" from the request), not just
  whatever single day is on screen. `_should_scrape()` still throttles what's
  actually fetched exactly as before, so this doesn't scrape more often than each
  course/date's own configured interval. Runs in a real thread
  (`run_worker(..., thread=True)`) so scraping several courses/days doesn't freeze
  the UI — confirmed live with an artificially slow fake scrape (tmux, headless):
  the tee sheet rendered instantly and stayed responsive while the background pass
  ran to completion. `r` is untouched — still a synchronous, always-immediate,
  single-day manual override on `DayDetailScreen` itself.

  A genuinely subtle bug surfaced while building this, worth remembering: the first
  attempt named the new method `_auto_refresh()`, which silently collided with
  Textual's own `DOMNode.__init__` setting `self._auto_refresh = None` (the private
  backing field for every widget's *built-in* `auto_refresh` reactive, unrelated to
  this feature). Since a plain instance attribute shadows a same-named class method
  in Python's attribute lookup, `self._auto_refresh()` silently resolved to `None()`
  instead of the intended method — a `TypeError: 'NoneType' object is not callable`
  with a traceback that stopped exactly at the call site, no deeper frames, which is
  itself the tell for this class of bug. Renamed to `_periodic_scrape()`
  (confirmed via a source grep that nothing in Textual's own codebase uses that name)
  once diagnosed via a minimal standalone reproduction outside pytest, isolating it
  from any test-specific behavior. Also caught and fixed a real test-isolation
  regression this feature's own tests introduced along the way: every test in
  `test_tui.py` that builds a real `TeetimeApp` now triggers this background scrape
  automatically, and none of those tests otherwise mock `scraper.py` — the full test
  suite's runtime jumped from ~15s to over a minute (real requests to the live pc
  caddie site, using this account's real saved club id) before a new autouse fixture
  mocked `scrape_once.scrape_due_for_club` to a no-op by default across that file. 6
  new tests (3 in `test_tui.py` for the auto-refresh wiring itself, 3 in
  `test_scrape_once.py` for the extracted `scrape_due_for_club()`) — 308 tests
  passing (was 302, per the entry just above).
- **Second round of real feedback, same day, from a screenshot of the confirm-booking
  form**: three fixes.
  - **Pre-filled confirm form** ("I already selected a specific time, and the TUI
    should know on which course I'm currently focused"): `ConfirmBookingScreen`
    gained `default_time`/`default_holes`, both shown as real Input *values* (not
    just placeholder hints) but left editable. `DayDetailScreen.action_confirm()`
    reads the currently highlighted row's own time straight off the `DataTable`
    (`_selected_slot_time()` — `None` for the "no data yet" placeholder row or an
    empty table) and derives holes from the course itself via
    `scraper._holes_from_course_label()` — the exact same derivation
    `_parse_my_reservations_html()` already uses, since a course category like "18
    Loch Tee 1" only ever means one hole count.
  - **Switch club/course from the tee sheet** ("how can i switch to a different
    course from the time schedule menu? It is somehow not possible to return to the
    previous menus like choosing the course or login"): new `s` binding on
    `DayDetailScreen`, delegating to `TeetimeApp.action_switch_club_or_course()`.
    `_start()`'s own club/course-selection logic was factored into a shared
    `_pick_club()` helper; the switch action deliberately does *not* reuse
    `_start()`'s skip-shortcuts (default_course, single-club auto-pick past the
    picker) — an explicit request to switch means actively choosing is the point,
    so it always shows the course picker and the club picker (if more than one club
    is saved). A real bug surfaced writing this: an `async def` action method
    dispatched straight from a keybinding isn't running inside a Textual worker
    context, and `push_screen_wait()` requires one (`NoActiveWorker` otherwise,
    confirmed empirically) — fixed by having the plain, non-async
    `action_switch_club_or_course()` kick off the actual picker flow via
    `run_worker(..., exclusive=True)`, same shape as `_start()` itself.
  - **A status-line message during auto-refresh** ("I noticed a slight delay between
    the auto-refresh and seeing the updated schedule. Wouldn't it be better if the
    tool had a loading screen?"): `_periodic_scrape()` now shows "Refreshing…" in
    the status line the moment a background pass starts, and "Refreshed." once it
    lands. Deliberately not a full loading *screen* — that would defeat the point of
    running the scrape in a thread in the first place (staying usable while it
    scrapes). Also worth noting: the delay was never partial data becoming visible
    either — each course/date is saved as one complete `Schedule` per scrape (see
    storage.py's own module docstring), so the table only ever shows the previous
    complete scrape or the new one, never a mix.

  Verified live in headless tmux against a seeded schedule and fake club/course
  config: selecting a row and pressing `c` correctly pre-filled both fields;
  pressing `s` showed the course picker even with `default_course` set, and picking
  a different course actually swapped the screen and re-scraped. 8 new tests (5 for
  the confirm pre-fill, 2 for the switch action, 1 for the status message) — 316
  tests passing (was 308).
- **Dim today's own already-passed slots (added 2026-09-07, direct feedback: "can
  you hide or make timeslots less visible that are in the past? For example now is
  11:18, so I need a visible feedback that I won't be able to make reservations for
  11:10 or earlier today")**: `DayDetailScreen.load_schedule()` now wraps a slot's
  time, occupancy, and player names in Rich's `[dim]` style (new `_dim_if()` helper)
  once its own time has already passed — but only when the screen is actually
  showing *today* (`self.date == _TODAY()`); a future or past day never compares
  itself against the current clock at all. Dimmed rather than hidden, matching the
  existing block_reason rows' own style — a past slot is still real information
  (who played it), just nothing you can act on anymore. New `_NOW_HHMM()` (added
  alongside `_initial_date()` earlier the same day) supplies "now" the same
  "patched as a whole in tests" way as `_TODAY()`. One existing test
  (`test_day_detail_next_and_prev_day_reload_schedule`) happened to use a fixture
  date that had, by the time this shipped, become literally "today" on this
  machine's real clock — pinned `_TODAY()` there to a fixed value so the test
  doesn't silently start failing again the next time the calendar catches up to a
  fixture date. Verified live in tmux with a real color comparison (two slots at
  the same fill ratio, one past and one future): the past slot's occupancy rendered
  in a visibly muted, desaturated tone against the upcoming slot's vivid one. 3 new
  tests — 319 tests passing (was 316).
- **Search for a club inline, and a way to back out of a picker (added 2026-09-07,
  direct feedback: "I want to be able to switch clubs on the fly. It is a hassle if
  you need to first save clubs into the config" and "how do I quit from club/course
  picker or return to the schedule?")**: two related fixes.
  - `club_picker.py`'s interactive UI was extracted from its own standalone
    `ClubPickerApp` into a plain `Screen[str | None]`, `ClubSearchScreen` — dismisses
    with the newly saved slug, or `None` if backed out without saving. `ClubPickerApp`
    is now a thin wrapper pushing it, same shape as `credentials_screen.py`'s own
    `CredentialsApp`/`CredentialsScreen` split. `tui.py`'s `ClubPickerScreen` gained
    an `offer_search` flag that appends a "🔍 Search for a club…" entry
    (`_SEARCH_FOR_CLUB_ID` sentinel) to the option list; picking it pushes
    `ClubSearchScreen` right there, authenticating with whichever club is already
    known (any saved club's credentials work platform-wide). The switch flow's own
    `_pick_club_or_search()` always shows this picker now — even with only one club
    saved — specifically so the search entry stays reachable; `_start()`'s own
    `_pick_club()` keeps skipping the picker when there's nothing to choose between,
    unchanged, since that's still the right behavior for a fast, automatic launch.
    A newly found club goes straight into course-picking for it, no need to
    re-select it from the (now-updated) club list. One more frozen-default bug
    caught while wiring this up: `ClubSearchScreen.__init__`'s `clubs_dir` parameter
    still used a class-definition-time default (`= club_config.CLUBS_DIR`) — fine for
    the screen's original standalone-only use, but wrong now that `tui.py` also
    constructs it directly without passing `clubs_dir` at all; fixed with the same
    None-sentinel pattern already used for `env_path`/`template_path`.
  - `ClubPickerScreen` and `CoursePickerScreen` both gained `escape` (dismiss with
    `None`, changing nothing) and `q` (quit the whole app) bindings — there was
    previously no way to back out of either screen at all short of force-quitting.
    `_start()` and the switch flow both now handle a `None` result: at startup
    (nothing to return to) it exits the app; from the switch flow (there's a real
    schedule to go back to) it simply leaves the current `DayDetailScreen` untouched,
    not popping or replacing anything until a club *and* course are both actually
    chosen.

  Verified live in tmux: the search entry appears even with only one club saved;
  selecting it correctly logs in and fetches the real (faked) directory; searching
  filters live. 9 new tests (2 in `test_club_picker.py` for `ClubSearchScreen`'s own
  dismiss-with-slug/`None` behavior, 7 in `test_tui.py` for the picker
  escape/cancel bindings and the full switch-and-search integration) — 328 tests
  passing (was 319).
- **A first taste of Phase 3 recommendations on today's own view (added 2026-09-07,
  after setting up scheduled background scraping via `launchd` — a real cron/launchd
  job was finally installed this session, closing the "history can't be backfilled"
  risk for good — the user asked to "continue with the next items")**: rather than
  wait on Phase 4's multi-day overview screen (still gated on a mockup sign-off),
  `DayDetailScreen.load_schedule()` now reuses the exact same deterministic pipeline
  `recommend.weekly_picks()` already uses — `search.search()` for party
  size/time-window/buffer, then `recommend.exclude_unplayable()` for weather/daylight
  — applied to just the one already-loaded `Schedule` instead of the whole overview
  window (`_recommended_times()`). A matching, still-upcoming, non-past slot gets a
  "★" prefix in the Time column. A club with no `availability` block configured, or
  a schedule with no weather attached, just means nothing gets marked — never an
  error. ~~One accepted, disclosed gap: `sun_times` isn't persisted by storage.py
  (see its own module docstring), so a `Schedule` loaded this way never has it —
  the daylight half of `exclude_unplayable()` can never actually exclude anything
  here, only the weather half can.~~ — **closed 2026-09-08, see below.**

  **Per-tee-time weather + sunrise/sunset, 2026-09-08** — a chain of direct
  feedback, each one surfacing the next real gap underneath the last:

  1. "I still don't see any weather forecast. Shouldn't that be visible in the
     tee time overview?" — a real screenshot, after the automatic location lookup
     above had genuinely already found and saved a location. Root cause:
     `TeetimeApp._club_config` was snapshotted once in `_open_club()` and reused
     for every background scrape for the rest of that session — a location added
     mid-session (exactly what had just happened) never reached
     `scrape_due_for_club()` until the app restarted. Fixed: `_periodic_scrape()`
     now re-resolves `_resolved_config(self._club_slug)` fresh on every pass
     rather than trusting the snapshot.
  2. "Yes per tee time indicator, also don't forget about the sunrise and sunset
     times" — asked once the missing-weather bug above was fixed and it became
     clear per-slot weather (part of the *original* Phase 2 plan — "shown per slot
     in the day-detail table," see that phase's own notes below — but only the
     invisible half, `conditions_during_round()`, had ever actually been built)
     had never shipped either. Investigating it surfaced the accepted gap struck
     through above was worse than "accepted": `sun_times` wasn't just unused by
     recommendations, it was fetched at scrape time and then unconditionally
     *dropped* — `storage.py`'s `scrapes` table had no columns for it at all, so
     nothing that ever loaded a schedule back out (every real TUI display, not
     just this one method) could have shown it even if it had wanted to.

  Fixed properly, not just displayed on top of the same gap: `storage.py`'s
  `scrapes` table gained `sunrise`/`sunset` columns, `save_schedule()`/
  `load_latest_schedule()` round-trip them, and `init_db()` migrates an
  already-existing table via `ALTER TABLE` rather than leaving this developer's
  own real accumulated scrape history behind (pc caddie hides the past — there's
  no re-scraping an old date to backfill it, so this had to be a migration, not a
  fresh schema). `tui.py` gained a `#daylight` line above the tee sheet (the
  day's own sunrise/sunset, or blank without a forecast) and a fourth table
  column (`_slot_weather_cell()`/`_weather_point_for_time()`) — a 🌧/💨 icon past a
  plain visual threshold (independent of a person's own configurable
  `avoid_rain_probability_percent`/`avoid_wind_kph` — this is "worth noticing at a
  glance," the same spirit as the existing occupancy fill-color logic, not a
  personal-comfort filter) plus that hour's temperature, or a plain ☀ otherwise.
  `_recommended_times()`'s own "accepted gap" note is retired — the daylight half
  of `exclude_unplayable()` can now actually exclude a too-late tee time through
  this method too, not just an invisible display gap closed.

  A second, real regression caught live while verifying all of the above (not
  hypothetical — it reproduced immediately): `DayDetailScreen.action_refresh()`
  (`'r'`) had *never* called `_attach_weather()` at all, unlike the background
  scheduled scrape — so the single most ordinary action on this screen, pressing
  `'r'`, silently overwrote any already-attached weather/sun_times with a
  weather-less schedule (`storage.py`'s own "latest scrape wins" rule), undoing
  the entire point of persisting `sun_times` the moment anyone actually used the
  feature. Fixed the same way as `_periodic_scrape()` above: resolves config fresh
  via `_resolved_config()` rather than a stale value, and now calls
  `_attach_weather()` before saving, matching the background path exactly.

  15 new tests across `test_storage.py` (round-trip, blank-when-never-fetched, and
  a from-scratch migration test that builds a real pre-migration `scrapes` table
  by hand and confirms the existing row survives untouched) and `test_tui.py`
  (the pure `_weather_point_for_time()`/`_slot_weather_cell()` helpers, the table
  column, the daylight line, the config-freshness fix, and the refresh-attaches-
  weather fix) — four of these (the migration, the table column, the config-
  freshness fix, and the refresh fix) confirmed to genuinely fail when
  temporarily reverted before being restored. Verified live end to end against a
  real club: a direct script call confirmed real sun_times/weather actually
  persist through a real scrape; the running TUI itself then showed a real
  "☀ Sunrise 06:48 · Sunset 19:49" line and a real per-slot "☀ 17°"/"☀ 22°"
  column tracking the hour, all sourced from one real `'r'` press.

  **Two more real gaps in this same feature, same day, both from direct live
  feedback**: "In the overview it says there are no dry timeslots, but when I
  navigate to the detailed view I can see that rain is only in the morning. I
  don't see chance of rain or amount of rain though."

  1. The per-slot weather cell only ever showed an icon plus temperature, never
     the actual numbers — answered "is this worth a glance" but not the question
     actually asked once weather was genuinely visible for the first time.
     `_slot_weather_cell()` now shows the real rain probability/amount (or wind
     speed) once either crosses the same visual threshold that already decided
     whether to show an icon at all — a plain ☀ and temperature for a row that's
     genuinely calm and dry, same as before.
  2. The overview's "no dry picks" message unconditionally implied rain — but
     `exclude_unplayable()` can reject a candidate for *either* weather or
     daylight, and `sun_times` had only started actually persisting through
     storage.py that same day (see the entry above), meaning the daylight check
     could, for the very first time, actually be *why* nothing survived. A tee
     time simply too late to finish before dark was very likely being reported to
     the user as if it were a rain problem. New `recommend.unplayable_reasons()`
     re-checks (for display only, not a third filtering pass) which reason(s)
     actually applied; `tui._day_pick_text()` now picks "no dry picks,"
     "too dark to finish," or a generic "nothing playable" (for a genuine mix)
     accordingly, instead of one label for all three cases.

  9 new tests (`test_recommend.py`'s `unplayable_reasons()` cases,
  `test_tui.py`'s weather-cell number formatting and the three distinct pick
  messages), two confirmed to genuinely fail when temporarily reverted before
  being restored. Verified live against a real club: a real morning-only rain
  window now shows "🌧 70%/0.4mm 16°" per slot, clearing to a plain "☀ 15°" by
  mid-morning, exactly matching the real forecast.

  A real, if narrow, bug surfaced building this: `DayDetailScreen.action_confirm()`
  was reading a selected row's time back out of the Time column's own *rendered*
  text — which, once dimming shipped, could already carry `[dim]...[/]` markup that
  would have leaked verbatim into the confirm form's time field for any past slot,
  unnoticed until the "★" prefix made an existing test actually catch it (asserting
  `"14:00"` and getting `"★ 14:00"` back). Fixed properly: `DayDetailScreen` now
  tracks each row's own plain `slot.time` separately (`self._row_times`, populated
  in `load_schedule()`) rather than ever parsing decorated display text back out.

  Also caught and fixed a test-isolation gap this feature's own tests exposed:
  `_recommended_times()` calls `club_config.load_club_config(self.club_slug)` on
  every `load_schedule()`, and most existing `DayDetailScreen` tests build the
  screen directly (not through a real `TeetimeApp`) without ever mocking that —
  `_day_detail()`'s own default slug ("musterhausen") happens to match a real file
  this developer's own machine has on disk, meaning every such test was silently
  reading real personal config off disk. Fixed with a new autouse fixture
  (`_no_real_club_config_by_default`) returning an empty config unless a test
  overrides it locally. Verified live in tmux with a schedule mixing past, future,
  fully-booked, and in-window-but-past slots: only the one truly-recommendable slot
  got the star, confirmed against the real rendered colors (not just the underlying
  markup string). 6 new tests — 334 tests passing (was 328).

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

**Implemented 2026-09-06**: `weather.py`'s `fetch_hourly_weather()` and
`fetch_sun_times()` are real (each an independent Open-Meteo request — see the
module's own docstring for why not one combined call), tested against mocked
responses (9 tests, `tests/test_weather.py`) rather than the live API on every test
run. `scrape_once.run()` now calls both and attaches the results to the `Schedule`
before saving, using the club's YAML `location` — this is what actually makes
`recommend.exclude_unplayable()` and `booking_watch.check_for_changes()`'s weather
checks see real numbers instead of always getting `None` back (both already had the
logic; they just had nothing real to look at yet). Best-effort: skipped if `location`
is still the `0.0, 0.0` placeholder, and any request failure is caught and logged
rather than sinking the whole scrape — occupancy is still the primary thing a scrape
is for.

**`calendar_context.py` implemented 2026-09-06** (8 tests, `tests/test_calendar_context.py`):
`fetch_public_holidays()` is a plain Nager.Date GET, mocked in tests like Open-Meteo
above; `classify_day()` is pure — priority order exactly as documented above
(tournament > public_holiday > vacation > weekend > workday), each boundary covered by
its own test (a vacation range's start/end dates inclusive, a holiday that falls on a
weekend still classifying as the holiday, a tournament on a holiday still classifying
as a tournament). Not yet wired into anything else — no caller populates a club's
`identity`/day-type view yet, since that's tui.py/analytics.py territory (Phases 4/5),
still stubs.

**Automatic `location` lookup, 2026-09-08** — real user report: "why don't i
currently see any weather forecast?" Root cause found by direct inspection, not
guesswork: none of this developer's own three saved clubs had ever had `location`
filled in at all (`club_config.new_club_stub()` never sets it — every consumer
just silently no-ops without it, `_attach_weather()`'s own docstring already said
so), so weather had genuinely never been fetched for any of them, ever, with
nothing in the app saying why. Direct follow-up once that was explained: "can the
scraper find out location data and fill it in automatically on the fly?"

Checked what pc caddie itself exposes first, live, before writing anything: the
tee-sheet page's own footer links to an "Impressum" (German legal imprint), but
that's the *platform vendor's* address (PC CADDIE://online GmbH, Bad Oldesloe),
not each club's; the club directory is plain `[club_id] Name` pairs, no city or
address anywhere. A general-purpose geocoder that only knows place names (Open-
Meteo's own, already used for `location`'s actual coordinates) returns nothing for
a golf club's business name — that kind of service is built for towns, not
venues.

New `geocode.py` uses OpenStreetMap's free Nominatim geocoder instead, which does
index individual mapped features (including many golf courses tagged
`leisure=golf_course`) — but pc caddie's own club names broke it outright at
first: querying the *exact* name pc caddie gives a club ("Golf Club Sonnenberg
e.V.", "Golfclub Domäne Musterhausen e.V.", "Nippenburg Golfclub GmbH") returned
zero results for all three real clubs tested live. Fixed with two normalizations,
`_normalize_query()`: drop the German legal-entity suffix ("e.V.", "GmbH", ...),
since OSM's own tagging never carries one, and merge a two-word/hyphenated "Golf
Club"/"Golf-Club" into the single word "Golfclub" OSM actually uses — confirmed
live that word order and extra descriptive words ("Domäne") don't matter once
those two are fixed, all three clubs then resolved correctly.

Wired into `club_picker.py`'s save flow (the one moment a club's real name is
known and nothing's been geocoded for it yet) — `find_club_location()` runs
automatically on every save, merging a `location` block into the new stub when
something's found, with the status line saying plainly whether it worked or not
either way. Deliberately best-effort, not a precise pin: of the three real clubs
tested, one matched the actual golf-course feature directly, two matched a
different nearby feature that happened to reference the club's name in its own (a
campsite, a parking area) — acceptable for what this feeds (a weather forecast,
where being a few hundred meters to a kilometer off the real clubhouse changes
nothing), not a substitute for the real address if precision ever mattered for
something else. Deliberately not back-filled onto already-saved clubs — a
one-time, one-directional lookup at save time is all this needs while there's no
real user base yet whose existing clubs would need retrofitting.

16 new tests (`test_geocode.py`'s `_normalize_query()`/`find_club_location()`
cases, plus `test_club_picker.py` covering the save-flow wiring itself), two
confirmed to genuinely fail when temporarily reverted (the `location` never
merged into the saved stub; the geocoder called with the club's raw, un-normalized
name) before being restored. A real test-isolation gap caught building this, same
shape as several before it in this project: a spy on `httpx.get` showed the very
first version of the save-flow test actually reaching the live Nominatim service
before an autouse fixture (mirroring `test_tui.py`'s own
`_fake_course_aliases_by_default`) was added to redirect every test in the file.
Verified live at every level: `find_club_location()` itself against the real
service for all three real club names (each now resolves); the full
stub-plus-location save pipeline end to end into a scratch directory (never the
real `clubs/`).

**A second, more commonly used gap in the same feature, same day**: the user
removed and re-added their real clubs to test the new automatic lookup, then
reported "I still don't see any weather forecast. Shouldn't that be visible in
the tee time overview?" Root cause: `tui.py`'s `f`-to-favorite — `ClubBrowserScreen`,
the app's actual everyday, one-keypress way to save a club, not the "search the
whole directory" screen — calls `club_config.add_favorite()` directly, which built
its own plain `new_club_stub()` and never went anywhere near the geocoding lookup
at all. The earlier work above only ever wired it into `club_picker.py`'s own
separate save flow. Fixed by factoring the lookup into a new
`club_config.new_club_stub_with_location(club_id, name)`, used by *both*
`add_favorite()` and `club_picker.py`'s own screen (which now calls it too,
instead of duplicating the same four lines) — one shared place for "create a new
club's starting config," so a location lookup added to it again in the future
can't miss one of the two paths the way this one did. 3 new tests in
`test_club_config.py`, one confirmed to genuinely fail when temporarily reverted.
A real test-isolation gap here too, same shape as the first: `test_club_config.py`
had several existing `add_favorite()` tests passing real club names with nothing
mocking `geocode.find_club_location()` at all — fixed with the same kind of
autouse fixture as `test_club_picker.py`'s own, confirmed this time by spying on
`httpx.get` across the *entire* test suite in one run, not just one file, and
seeing zero real requests. Verified live again, this time through the actual
`add_favorite()` path itself (not a hand-rolled equivalent): a real club name,
saved into a scratch directory, comes back with a real geocoded `location`.

**A third, real gap in the same feature — found only after the fix above still
didn't work for the actual user, twice** ("i followed your instructions but still
see no weather data"): `ClubBrowserScreen._favorites()` was handing back the file
*slug* as if it were the club's display name, for any club shown via the plain
favorites list (the default view — an empty search box) rather than a live
directory search. A slug ("golfclub-domane-musterhausen-e-v": lowercase,
hyphenated, umlauts folded away, "e.V." mangled into "-e-v") reads close enough to
a real name to go unnoticed in the UI itself — this is genuinely how the favorites
list has *always* rendered a club's name, not a new bug — but it's a confirmed dead
end for `geocode.find_club_location()`, which needs the real name to have any
chance of matching. So the exact sequence recommended to actually fix the user's
real "no weather" problem (unfavorite, then refavorite, from that same plain
list) fed the geocoder a string that could never have worked, twice in a row.

Fixed at the source rather than patched around: `club_config.new_club_stub()`
gained an optional `name` parameter, persisted as a real `name` key once it's
genuinely known (a directory search, or `club_picker.py`'s own screen already
supply one) — `new_club_stub_with_location()` now threads it through.
`ClubBrowserScreen._favorites()` reads that back (`config.get("name") or slug`,
falling back to the slug only for a favorite saved before this fix existed) —
fixing the geocoding dead end *and*, as a side effect, a real display bug that
had just never been reported: the favorites list itself has been showing the raw
slug as every favorited club's own name the whole time.

Also surfaced along the way, worth knowing rather than a dead end for future
testing: `club_config.list_clubs()`/`load_club_config()`/`save_club_config()`
still take a frozen `clubs_dir: Path = CLUBS_DIR` default (the exact gotcha
`add_favorite()`/`is_favorite()`'s own `None`-sentinel pattern already avoids) —
harmless for the real app (which never needs to override `CLUBS_DIR` after
import), but it means patching `club_config.CLUBS_DIR` alone doesn't reach these
three in a test; they need to be substituted directly (see this file's own
`_wire_real_club_config_to()` test helper). Not fixed here — a real, valid future
cleanup, but out of scope for closing today's actual bug.

And a related, separate rough edge worth knowing about, not itself a bug: typing
a plain numeric club id into the search box (as opposed to searching by name)
deliberately never supplies a name at all (`store_names=False` — "open this club"
is a prompt, not the club's name, see `on_input_changed()`'s own comment) — so
re-adding a club that way still can't geocode either, correctly matching the
existing "no name to geocode with" case, but easy to reach for by habit since it's
the more familiar way to jump straight to a specific club.

3 new tests, one confirmed to genuinely fail when the fix was temporarily
reverted before being restored — and doing so reproduced the exact real symptom
directly: the favorites list rendered the literal slug
"★ [0000001] golfclub-domane-musterhausen-e-v" instead of the real club name.

**A fourth reframe of the same feature, this time a genuine design change rather
than a bug**: everything above still tied a club's location to *saving* it,
because that's the only place the lookup ever ran. Live use exposed why that
still wasn't enough. A real screenshot of a real, correctly-named club
("Golfclub Sonnenberg e.V.") showed no weather at all, alongside "weather forecast
is only available for the next 3 days" and "not really sure why it is listing
events in the weather column." Checking the user's actual files (`clubs/`,
`data/`) found the real cause of all three at once: `clubs/` had exactly one
saved club, and Sonnenberg wasn't it — the 2026-09-07 favorites rework already
lets any club be opened and scraped straight from search, without ever being
favorited, and *that* path never ran the geocoding lookup at all, so an unsaved
club had zero weather for every single day. Days 1–3 only looked like they had
weather because `_day_tag_or_weather()` already shows a tournament name ahead of
weather when one exists for that day (working as designed) — day 4 onward, with
no tournament to mask it, showed the plain "—" that "no weather at all" actually
looks like. Re-running the real geocode lookup for "Golfclub Sonnenberg e.V."
confirmed it still resolves correctly (the most reliable of the three real clubs
tested, matching the actual OSM golf-course feature directly) — nothing wrong
with the geocoding itself, just that it had never been asked to run.

Direct follow-up once this was explained: "I don't want to first save a club in
order to see weather forecast... make saving a club to a bare minimum
requirement, like in terms of favorites." So a club's location is no longer tied
to being favorited at all. `storage.py` gained a `club_meta` table (one row,
key `"location"`) in the same per-club db every club already gets the moment
it's scraped, favorited or not — `save_location()`/`load_location()`. A new
`tui._location_for_club(club_id, club_name)` checks that cache first, then
geocodes live and caches the result on a genuine first-ever open, same
one-lookup-per-club rule `new_club_stub_with_location()` already follows for the
saved-club path. `_resolved_config()` (its `club_id`/`club_name` are both
optional, so every unrelated caller is unaffected) fills in `location` from this
whenever clubs/*.yaml has none — whether because there is no clubs/*.yaml at
all, or because one exists but was saved before a location could be found.
Wired into every place `_resolved_config()` already ran: `OverviewScreen`,
`DayDetailScreen`'s pick-marking and manual refresh, and the app's own
background periodic scrape.

9 new tests across `test_storage.py` (the cache round-trips) and `test_tui.py`
(the fallback itself — geocodes an unsaved club, reads the cache instead of
re-geocoding, leaves an already-saved location alone, fills in a missing one
even for a saved club, no crash without a name to geocode with), three
confirmed to genuinely fail when temporarily reverted. Verified live in an
isolated scratch directory against the real "Golfclub Sonnenberg e.V." /
`0000002`: the first call geocodes and returns the real coordinates, creating
only `data/0000002.db` — no `clubs/` directory at all, confirming this never
requires saving the club; a second call (with the network call itself made to
raise, to prove it) returns the same coordinates straight from the cache.

**The Weather column's tournament icon relabeled, same session** ("not really
sure why it is listing events in the weather column"): explained the existing,
deliberate design (a day with something blocking its tee sheet is shown ahead
of weather, on the theory that it's the more consequential fact), but the
question exposed a real overclaim underneath it. `schedule.events` — and from
there `_day_tag_or_weather()`'s 🏆 icon — was built from *any* non-empty
`block-time` reason at all, with nothing to tell a genuine competitive
tournament apart from a routine ladies'/members' day or a maintenance closure;
pc caddie's own tee sheet doesn't publish that distinction anywhere, and
`scrape_events_calendar()` (the one source that plausibly could) has been an
unimplemented stub since Phase 1. A trophy specifically claims "competition" —
more than this app can actually verify from real data. Also found while
checking this: `disable-time` reasons (advance-booking-window notices, e.g. "4
Tage im Voraus ab 20 Uhr buchbar (KP)") were flooding into `events` right
alongside real block-time ones — a booking-window mechanic is never a
day-level event at all, and this wasn't just a display glitch: `events`
also feeds `analytics.py`'s `has_tournament` day-type classification
(`calendar_context.classify_day()`), so an advance-booking notice was silently
able to mislabel an ordinary day as a "tournament day" for crowd-heatmap
grouping purposes too, not merely showing up wrong in one column.

Fixed both: new `scraper._event_names()` reads `events` directly off
`block-time` rows only (never `disable-time`), factored out of
`parse_schedule_html()` rather than derived from already-flattened `Slot`
objects (which don't carry which status produced their `block_reason`) — a
blank block-time label (a real, confirmed case, see `_parse_slot_row`'s own
docstring) is excluded here too, same as before. `_day_tag_or_weather()`'s
icon changed from 🏆 to 📌 — deliberately generic, since `events` is
genuinely just "the club published a reason a slot isn't normally bookable
today," not a confirmed competition. Left `calendar_context.py`'s own
"tournament" day-type name and priority ordering untouched — that's a
separate, working, already-documented classification bucket, not itself
what was reported wrong.

7 new/changed tests across `test_scraper.py` (`_event_names()`'s own cases:
block-time included, disable-time excluded, blank labels excluded, dedup+sort;
the existing full-page integration test updated to expect only the genuine
event) and `test_tui.py` (the icon change). Verified live: a fabricated page
with both a real block-time event and a disable-time notice on the same day
now reports only the genuine event in `schedule.events`, rendered as "📌
Dienstag-Ladies" in the overview cell — the notice no longer appears at all.
526 tests passing (was 522).

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

**Settings screen, added 2026-09-06 — built ahead of Phase 4's TUI, per direct
feedback that preferences needed to be editable from the UI, not just by hand-editing
YAML.** `src/settings_screen.py` is a standalone Textual screen (`python -m
src.settings_screen <club-id>`) for the `availability`/`preferences` blocks above plus
the scrape interval — the settings that actually came up in that feedback, not a
general club-config editor (things like `club_id`/`location`/`identity` are set-once
values, still hand-edited). `club_config.save_club_config()` is the underlying
write-back — implemented and tested alongside it, with one accepted limitation: it
rewrites the whole YAML file, so hand-written comments in a club's own copy don't
survive a save (the checked-in `club.example.yaml` template is never touched, so it
stays available as reference either way). This is genuinely a separate screen from the
eventual tui.py home screen, not a preview of it — no club/course picker, no tee-sheet
view, just the settings form.

**Wired into the main app, 2026-09-08** — direct feedback once the overview screen
existed and a real user went looking for it: "i don't even know where to configure
from the UI." Standalone-only had quietly become a real gap, not a deliberate
scope line, once there was a whole running app around it with no path in. Converted
`SettingsScreen` from its own standalone `App` to a plain `Screen` (a thin
`SettingsApp` wrapper keeps the standalone command working unchanged), and bound `e`
to it on both `OverviewScreen` and `DayDetailScreen`. Editing settings on a club
that isn't a favorite yet (`club_slug is None`) favorites it automatically first —
editing settings needs somewhere to write them, and that's already what favoriting
means — rather than sending the user to find `f` on a different screen first. A
saved change reloads whichever screen is current immediately, since availability/
preferences changes can affect the ★ marker, the overview's pick column, and "This
week's picks" all at once. 6 new tests (2 integration-level through a real
`TeetimeApp`, the rest the existing suite's own `SettingsScreen` tests updated for
the `App`→`Screen` change).

**Made global, same day** — direct same-day follow-up: "i also want the settings/
preferences to be global and not tied to a specific club." Correct about what these
actually are: your own standing availability and weather comfort are facts about
*you*, not about any one club, so the per-club design meant re-entering the same
rules into every second club you added, never actually a different answer. New
`global_preferences.py` reads/writes one shared file
(`~/.config/teetime-monitor/preferences.yaml`, same directory `user_config.py`
already uses for theme/language — its own file rather than that module's flat
`KEY=value` format, since this data is genuinely nested). `SettingsScreen` no longer
takes a club argument at all — there's only the one settings set to open — and the
"favorite this club first" behavior from the paragraph above is gone entirely, since
there's no longer a club-specific file to need one for. `tui.py` gained
`_resolved_config(club_slug)`, a shallow merge of a club's own genuinely-per-club
settings with the global file on top, used everywhere `OverviewScreen`/
`DayDetailScreen` previously read a club's `availability`/`preferences` directly — a
side benefit found while wiring this up: recommendations now work on a club you
haven't even favorited, since your global rules no longer need a per-club file to
attach to. `scrape_once.py`'s `run()`/`scrape_due_for_club()` merge the same file in
too, so the background scrape's booking-watch buffer check and scrape-interval
throttling both use your current global settings regardless of which club they're
scraping. `clubs/club.example.yaml` had its `availability`/`preferences`/
`daylight_buffer_minutes`/`scrape_interval_minutes*` blocks removed accordingly;
`location`, `overview_days`, `default_course`, `identity`, `ai_assist`, and
`round_duration_minutes` stay per-club, since each of those is a genuine per-club
fact. One real test-isolation gap caught while building this, same shape as several
before it in this project: an early version of a new test opened settings through a
real `TeetimeApp`, saved, and wrote directly to this developer's actual
`~/.config/teetime-monitor/preferences.yaml` before an autouse fixture (mirroring the
one already protecting `theme.CONFIG_FILE`) was added to redirect it in every test.
7 new tests (`global_preferences.py` directly, `_resolved_config()`'s merge, and
`scrape_once.run()` actually using the global buffer setting for a real
`booking_watch` check). Verified live across two real, unrelated clubs sharing one
fake home directory: writing an availability rule for one showed the same ★
recommendation on a completely different club's own tee sheet.

**6-point UI/UX pass, same day** — direct feedback on the newly-reachable, newly-
global settings screen, delivered as a numbered list:

1. *Buttons need to follow common layout conventions (aligned to the right)* — Save
   and Quit were left-hugging the window because Textual's `Horizontal` (`#buttons`)
   doesn't align its children right by default. Added `align: right middle;`, and
   swapped the order to Quit-then-Save so the primary action is rightmost, matching
   the ordinary OS-dialog "Cancel ... Save" convention. Verified by temporarily
   reverting the alignment and confirming a new position-based test genuinely fails
   (`save_button.region.right` dropped from >60 to 34 on an 80-column screen).
2. *Entries take too much vertical space (two rows), labels don't line up* — actually
   three rows: `Input`'s default rendering draws its own top/bottom border, against
   a one-row `Label`. Both `Input` and `Select` support a `compact=True` flag
   (border-less, one row) that Textual already ships but this screen wasn't using;
   `Switch` has no such flag, so it gets a direct `border: none;` override instead.
   `.field-row`'s height dropped from 3 to 1 to match. Reverting just the CSS height
   (not the compact flags) and rerunning confirmed a new test genuinely fails
   (resolved row height 3, not 1).
3. *Many fields could be dropdowns; ranges could use two-handed sliders* — checked
   Textual's actual widget set first: it ships `Select` (dropdown) but no
   slider/range widget of any kind, so the slider half of this isn't something
   Textual can currently do. Converted the fields whose real values only ever come
   from a small known set — party size (1-4), the daylight buffer, and both scrape
   intervals — to `Select` dropdowns with sensible presets (a dropdown also closes
   off "not a number" typos for exactly these fields, since it can't hold a value
   outside its own options). Left genuine ranges (time windows, rain/wind/
   temperature thresholds) as free text: a discrete list for those would be either
   too coarse to be useful or too long to beat just typing a number. A value saved
   outside the preset list (hand-edited YAML, or an old default no longer in the
   list — an early version of the scrape-interval presets accidentally omitted
   `scrape_once.py`'s own 360-minute default, caught by eyeballing a fresh install
   live) is added back into the dropdown under its own value rather than lost or
   crashing the screen.
4. *Group entries into categories* — `FIELDS` now carries a `group_key`, and
   `compose()` wraps each group in an expanded-by-default `Collapsible` (Textual's
   own expandable-section widget): Availability / Weather / Priorities / Timing &
   scraping.
5. *The footer doesn't scale — hides elements when the window narrows* — real,
   global bug, not settings-screen-specific: `TranslatedFooter` (docked at the
   bottom of every screen in the app) had a fixed `height: 1`, so its one joined
   line of key hints could only be clipped, not wrapped, once the window got
   narrower than that line. `DayDetailScreen` alone has ten hints, easily wider than
   a narrow terminal. Changed to `height: auto`, which lets Textual's `Static` wrap
   normally. Verified against the real regression: reverting to `height: 1` and
   rerunning a new test (`DayDetailScreen`'s footer at 40 columns) confirmed it
   fails (resolved height stuck at 1, needed >1).
6. *Overall consistency; is the footer/keybind order logical* — `credentials_screen.py`
   turned out to have the exact same field-row-height mismatch and left-hugging
   button row as settings_screen.py, just never called out by name — fixed there too
   for consistency (compact `Input`s, right-aligned Quit-then-Save). For ordering:
   `ClubBrowserScreen`'s footer had `escape` (Back) placed right after `enter`, ahead
   of `Favorite`/`Refresh` — inconsistent with `OverviewScreen`/`DayDetailScreen`,
   both of which put their own actions before escape/commands/quit at the end.
   Reordered to match (`enter`, `f`, `r`, `escape`, `q`), which also makes more sense
   given this screen is usually opened as the app's own home screen
   (`allow_cancel=False`), where escape often does nothing at all. Every other
   screen's ordering (primary action first, this screen's own actions next,
   escape/commands/quit last) was already consistent. Not attempted: making the
   settings form itself reflow at very narrow widths (its fixed-width label/input
   columns need roughly 65+ columns to both stay visible) — that's a pre-existing
   limitation, not something this pass introduced, and wasn't part of the feedback.

6 new tests. All temporarily-reverted-to-confirm-it-actually-fails checks above were
genuine, not just CSS-text assertions — each measures real resolved widget positions/
sizes through Textual's own test harness. Verified live in an isolated sandbox
(`HOME` pointed at a scratch directory, never the real `~/.config/teetime-monitor/`).

**Narrow-window fallback, same-day follow-up** ("I'd like that made more flexible
too", in response to the "not attempted" note closing point 6 above) — the settings
form's fixed 42-column label + 20-column field layout needed roughly 70+ columns
and had nowhere to shrink to below that, so a narrower window clipped the field
clean off screen rather than reflowing. This version of Textual has no CSS media
query, so `SettingsScreen.on_resize()` measures the screen's own actual width and
toggles a `-narrow` class; while set, `SettingsScreen.-narrow`'s CSS rules switch
every field row from side-by-side to label-above-field (both spanning the full
width) — taller per field, but nothing hidden or cut off, which matters more at a
narrow width than staying compact does. The exact threshold (72 columns) was found
empirically, not calculated: resized a live terminal down column by column and
found a `Select` field's own dropdown arrow started getting clipped at 70-71,
before the row would have overflowed outright. 2 new tests (435 total, was 433),
both confirmed to genuinely fail against real resolved widget heights/positions
when the fix was temporarily reverted (`-narrow` never applied; a field pushed
past the right edge of a 50-column screen) before being restored. Verified live
across several widths from 30 to 80 columns in an isolated sandbox — including the
exact 71/72 boundary, and an extreme 30-column case that stayed fully visible
(labels wrapping, nothing cut off) rather than breaking outright.

**Time fields split into hour/minute, same-day follow-up** ("can you at least
split the input boxes for the time ranges into something like hh:mm?"): the four
weekday/weekend window fields were a single free-text `"17:00"`-or-blank `Input` —
now two small `Select` dropdowns (hour 00-23, minute :00/:15/:30/:45) joined by a
`:` separator, the same "small known set of values → dropdown" treatment
`min_open_spots` and the scrape intervals already got in the 6-point pass above.
Kept the split contained to the UI layer: `_time_widget_ids()` and the
`"optional_time"` branches of `compose()`/`_read_widget_values()` are the only
places that know a time field is really two widgets now —
`widget_values_to_config()` (and its own existing tests) still receive one plain
`"HH:MM"` string per field, unchanged, since `_read_widget_values()` recombines the
two dropdowns before handing anything off. A blank hour means "not set" regardless
of the minute dropdown; a chosen hour with no minute picked collapses to `:00`
rather than being a second way to mean "not set." A stored minute outside the
quarter-hour presets (hand-edited YAML, or an old value from before this change)
loads and stays selectable via the same "inject the current value in if missing"
handling every other dropdown in this screen already uses. 4 new tests (439 total,
was 435), one confirmed to genuinely fail (a broken combine step lost the saved
value entirely) when temporarily reverted before being restored. Verified live at
both a normal and a narrow (50-column, stacked) width.

**Buffer split into before/after, same-day follow-up** ("does a symmetric buffer
make sense or should it be adjustable asymmetrically?" -> "split it like in your
recommendation, and make it a dropdown in 10 minute increments"). Real design
question, not a bug report — walked through it before touching code: the group
ahead of you slowing your pace and the group behind you crowding in aren't the
same concern, so one symmetric `buffer_minutes` either over- or under-protects
against whichever direction actually matters to a given person. Split into
`buffer_before_minutes`/`buffer_after_minutes` everywhere `availability`'s buffer
is read — `search.py`'s `SearchCriteria`/`_has_buffer_clearance()` (recommendations),
`booking_watch.py`'s `_neighbor_changes()`/`check_for_changes()` (the post-booking
"someone crowded you" alert), and the settings screen, where both render as
`Select` dropdowns in 10-minute steps (`BUFFER_CHOICES`), same treatment as
`min_open_spots`/the scrape intervals.

Real backward-compatibility concern caught before shipping, not after: the actual
`clubs/*.yaml` on this developer's own machine still has the old single
`availability.buffer_minutes: 10` (never migrated when settings went global,
since nothing had been saved through the new settings screen in production yet) —
renaming the key outright would have silently dropped that real, currently-active
10-minute buffer to zero in both directions, with no error to notice. Fixed with
`search.resolve_buffer_minutes(availability, direction, default)`: reads the new
direction-specific key if present, otherwise falls back to the old single key for
both directions. Used at every read site (`recommend.py`, `scrape_once.py`) *and*
in the settings screen's own `config_to_widget_values()` — the screen must show
what the app is actually doing, not just what's literally under the new key yet,
or opening it would show "0 min / 0 min" for someone whose real buffer is still
faithfully being read as "10 min both ways." A save always writes the new keys
(ordinary "int" fields) and now also drops the old `buffer_minutes` key once it
does, so a saved file doesn't carry a dead, confusing leftover key forward.

14 new tests (455 total, was 439) across `search.py`, `booking_watch.py`,
`recommend.py`, `scrape_once.py`, and `settings_screen.py` — asymmetric cases
specifically designed so a lazy "just use whichever buffer is bigger"
implementation would still fail them (a close flight on the *unprotected* side
must NOT be rejected, checked with no flight at all on the protected side, so
there's nothing for a non-direction-aware shortcut to coincidentally get right).
Confirmed genuinely by reverting three separate pieces in turn (the direction
split itself, the settings-screen display fallback, the stale-key cleanup) and
watching the corresponding tests fail before restoring each. Verified live: wrote
a fake global preferences file with the old single key (mirroring this developer's
own real, unmigrated club file) and confirmed the settings screen shows "10 min"
on both new dropdowns, not "0 min."

**Standing note, right after the above**: "don't worry about my configs, we are
still developing the tool and I won't be using it productively yet." The
backward-compat work above is left in (it was already built and tested, and
ripping out working code for no benefit isn't worth the churn), but future config
schema changes (a renamed/split/removed key) don't need a `resolve_*()`-style
fallback or any other migration path while the tool has no real users yet — just
change the shape outright and let this developer's own local files need
re-entering. Re-check before assuming this still holds once real use starts.

**Hour dropdown trimmed to plausible tee times, same-day follow-up** ("can you
please remove hours that don't make sense from the dropdown menus?"). The
weekday/weekend window's hour `Select` offered the full 00-23 — including hours
no golf club is ever open at (a "workdays after 02:00" window makes no sense).
Narrowed to `EARLIEST_TEE_HOUR`-`LATEST_TEE_HOUR` (05:00-21:00), chosen to
comfortably cover real confirmed tee times seen live (as early as 06:40, see
`docs/pccaddie-markup-notes.md`) with room on both ends for an early-summer
sunrise round or a last-light evening one, without offering the entire clock. A
value outside that range (hand-edited, or saved before this change) still loads
and stays selectable — the same generic "keep the actual current value
selectable" mechanism every other dropdown on this screen already relies on, not
new migration logic (see the standing note just above). 2 new tests (457 total,
was 455), one confirmed to genuinely fail (the full 00-23 range still offered)
when the restriction was temporarily reverted before being restored.
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

**Implemented 2026-09-07, as `tui.OverviewScreen`** — the actual home screen once a
club/course is picked, replacing the old "land straight on today's tee sheet" flow. One
row per attempted day (a `DataTable`, same widget `DayDetailScreen` already uses, not a
custom card grid — the mockup's cards were a design-conversation aid, not a pixel spec):
weekday + exact ISO date (a direct, resolved mockup-feedback point: exact dates, not
ambiguous MM/DD), weather-or-tag, a six-block "heat strip" for 08:00-20:00 colored by
average fill ratio, and that day's own pick. Real deviations from the plan above, each
for a concrete reason found while building it:
- **Not the "Overview Areas" aggregate page** — reuses `storage.load_latest_schedule()`
  per day for the *already-selected* course instead. That page's aggregate counts don't
  carry enough detail for the pick column (a real recommendation needs actual slot
  times, not just a busy/free ratio), and the per-course data was already being scraped
  and stored for `DayDetailScreen`'s own drill-down — a second, separate data path for
  the overview would mean two sources that could disagree.
- **Tournament flag comes from `schedule.events`** (the block-reason names
  `parse_schedule_html()` already collects from the tee sheet itself), not a separate
  `ts_calendar` fetch — one real club during testing showed three different events
  across five days straight off the tee sheet, with no second request needed.
- **How many days to show is no longer a fixed "4-5 day" grid** — see the 2026-09-07
  cross-club sweep (scraper.py's module docstring): a club's own bookable window ranges
  1-31 days, so `overview_days` (config, still defaulting to 5) is how many day-rows to
  *attempt*, and `scraper.fetch_available_dates()` decides per-refresh which of those
  are actually open; a day beyond the real window renders as "not open for booking yet"
  rather than a misleadingly empty row.
- **"This week's picks" only shows once `availability` rules are actually configured** —
  a "Still open" question from the mockup review, now resolved: showing "no picks"
  under every single day on an unconfigured club would read as broken, not empty.
- Drilling into a day is `enter` on the row; `escape` on `DayDetailScreen` pops back
  and reloads the overview, in case a scrape landed while drilled into that day.

29 new tests (`tests/test_tui.py`), including the pure heat-strip/weather-tag/pick-text
helpers directly, not just through the screen. Verified live in tmux against a real,
previously-unscraped club: real tournament names rendered as tags, the heat strip's
green/yellow/bold-red coloring confirmed via raw ANSI capture (not just the underlying
markup string), and the club's own narrower real window (4 days, not 5) correctly
greyed out the 5th attempted row.

- **Search** (implemented 2026-09-08, see below — deliberately not bundled with the
  overview above, per the mockup review's other resolved question that it should stay
  its own screen): for the one-off cases that don't match your saved `availability`
  defaults — e.g. "just this once, 3 players, weekdays only, after 15:00." New
  keybinding opens a small form; `search.py`'s `SearchCriteria` covers:
  - **Party size** (`min_open_spots`) — enough open spots in the slot for your group
  - **Separate workday/weekend time windows** (`weekday_window` / `weekend_window`) —
    a day type with no window set is skipped entirely, so leaving one out means "only
    the other day type"
  - **Buffer from other flights** (`buffer_before_minutes`/`buffer_after_minutes`,
    split 2026-09-08 — see this same day's entry above) — a minimum gap to the
    nearest other booked flight ahead of you and behind you, checked separately
  - Hard filters run as plain deterministic code (`search.py`), same as Phase 3; the
    matches are then ranked by the same `ai_assist.rank_slots()` call Phase 3 uses, with
    the typed-in criteria's candidates in place of the saved-default ones — same engine,
    different input.

**Implemented, same session** ("what should we build next?" → "ad hoc search screen
(Recommended)", from a short menu of the remaining backlog): new `tui.SearchScreen`,
pushed from `OverviewScreen` via `/` (reserved for exactly this since the screen's
own docstring first flagged it as "not yet built," 2026-09-07). Backend needed zero
new code — `search.py`, `recommend.exclude_unplayable()`, and `ai_assist.rank_slots()`
were all already real and fully tested — so the actual work was wiring a form to the
existing pipeline: `recommend.weekly_picks()` was refactored into a general
`ranked_matches(schedules, criteria, config)` (the same three-step pipeline, just
taking an explicit `SearchCriteria` instead of deriving one from a club's saved
`availability`), with `weekly_picks()` now a two-line wrapper calling it with the
usual default criteria — confirmed behavior-preserving (`weekly_picks()`'s own
existing tests all still pass unchanged). The form itself reuses
`settings_screen.py`'s own `HOUR_CHOICES`/`MINUTE_CHOICES`/`MIN_OPEN_SPOTS_CHOICES`/
`BUFFER_CHOICES` directly, for the same look, the same 05:00-21:00 hour trim, and the
same "can't hold an invalid value" guarantee — pre-filled from your saved global
availability defaults (edit from there for this one case, not type everything from
scratch), and searches whatever days `OverviewScreen` already has loaded
(`self._schedules`), not a fresh scrape. `escape`/`q` dismiss back to the overview /
quit the whole app respectively, matching `ClubBrowserScreen`/`CoursePickerScreen`'s
convention for a screen that's part of the main flow (not `SettingsScreen`'s own
"q closes just this screen," since that one's also runnable standalone). 9 new tests
in `test_tui.py` plus 1 in `test_recommend.py`, two confirmed to genuinely fail when
temporarily reverted (the `/` binding removed; the typed-in criteria ignored in
favor of the config's own saved defaults) before being restored. Verified live
against a real, previously-unscraped club (Sonnenberg, 0000002) in a fully isolated
sandbox (`PYTHONPATH` pointed at the repo, `cwd` a scratch directory, so `clubs/`/
`data/` never touch the real project's own): reached the search screen from the real
running app, confirmed the pre-filled blanks and dropdown ranges render correctly
against real loaded data.

**Two real gaps in "This week's picks"/the daily ★ pick, found from a real
screenshot**: "Can you explain why it only recommends tee times on Tuesday? Also,
why does it always recommend 16:00 on any other day?" Both traced to the same root
cause — `ai_assist.enabled` wasn't set for this club, so nothing was ever actually
*ranking* candidates; the deterministic baseline alone was standing in as "the
recommendation" everywhere.

1. **"This week's picks" showed 5 times, all on the same day.** `tui.OverviewScreen.
   _update_picks()` just truncated `weekly_picks()`'s output to its first
   `OVERVIEW_MAX_PICKS_SHOWN` (5) entries — and `search.search()` walks schedules in
   date order, exhausting every matching slot in the *first* day before ever looking
   at the next one. A day with a wide enough window (here: 16:00-18:00 at 10-minute
   intervals) easily has 5+ open slots on its own, so it fills the entire displayed
   list and every other day in the week never gets a chance to appear, regardless of
   whether it also had good options. Fixed with `recommend.diversify_by_day()`: at
   most one pick per date, in the picks' own order (best-first once AI ranking is on,
   otherwise chronological) — a pure, separately-tested function, not folded into
   `weekly_picks()` itself, since the ad hoc search screen's own results table
   deliberately shows every match for a typed-in query, not a diversified digest.
2. **The daily ★ pick was always the literal earliest slot**, not a judged "best"
   one — so once a saved window starts at 16:00 and that exact slot happens to be
   open (the common case), it wins by default every single day, regardless of how the
   rest of the window compares. `tui._availability_pipeline()` used to call
   `search()` + `exclude_unplayable()` directly; now it calls
   `recommend.ranked_matches()` instead — the exact same pipeline `weekly_picks()`
   uses — so "the best slot for one day" and "the best slots for the week" can never
   disagree about what counts as best. `_day_pick_text()` changed from
   `min(candidate.slot.time for candidate in playable)` to `playable[0].slot.time`
   accordingly. With `ai_assist.enabled` false (still this developer's own real
   default), `ranked_matches()` returns exactly what `exclude_unplayable()` alone
   would have, in the same order real scraped slots always come in (chronological) —
   so this is behavior-preserving until AI ranking is actually turned on; only then
   does the star start reflecting genuine judgment instead of plain chronological
   order. `DayDetailScreen._recommended_times()` (which marks *every* good slot with
   ★ in the day-detail table, not just one) was already order-independent — a plain
   set built from `playable` — so it needed no change at all.

6 new tests across `test_recommend.py` (`diversify_by_day()`'s own cases) and
`test_tui.py` (the AI-ranked-vs-earliest distinction, and a real reproduction of the
reported symptom: one day seeded with 5 open slots and four other days with one each,
confirming the overview now shows all 5 distinct dates rather than 5 times on day
one), two confirmed to genuinely fail when temporarily reverted — including a direct
before/after capture of the exact reported symptom disappearing. Verified live in an
isolated sandbox reproducing the real screenshot's own settings (16:00-18:00 weekday
window): raw `weekly_picks()` output was five consecutive Tuesday times exactly as
reported; `diversify_by_day()` turned that into one pick per day across four
distinct dates.

Turning `ai_assist.enabled` on itself was raised and deliberately left for the user
to decide, not enabled silently: a real Anthropic API key is already configured on
this machine, and with `ranked_matches()` now wired into *both* the daily pick (once
per visible day) and the weekly digest, turning it on would mean several separate
paid API calls every time the overview loads, not just one — worth knowing before
opting in, and worth revisiting (e.g. batching per-day calls into one) if the answer
turns out to be yes.

**`ai_assist` moved from per-club to the shared settings screen, same day** ("Sounds
fine, the ai feature should be an option in the settings menu" — the direct answer,
once the cost trade-off above was laid out). This reverses a deliberate design
decision from the 2026-09-08 "make settings global" rework, which explicitly kept
`ai_assist` in `clubs/*.yaml` on the theory that model choice is a per-club
cost/quality tradeoff. In practice nothing about wanting AI ranking on or off (or
which model) actually varies by club here, and the request itself was for one
switch, not a per-club dial — the same shape of correction `availability`/
`preferences` already went through that same day.

`settings_screen.py` gained a fifth `Collapsible` group ("AI ranking") with two new
fields: `ai_assist.enabled` (a `Switch`, same as any other "bool" field) and
`ai_assist.model` (a `Select` of the real Claude model families available at the
time — opus-5/sonnet-5/haiku-4.5 — defaulting to `ai_assist.DEFAULT_MODEL`). The
model field needed a genuinely new `Field.kind` — `"str"` — since every existing kind
("int"/"optional_float"/"optional_time"/"bool") assumes a number, flag, or time; a
model id is just a plain string, passed through unparsed with a blank falling back to
the default. Composed for free through the *existing* generic "a field with `choices`
renders as a `Select`" branch in `compose()` — no special-casing needed there, since
that check was already `kind`-agnostic. `_resolved_config()`'s existing shallow merge
(global overrides a club's own YAML) means a club file that still has `ai_assist` set
directly keeps working as a fallback; it just no longer wins once the shared settings
file has actually set one. `clubs/club.example.yaml`'s own `ai_assist:` block was
commented out with a pointer, matching the exact precedent already set for
`availability`/`preferences` in that same file — and its comment was also corrected
along the way: it used to claim `ai_assist` was "the actual mechanism behind
tee-sheet parsing" too, which was already stale (`classify_booking_label()` has never
actually been called from `scraper.py`'s real parsing path — the deterministic rules
turned out sufficient in practice; only `rank_slots()` is a real, wired-in caller
today).

10 new tests in `test_settings_screen.py` (the new "str" kind's own parsing/fallback
cases, the two fields' defaults/round-trip, a full render-and-save scenario through
the real Switch/Select widgets), one existing test updated for the new group. Four
confirmed to genuinely fail when temporarily reverted (a plain `NoMatches` error —
the fields not rendering at all — rather than a wrong-value assertion, since nothing
about "str" existed yet to revert to a subtly-broken state). Verified live in an
isolated sandbox: the real settings screen shows "AI ranking" as its own section,
`AI-ranked recommendations` (Switch) and `AI model` (dropdown, `claude-opus-5`
preselected) both render and scroll into view correctly alongside every other group.

**The model dropdown removed again, same session, one question later**: "Are you
sure haiku is not good enough for this to work?" Worth taking seriously rather than
defending the default reflexively — `ai_assist.DEFAULT_MODEL = "claude-opus-5"` was
never a considered quality requirement for *this* task, just an arbitrary starting
value picked back at this module's very first implementation (2026-09-06), before
there was a real cost-conscious user or a real call path to weigh it against. By the
time `rank_slots()` actually runs, `search.py`/`exclude_unplayable()` have already
thrown out every candidate that fails party size, time window, weather, and
daylight — the model's whole job is picking the best of an already-short, already-
valid list and writing one short plain-language reason per pick. That's a small,
structured, low-stakes task, not one that calls for a slower/pricier model. Changed
`ai_assist.DEFAULT_MODEL` to `claude-haiku-4-5-20251001` accordingly. Direct
follow-up once that reasoning was laid out: "I would not even offer the other
options, since they seem overkill" — so the model `Select` added in the entry just
above was removed entirely, along with the `"str"` `Field.kind` it was the only user
of (no longer any string-shaped, non-numeric/flag/time setting on this screen to
justify keeping it speculatively). A club's own hand-edited `ai_assist.model` (if any
predates this) still works as a fallback through the same shallow merge as
`ai_assist.enabled` itself — this screen just no longer offers a way to set one.

5 of the 10 tests from the entry above were updated (the "str"-kind-specific cases
removed rather than kept around for a mechanism nothing uses any more; the
render/save scenario simplified to just the one Switch). Verified the removal is
real the same way the addition was: reverting it back out and confirming
`ai_assist.model`'s field id genuinely stopped existing on the rendered screen.

**The overview's Weather column split into Weather + Events, and a real storage bug
found along the way, same day**: a real screenshot, direct feedback: "It shouldn't
mix up events with weather data. Can you make an extra column for the events?" The
2026-09-08 fix (📌 instead of 🏆) had softened the *icon*, but the actual complaint —
a column literally labeled "Weather" showing something that isn't weather at all —
was still there. `tui._day_tag_or_weather()` split into `_weather_cell()` (always
real weather, or nothing) and `_event_cell()` (the day's own block-reason note, or
nothing), each its own `OverviewScreen` column now (`Day | Weather | Events | Heat
08–20 | Pick`).

Building a real end-to-end test for this (seed a genuine scraped-and-saved schedule
with both an event and weather, check it through the actual overview table) surfaced
a second, independent bug — not the one being fixed, a new one this same feature
exposed: `storage.load_latest_schedule()` was *re-deriving* `events` from the loaded
slots' own `block_reason` (`sorted({slot.block_reason for slot in slots if
slot.block_reason})`) instead of reading back whatever `Schedule.events` actually
was at save time. A `Slot` only ever carries `block_reason` *text*, never which
`data-status` produced it — so this re-derivation could never tell a genuine
block-time event apart from a disable-time advance-booking notice, silently
reintroducing, on every single load, the exact bug `scraper._event_names()` had
just been fixed to avoid at scrape time the day before (see "Stop overclaiming
'tournament'" above). Since `OverviewScreen` (and `analytics.py`) only ever see a
schedule *after* it's round-tripped through storage, that earlier fix had never
actually been effective for any real, persisted data — only for a schedule still
held in memory immediately after scraping, which nothing in the running app
actually displays.

Fixed the same way `sun_times` was (see `init_db()`'s own docstring, one day
earlier): `scrapes` gained a real `events` column (JSON-encoded), migrated in for
existing databases via `ALTER TABLE`, written directly from `Schedule.events` at
save time, read back verbatim at load time — no re-derivation at all any more. A row
saved before this column existed reads back as no events, same "no migration
fallback needed yet" stance as everywhere else in this project; the very next real
scrape overwrites it correctly.

9 new tests across `test_storage.py` (the real re-derivation bug, reproduced and
fixed; the pre-existing-column migration) and `test_tui.py` (`_weather_cell()`/
`_event_cell()`'s own cases, a full overview-table integration test seeding a real
saved schedule with both an event and weather and checking both columns render
correctly). Verified live in an isolated sandbox, headless tmux, against the real
site (club 0000001): a fabricated event+disable-time-notice day scraped, saved, and
reloaded through actual storage showed "☀ 20°/20°" in Weather and "📌
Dienstag-Ladies" in Events — confirmed via `parse_schedule_html()` → `save_schedule()`
→ `load_latest_schedule()`, the exact real pipeline the running app uses, not a
hand-built `Schedule`.

**`escape`/`q` made consistent across every screen, same session**: "Also I noticed
that exiting the settings you need to hit q, while returning to the overview is ESC
and exiting the TUI is again q. Please make key binds consistent." `SettingsScreen`
was the one real outlier reachable from the running app: no `escape` binding at
all, and `q` meant "close just this screen" rather than "quit the whole app" — a
genuine, user-visible inconsistency once pushed from `tui.py` (where every other
screen's `q` really does exit the process), even though it was never actually a
problem in `SettingsScreen`'s own standalone mode (`SettingsApp.on_mount()`'s
dismiss-callback already exits the app the moment the screen closes either way, so
that mode's behavior is unchanged by this fix). Now: `escape` dismisses just the
screen (what `q` used to do), `q` calls `self.app.exit()` directly, matching
`ClubBrowserScreen`/`CoursePickerScreen`/`SearchScreen`/`HeatmapScreen`/
`DayDetailScreen`'s own convention exactly. The button that dismisses the screen
is relabeled "Cancel," not "Quit" — it was always really a cancel action (reusing
an existing i18n key rather than adding one), and leaving it labeled "Quit" once
the `q` *key* genuinely meant something different would have been its own new
inconsistency.

The identical pattern (no `escape`, `q` = close screen, a "Quit" button that's
really Cancel) turned out to exist in two more places — `credentials_screen.py` and
`club_picker.py`'s `ClubSearchScreen` — fixed the same way, even though neither is
currently reachable from the running main `tui.py` app (so neither had actually
produced a live user complaint yet, just the same latent inconsistency waiting to
resurface whenever either gets reintegrated or run standalone).

A real regression caught by the existing suite, not a new test: two already-passing
`test_tui.py` scenarios (editing settings via `e`, saving, then closing) had been
pressing `"q"` to close `SettingsScreen` and continue — exactly the real flow the
user reported. Once `q` started meaning "quit," those tests would have tried to
exit the real app mid-scenario instead of returning to the overview; fixed to press
`escape` instead, which is now also the *correct*, consistent key to actually use.

15 new/changed tests across `test_settings_screen.py`, `test_credentials_screen.py`,
and `test_club_picker.py`, three confirmed to genuinely fail when the fix was
temporarily reverted (a plain `NoMatches` on the renamed button id, not a
behavioral assertion, since the old id no longer exists at all once fixed).

**Weather split into Temperature/Precipitation/Wind, Events added to the day-detail
table, and a per-slot daylight marker, same day**: "can you please split weather
into Temperature, Precipitation, and wind columns (both in the overview and
detailed view)? Also I would prefer if detailed view had a separate events column.
Basically detailed view should mirror overview with the difference, that you have
the detailed timeslotes" — followed immediately by "could you implement an
indicator of sunrise and sunset in the detailed view directly into the timeslots?
It would also be great if you could immediately see in the detailed view, which of
the timeslots are already too late until sunset."

Both screens' single combined weather cell (`_weather_cell()`/`_slot_weather_cell()`)
split into three: `_temperature_cell()`/`_precipitation_cell()`/`_wind_cell()` for
the day-level overview (peak/average across the daytime window), and
`_slot_temperature_cell()`/`_slot_precipitation_cell()`/`_slot_wind_cell()` for the
per-slot day-detail table (that exact hour's reading). A real behavior change, not
just a layout one: the old combined cells only ever showed the actual rain%/mm or
wind speed once a threshold fired, staying a bare icon otherwise — now that each has
its own dedicated column, the real number always shows; the same threshold
(`_SLOT_RAIN_ICON_THRESHOLD_PERCENT`/`_SLOT_WIND_ICON_THRESHOLD_KPH`) still decides
whether the 🌧/💨 icon itself appears, layered on top of the number rather than
gating it.

`DayDetailScreen` gained its own Events column, mirroring the overview's (the
"detailed view should mirror overview" ask) — but at the per-slot level it's
`slot.block_reason` for that specific row, not the day-level `schedule.events` the
overview shows, since "why can't I book this specific time" is exactly the question
a per-slot column should answer. This meant restructuring the blocked-row case:
the reason text used to be jammed into the Occupancy column (`f"[dim]{reason_text}
[/]"` in place of "X/Y"); now Occupancy shows a plain dash for a blocked row (same
"nothing here, see elsewhere" convention as the overview's own placeholders) and the
real reason moves to Events.

Sunrise/sunset itself was already shown above the table (`#daylight`, since
2026-09-08); the new ask was a per-slot indicator, not just the day-level summary.
New `_too_late_for_daylight(slot_time, schedule, config)` reuses
`recommend._round_duration_minutes()`/`playability.is_playable()` directly — the
exact same computation `exclude_unplayable()` already uses for the ★ recommendation
— so a 🌙 marker in the Time column can never disagree with what actually drives
that system. Deliberately independent of whether `availability` is configured at
all (unlike ★): it's a plain physics fact about the slot, not a preference
judgment, so it has to work on a club with no saved rules too. Mutually exclusive
with ★ by construction, since a daylight-failing candidate is never ★-recommended
in the first place.

24 new/changed tests across `test_tui.py` (the six split cell functions' own cases,
the new per-slot Events column, `_too_late_for_daylight()`'s own cases including the
configured-buffer boundary, a real day-detail table integration test confirming ★
and 🌙 never coexist on the same row), several existing column-index/header
assertions updated for both screens' wider tables. Verified live in an isolated
sandbox, headless tmux, against a fabricated schedule with open/occupied/blocked
slots and mixed weather: Temperature/Niederschlag/Wind/Termine all rendered with
real numbers in the correct columns, the sunrise/sunset line showed above the
table, and 🌙 correctly marked every slot too late to finish before the configured
sunset — confirmed through the real `parse_schedule_html()` → `save_schedule()` →
`load_latest_schedule()` pipeline, not a hand-built `Schedule`.

**An icon legend, and a real icon collision found while designing it, same
session**: "Would it make sense to implement a legend, since we already have so
many icons?" Checking the actual icon inventory before answering surfaced a real
problem, not just an opportunity: 📌 was already doing double duty — a confirmed
booking in the overview's Pick column (`_day_pick_text()`) *and* a day's event/
closure note in the Events column (`_event_cell()`). The two sat in different,
labeled columns, so it was never actively confusing in context, but a standalone
legend would have had to list the same icon twice with two different meanings,
which defeats the point of having one. Fixed at the source rather than working
around it: `_event_cell()`/`_slot_event_cell()` changed from 📌 to 📋, leaving 📌
uniquely meaning "confirmed booking" everywhere it appears.

New `_legend_line()` plus `OVERVIEW_LEGEND`/`DAY_DETAIL_LEGEND` — one (icon, i18n
key) list per screen rather than one shared list, since the two screens don't quite
use the same icons (only `DayDetailScreen` has 🌙; only `OverviewScreen`'s Pick
column has a standalone 📌). A dim `#legend` line renders at the bottom of both
screens, set once in `on_mount()` (both screens already rebuild wholesale on a
language switch, so no separate re-render path was needed).

5 new tests: `_legend_line()`'s own formatting, a direct assertion that no icon
repeats within either screen's own legend list (the regression test for the actual
bug found), that 🌙 only appears in `DayDetailScreen`'s list, and a real render
check on each screen. Verified live in an isolated sandbox: both legends render at
the bottom of their real screens with the correct icons and translated meanings,
in both English and German.

**Round duration moved from per-club YAML to the shared settings screen, same
session**: direct follow-up right after being asked (and answering) what the
existing 120/240-minute defaults actually were: "make pace speed adjustable in
settings ;)". Same correction `ai_assist` and `availability`/`preferences` already
went through — `round_duration_minutes` had been kept per-club on the theory that
pace genuinely varies by course, but the actual ask was for one adjustable pair of
settings, not a per-club dial. Two new `Select` dropdowns under "Timing &
scraping" (`ROUND_DURATION_NINE_CHOICES`: 60-180 min in 15-min steps;
`ROUND_DURATION_EIGHTEEN_CHOICES`: 150-330 min in 30-min steps — a wider range
would otherwise mean a much longer dropdown for the same "plausible values" spirit
every other preset list here already has). No changes needed in
`recommend._round_duration_minutes()` itself — it already just reads whatever
`config["round_duration_minutes"]` it's handed, and `_resolved_config()`'s existing
shallow merge means this file's value wins the same way every other global setting
already does; a club's own value (if any) still works as a fallback.

3 new tests across `test_settings_screen.py` (defaults, edited round-trip, a real
render-and-save scenario through the actual Select widgets), all confirmed
genuinely dependent on the change by reverting it and watching a plain `NoMatches`
(the fields not existing at all) rather than a wrong-value assertion. Verified live
in an isolated sandbox: the real settings screen shows both new dropdowns under
"Timing & scraping" with "120 min"/"240 min" preselected, alongside the existing
daylight buffer and scrape interval fields.

**Legend wrapping fixed for real, same session**: direct follow-up on the icon
legend above — "legend needs to wrap up, since some words might be cut off." The
first attempt joined each icon to its meaning with a non-breaking space (U+00A0),
expecting that to stop a line break from landing between them the way it would in a
browser. Checked live instead of assumed: it didn't help at all — Rich's own
word-wrapper (`rich._wrap.divide_line`) splits on Python's plain `\s` regex, which
treats U+00A0 as ordinary whitespace, not a browser's specially "unbreakable" one, so
a narrow terminal still split an icon from its own meaning exactly as before. Fixed
by not handing Rich one long string to wrap at all: new `_wrap_legend()` packs
`_legend_pairs()`'s icon+meaning units onto lines itself, greedily, using
`rich.cells.cell_len` (the same width measure Rich's own wrapper uses) so a line
break can only ever fall *between* whole pairs, never inside one — a pair wider than
the available width still gets its own line rather than being cropped. Both
`OverviewScreen` and `DayDetailScreen` now also implement `on_resize()` (mirroring
`SettingsScreen`'s own — `events.Resize` doesn't bubble) so the legend re-wraps live
as the terminal is resized, not just at mount time.

9 changed/new tests across `test_tui.py` (`_wrap_legend()`'s own cases including one
that reproduces the exact original bug against the real `OVERVIEW_LEGEND`, plus a
real screen-mounted integration test at a narrow width). Verified live in an
isolated sandbox, headless tmux: at 60 columns the wrap now falls cleanly between
"📋 Termin/Sperrung" and "📌 gebucht" rather than mid-pair, and re-resizing the same
pane down to 40 columns live re-wraps to three lines with no pair ever split.

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

**Implemented 2026-09-06** (12 tests, `tests/test_analytics.py`): `best_times_by_weekday()`,
`personal_stats()`, `crowd_heatmap()`, and `predict_crowding()` are all real, plain
aggregation over `storage.py`'s two new read helpers (`distinct_scraped_dates()`,
`load_all_confirmed_bookings()`, added alongside this). One thing revised during
implementation, not just assumed: `predict_crowding()`'s "hand confidence to
`ai_assist.summarize_history()`" plan (described above) doesn't actually fit —
`summarize_history()` returns prose commentary, not a number usable as a
machine-checkable confidence score. Replaced with a plain minimum-sample-size floor
(`MIN_SAMPLES_FOR_PREDICTION = 3`) instead: `crowd_heatmap()`'s returned shape now
carries a sample count alongside each average (`{"average": 0.9, "samples": 4}`, not a
bare float as the earlier sketch above showed), and `predict_crowding()` returns `None`
for a bucket with too few samples rather than a number that looks confident but isn't.
`ai_assist.summarize_history()` remains exactly right for the genuinely open-ended
half — personal-stats commentary — just not this specific numeric-confidence problem.

**`HeatmapScreen` implemented 2026-09-08, as a readiness view rather than the colored
grid described above** — direct request: "Can we still start building the UI for the
heat map? We need a menu to track how much data has been collected, and how much is
still needed to be functional." `analytics.crowd_heatmap()`/`predict_crowding()` had
been real and tested since the day above, but nothing in the running app had ever
called them, or `calendar_context.py` at all (that module has been fully implemented
and tested since Phase 2, but a club's own `calendar.country_code`/
`calendar.vacation_ranges` had never actually been read by anything before this
screen needed them — `tui._holidays_for_club()`/`_vacation_ranges_for_club()` are the
first real wiring). Building the colored grid first would have meant shipping a
screen that's almost entirely empty — every real club here is at most a couple of
days into accumulating history — so this leads with the actually useful question
right now instead: new `analytics.heatmap_readiness()` reports, per
`calendar_context.DAY_TYPES` bucket, how many hours have any data at all versus how
many have hit `MIN_SAMPLES_FOR_PREDICTION` ("ready" reuses that exact existing floor,
not a second invented threshold), plus a running sample count. `h` (from
`OverviewScreen`) opens the new screen: a table with one row per day type — always
five rows, even at zero samples, since a club with no `calendar.country_code`
configured correctly showing 0 forever for "public_holiday" is itself useful
information, not something to hide — and below it, a compact colored preview (reusing
the overview's own heat-strip green/yellow/bold-red thresholds) for any day type that
already has at least one ready hour. Real today, but empty for every real club here so
far, since none has hit the floor yet outside a synthetic test.

16 new tests across `test_analytics.py` (`heatmap_readiness()`'s own cases) and
`test_tui.py` (the two new calendar-wiring helpers, the status-text/cell-color/
preview-markup pure functions, and the screen itself mounted with real seeded
scrapes). Verified live in an isolated sandbox, headless tmux, with three synthetic
Mondays feeding one real "workday" hour past the readiness floor: the table showed
"Workday: 3 hours w/ data, 1 ready, 3 samples," and the preview line rendered a real
green block at 09:00 and a real bold-red block at a second, fully-booked hour —
confirmed via raw ANSI capture, not just the underlying markup string.

**Reworked 2026-09-09 to actually match the original signed-off mockup**: direct
feedback ("iirc the heatmap had to be on a daily basis, remember the mockup?"), and
checking the real mockup file instead of relying on memory confirmed it was right —
a genuine mismatch, not a false alarm. The mockup's grid was real days of the week
(Sun-Sat, each its own column, captioned "Actual days of the week, not a rough
workday/weekend split — Friday afternoon clearly isn't a Tuesday afternoon"), with
holiday/vacation/tournament shown in a separate "special days" panel underneath, each
compared only against *other* days of the same kind. What had actually been built
instead (the day above) grouped by `calendar_context.DAY_TYPES` on one single axis —
tournament/public_holiday/vacation/weekend/workday as five buckets — which collapses
every Monday through Friday into one "workday" bucket, exactly the loss of weekday
granularity the mockup's own caption called out.

`analytics.crowd_heatmap()` now returns `{"by_weekday": {"Monday": {...}, ...,
"Sunday": {...}}, "special_days": {"tournament": {...}, "public_holiday": {...},
"vacation": {...}}}` — an ordinary day (`calendar_context.classify_day()` returning
"weekend" or "workday") goes into `by_weekday` keyed by its actual weekday name, a
special day goes into `special_days` instead and is *not* also counted toward its
weekday, so neither group's average gets diluted by the other's days. New
`calendar_context.WEEKDAYS` (Sun-Sat, matching the mockup's own column order) and
`SPECIAL_DAY_TYPES` (the three DAY_TYPES that aren't "weekend"/"workday").
`predict_crowding()` now takes a weekday name or a special day type as its lookup
key rather than a plain day-type string, and checks whichever of the two groups
actually holds it. `heatmap_readiness()` and `HeatmapScreen` split the same way: two
tables now ("By weekday" — 7 rows, Sun-Sat — and "Special days" — 3 rows), rather
than one flat list of five day-type rows.

8 changed/new tests across `test_analytics.py` (crowd_heatmap()/predict_crowding()/
heatmap_readiness()'s new shape, including a case confirming a tournament day
contributes to `special_days` and *not* to its own weekday's average) and
`test_tui.py` (the preview-markup helper over both groups, the screen showing 7 + 3
rows). Verified live in an isolated sandbox, headless tmux, with three synthetic
Mondays and three synthetic public holidays each past the readiness floor: "By
weekday" showed Monday as "1/1 hours ready, 3 samples," "Special days" showed
Feiertag (public holiday) the same, and the preview rendered a real yellow block for
Monday and a real bold-red block for the fully-booked holiday hour — confirmed via
raw ANSI capture. Going forward: a new screen or data shape gets checked against its
own mockup (if one exists) before being called done, not just built to a written
spec and assumed to match it.

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

**Implemented 2026-09-06** (11 tests, `tests/test_ai_assist.py`, all against a mocked
`anthropic.Anthropic` client — these calls genuinely cost money and need a real API
key, neither of which a unit test should depend on): `classify_booking_label()` and
`rank_slots()` use `client.messages.parse()` with a Pydantic `output_format` exactly as
originally sketched; `summarize_history()` uses plain `client.messages.create()`
instead, since open-ended commentary has no fixed schema to hold it to.
`recommend.weekly_picks()` (Phase 3) now actually checks a club's `ai_assist.enabled`
flag before calling `rank_slots()` at all — previously nothing read that flag, since
there was no real call yet for it to gate. Any failure calling `rank_slots()` (no key
configured, a network hiccup, a rate limit) falls back to the plain filtered list
rather than raising, matching the "a short sane list beats no list at all" design
already documented for that function. `rank_slots()`'s prompt optionally includes each
candidate's weather (via `context["schedules"]`, keyed by `(date, course)`) — the
worst conditions across the round's duration, same as `exclude_unplayable()` already
computes, so Claude can weigh genuinely close trade-offs like "slightly more rain but
much emptier" instead of ranking blind.

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
- pc caddie's real login form and whether the tee sheet sits inside an iframe (see
  `docs/spec-v1.md` for detail) — the original v1 risks. Both resolved: the tee sheet
  is a separate, non-iframed page reachable directly and needs no login at all (found
  2026-09-05, see "Live site findings"); the login form itself turned out to be a
  plain HTML POST, no JS, no CSRF token, inspected live 2026-09-06 (see `scraper.py`'s
  `login()`) — Claude never entered or saw the actual password to confirm this; the
  user logged in themselves and Claude inspected the resulting form's HTML.
- ~~`scrape_my_reservations()`'s parsing only covers the confirmed empty state~~ —
  **resolved 2026-09-07**: a real demo booking was made and inspected live, confirming
  the populated-row markup (see `login()`'s note above). Still raises
  `NotImplementedError` for anything that doesn't match the now-confirmed shape,
  rather than guessing at further unseen variants.
- **AI calls cost money and send data to Anthropic's API, starting from Phase 1** —
  not deferred/opt-in the way an earlier draft of this roadmap had it. Tee-sheet
  contents (including other members' names, if visible), your availability/preference
  settings, and aggregated history all pass through `ai_assist.py` calls. Model choice
  per call is configurable specifically so cost is a dial you control, not a decision
  made for you.
- ~~History can't be backfilled.~~ **Mitigated 2026-09-07**: pc caddie still hides
  past tee sheets, so any day neither scraped nor confirmed is still a permanent
  gap — but `scrape_once.py` is no longer only ever run by hand or from an open TUI.
  A real `launchd` job (`~/Library/LaunchAgents/com.teetimemonitor.scrape.plist`,
  firing every 15 minutes, `_should_scrape()` still throttling what's actually
  fetched) now keeps it running unattended on this machine regardless of whether the
  TUI is ever opened that day — the standing installation step every earlier
  mention of this risk explicitly left for "the user's own call" has now actually
  been made.
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
- ~~The booking-date window (`overview_days`) is a fixed number in config.~~
  **Resolved 2026-09-07** by `scraper.fetch_available_dates()`, which reads the club's
  own "Date" `<select id="timetable_selection_date">` — the list of days it is actually
  taking bookings for. The cross-club sweep below measured this at **1 to 31 days**
  across 79 real clubs (8 the most common), against a configured default of 5: the
  fixed number was simultaneously asking some clubs for dates their site rejects
  outright ("Selection invalid.") and ignoring most of the window the rest offer.
  `scrape_once.scrape_due_for_club()` now uses the real window, capped by
  `MAX_OVERVIEW_DAYS` (one club advertises 366 days), with `overview_days` kept as the
  fallback for the 5-in-45 clubs whose page has no date selector at all.
- **Only a sample of clubs has been verified, not all of them.** The sweep below covered
  79 real clubs out of a directory of 1300+. It was also read-only and anonymous, so it
  says nothing about how an authenticated view differs. It covers the failure modes that
  actually showed up; it is not proof that none remain.

### Cross-club validation sweep (2026-09-07)

Everything in "Confirmed pc caddie markup reference" was written against one club, then
a second. Direct feedback — that the scraper has to work for clubs the user can't check
themselves — prompted checking it against a real spread instead: 79 clubs, sampled by
probing public tee-sheet URLs across German, Swiss, Luxembourgish and Italian-speaking
clubs (club ids turn out to be `0` + country calling code + a club number, so the space
is samplable). Each was then run end-to-end through the actual parser. What it found:

| Finding | Scale | Status |
| --- | --- | --- |
| No course selector at all (single-course clubs) | 18 of 39 with a tee sheet (46%) | Fixed — `SINGLE_COURSE_ALIASES` |
| Course notes read as players' names | 27 of 45 clubs | Fixed — the colspan rule |
| French/Italian anonymized-placeholder variants missing | 4 variants, every CH/LU club | Fixed — `KNOWN_ANONYMIZED_LABELS` |
| No tee sheet published at all | 7 of 79 | Fixed — `NoTeeSheetError` |
| Negative `data-seat_bookable` on over-full slots | 2 clubs | Fixed — clamped |
| Bookable-date window varies 1–31 days | all | Fixed — `fetch_available_dates()` |
| `data-status="past-time"`, a 5th undocumented value | 2950 of 3227 rows | Documented; already parsed correctly |
| Seats per slot | 4 on all 39 | Now read from the header anyway |

Held everywhere, no exceptions: `table.pcco-tt-timetable`, `tr.pcco-tt-time-person`, and
the `data-time` / `data-status` / `data-seat_bookable` attributes.

The most consequential of these is the first: a hard `NotImplementedError` for any club
without an "Area" selector meant the tool simply did not work for nearly half of pc
caddie's clubs, which no amount of testing against two clubs that both *have* one would
ever have surfaced. The second is the most insidious — it silently fabricated data
("Nur für Mitglieder", "Greenfee CHF 140.-" and similar becoming players' names), which
would have quietly poisoned the crowd heatmap and every recommendation built on it.

After the fixes, all 79 clubs either load correctly (72) or report cleanly that the club
publishes no tee sheet (7).

~~How the 27-hole rotation is actually presented on the site is unverified~~ — resolved
2026-09-05, see "Live site findings": a fixed 3-option course picker plus a separate
"Runde X+Y" banner, simpler than the rotating-dropdown risk this used to be. **Half-
corrected 2026-09-07**: "fixed" turned out to only mean *within* one club — a second
real club added the same day ("Golf Club Sonnenberg e.V.") has a completely different
5-option course lineup with its own alias codes, sharing no pattern with the first
club's. The hardcoded `COURSE_ALIASES` this assumption produced was silently sending
the wrong codes to every club but the one it was recorded from — "it doesn't pull any
data" for Sonnenberg was the direct, user-reported symptom. Fixed by
`scraper.fetch_course_aliases()`, which reads each club's own "Area" `<select>` live
instead of trusting a recorded constant; `tui.py` and `scrape_once.py` both now call
it per-club rather than importing `COURSE_ALIASES` directly. A related, independently-
broken assumption surfaced fixing this: `recommend.py`'s own hole-count regex
(`r"(\d+)\s*Loch"`) required "Loch" immediately after the number with no hyphen, so it
silently failed to match Sonnenberg's own naming ("18-Loch Schleife") and fell back to
a hardcoded 18 for every one of that club's courses, including its real 9-hole and
short-course options — fixed by reusing `scraper._holes_from_course_label()` instead,
which only ever matches a leading digit and so handles both naming styles.

## Out of scope (all phases)
Booking/auto-booking, notifications, packaging/distribution, mobile support (pc
caddie's own app already covers that). Multi-club support was on this list originally;
reversed 2026-09-05 — see Phase 0.
