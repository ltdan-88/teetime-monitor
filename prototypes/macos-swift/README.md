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

**It does no scraping at all.** It opens the SQLite database the Python scraper already
maintains, read-only, and renders it. The launchd agent keeps working exactly as it
does today; this is a second reader of the same data.

That is why it's ~400 lines instead of ~5,000. It deliberately sidesteps the entire
expensive half of a real rewrite — the scraper, the login, the parsing rules, the
weather and calendar fetches, the recommendation pipeline — all of which stay in
Python. Treat that as the prototype's main finding, not a detail: a hybrid like this is
genuinely viable, and is far cheaper than porting the backend.

One piece of real logic *is* mirrored rather than skipped: the weather fallback from
v0.30.1 (when the newest scrape has no weather, fall back to the most recent earlier
scrape of the same course/date that does). Without it the prototype would show the same
blank column the Python app used to.

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

## What it deliberately doesn't do

No scraping, no login, no booking, no settings, no preferences, no search, no heatmap,
no i18n, no notifications, no writes of any kind. It reads and it draws.
