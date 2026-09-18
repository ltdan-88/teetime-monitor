# teetime-monitor — macOS Swift prototype

A deliberately small SwiftUI prototype of the overview screen, built to answer one
question: **what would a native macOS version feel like, and what would it cost?**

Not a rewrite. Not shipped. Not wired into the Homebrew formula.

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

Needs **only the Command Line Tools** — no Xcode, no Swift Package Manager, no
dependencies:

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
neither alone works. Text scales through SwiftUI's own `dynamicTypeSize` -- every
view here already uses semantic fonts (`.caption2`/`.headline`/`.title2`), so one
environment value at the root scales all of it with no per-view change and none of
`.scaleEffect`'s blurriness. Fixed pixel dimensions can't follow that, and would
clip larger text or strand smaller text, so every one of them moved into a single
`Metrics` enum and multiplies by the scale factor at its use site. "Medium" maps to
macOS's *own* default Dynamic Type size, so an install that never touches this looks
exactly as it did.

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
(the heatmap's own aggregation, most of add-a-club).

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

**One known, flagged gap**: a club's `calendar.vacation_ranges` is a YAML *list* of
`{start, end, label}` maps, and `YAML.swift`'s parser is deliberately scoped to
nested maps of scalars only (no lists -- see its own docstring). A vacation day
classifies as an ordinary weekend/workday here instead of its own bucket, until
that's worth a real list parser. Narrower than it sounds today: neither of this
install's own two saved clubs has a `calendar:` block configured at all yet, so
this changes nothing real yet, only what a future hand-entered vacation range
would do.

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
