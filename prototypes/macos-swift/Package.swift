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
/// excluding only the SwiftUI view files (`App.swift`'s own `@main`/window plus the
/// four sheets) -- those are layout, not logic, and pulling `App.swift`'s `@main`
/// into a library target risks an entry-point conflict with the test executable for
/// no real test value: a view's *body* isn't something an assertion can check
/// without snapshot-testing infrastructure this project doesn't have. Everything
/// with real behaviour -- SQLite reads/writes, YAML/config parsing, unit
/// conversion, day classification, the heatmap aggregation, directory search,
/// translation lookup -- has no SwiftUI view dependency and lives here.
let package = Package(
    name: "TeetimeMonitorCore",
    platforms: [.macOS(.v14)],
    targets: [
        .target(
            name: "TeetimeMonitorCore",
            path: "Sources",
            exclude: [
                "App.swift", "SettingsViews.swift", "SearchSheet.swift",
                "AddClubSheet.swift", "HeatmapSheet.swift",
            ]
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
    ]
)
