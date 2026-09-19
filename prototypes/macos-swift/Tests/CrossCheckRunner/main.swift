import Foundation
@testable import TeetimeMonitorCore

// Reads the reference JSON `scripts/cross_language_reference.py` generates from
// the real Python functions, recomputes the Swift port of each one for the same
// inputs, and fails on any mismatch. Usage:
//
//   python scripts/cross_language_reference.py > /tmp/reference.json
//   swift run CrossCheckRunner /tmp/reference.json
//
// See that script's own docstring for why this exists and what it deliberately
// doesn't cover (crowd_heatmap() -- reads a database rather than taking plain
// arguments, so a meaningful cross-check needs a shared fixture format neither
// side has yet; that comparison is still pinned once, by hand, in
// AnalyticsTests.swift instead).

guard CommandLine.arguments.count > 1 else {
    print("usage: CrossCheckRunner <reference.json>")
    exit(2)
}

guard let data = FileManager.default.contents(atPath: CommandLine.arguments[1]),
      let reference = try? JSONSerialization.jsonObject(with: data) as? [String: [[String: Any]]] else {
    print("could not read or parse \(CommandLine.arguments[1])")
    exit(2)
}

var checked = 0
var failed = 0

/// Loose equality between a value the Swift port just computed and the JSON value
/// `JSONSerialization` decoded for the same case's `"expected"` field -- NSNumber
/// vs a native Swift numeric, `NSNull`/JSON `null` vs Swift's own `nil`, and
/// array-of-array for the directory search results.
func jsonEqual(_ actual: Any, _ expected: Any) -> Bool {
    if expected is NSNull, "\(actual)" == "nil" { return true }
    if let da = actual as? Double, let de = expected as? Double { return abs(da - de) < 1e-6 }
    if let sa = actual as? String, let se = expected as? String { return sa == se }
    if let aa = actual as? [[String]], let ea = expected as? [[Any]] {
        guard aa.count == ea.count else { return false }
        return zip(aa, ea).allSatisfy { rowA, rowE in (rowE as? [String]) == rowA }
    }
    return "\(actual)" == "\(expected)"
}

func runGroup(_ name: String, _ compute: ([String: Any]) -> Any) {
    for row in reference[name] ?? [] {
        guard let args = row["args"] as? [String: Any] else { continue }
        checked += 1
        let actual = compute(args)
        let expected = row["expected"] ?? NSNull()
        if !jsonEqual(actual, expected) {
            failed += 1
            print("MISMATCH [\(name)] args=\(args)")
            print("  python: \(expected)")
            print("  swift:  \(actual)")
        }
    }
}

runGroup("units_temperature") { args in
    Units.temperature(args["celsius"] as! Double, args["units"] as! String)
}
runGroup("units_wind_speed") { args in
    Units.windSpeed(args["kph"] as! Double, args["units"] as! String)
}
runGroup("units_precipitation_mm") { args in
    Units.precipitationMM(args["mm"] as! Double, args["units"] as! String)
}
runGroup("units_temperature_symbol") { args in Units.temperatureSymbol(args["units"] as! String) }
runGroup("units_wind_symbol") { args in Units.windSymbol(args["units"] as! String) }
runGroup("units_precipitation_label") { args in Units.precipitationAmountLabel(args["units"] as! String) }

runGroup("classify_day") { args in
    let vacationRanges = (args["vacation_ranges"] as! [[String: Any]]).map {
        VacationRange(start: $0["start"] as! String, end: $0["end"] as! String, label: "")
    }
    return CalendarContext.classifyDay(
        date: args["date"] as! String, holidays: args["holidays"] as! [String],
        vacationRanges: vacationRanges, hasTournament: args["has_tournament"] as! Bool)
}

runGroup("directory_search") { args in
    let directory = (args["directory"] as! [[String]]).map { DirectoryEntry(clubID: $0[0], name: $0[1]) }
    return ClubDirectoryStore.search(directory, query: args["query"] as! String).map { [$0.clubID, $0.name] }
}
runGroup("looks_like_club_id") { args in
    ClubDirectoryStore.looksLikeClubID(args["query"] as! String) as Any
}

print("")
if failed == 0 {
    print("\u{2713} \(checked)/\(checked) cross-checked cases match Python")
    exit(0)
} else {
    print("\u{2717} \(failed)/\(checked) cross-checked cases DISAGREE with Python")
    exit(1)
}
