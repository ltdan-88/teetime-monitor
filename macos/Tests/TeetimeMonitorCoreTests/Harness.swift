import Foundation

/// A minimal, framework-free test harness -- see `Package.swift`'s own docstring
/// for why: neither XCTest nor swift-testing's macros are available under a bare
/// Command Line Tools install, confirmed directly rather than assumed.
///
/// Deliberately small: one global counter pair, one assertion function, one runner.
/// Enough to catch a regression and say exactly where, not a reimplementation of
/// XCTest's own feature set.
final class Harness {
    static var passed = 0
    static var failed = 0
    private static var currentGroup = ""

    static func group(_ name: String, _ body: () -> Void) {
        currentGroup = name
        body()
    }

    static func check(
        _ name: String, _ condition: @autoclosure () -> Bool,
        file: String = #fileID, line: Int = #line
    ) {
        if condition() {
            passed += 1
        } else {
            failed += 1
            print("FAIL  [\(currentGroup)] \(name)  (\(file):\(line))")
        }
    }

    static func checkEqual<T: Equatable>(
        _ name: String, _ actual: T, _ expected: T,
        file: String = #fileID, line: Int = #line
    ) {
        if actual == expected {
            passed += 1
        } else {
            failed += 1
            print("FAIL  [\(currentGroup)] \(name)  (\(file):\(line))")
            print("      got:      \(actual)")
            print("      expected: \(expected)")
        }
    }

    /// `abs(a - b) < tolerance`, for Double comparisons where an exact `==` would
    /// be fragile against floating-point rounding -- most callers here instead
    /// compare against a Python-computed reference value to a fixed precision.
    static func checkClose(
        _ name: String, _ actual: Double, _ expected: Double, tolerance: Double = 1e-9,
        file: String = #fileID, line: Int = #line
    ) {
        if abs(actual - expected) < tolerance {
            passed += 1
        } else {
            failed += 1
            print("FAIL  [\(currentGroup)] \(name)  (\(file):\(line))")
            print("      got:      \(actual)")
            print("      expected: \(expected)")
        }
    }

    static func summarizeAndExit() -> Never {
        let total = passed + failed
        print("")
        if failed == 0 {
            print("\u{2713} \(passed)/\(total) passed")
            exit(0)
        } else {
            print("\u{2717} \(failed)/\(total) FAILED (\(passed) passed)")
            exit(1)
        }
    }
}

/// A fresh scratch directory under the real system temp dir, auto-removed when the
/// returned value goes out of scope -- the Swift-side equivalent of pytest's own
/// `tmp_path` fixture, used by every test here that touches the filesystem so nothing
/// ever reads or writes this machine's real `~/.config/teetime-monitor`.
final class TempDir {
    let path: String
    init() {
        path = NSTemporaryDirectory() + "teetime-core-tests-\(UUID().uuidString)"
        try! FileManager.default.createDirectory(atPath: path, withIntermediateDirectories: true)
    }
    deinit { try? FileManager.default.removeItem(atPath: path) }
    func file(_ name: String) -> String { path + "/" + name }
}
