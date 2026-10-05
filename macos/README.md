# teetime-monitor — macOS GUI

A native SwiftUI companion to the terminal app, reaching the same real backend —
same scrape history, same config, same console scripts — through a second,
graphical front end. `brew install`/`upgrade` on macOS builds it straight into
the Cellar alongside the TUI (see the root
[`README.md`](../README.md#a-macos-companion-app-macos-only)), and since
v0.40.0 it covers what the terminal app does, with two known differences: the
heatmap's per-weekday readiness screen (`s` in the TUI heatmap) is TUI-only, and
a club's default course can only be set here (Settings → Clubs) — the TUI reads
`default_course:` from the club's YAML but has no field for it.

Not a rewrite, and moved out of `prototypes/` (2026-09-25) once it stopped
being one in every sense that mattered — see "Promoted out of `prototypes/`"
below for exactly what that did and didn't change. It started (below) as a
deliberately small sketch answering one question: **what would a native macOS
version feel like, and what would it cost?** That history stays in this file
because the answer it found — a thin native shell over Python's own state and
console scripts — is still the architecture today, not because the app itself
is still a sketch.

## What it does

Shows the multi-day overview — one card per bookable day, with the day's 08:00–20:00
weather summary (worst condition, high/low, average rain chance, peak wind), the
six-bucket occupancy heat strip, day events, and your confirmed booking. Click a day to
expand its tee times in place: seat pips, free count, per-slot weather, your own slot
flagged, post-sunset slots dimmed, and the TUI's per-slot markers: ★ on the recommended
times and a moon on those whose round would not finish before sunset.

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

To point it at a copy instead, put the copy in its own directory (keeping the
`<club_id>.db` name) and launch with `TEETIME_MONITOR_DATA_DIR` set — there is no
`--db` flag any more (dropped in the club-picker rework, f4ffb12):

```bash
mkdir -p /tmp/tm-copy && cp ~/.local/share/teetime-monitor/0497758.db /tmp/tm-copy/
TEETIME_MONITOR_DATA_DIR=/tmp/tm-copy ./TeetimeMonitor.app/Contents/MacOS/TeetimeMonitor
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

## ★ and moon markers on the slot rows, same as the TUI (2026-10-05)

The last visible gap in an expanded day: the TUI marks recommended slots with ★ and slots whose round would end after sunset with 🌙, and the GUI showed only one pick time per day. `picks_cli.py` now also returns per-date `"recommended"` and `"too_late"` lists of "HH:MM" (from `pipeline._recommended_times_for()`, off the same cached pipeline result as the pick, and `pipeline._too_late_for_daylight()`; absent when empty, ignored by older builds), so the two apps cannot disagree. `PicksClient` decodes them into `DayVerdict` (so they clear with the verdicts on a club/course change) and `SlotRow` draws a star or moon in a fixed `Metrics.slotMarker` column ahead of the time, so times stay aligned on rows with and without a marker; the star wins if a slot is in both lists, as in the TUI. The "?" legend lists both with the TUI's wording (`legend.recommended`, `legend.too_late`, compared text-for-text by the cross-check). A slot already past today carries neither, like the TUI. The two known differences at the top of this file are unchanged; there is no remaining gap in the overview's per-slot markers.

## Focused row is now highlighted; player filter picked through the directory (2026-09-29)

Two direct follow-ups to the previous entry. (1) Double-clicking a player scrolled to and expanded their tee time but selected nothing, so the row was still hard to spot: the GUI now tints that row (`OverviewModel.highlightedSlot`) for a couple of seconds. (2) The Search screen's Player dropdown listed every name ever seen and was too long to use. It is now a "Choose player…" button that opens the Player directory in pick mode (A–Z index and search included; picking a name closes it and sets the filter, with a × to clear) in both the TUI (`KnownPlayersScreen(pick=True)`) and the GUI (`PlayerDirectorySheet(onSelect:)`). Escape keeps the previous choice. Follow-up (2026-09-29): the highlight is now stronger (70% accent fill plus a solid 2pt accent outline, held ~4 seconds), and the Player directory/picker rows now show hover and click-selected states (accent tint plus outline); in picker mode the selection is visible for a moment (0.3s) before the sheet closes. Fix (2026-09-29): jumping to a tee time was unreliable when the player's day wasn't yet expanded, most visibly after choosing one of several hits: the scroll ran before the lazy day body existed, and the generic expand-scroll to the day's ★ pick raced it. The jump now suppresses that scroll for its own day and retries the scroll as layout settles. Second fix (2026-09-29, "expands day but no highlight"): the highlight's timer used to start at the jump, so a late or failed scroll spent it off-screen. It now starts only once the focused row has actually appeared on screen (`SlotRow.onAppear`), the scroll is retried until then, and the focused row is never dimmed by the outside-window/past-sunset fade. Third fix (2026-09-29): a jump now collapses every other expanded day first, so a target below earlier jumps' open days always fits on screen.

## Reset filters in Search; friends filter and star in the Player directory (2026-09-29)

Two direct requests. (1) Search now has a "Reset filters" button (TUI `#reset`, GUI next to Search) that puts every field back to the saved availability defaults, turns "Friends only" off and clears the Player filter. (2) The Player directory gained a "Friends only" switch/checkbox (TUI `#friends-only`, GUI toggle beside the sort picker). Sorting by Friend already ordered friends first in both front ends (new tests pin that down), but the GUI rows gave no visible friend marker, so the sort looked like a no-op; friends now show a gold star before their name.

## Player directory crash fix (2026-09-29)

A crash report (scrolling the Player directory: `ViewListTree.visitItem` assertion inside SwiftUI's `List`/`NSOutlineView`) traced to the directory's conditional `Section`/`ForEach` structure (with an `.id` on the `Section`). The directory now uses a `ScrollView` + `LazyVStack` with pinned A–Z section headers (the same shape the Overview uses) instead of a `List`; behaviour, the A–Z index strip and row states are unchanged.

## Double-click a player to jump to their tee time; wording aligned with the TUI; friends/players into search (2026-09-28)

Three more direct follow-ups on the work right above, same session:

**Double-click a player in the directory, jump to their tee time** -- scoped
live, before building: only the currently-loaded window (not full scrape
history -- that's what you'd actually act on), multiple hits get a small
picker (`.confirmationDialog`), one hit jumps straight there. The real design
problem wasn't the lookup (`playerSlotHits(for:in:)`, a pure function over
`model.visibleDays` -- 4 new tests) but the *jump*: `ContentView`'s existing
scroll-on-expand (`.onChange(of: model.expanded)`) only fires when `expanded`
itself changes, which is a no-op (and triggers nothing) when the target day
is *already* open -- exactly the case double-clicking a friend playing later
today would hit. Added a second, independent `OverviewModel.scrollRequest`
(a `ScrollTarget?` the sheet sets and `ContentView` clears once handled) so a
focus request always scrolls, expanded or not. `PlayerDirectorySheet.model`
is optional -- this sheet is reachable both from Overview directly (which
hands over a live model) and from Preferences' own "Priorities" section
(which has never carried one); double-click quietly does nothing from the
second path rather than plumbing a model through a sheet that has nowhere to
scroll to anyway.

One real compiler surprise along the way: `.onChange(of: model.scrollRequest) { _, new in ... }`
failed with "the compiler is unable to type-check this expression in
reasonable time" until the closure's parameter types were spelled out
explicitly (`(_: OverviewModel.ScrollTarget?, new: OverviewModel.ScrollTarget?) in`)
-- a nested `Equatable` struct type seemingly pushed this specific
`onChange` overload's inference past what `-Onone` will resolve quickly.
Also hit: `@ObservedObject var model: OverviewModel?` doesn't compile at all
("generic struct 'ObservedObject' requires that 'OverviewModel?' conform to
'ObservableObject'" -- an `Optional` never satisfies that regardless of what
it wraps), so `model` is a plain, unwrapped stored property instead; nothing
inside this sheet's own body needs to re-render off it living, only read
once per double-click and written once per jump.

**Wording audit, done thoroughly rather than just fixing the one reported
pair** -- see `ROADMAP.md`'s own dated entry for the full list (settings
section headers, the "Ihr"/"dein" formality slip in both apps' own handicap
label, the heatmap toolbar button). The one worth detailing here since it's
GUI-only: `heatmap.legend.open/mid/full` used to be shared, verbatim,
between `HeatmapSheet`'s own predictive grid cells and the Overview's own
real-time per-day heat strip (`App.swift`'s `heatSwatches`, whose own comment
used to say "reuses HeatmapSheet's own legend wording verbatim ... rather
than inventing separate copy for the same three states"). That reasoning
was itself the bug: `Analytics.HeatmapBucket.average` (the predictive grid's
own number) is a multi-week average, while the Overview strip's own ratio is
one real day's live booked/capacity fraction -- not "the same three states"
at all, just the same three-color *threshold* (`fillColor()`) applied to two
different facts. Wording that's accurate for a live count ("under half
booked") reads as a live status update, not a historical pattern, which is
actively misleading on a cell that's actually an average. Split into
`heatmap.legend.*` (now "usually quiet"/"fills up"/"usually full", matching
`tui.py` exactly) for the predictive grid, and a new `overview.crowd_legend.*`
(kept the original live-count wording) for the real-time strip, each now
used by exactly one of the two views.

**"implement players or friends into the search"** -- `SearchSheet` gains a
"Friends only" `Toggle` and a "Player" `Picker` (built from
`Store.knownPlayers(dbPath:)`, loaded once at `init` the same way
`PlayerDirectorySheet.reload()` already does a plain synchronous read;
friends shown starred), both threaded through `SearchCriteriaPayload`'s own
JSON (`friends_only`, `player` -- omitted entirely when nothing's picked,
matching the window fields' own present-vs-absent convention) to
`search_cli.py`'s new post-filter. Mirrors `SearchScreen`'s own two new
fields exactly, same wording, same "friends-only is a hard exclude, not just
a reorder" distinction from the existing `prioritize_friends` preference.

## Stale window hint after a course switch, and a Contacts-style player directory (2026-09-28)

Two direct reports in one message, both fixed:

**"the notification only applies for 18 hole match"** -- the "your window
opens too late" hint (`window_too_late_hint()`, ported straight through via
`picks_cli.py`'s own JSON) was itself always course-aware (`_round_duration_
minutes()` already picks "nine" vs. "eighteen" off the course label), so the
Python side was never the bug. `OverviewModel.reload()` was: switching course
only ever *overwrote* `picks`/`verdicts`/`windowHint` once the new course's
own `teetime-monitor-picks` subprocess call actually returned -- there was no
synchronous clear on the switch itself, so the *previous* course's hint (a
real 18-hole, ~4h-round number) stayed on screen, now attached to whatever
9-hole course you'd just switched to, for as long as that fetch took. Fixed
with a new `picksRequestKey` (the (path, course) the on-screen state was
actually fetched for): `reload()` now blanks those three the instant it sees
a request for a *different* key, but leaves them alone for a same-key
reload -- the 2-second DB-mtime watcher and a confirm/cancel both call
`reload()` too, for the *same* course, and clearing on those as well would
have flashed the pick badges/hint to empty and back on every routine
background refresh.

The clearing decision itself (`OverviewModel.picksRequestChanged(from:to:)`)
is a pure static function, not inline in `reload()` -- not by design up
front, but by a real CI failure: a first version of this fix's own test drove
a real `reload()` + `PicksClient.run()` subprocess call, asserting a same-
course reload leaves `windowHint` alone. Passed locally (this dev machine has
`teetime-monitor-picks` installed, so that call is genuinely async and
`reload()` returns before it completes) and failed in CI (a clean runner with
no such binary, where `PicksClient.executable()` finds nothing and its
completion fires *synchronously*, inside `reload()`, with an empty result --
clearing the very state the test asserted would survive). The test was
timing-dependent on an environment detail that had nothing to do with the
actual fix. Pulling the decision out into its own pure function let the two
regression tests (`testSwitchingCourseCountsAsChanged`/
`testReloadingSameCourseDoesNotCountAsChanged`) target it directly, with no
subprocess, no RunLoop spin, and no environment dependence left at all.

**"make the player directory a feature[sic] similar features like in common
contact directories (e.g. alphabet letters as separators)"** -- `PlayerDirectorySheet`
now groups by the first letter of family name into real `Section`s, plus a
tappable A-Z jump strip down the trailing edge (`ScrollViewReader.scrollTo`),
the same shape Contacts.app's own list uses. Only shown sorted by name --
grouping a handicap- or gender-sorted list by family-name letter would
scatter one person's own initial across the whole list instead of collecting
it, so the header/strip both gate on `sectionsShown` (`sortField == .name`).
The grouping itself is a free function (`groupPlayersByFamilyNameLetter`),
not sheet-private state, specifically so `TeetimeMonitorCoreTests` can
exercise it directly -- 4 new tests, adjacent-run grouping, case-insensitivity,
the family-name (not full-name) rule, and the "#" fallback for a name with no
leading letter.

Neither change has a screenshot to verify against: this machine's screen is
locked for this whole session (see the entry below), and `List`/`Section`
render as an empty box through `ImageRenderer` the same way `Form` already
does (no real window for native chrome to draw into) -- confirmed once
already, not re-litigated here. Verified instead by the two new automated
suites (222 Swift tests passing) and by reading the actual code path
end to end.

## README screenshots, finally (2026-09-28)

Direct question: "why don't we have screenshots for the companion app?" --
the TUI's own six had just been refreshed (see root README.md's own history);
this app had never had any, prose-only since it existed. Two, not six:
`DayCardHeader`/`DayCardBody` (collapsed day list, one day expanded) render
correctly off-screen via `ImageRenderer` -- the same mechanism
`VisualRegressionRunner` already trusts for exactly those two views -- but the
full `ContentView` and any `Form`-based sheet (Preferences, Search, Heatmap)
do not: `Picker`s render as a broken "missing resource" glyph with no real
window to draw native chrome into, and `Form`/`List` render as an empty box
outright. Confirmed directly rather than assumed, matching
`VisualRegressionRunner`'s own already-documented "native-control-bearing
views ... not confirmed" caveat -- this just cashed that caveat in for real.

A real on-screen window (`screencapture`) was the other option, and was
tried first, since the user had explicitly OK'd it (quit the real app,
relaunch pointed at fixture data, screenshot, restore the real app after).
Ruled out for a real, checked reason, not assumed: this machine's screen is
locked (`CGSSessionScreenIsLocked` via `CGSessionCopyCurrentDictionary` ==
`1`) -- `screencapture` returns the lock screen's own static frame regardless
of which window or region is asked for, byte-identical across repeated
attempts. Correctly out of reach, not a bug to route around.

Screenshots render against the exact same fake "Golfclub Musterhausen e.V."
demo data (`build_fixture.py`, see the root README's own screenshot-refresh
history) the TUI's own six were regenerated from -- same club, same
anonymized "X Mustermann"/"X Musterfrau" player names, reached the normal
way via `TEETIME_MONITOR_CONFIG_DIR`/`_DATA_DIR`. Rendered by a temporary
`ReadmeScreenshotRunner` executable target (own `main.swift`, added to
`Package.swift`, both deleted once the two PNGs were copied into
`assets/en/`/`assets/de/` as `gui-overview.png`/`gui-expanded.png`) rather
than left as permanent infrastructure -- matches the TUI's own screenshot
script, which lives in a scratchpad, never the repo.

## Handicap preference: play with similar or better HCP (2026-09-27)

Direct follow-up to the player directory work above: "would it make sense to
have the option to choose to play with similar HCP or with better HCP for
better pace?" Real per-slot data, not an inferred pattern -- the same
distinction that ruled out a friends-presence heatmap and a field-composition-
by-time-of-day idea earlier the same day (both would have relied on a
statistical pattern across a still-short scrape history; this reads a
specific slot's already-known, already-booked players' real handicaps right
now). Validated against the real database first (98% HCP coverage among
currently-booked players in upcoming slots) before building.

New `hcpPreference` on `Preferences` ("off"/"similar"/"better", same
opt-in-off default as `prioritizeFriends`), a `Picker` in `PreferencesSheet`'s
Priorities section, and `Store.myHandicap(dbPath:)` reading the same
`club_meta` table `storage.load_my_handicap()` writes on the Python side.
Your own handicap is auto-scraped, never entered here (confirmed with the
user: "auto scrape is very accurate since it is entered by my club") -- read
for free off the same "My Reservations" page already fetched every sync pass
(`Mein Handicap Index: 43,8` in its account-menu markup), so a read-only
"Your handicap" row is the only place this app ever shows it. Field-average
HCP is fed into the AI prompt when ranking is on, same "aggregate number,
never a name" treatment `friend_count` already gets.

## Why no pick, your window, and jumping to it -- same as the TUI (2026-09-27)

Bundle C of a TUI/GUI consistency audit (see ROADMAP.md). `picks_cli.py` now
returns each day's own window and, with no pick, why; `PicksClient.parse()`
turns that into `DayVerdict`s plus an optional `WindowHint`. A no-pick day
shows a 🌙/🌧 capsule in the badge's fixed column (sentence on hover),
out-of-window slots dim, an expanded day scrolls to its ★ pick or where your
window opens (`OverviewModel.focusTime`, `ScrollViewReader`), and a hint row
explains -- with a Preferences button -- when your window opens too late to
finish before dark. `Day.visibleSlots` (sunrise row through sunset row) replaces
this app's own old 07:00-19:30 clip, matching the TUI. All decided in Python,
none of it re-derived here.

## Numbers now match the TUI exactly; occupancy counts free seats in both (2026-09-27)

Found comparing real renders of both apps from the same database (bundle A of
a TUI/GUI consistency audit -- see ROADMAP.md): the day header showed a low of
11° where the TUI showed 12°, wind 10 vs. 11. Same data, same aggregation --
this app truncated with `Int(x)`, the TUI rounds. New `wholeNumber()`
(Formatting.swift) replaces every truncating display site, and
`CrossCheckRunner`'s `whole_number` group pins it to Python's own `f"{x:.0f}"`
(halves and negatives included). The TUI also switched its slot occupancy
from "2/4" (booked) to "2 frei" -- the same free-seat count this app has
always shown, so one number no longer means opposite things across the two.

## Player directory: sortable/searchable, wider sheet, gender/HCP/status columns (2026-09-27)

Direct follow-up on the entry below: the sheet needed to fit its own content
at a glance rather than truncating a long name, and the directory needed to
be sorted alphabetically by family name and -- "better" -- sortable and
searchable outright. Also answered a genuine open question in the same
message ("further scrapable information... worth to display?") by checking
the real authenticated tee sheet HTML directly: each player cell also
carries a gender marker, membership status ("Mitglied"/"Gast"), and a live
handicap -- confirmed with the user (wanted all three) before building it.

`PlayerDirectorySheet` gained a search `TextField`, a sort `Picker` plus an
ascending/descending toggle (`PlayerSortField`, mirroring
`known_players_screen.py`'s own `_SORT_KEYS` field-for-field), and three new
fixed-width columns (`Metrics.playerGender`/`.playerMemberStatus`/
`.playerHandicap`, sized for the longer of the two languages this app ships
-- same convention every other fixed-column row already follows). New
`SheetSize.directory` (700×640) replaces `.browser` for this one sheet,
sized as the actual sum of its own columns' widths so the widest real name
("Bettina Brauch-Hasenmaier") never needs truncating. `KnownPlayer` gained a
`familyName` sort key (last whitespace token -- same heuristic as
`models.family_name()`, checked directly against this club's own 373 real
names, including a hyphenated surname, a middle initial, and a leading
title) -- now the directory's own default order in both front ends, and now
cross-checked against Python (`CrossCheckRunner`'s new `family_name` group).

A new `player-row-multi` `VisualRegressionRunner` fixture (four players
spanning long/short names and present/missing gender/status/handicap) locks
the new columns' alignment going forward -- deliberately rendering
`PlayerRowColumns` alone rather than the full row, since a native `Button`'s
own off-screen rendering falls outside that harness's documented scope (see
its own "Scope, stated plainly" section) -- an early attempt that included
the trailing friend button rendered it as an unrelated placeholder glyph,
confirming that exclusion is real, not just theoretical.

Verified via `swift build`, `TeetimeMonitorCoreTests` (196 assertions),
`VisualRegressionRunner` (3 fixtures) and `CrossCheckRunner` (66 cases) --
all pass. Live against the user's real database: a real scrape recorded
gender/status/handicap for 111 of 374 known players, sorted correctly by
family name.

## Search reflowed top/bottom; player directory reachable from Overview (2026-09-27)

Direct follow-up feedback on the two entries below. Real names run longer than
the placeholders `SearchSheet` was originally sized for, so its side-by-side
`HStack` (criteria left, results right, `SheetSize.split` at 760×540)
truncated names with no way to see the rest. Reflowed to a top/bottom
`VStack` -- criteria in a `Form` on top, then a full-width results `List`
below -- reusing `SheetSize.browser`; `SheetSize.split` is now unused and
deleted.

The player directory itself (previous entry) was only reachable via
Preferences → Priorities, several menus away from the Overview it's actually
useful from mid-session. Added a toolbar button and `⌘`-menu item next to
Search and Heatmap (`AppCommands.onPlayerDirectory`, wired in `App.swift` and
`Main.swift`) opening the same `PlayerDirectorySheet` directly.

Verified via `swift build`, `TeetimeMonitorCoreTests` (196 assertions) and
`VisualRegressionRunner` (both fixtures) -- all pass unchanged.

## Player directory + real "prioritize friends" (2026-09-27)

Real names from authenticated scraping were only ever visible per-slot --
this is a browsable directory over that same data (a new `known_players`
table, populated incrementally on every scrape), with the ability to mark
some as friends. That finally gives `prioritize_friends` (a no-op preference
until now) two real effects, confirmed with the user before building either:
a deterministic sort in `recommend.ranked_matches()` that works even with AI
off, and a friend *count* (never a name) fed into the AI prompt when ranking
is on.

New `PlayerDirectorySheet` needed no CLI script -- `Store.swift` already
writes directly to SQLite for simple reads/writes, so
`knownPlayers()`/`setPlayerFriend()` just follow that same shape. Opened from
a new button in `PreferencesSheet`'s "Priorities" section, right next to the
toggle it gives effect to. Verified live against the real database: a real
scrape captured 373 real names, marking one a friend sorted their real slot
first, and the AI prompt was confirmed to contain only a count, never the
name.

## Authenticated scraping: real player names (2026-09-27)

The user found, live, that logging into pc caddie's own site showed other
players' real names once they opted into its reciprocal name-sharing — an
anonymous fetch (everything this scraper had ever done) only ever shows
placeholder text. The parsing side of this was already built years ago and
never wired up (`scraper._parse_slot_row()`'s `authenticated` parameter,
present since day one); `scraper.scrape_schedule()` now accepts an
already-logged-in `httpx.Client`, and `scrape_once.py` builds one shared
authenticated session per scrape pass (background scraper included, confirmed
with the user first) rather than one login per date/course.

Real names never reach any AI provider — `ai_assist._describe_candidate()`'s
"friends already booked" line, which used to include every player in a slot
unfiltered, was dropped entirely (confirmed with the user before building this:
no existing "friends list" to filter to instead, so drop rather than
half-fix). `Store.swift`'s `Slot` gained `players: [String]`;
`SearchClient.swift`'s `SearchMatch.players` was already fully wired and just
never rendered. Both `SlotRow` and `SearchResultRow` now show players when
present, same tooltip treatment as AI reasons.

## The Overview never showed a recommended pick (2026-09-27)

The TUI's Overview has shown a "★ HH:MM" recommended pick per day (AI-ranked
once `ai_assist.enabled`) since 2026-09-08 -- the GUI's Overview never had an
equivalent, only its ad hoc Search sheet did. Surfaced right after getting a
real Gemini key working end to end: reasons showed up in Search, nothing
changed in the Overview.

New `teetime-monitor-picks` console script (`src/picks_cli.py`, sitting right
next to `search_cli.py`) calls `pipeline._availability_pipeline()` directly for
each date in a window -- the exact function the TUI's own Pick column calls --
so the GUI's pick can never disagree with what the TUI shows for the same
data. New `PicksClient.swift` mirrors `SearchClient.swift`'s shell-out shape;
`OverviewModel.reload()` fires it fire-and-forget right after its own
synchronous SQLite reload, riding the same 2-second DB-mtime-watcher cadence
`reload()` already runs on -- no new timer. `DayCardHeader`'s existing
booking-flag badge slot gained a second branch (no confirmed booking, but a
pick exists) showing a "★ HH:MM" badge with reasons in a `.help()` tooltip,
same two-tier priority the TUI's own Pick column uses.

Found live while testing this: Gemini's free-tier `gemini-flash-latest`
returned a real `503 UNAVAILABLE` ("high demand") on roughly half of a run of
consecutive live calls, and `ai_assist.py` had no retry anywhere. New
`_with_retry()` (all four providers, not just Gemini) retries once for
anything except the provider's own auth-error class. Verified against the
real database: a genuine pick with real German-language reasons came back
from the CLI directly. Full interactive confirmation of the badge in the
running app wasn't possible in this sandbox (no native desktop computer-use
tool available, only Chrome-browser control) -- verification stopped at the
CLI's real output plus a clean build+launch.

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
`pipeline._resolved_config(club_slug=None, club_id, club_name)` and
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
this CLI isn't. `pipeline._crowd_estimates()` — the exact function `SearchScreen.
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
`pipeline._resolved_config()` directly for the config merge so it can't drift from what
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

## The Python-helper runner (2026-10-05)

Every helper call goes through `Subprocess.run` (`Sources/Subprocess.swift`):
- **Timeout per call**, SIGTERM then SIGKILL after 2 s, surfaced as `SubprocessError.timedOut`
  (picks 60 s, search 90 s, preview 120 s, login / AI verify 30 s, scraper refresh 300 s,
  directory refresh and add-club 60 s). `Subprocess.Timeout` holds them.
- **Cancellation**: `run` takes a `SubprocessHandle`; `cancel()` terminates the child and the
  client's `done` is then never called. `OverviewModel.fetchPicks()` cancels the superseded
  picks run (latest wins) instead of letting it finish; the search sheet cancels on close.
- **Executable lookup** is `Subprocess.resolve(name)`: `$TEETIME_MONITOR_BIN_DIR`,
  `/opt/homebrew/bin`, `/usr/local/bin`, `~/.local/bin` (uv tool installs), then one
  `which` with a 3 s timeout. Hits are cached for the app's lifetime; a miss for 30 s.
- **SIGPIPE**: the stdin write end is non-signalling and `Main.swift` ignores SIGPIPE, so a
  helper that exits without reading its input can't kill the app.

## What it deliberately doesn't do

No scraping (beyond shelling out to the existing scraper binary; login, search, and
the two directory actions behind add-a-club are the same shelling-out shape), no
real booking on pc caddie itself.
