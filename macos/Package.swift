// swift-tools-version:5.9
import PackageDescription

/// Test infrastructure only -- the shipped `.app` still builds via `build.sh`'s
/// plain `swiftc Sources/*.swift`, untouched by this file, per this prototype's own
/// "Command Line Tools only, no Xcode" rule (see README.md).
///
/// `TeetimeMonitorCoreTests` is a plain **executable** target, not SPM's own
/// `.testTarget` -- tried first, and rejected for a concrete, verified reason:
/// `.testTarget` needs either XCTest (its frameworks aren't present under a bare
/// Command Line Tools install -- confirmed directly: `unable to resolve module
/// dependency: 'XCTest'`) or swift-testing's `@Test`/`#expect` macros (also
/// confirmed directly: `plugin for module 'TestingMacros' not found`, the exact
/// "macro plugin ships with Xcode, not the Command Line Tools" gotcha this project
/// already hit once for SwiftUI's own `@State` -- see `Box.swift`). A plain
/// executable with hand-rolled assertions needs nothing beyond `swiftc` itself, so
/// it's the one shape of "tests" that's actually runnable here. Run with
/// `swift run TeetimeMonitorCoreTests`.
///
/// `TeetimeMonitorCore` points at the *same* `Sources/` directory `build.sh` globs,
/// excluding only `Main.swift` -- just the `@main`/`WindowGroup`/menu-commands
/// `Scene`, pulled out into its own file (2026-09-26) specifically so it *can* stay
/// excluded without taking the rest of `App.swift` down with it: pulling a second
/// `@main` into a library target risks an entry-point conflict with the test
/// executables below, and it's the one piece of this app that's a `Scene`, not a
/// `View`, with nothing for `VisualRegressionRunner` to render anyway.
///
/// Every SwiftUI view file, `App.swift` and all four sheets
/// (`SettingsViews`/`SearchSheet`/`AddClubSheet`/`HeatmapSheet`), is included now --
/// previously excluded wholesale ("a view's own body isn't something an assertion
/// can check without snapshot-testing infrastructure this project doesn't have").
/// `VisualRegressionRunner` is that infrastructure; it (so far) only actually
/// renders `DayCardHeader`/`SlotRow` (see its own docstring for why the rest isn't
/// covered yet), but `ContentView` itself references every sheet type directly, so
/// there's no excluding any subset of these four without the library failing to
/// compile at all -- confirmed directly, not assumed (tried excluding just the
/// sheets while including `App.swift`, got "cannot find 'SettingsSheet' in scope"
/// etc.). Everything with real behaviour -- SQLite reads/writes, YAML/config
/// parsing, unit conversion, day classification, the heatmap aggregation,
/// directory search, translation lookup -- already had no SwiftUI view dependency
/// and lives here regardless, view files included or not.
let package = Package(
    name: "TeetimeMonitorCore",
    platforms: [.macOS(.v14)],
    targets: [
        .target(
            name: "TeetimeMonitorCore",
            path: "Sources",
            exclude: ["Main.swift"]
        ),
        .executableTarget(
            name: "TeetimeMonitorCoreTests",
            dependencies: ["TeetimeMonitorCore"],
            path: "Tests/TeetimeMonitorCoreTests"
        ),
        // The cross-language drift guard: reads the JSON
        // ../../scripts/cross_language_reference.py generates from the real Python
        // functions and recomputes the Swift equivalents for the same inputs,
        // failing if anything disagrees. A standing check, not the one-time-by-hand
        // verification every port here previously got -- see that script's own
        // docstring for the full reasoning.
        .executableTarget(
            name: "CrossCheckRunner",
            dependencies: ["TeetimeMonitorCore"],
            path: "Tests/CrossCheckRunner"
        ),
        // Visual regression checks (added 2026-09-26, direct request following
        // three rounds of grid-alignment bugs that only ever showed up in a
        // real screenshot, never in `TeetimeMonitorCoreTests`' own assertions):
        // renders real views -- `DayCardHeader`/`SlotRow`, the ones the bugs
        // were actually in -- off-screen via `ImageRenderer` and diffs the
        // result against a stored reference PNG, so a regression here fails a
        // build instead of waiting for the next screenshot someone happens to
        // take. See that target's own `main.swift` docstring for the full
        // contract (recording mode, tolerance, why native-control-bearing
        // views like the Club/Platz row aren't in scope yet).
        .executableTarget(
            name: "VisualRegressionRunner",
            dependencies: ["TeetimeMonitorCore"],
            path: "Tests/VisualRegressionRunner",
            // Not `resources: [.copy(...)]` -- `main.swift` reads/writes
            // `References/`/`Failures/` directly via its own `#filePath`, so a
            // `--record` run writes straight back into the source tree instead
            // of a copied, git-invisible resource bundle. Excluded here only so
            // SPM's own source scan doesn't warn about "unhandled files" it was
            // never going to compile anyway.
            exclude: ["References", "Failures"]
        ),
    ]
)
