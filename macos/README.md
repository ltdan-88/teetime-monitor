# teetime-monitor — macOS GUI

A native SwiftUI companion to the terminal app, reaching the same real backend —
same scrape history, same config, same console scripts — through a second,
graphical front end. `brew install`/`upgrade` on macOS builds it straight into
the Cellar alongside the TUI (see the root
[`README.md`](../README.md#a-macos-companion-app-macos-only)), and as of
v0.40.0 it has full feature parity with the terminal app: nothing left on
either side that the other can't do.

Not a rewrite, and moved out of `prototypes/` (2026-09-25) once it stopped
being one in every sense that mattered — see "Promoted out of `prototypes/`"
below for exactly what that did and didn't change. It started (below) as a
deliberately small sketch answering one question: **what would a native macOS
version feel like, and what would it cost?** That history stays in this file
because the answer it found — a thin native shell over Python's own state and
console scripts — is still the architecture today, not because the app itself
is still a sketch.

## What it does

Shows the multi-day overview — one card per bookable day, with the noon forecast, the
six-bucket occupancy heat strip, day events, and your confirmed booking. Click a day to
expand its tee times in place: seat pips, free count, per-slot weather, your own slot
flagged, and post-sunset slots dimmed.

## The shortcut that makes it cheap

**It does no scraping, ever.** It opens the SQLite database the Python scraper already
maintains, read-only for most of what it shows, and renders it. The launchd agent keeps
working exactly as it does today; this is a second reader (and, since Tier 1/2, a
second local writer and occasional invoker) of the same state.

That is why it's still a few thousand lines, not tens of thousands, despite having
grown well past the original overview-only sketch below into real login, search,
add-a-club, and a heatmap. Real backend logic — the scraper itself, pc caddie's login
form, `search()`/`ranked_matches()`'s filtering and AI ranking, the authenticated
directory fetch, geocoding — stays in Python, reached by shelling out to small,
well-scoped console scripts (see each dated section below for exactly which). What
*did* move into Swift, over the course of that same work, is a growing set of small,
stable, pure functions this prototype ports directly and verifies against Python's own
output rather than reimplementing from a guess: the day-card weather aggregation, the
v0.30.1 weather fallback (below), the platform-directory search/club-id matching, and
the crowd heatmap's own aggregation. Treat the split itself as the prototype's main
finding, not a detail: a hybrid like this is genuinely viable, and knowing which side
of that line a given piece of logic belongs on turned out to be a real, recurring
design decision, not a one-time architecture choice made at the start.

One piece of real logic was the first to be mirrored rather than skipped: the weather
fallback from v0.30.1 (when the newest scrape has no weather, fall back to the most
recent earlier scrape of the same course/date that does). Without it the prototype
would show the same blank column the Python app used to.

## Build and run

Needs **only the Command Line Tools** — no Xcode, no dependencies:

```bash
./build.sh
open TeetimeMonitor.app
```

It reads `~/.local/share/teetime-monitor/<club_id>.db` — the same fixed location the
Python side uses since v0.31.0 (`src/paths.py`), honouring `TEETIME_MONITOR_DATA_DIR`
the same way. That shared convention is what makes the GUI possible at all: an app
launched from Finder gets `cwd = "/"`, so nothing working-directory-relative could
ever be found.

Point it at a copy instead with `--db`:

```bash
./TeetimeMonitor.app/Contents/MacOS/TeetimeMonitor --db /path/to/0497758.db
```

## Tests (2026-09-19)

```bash
swift run TeetimeMonitorCoreTests
```

Still only the Command Line Tools — `Package.swift` exists for this one purpose,
not as a dependency manager for the app itself, which `build.sh` still builds
exactly as before, untouched by any of this.

Not `swift test`: SPM's own `.testTarget` needs either XCTest (its frameworks
aren't present under a bare CLT install — confirmed directly, not assumed:
`unable to resolve module dependency: 'XCTest'`) or swift-testing's `@Test`/
`#expect` macros (also confirmed directly: `plugin for module 'TestingMacros' not
found` — the exact "the macro plugin ships with Xcode, not the Command Line
Tools" gotcha this project already hit once for SwiftUI's own `@State`, see
`Box.swift`). `TeetimeMonitorCoreTests` is a plain executable with a hand-rolled
`Harness` instead — 173 assertions across 13 files (2026-09-19 on), exits 1 on
any failure, runs in CI on `macos-latest` (which does happen to ship full Xcode,
but the same executable shape works identically there and on a bare-CLT machine,
so it's what a contributor actually runs before opening a PR).

Covers the areas that carry real cross-language duplication risk — unit
conversion (including `precipitationAmountLabel`, added once precipitation
cells started showing the actual mm/in amount, not just the probability), the
heatmap aggregation (cross-checked cell-by-cell against a real club's data the
day it was ported; the specific cells that check produced are pinned as
fixture data here), day classification, YAML parsing (including the
`16:00`-looks-like-a-sexagesimal-number quoting rule, the omitted-vs-present
window semantics bug twice — once for `preferences.yaml`, once for ad hoc
search's own JSON payload — and, since 2026-09-19, decoding a double-quoted
scalar's own `\uXXXX`/`\n`/`\t`/`\\`/`\"` escapes, the exact shape of a real,
live "umlauts are broken" bug traced to this parser never having implemented
that at all), the scale reshuffle's own identity tier (`.small`, not
`.medium`, is the "1.0x, fresh install looks unchanged" factor now), the
config-file blank-line-growth bug, translation table parity (187 keys, both
languages, matching `{placeholders}`), and the platform-directory search/
club-id matching. Deliberately excluded SwiftUI view bodies (`App.swift`'s own
`@main` plus the sheets) as of this date — layout wasn't something an
assertion could check without snapshot-testing infrastructure this project
didn't have yet. It does now: see "Visual regression checks" below, added
2026-09-26 once three real layout bugs in a row made the gap in this
paragraph itself worth closing.

## Multi-provider AI credentials (2026-09-26)

Direct follow-up to turning AI ranking on for the first time and noticing the GUI
never asked for an Anthropic API key at all: `ai_assist.enabled`'s toggle in
Settings had no credentials UI anywhere, unlike pc caddie login, and silently
relied on `ANTHROPIC_API_KEY` already sitting in `.env` — if it were missing, the
toggle looked on but did nothing (`recommend.ranked_matches()`'s own best-effort
fallback swallows the failure). Widened while there: not everyone has an
Anthropic account, so this became a real choice of four providers (Anthropic,
OpenAI, Gemini, Grok), not just a key field for one vendor.

Settings now has an "AI provider" section, mirroring the existing Login
section's shape exactly: a `Picker` for the provider and a `SecureField` for its
key, one Save button. New `teetime-monitor-ai-login` console script
(`src/ai_login_cli.py`) wraps `ai_assist.py`'s own `verify_api_key()` — a
`models.list()` call per provider, not a generation call, so saving a key never
itself costs money — and `AICredentialsClient.swift` shells out to it the same
way `LoginClient.swift` already does for pc caddie, same stdin-JSON-in,
stdout-JSON-out contract, same reasoning (never argv, never an inherited
environment variable, so a key never shows up in `ps`). Saving a key for a
provider makes it the active one; a blank key when that provider already has one
saved just switches to it without retyping — same blank-means-keep convention
`LoginClient` already uses for `PCC_PASS`.

`ai_assist.py` itself gained a real per-provider dispatch, not just per-provider
key storage: OpenAI and Grok share one code path since xAI's API is
OpenAI-compatible (`openai.OpenAI(base_url="https://api.x.ai/v1")`, its own
`XAI_API_KEY` — no separate SDK needed), Gemini uses `google-genai`'s own
`response_schema` structured output. `openai`/`google-genai` joined `anthropic`
as core (not optional) dependencies, same placement reasoning: all three are
lazily imported on first actual use, so a default launch (AI off, or AI on with
Anthropic, still the common case) never pays for the other two.

Verified: `swift build`, the hand-rolled `TeetimeMonitorCoreTests` (196
assertions) and `VisualRegressionRunner` both still pass unchanged, and the real
built `.app` launches cleanly with the new section present. Full interactive
click-through of the new picker/field (as opposed to a build-and-launch check)
wasn't possible in this sandbox — the same Automation-permissions limitation
noted further down under "Grid alignment" (`Terminal.app`/System Events
automation blocked outright) — so this was verified via `swift build`
succeeding, the pure-logic test suites above, and a real launch, not a live
screenshot of the new controls themselves.

## Visual regression checks (2026-09-26)

Direct request, right after the third grid-alignment round below: every one
of those three bugs was only ever found from a real screenshot, because
nothing in `TeetimeMonitorCoreTests` renders a view at all -- column position
isn't something a value-equality assertion sees. New `VisualRegressionRunner`
target (`swift run VisualRegressionRunner`, or `--record` to write/update
references) renders the actual `DayCardHeader`/`SlotRow` views off-screen via
`ImageRenderer` -- confirmed directly that this works from a bare
command-line executable with no real window or `NSApplication` run loop, not
assumed -- and diffs the result against a reference PNG committed under
`Tests/VisualRegressionRunner/References/`. Both fixtures deliberately stack
several rows with genuinely different WMO weather codes (sun/cloud/rain/snow
-- different SF Symbol glyph widths, not just different colors), so a
regression that drops any of the `.frame()`s from the last two sections shows
up as those rows no longer lining up -- verified directly by re-introducing
the `SlotRow` condition-icon bug from below and confirming the runner both
catches it (1.4% of pixels differ, comfortably past the 0.5% tolerance) and
writes a diff image with the exact shifted region in red, before reverting it.

Needed one real restructuring to make possible: `App.swift`'s own `@main`
`WindowGroup`/menu-commands scene moved to a new `Main.swift`, the only file
`TeetimeMonitorCore` still excludes, so the rest of `App.swift` (and, it turned
out, all four sheets too -- `ContentView` references every one of them
directly, so partially including this module doesn't compile) could join the
library `VisualRegressionRunner` links against without a second `@main`
conflicting with the existing test executables.

**Tolerance, not exact-byte comparison** -- a pixel counts as different past a
per-channel delta of 30/255, and a case only fails once more than 0.5% of the
image differs that much, wide enough to absorb any font-hinting/anti-aliasing
noise between the macOS version a reference was recorded on and whatever
`swift-tests`' own `macos-latest` runner happens to be, narrow enough that a
whole column shifting by even a few points still fails.

**Scope, stated plainly rather than silently assumed**: only pure-SwiftUI
views (`Text`/`Image`/`Label`) are covered so far. The Club/Platz row's own
course `Picker` -- an `NSPopUpButton` under the hood -- is a real candidate
for the same bug class, but whether `NSViewRepresentable` content reliably
draws through `ImageRenderer` outside a real, on-screen window isn't
confirmed either way yet. Extending coverage there means checking that
first, not assuming `ImageRenderer` treats it the same as native SwiftUI
content just because the two cases here worked.

## Grid alignment: three rounds, one recurring bug shape (2026-09-26)

Direct feedback, in order: "make sure that the dropdowns and buttons are
better aligned (e.g. like on a grid)" → fixed, then "icons, temperatures,
wind, sunrise/sunset times etc. are not always aligned between the different
days" → fixed, then a direct request to audit every other menu and the TUI
for the same expectation. All three rounds turned out to be the same
underlying mistake in different places: a SwiftUI view sized to its own
content instead of a fixed column, so something *else* on the same row (a
wider weather icon that day, an extra digit, a differently-selected course
name) shifted everything after it sideways relative to the row above or
below. Fixed the same way everywhere it was found — a `Metrics` constant
sized for the widest plausible value, applied as a fixed-width `.frame()` —
matching the column discipline `SlotRow` already had for its own time/temp/
precip/wind cells before any of this started.

**The Club/Platz row** (v0.40.2). The course dropdown's own right edge used
to land well short of the action-button row's own right edge below it — the
whole row was narrower than the window, not just one field misaligned within
it. The real fix took three failed attempts to find: a plain trailing
`Spacer`, `.frame(maxWidth: .infinity)` on the row, `.overlay(alignment:
.trailing)`, and a `ZStack` with an explicitly `GeometryReader`-measured
width all *looked* like they should work and didn't, because giving the
course `Picker` any width constraint at all (`.frame(width:)`, even
`.frame(minWidth:)`) silently broke every one of them regardless of how the
surrounding layout was written. Removing that frame entirely -- the Picker
now sizes to its own selected course name, same as the Club picker beside it
already did -- is what actually fixed it. `Metrics.picker` is gone; nothing
else used it.

**The day-card header** (v0.40.3). `DayCardHeader`'s collapsed summary row --
condition icon, temp, rain, wind, sunrise/sunset -- had never had fixed
columns at all, each field sizing to its own content. New `Metrics.
dayWeekday`/`dayCondition`/`dayTemp`/`dayRain`/`dayWind`/`daySun`, one per
field, each wrapped in a `Group` even when its own value is `nil` so a day
with no wind/rain/sun data for some field reserves that column's width
instead of collapsing it and shifting everything after it -- the exact
"reserves its own fixed-width slot regardless of content" rule
`Metrics.bookingBadge` already established for the heat-strip/booking badge
slot, just not yet applied to this row when it was first written.

**The follow-up audit** (v0.40.4) went looking for the same shape elsewhere
rather than assuming these two were the only two. Found it once more:
`SlotRow`'s and `SearchResultRow`'s own per-slot condition icon (the same
`icon(for:)` call the day header uses) had no fixed width either, so the
temp/precip/wind cells after it -- despite each of *those* already being in
their own fixed column -- still drifted by however much that specific
weather glyph happened to render. New `Metrics.slotCondition` (16, smaller
than the day header's own 20 since both real call sites render it at
caption/caption2 size) closes it in both places. Checked and ruled out
elsewhere: `HeatmapSheet`'s grid, every `Form`-based sheet (Preferences,
Settings, Search's own criteria column, Add a Club's result list) --
`Form`/`.formStyle(.grouped)` and `List` both already give every row the
same real width to work with, which is exactly the ingredient a plain
`VStack` row was missing above, so the manual `HStack { Text; Spacer;
Control }` rows those forms use were never actually at risk the same way.

**The TUI, checked the same day, needed no changes.** Its own day-list/search
`DataTable`s compute each column's width as the max `_cell_visible_width()`
across every row *before* rendering any of them (`tui.py`'s own
`_render_table()`), and its Settings/Preferences screens set `.field-label`/
`.field-input`/`.field-time-group` widths once, in CSS, applied to every
field row by class rather than per instance -- both are structurally
incapable of the SwiftUI bug above, and the label/field alignment there was
already a direct fix from Phase 4 (2026-09-08). Confirmed by reading both
mechanisms rather than a live screenshot -- launching a second terminal for
one was blocked by this sandbox's own Automation permissions for
`Terminal.app`, not by anything in the TUI itself.

## Promoted out of `prototypes/` (2026-09-25)

Direct call, after closing the feature gaps below: "it isn't a prototype
anymore." Structural, not architectural — nothing about the hybrid split
(Swift for the view, Python for real logic) changes here, only the identity
this app presents as:

- **Moved** `prototypes/macos-swift/` → `macos/`, via `git mv` (history/blame
  intact). Every path reference that pointed at the old location — the
  Homebrew formula's own `install` step, `.github/workflows/tests.yml`'s
  `swift-tests` job, both root READMEs, `scripts/cross_language_reference.py`,
  `src/paths.py`/`src/login_cli.py`'s own doc comments, `.gitignore` — moved
  with it. `build.sh`'s two `../../` relative paths (to `pyproject.toml` and
  `src/club_directory_seed.json`) became `../` — one directory level shallower
  now, and easy to miss since nothing fails loudly until the very next build.
- **Renamed** the `@main` App struct from `TeetimeMonitorPrototype` to
  `TeetimeMonitorApp` — the one identifier in this codebase that actually
  named the old status, rather than just describing it in prose.
- **New bundle id**: `dev.ltdan88.teetimemonitor`, replacing the placeholder
  `dev.local.teetime.prototype` every build before this one shipped. A
  one-time identity change from macOS's own point of view — nothing this app
  stores keys itself on the bundle id (state lives in
  `~/.config/teetime-monitor`/`~/.local/share/teetime-monitor`, not
  `~/Library/Containers/<bundle-id>/...`), and it requests no permission that
  would need re-granting, so the only real effect is a fresh `TeetimeMonitor`
  entry in Launchpad/Spotlight rather than the app being recognized as an
  update to itself.
- **Left alone, deliberately**: the historical narrative throughout the rest
  of this file. A dated entry saying "this prototype ports directly" was true
  the day it was written, the same way a changelog entry or a commit message
  is — rewriting every one of those to match a label that only became
  accurate today would blur exactly the history this file exists to keep.

## Browse before saving, crowd_estimates in search, and block-style vacation ranges (2026-09-25)

Closed the last three known, flagged gaps this README carried against the TUI —
one real feature gap left open since the round below, plus two smaller "not
computed"/"not recognized" limitations flagged inline elsewhere in this file.

**Browse before saving** — the feature gap. `ClubBrowserScreen`'s own `enter`
takes any club id straight to a real, live-scraped overview with no
`clubs/*.yaml` ever written; picking a club there is a completed action with
something to look at, not a prerequisite gate behind favoriting first. Add a
Club's own rows now do the same: each has an **Open** button (ordered first,
same convention as that screen's own footer) alongside **Add**, either usable
without the other. New `teetime-monitor-preview-club` console script wraps
exactly two existing calls rather than reimplementing anything —
`tui._resolved_config(club_slug=None, club_id, club_name)` and
`scrape_once.scrape_due_for_club(slug=None, config, force=True)`, the same two
calls `TeetimeApp._open_club()`/`_periodic_scrape()` already make for an
unsaved club, `slug=None` already an ordinary, handled case throughout
(`_sync_my_reservations()`'s own first line is `if not slug: return`). Scrapes
straight into `<club_id>.db` — the same fixed-name database `Store.days()`/
`Store.courses()` already read for *any* club file that exists, favorited or
not — which is what makes the Swift side of this so thin: `OverviewModel.
startPreview()` just points `clubPath` at `Store.dbPath(clubID:)` and every
other view (day list, weather, Search, the heatmap, confirm/cancel) already
works unchanged, no new rendering path of its own. A persistent banner ("Previewing
— not saved yet") replaces the Club row's own favorites-only Picker while
active, with **Add to Favorites** and **Close** actions; **Refresh** shells out
to the same preview script instead of `teetime-monitor-scrape` while
previewing, since that script only ever iterates saved favorites and would
otherwise silently do nothing for an unsaved club.

**`crowd_estimates` in ad hoc search** — previously a flagged gap in
`search_cli.py`'s own docstring ("not computed here... `analytics.
crowd_heatmap()` needs a live public-holidays fetch this offline-by-design CLI
doesn't make"). That framing didn't actually hold up: nothing stops a script
from making a live fetch, it was really about not adding one to a call site
that runs on every table redraw (`OverviewScreen`'s own render path), which
this CLI isn't. `tui._crowd_estimates()` — the exact function `SearchScreen.
_run_search()` itself calls, gated the same way on `ai_assist.
avoid_predicted_crowd` — is now reused directly, so AI ranking run from the
Swift app's own Search sheet can no longer drift from what the TUI computes
for the same club. `_compute_crowd_estimates()`/`_crowd_estimates()` both
gained an optional `db_path` parameter for this (default `_db_path(club_id)`,
every existing caller unaffected) since `search_cli.py` resolves its own
`--db-path` directly rather than by club id.

**Block-style `vacation_ranges`** — `CalendarContext.vacationRanges()`
previously only recognized the one-line flow-style list item
(`- { start: ..., end: ..., label: ... }`) `clubs/club.example.yaml` itself
documents, explicitly flagging the block-style form (`- start: ...` with
`end:`/`label:` indented on the lines under it) as a real, smaller scope limit
`yaml.safe_load()` accepts but this scanner didn't. Closed by widening that
same narrow, purpose-built scanner (not `YAML.swift`'s shared parser — see its
own docstring for why that stays out of scope) to recognize both indentations
`yaml.safe_load()` itself accepts for a block-style item — the dash lined up
with `vacation_ranges:` itself, or indented under it — confirmed against real
`yaml.safe_load()` output for both before writing this, not assumed.

## A long live-feedback round (2026-09-19–20): feature parity, a real data bug, and repeated layout fixes

The single biggest round of direct feedback this prototype has had, working
from real screenshots of the running app rather than just descriptions. Three
kinds of outcome came out of it, worth separating:

**Closed real feature gaps against the TUI.** An audit at the start of this
round (comparing every TUI screen/setting against this app's own) found three
structural gaps; two are closed now:
- **Removing a saved club.** The TUI's own `f` toggles favorite/un-favorite;
  this app could only ever add one. A new "Clubs" section in Settings lists
  every saved club with a remove action, integrated there (not a second
  standalone toolbar entry) alongside "Add a Club…" — see "What's still Tier
  2" above for the implementation.
- **Scrape-interval and AI-ranking settings.** Both previously TUI/YAML-only,
  despite this app's own translation strings implying otherwise. New Settings
  sections mirror `settings_screen.py`'s own `FIELDS` exactly (the same
  `SCRAPE_INTERVAL_NORMAL/BOOKED_CHOICES` preset dropdowns, `ai_assist.enabled`/
  `avoid_predicted_crowd` toggles). `PreferencesStore.swift`'s own `ai_assist`
  map is *merged* into on save, not replaced wholesale, so a hand-set
  `ai_assist.model` (a real fallback `settings_screen.py` itself still honors,
  with no widget on either front end) can't be silently dropped.
- **Browsing a club's schedule before saving it**, the way `ClubBrowserScreen`
  can — closed 2026-09-25, see "Browse before saving" below. The third gap
  found in this round stayed open the longest of the three.

**A real, live data-correctness bug, not a UI one.** Reported as "umlauts seem
to be broken," traced to a real saved `clubs/*.yaml` on the reporting machine
whose `name:` field held a literal six-character backslash-`u`-plus-four-hex-digit
escape sequence as plain text instead of decoding into the character it names
-- the real club affected has "Domäne Niederreutin e.V." in its own name, and before this fix its saved YAML held that escape
sequence for the *decomposed* combining-diaeresis mark specifically (a base
letter plus a separate combining character), not even a single precomposed
codepoint. Two real causes stacked: `club_config.save_club_config()`/
`global_preferences.save_preferences()` called `yaml.safe_dump()` without
`allow_unicode=True`, so PyYAML backslash-escapes every non-ASCII character in
a double-quoted scalar; and `YAML.swift`, this prototype's own hand-rolled
parser, never implemented `\uXXXX` (or any) escape decoding for double-quoted
strings, since nothing this app itself had ever written needed it before.
Fixed on both ends — Python now writes raw UTF-8 (nothing needs escaping
going forward), and the Swift parser now decodes `\uXXXX`/`\n`/`\t`/`\\`/`\"`
so a file an older version already wrote reads correctly with no re-save
needed. Also closed the same round: new clubs now get `calendar.country_code`
geocoded automatically (`geocode.find_club_country_code()`, a second
Nominatim request alongside the existing location lookup, deliberately kept
separate from `find_club_location()` so that function's own tested contract
doesn't change) — the crowd heatmap's "no country set" message now explains
both that, and the remove-and-re-add path for a club saved before the fix.

**Layout iteration, including one bug the prototype's own environment
couldn't have caught.** Several real, specific reports across two rounds:
precipitation cells now show the actual mm/in amount alongside the
probability (`"70%/1.5mm"`, mirroring `tui._slot_precipitation_cell()`'s own
combined cell exactly) rather than just the percentage; `.help()` tooltips
were missing entirely from Search's own weather cells and from the seat
pips/open-spot count everywhere; the heatmap's two grids now sit side by side
with a shared hour-of-day row set (a real correctness fix the side-by-side
layout required — the by-weekday and special-days groups don't necessarily
cover the same hours on their own) and a legend fixed below the scrolling
content instead of scrolling away with it; both that sheet and Search's own
had their fixed heights trimmed once the new layouts left large blank gaps;
the day list's booking badge and heat strip swapped order, the club/course
picker labels now sit above their controls consistently, and the freshness/
version status line moved from beside the (now clickable, combined) club
title down to the bottom of the window, next to the legend it's now grouped
with. One fix took two attempts: `HeatStrip`'s own horizontal offset had
already been "fixed" twice (a fixed-width badge slot, then `maxWidth:
.infinity` on the header) before a fresh screenshot showed it still drifting
— the actual cause was a `Spacer` inside a *pinned* `LazyVStack` `Section`
header not reliably inheriting an expanded width from several layout levels
up. Replaced with `.overlay(alignment: .trailing)`, which positions the
trailing group against the leading content's own resolved frame directly,
with nothing left to propagate. Every one of these needed the same
disclosure repeated through the round: this environment has no Screen
Recording permission, so nothing here could be self-verified by rendering it
— each fix is grounded in reading the actual SwiftUI layout code and reported
symptoms, not a screenshot taken here.

## What building it actually taught us

- **`@State` needs Xcode.** It's a macro now, and `SwiftUIMacros` ships with Xcode, not
  the Command Line Tools. A static SwiftUI view compiles fine without it; the moment
  you add state, it doesn't. The workaround used here is the older, macro-free
  `ObservableObject` / `@Published` / `@StateObject` trio — identical behaviour, builds
  with plain `swiftc`. `@Observable` also works (its macro plugin *is* bundled).
- **A double-clickable `.app` needs no Xcode either** — a hand-written `Info.plist`, a
  directory layout, and ad-hoc `codesign` are enough. See `build.sh`.
- **SQLite needs no dependency** — `import SQLite3` is in the macOS SDK.
- **Distribution wouldn't need notarization**, because the Homebrew formula builds from
  source; a Swift version could do the same with `swift build`.

## Tier 1: made productive (2026-09-18)

Preferences, Settings (minus login), confirm/cancel a booking, and banner
notifications -- all without a single Python change, because none of them ever
needed pc caddie: they're local file/SQLite edits the Python side already owns the
shape of.

- **Preferences & Settings** read and write the real `preferences.yaml` and
  `~/.config/teetime-monitor/config` directly. `YAML.swift` is a small hand-written
  codec scoped to this file's exact shape (nested maps of scalars, no lists) --
  verified byte-for-byte round-trip against a real saved file, both directions
  (Swift reads what Python wrote; Python reads what Swift writes).
- **Confirm/cancel** writes a `confirmed_bookings` row exactly like
  `storage.save_confirmed_booking()` does -- append-only, `source: "manual"`,
  `holes` derived the same leading-digits way `scraper._holes_from_course_label()`
  does. A confirming dialog on tap, not a silent write, matching why
  `ConfirmBookingScreen`/`CancelBookingScreen` exist on the Python side: this marks
  a *local* record of what you already booked on pc caddie's own site, not a real
  booking action.
- **Banners** read `booking_changes.message` -- the plain-English fallback that
  table's own schema comment says exists "for any non-TUI consumer." Deliberately
  not `i18n.render_booking_change()`'s kind+params re-rendering, which is real
  per-language logic this prototype doesn't reimplement.

A real, live notification surfaced during this work: an actual "1 more player
joined your tee time" banner had been sitting unseen in this developer's own
database the whole time, with no way for any front end to show it until this.

**Two real bugs caught before shipping**, both from testing against copies of real
data rather than trusting the code:
- Writing an *empty* time window (`{}`) instead of omitting the key entirely would
  have silently turned "no weekend rules configured" into "any weekend time is
  fine" -- confirmed by reading `recommend.default_criteria_from_config()`'s own
  `_window()` closure, which treats an absent key and a present-but-empty one as
  genuinely different outcomes.
- The `KEY=value` writer grew one blank line on every single save (a `split` vs.
  Python's own `splitlines()` mismatch on a trailing newline) -- caught by writing
  the same key five times and diffing the byte count, not by inspection.

## German, for real (2026-09-18)

Follow-up to the third item below: the Language picker now translates **this app**,
not just the terminal one. `I18n.swift` holds 173 keys in English and German, with
the same lookup rule `i18n.py` uses (requested language, then English, then the key
itself, so a missing string degrades to readable English rather than a blank
control).

**Shared vocabulary, deliberately.** Where `src/i18n.py` already had a German term
for the same concept it was copied verbatim rather than re-invented -- "Zeit",
"Wetter", "Spieler", "gebucht", "Suchen", "Einstellungen", "Design", "Min. freie
Plätze (Gruppengröße)", "Abstand zur Gruppe davor", "Regen vermeiden", "Zeiten mit
Freunden bevorzugen", "Auslastungs-Heatmap", "Nach Wochentag", "Besondere Tage",
"pc caddie Anmeldung", "Passwort", "Speichern", "Abbrechen". Someone moving between
the two front ends should meet one set of words for one set of ideas.

Two things that would have quietly half-worked, caught before shipping:

- **Nothing observed the language.** Assigning to the singleton would have updated
  the file and re-rendered nothing -- the exact "setting appears to do nothing"
  shape this round started with. Every view root now observes `AppLanguage`,
  including the `App` scene itself, since the Actions menu's own titles go through
  `t()` and `.commands` is evaluated there.
- **`t` was shadowed.** `if let t = w.temperatureC` quietly hid the global `t()`
  function inside two views; the compiler caught it, and those locals were renamed.

Dates follow the language too (`Sa. 19 Sept.` rather than `Sat 19 Sep`) -- parsing
still pins `en_US_POSIX`, since that reads a fixed ISO shape and must not follow the
display locale.

The Language picker also moved from the "Terminal app" section to "Display": it now
changes this app immediately, and still writes `LANG=` for the TUI to pick up on its
next restart.

## Three bugs found by using it (2026-09-18)

Reported directly after the design pass below: "Scale changes don't seem to change
any font size. Also ... language settings or changing metric to imperial also
doesn't change anything." Three separate causes, only two of them bugs:

1. **Scale did nothing** -- a real bug, and an assumption worth recording: the first
   version set SwiftUI's `dynamicTypeSize` environment value and expected semantic
   fonts (`.caption2`, `.title2`...) to follow it. **That is iOS behaviour. macOS
   has no Dynamic Type**, so `.body` stayed 13pt no matter what that value said, and
   the feature was inert from the moment it shipped. Fixed by computing point sizes
   directly: `TextRole` names each style's real macOS size, `scaledFont()` multiplies
   it, and all 62 `.font()` call sites now go through it. The factor range widened to
   0.85/1.3 at the same time -- "no visible change" is exactly the failure mode not
   to repeat.
2. **Imperial did nothing** -- also a real bug, and a subtler one: the Units picker
   had been writing `units:` to `preferences.yaml` correctly since Tier 1, and the
   *TUI* honoured it the whole time. This app simply never read it back. Every
   temperature was a hardcoded `"%.0f°"`, every wind speed a bare km/h number. New
   `Units.swift` ports `src/units.py` exactly (verified against it: 20C -> 68.0000F,
   18kph -> 11.1847mph, 1.5mm -> 0.0591in, identical to four decimal places) and
   `AppUnits.shared` applies it live on Save, the same singleton shape `AppTheme`
   already uses. The >=30 wind flag deliberately still tests raw km/h, matching
   `tui._SLOT_WIND_ICON_THRESHOLD_KPH` and `units.py`'s own rule about not converting
   stored thresholds.
3. **Language does nothing here -- and genuinely isn't implemented.** Not a bug in
   the code: this app has no translations at all, every string in it is an English
   literal, and the picker only ever set `LANG=` for the TUI. That *was* stated in
   the section footer, but a control that appears to do nothing reads as broken
   regardless. Relabeled "Language (terminal app only)" as an honest interim state.
   Translating the GUI's own ~108 user-visible strings is real work and a separate
   decision -- and if it happens it should reuse `i18n.py`'s existing German
   vocabulary rather than inventing parallel wording for the same domain terms.

## Design pass and interface scale (2026-09-18)

Direct request after seeing the app with all of Tier 2 in it: "make the design more
consistent, user friendly, and maybe offer different scales." Three separate
problems, all of them symptoms of the same thing -- the interface had grown
feature-by-feature without anyone laying it out as a whole:

1. **The header was overloaded.** Club identity, six action buttons and two pickers
   all competed for one row, which is what squeezed the club name into wrapping one
   word per line (patched with `.lineLimit(1)`; this fixes the cause). Now two rows:
   identity and the two *labeled* pickers on top ("Club" / "Course" -- they were
   unlabeled dropdowns stacked in a corner), actions on their own row below.
2. **Six bare icons explained only by tooltip.** Now labeled buttons, grouped by
   what each is actually for -- act on this course's data (Refresh / Search /
   Heatmap), manage which clubs exist (Add Club), change how the app behaves
   (Preferences / Settings) -- with a divider and a spacer making those groups
   visible instead of six evenly-spaced icons implying six unrelated things.
3. **Five sheets at five different hand-picked sizes** (460x560, 440x500, 640x680,
   560x560, 700x620 -- no two alike, none chosen for a reason that outlived the
   sheet being written). Now three named sizes in `SheetSize` by what a sheet *is*:
   a settings form, a form-plus-results browser, or a wide data display.

**Scale** (Small / Medium / Large, in Settings → Display) is two halves, because
neither alone works: explicitly-sized fonts via `TextRole`/`scaledFont()` (see
"Three bugs found" below for why this isn't SwiftUI's own `dynamicTypeSize` --
macOS ignores that for semantic fonts entirely, which is exactly the bug that
section is about), and fixed pixel dimensions, all collected into one `Metrics`
enum and multiplied by the scale factor at each use site so text and the
indicators beside it stay in proportion.

Reshuffled 2026-09-19, direct request ("make old large scale new medium scale,
old medium is now small, large needs to be extra large"): what used to be
Medium (1.0, effectively no scaling) is now Small; what used to be Large (1.3)
is now Medium; the new Large is a genuinely bigger step (1.6), not a repeat of
the old ceiling under a new name. `AppScale`'s own default fallback moved from
`.medium` to `.small` along with it, since `.small` is now the "fresh install
looks unchanged" tier `.medium` used to be. The case names/raw values
(`small`/`medium`/`large`, what `GUI_SCALE=` actually persists) didn't change,
only what each one means.

Persisted as `GUI_SCALE=` in the same `~/.config/teetime-monitor/config` file
`THEME=`/`LANG=` already share. Verified in both directions rather than assumed:
Python reads the file correctly with the new GUI-only key present, and
`user_config.save_value()` preserves it when the TUI writes a theme (it rewrites
only the key it's given); the Swift writer still doesn't grow the file across
repeated writes (the blank-line bug from Tier 1, re-checked with three keys
present). Applies live on Save -- same `@Published` singleton shape as `AppTheme`,
no relaunch.

## What's still Tier 2

Nothing, as of the heatmap (below) -- every feature originally scoped for Tier 2
turned out to either need a real console-script action after all (login, search's
ranking, the directory fetch, add-a-club's geocoding) or, on closer reading,
qualify for Tier 1 once its actual dependencies were checked rather than assumed
(the heatmap's own aggregation, most of add-a-club). Two more additions since
confirm the same pattern rather than breaking it: removing a saved club
(`Store.removeClub(slug:)`, a direct unlink of `clubs/<slug>.yaml`, mirroring
`club_config.remove_favorite()` exactly -- scrape history is kept, keyed by
club id not slug) and the scrape-interval/AI-ranking settings (both just more
fields on the same `preferences.yaml` `PreferencesStore.swift` already reads
and writes) needed nothing from Python beyond the file format itself.

## The heatmap (2026-09-18, v0.35.0): scoped as Tier 2, shipped as Tier 1

Turned out not to need a new console script at all. `analytics.crowd_heatmap()` is
"plain SQL/code, no AI involved" by its own module docstring -- grouping
already-scraped occupancy by weekday/special-day-type and hour, then averaging --
and its one real dependency, public holidays, is a plain unauthenticated GET
against Nager.Date, not Python-specific logic. Both port directly
(`Analytics.swift`/`CalendarContext.swift`), the same call already made for the
day-card weather formulas, this time verified cell-by-cell: a real club's real
scrape history run through both Python's `crowd_heatmap()` and the Swift port
produced identical output for every one of 95 real (weekday, hour) and (special-day,
hour) cells, average and sample count both, including a same-date reclassification
from "Monday" to "public_holiday" moving a day's samples wholesale between buckets
in both implementations identically.

A new toolbar button (also in the Actions menu) opens `HeatmapSheet`: two grids
(by weekday, and special days compared only against others of their own kind),
hour-of-day as rows, a legend for the four cell states -- mirroring `HeatmapScreen`.

**One known, flagged gap, closed 2026-09-19**: a club's `calendar.vacation_ranges`
is a YAML *list* of `{start, end, label}` maps, and `YAML.swift`'s parser is
deliberately scoped to nested maps of scalars only (no lists -- see its own
docstring). Rather than widen that shared parser (real risk to `preferences.yaml`'s
own already-verified byte-for-byte round-trip, for a field neither of this
install's own saved clubs used yet), `CalendarContext.vacationRanges()` is now a
second, narrow, purpose-built scanner for exactly this field's own *documented*
shape -- the flow-style list `clubs/club.example.yaml` itself shows and comments as
the intended way to fill this in (`- { start: "2026-07-04", end: "2026-09-15",
label: "summer break" }`), confirmed against a real `yaml.safe_load()` of that
exact text before writing the Swift side. Still a real, smaller scope limit, stated
plainly: a block-style list item (`- start: ...` with `end:`/`label:` indented on
following lines) is valid YAML `yaml.safe_load()` also accepts, and this scanner
doesn't recognize it -- only the one-line `{ ... }` form.

**One thing this round couldn't fully verify**: the live holiday fetch itself.
Cross-checked that raw network egress works from this environment's own sandbox
(a synchronous fetch succeeded), and the running `.app` stayed fully responsive
after triggering a real fetch (against an isolated copy with `calendar.country_code`
set, since neither real saved club has one) -- but ad hoc `URLSession` completion-handler
probes compiled as bare command-line binaries repeatedly hung in this same sandbox
(a known class of gotcha: a single-shot `RunLoop.run(mode:before:.distantFuture)`
doesn't reliably pump a concurrent dispatch queue's callback the way a real AppKit
app's own run loop does), so the fetch's *content* landing correctly in the sheet
wasn't directly confirmed this round the way the aggregation logic was.

## Add a club (2026-09-18, v0.35.0): the third Tier 2 piece

A new toolbar button (also in the Actions menu) opens `AddClubSheet` -- search the
platform directory by name, or type/paste a club id or booking link, and add it as
a favorite. Turned out to split cleanly along this prototype's usual line:

- **Searching stays Tier 1.** `club_directory.py`'s own `search()` (case-insensitive
  substring match) and `looks_like_club_id()` (a couple of regexes) are simple and
  stable enough to port directly, the same call already made for the day-card
  weather aggregation formulas -- verified against Python output for every case
  (bare digits, a 7-digit id, a pasted `/clubs/<id>/` URL, non-matching text).
  `ClubDirectoryStore.swift` reads the same two files the TUI does: the live cache
  (`club-directory.json`) if one exists, falling back to the bundled
  `club_directory_seed.json` snapshot otherwise -- now copied into this app's own
  `Contents/Resources` by `build.sh`, so a fresh install can search ~1300 clubs by
  name with zero setup, the same first-run guarantee `load_seed_directory()` gives
  the TUI.
- **Two actions genuinely needed Python.** New `teetime-monitor-directory-refresh`
  (`src/directory_cli.py`) does the live, authenticated fetch `search()` has nothing
  to search until it's run at least once (`club_directory.refresh_directory()`,
  resolving credentials the same way `ClubBrowserScreen`'s own `r` does). New
  `teetime-monitor-add-club` (`src/add_club_cli.py`) saves a chosen result
  (`club_config.add_favorite()`), including its best-effort geocoding lookup, so a
  club added from the Swift app gets weather immediately, the same as one added
  through the TUI.

Verified end to end against the real installed binaries: `looksLikeClubID`/`search`
matched Python's own output for every case tried; a minimal real `.app` bundle (not
just a bare `swiftc` binary, which has no meaningful `Bundle.main`) confirmed the
bundled seed resource actually resolves at runtime, and that a real live cache
correctly wins over it; `teetime-monitor-directory-refresh` ran a real authenticated
fetch (1303 clubs) against an isolated copy of real credentials; `teetime-monitor-
add-club` saved a real club end-to-end, geocoding included. Real `.env`/cache/clubs
confirmed untouched throughout.

## Search (2026-09-18, v0.34.0): the second Tier 2 piece

A real ad hoc search now, not just the day list -- `⌘F` opens a sheet mirroring
`SearchScreen`: criteria pre-filled from your saved Preferences (min open spots,
weekday/weekend windows, buffers), edit for this one search, same "starts from your
defaults" UX that screen shares with the Preferences screen itself. New console
script `teetime-monitor-search` (`src/search_cli.py`) wraps the exact
`recommend.ranked_matches()` pipeline `SearchScreen._run_search()` uses, reusing
`tui._resolved_config()` directly for the config merge so it can't drift from what
the TUI itself would compute. Only the typed criteria cross over stdin as JSON;
schedules are loaded by the script itself straight from the club's own SQLite
database, not round-tripped through the pipe -- results (a JSON array) come back
with occupancy and any AI-ranking `reasons`, and `SearchSheet` cross-references each
match's date against `Store.days()` (already read directly elsewhere in this app)
to show weather per result without the CLI needing to serialize it. Tapping a
result opens the same confirm dialog `SlotRow` already uses.

Known, flagged gap carried over from the CLI itself: `crowd_estimates` isn't
computed (needs a live public-holidays fetch), so AI ranking runs when a club has
it enabled, just without that one bias signal.

Verified end to end against the real installed binary and a real club's data:
confirmed the same JSON criteria the CLI expects, confirmed a genuine zero-match
result was actually correct (a 240-minute round teeing off after 16:00 fails this
real club's own playability check against a ~19:25 sunset plus its 30-minute
daylight buffer -- not a bug), and confirmed a real positive match set parses
correctly, all against an isolated copy that left the real `.env`/preferences
untouched.

## Login (2026-09-18, v0.33.0): the first Tier 2 piece

`Settings` now has a real pc caddie login, no longer a placeholder. New console
script `teetime-monitor-login` (`src/login_cli.py`) wraps the exact same
save-then-optionally-verify flow `CredentialsScreen` already uses (blank password
keeps the existing one; a rejected or unreachable verification doesn't undo the
save) -- the Swift app shells out to it instead of reimplementing `scraper.login()`
or `.env` writing itself. Credentials cross the process boundary over the child's
stdin as one JSON object, never argv or an inherited environment variable (so they
never show up in `ps` for this process or its parent), and the result comes back as
one JSON object on stdout rather than translated text, so `LoginClient.swift`
doesn't need this project's own i18n strings to read the outcome. Verified end to
end against the real script and a real (rejected, on purpose) pc caddie login
attempt, against an isolated `.env` copy -- see `login_cli.py`'s own docstring for
the full JSON contract.

## Polish round (2026-09-18): live theming, sunrise/sunset, full weather

Four direct remarks after using Tier 1:

1. **"m" for minutes is ambiguous with meters.** Every Stepper label in Preferences
   now spells out "min" — matches Python's own `settings_screen.py` labels, which
   spell "(minutes)" out in full rather than abbreviating at all.
2. **"Do theme changes work, and can it not need a relaunch?"** They didn't apply to
   this app at all before this — Settings only ever wrote `THEME=` to the shared
   config file for the *TUI* to pick up next launch. New `Theme.swift` gives the
   Swift app its own live rendering of all 10 themes (`AppTheme`, a singleton
   `ObservableObject` every themed view observes) — picking a theme and hitting Save
   redraws the running window immediately, no relaunch. The three brew-launcher
   originals (green/amber/red-sands) use the *exact* hex values from `theme.py`'s
   own `CUSTOM_THEMES`; the seven Textual built-ins aren't defined in this repo at
   all (Textual's own registry owns them), so those use each palette's own
   well-known published colors instead — close to what the TUI renders, not a
   byte-for-byte extraction of it.
3. **Sunrise/sunset now show two ways**, both mirroring `tui.py` exactly: a compact
   "↑07:06 ↓19:29" on the collapsed day row, and — the specific slot row nearest
   each one — a labeled marker, using the identical `_closest_slot_time()` logic
   including its earlier-wins tie-break. Found and fixed while wiring this up: the
   expanded view's own 07:00–19:30 row clip would have silently hidden the sunrise
   marker on any day sunrise falls earlier than 07:00 (it was 06:51 as of
   2026-09-08) — the clip now always keeps whichever row carries a marker.
4. **Precipitation, wind and day-level condition were genuinely missing**, not just
   unstyled — the data was already parsed and sitting in `WeatherPoint`, never
   rendered. Every slot row now shows rain% (🌧 above 50%) and wind speed (💨 above
   30kph), the same thresholds `tui._slot_precipitation_cell()`/`_slot_wind_cell()`
   use. The collapsed day header now shows the actual day-level summary
   (`tui._condition_cell()`'s "worst icon across daytime", `_temperature_cell()`'s
   high/low, `_precipitation_cell()`'s average, `_wind_cell()`'s peak) instead of
   whatever the forecast happened to say at noon.

## Labels, and what actually needs a TUI restart (2026-09-18)

Two more direct remarks after the polish round above:

1. **Some columns/fields had no label at all** — the day header's temp/rain/wind
   figures were bare numbers with no unit or icon (unlike wind, which already had
   one), and the expanded slot row's rain%/wind cells were the same. Fixed by giving
   every one of those its own icon (`Label`, not bare text — temp gets
   `thermometer.medium`, rain gets `drop.fill`, matching the icon wind already had)
   plus a `.help()` tooltip for the exact figure on hover. Added a `LegendLine`
   below the day list, one line for the whole window rather than repeated per card —
   the same role and placement `tui.py`'s own `OVERVIEW_LEGEND` plays under the
   TUI's table, for the same reason: icons that "seemed obvious" while building them
   aren't obvious to someone opening the app cold.
2. **Which settings actually need a TUI restart, checked against the source rather
   than assumed:**
   - **Preferences (availability, weather thresholds, buffers, pace, priorities) and
     Settings' Units/AI/scrape-interval fields are already live in a running TUI —
     no restart, no need to even reopen its own Settings screen.** `tui.py`'s
     `_resolved_config()` calls `global_preferences.load_preferences()` fresh,
     uncached, on every single render — this was already true of the codebase
     before any of this work, not something added here. Both sheets now say so
     explicitly instead of leaving it to be assumed.
   - **Theme and language are the one place that's genuinely different**, and do
     need an actual restart — not just reopening Settings within the same running
     TUI session. `i18n.get_language()` resolves once per process and caches
     (`_current_language`), never re-reading the file after that; `club_config.py`
     calls `load_dotenv()` once at import time for `.env` credentials, same
     pattern. Confirmed this isn't fixed by simply reopening the TUI's own Settings
     screen either: its Theme field's `getter` *does* re-read disk, but the
     `setter` that actually repaints `app.theme` only fires when the picked value
     differs from what the getter returns — so an unchanged reselection (which is
     what reopening-without-touching-anything amounts to) applies nothing. Fixed
     `SettingsSheet`'s messaging to say "next restart" specifically rather than the
     vaguer, easy-to-misread "next time it opens."

## What it deliberately doesn't do

No scraping (beyond shelling out to the existing scraper binary; login, search, and
the two directory actions behind add-a-club are the same shelling-out shape), no
real booking on pc caddie itself.
