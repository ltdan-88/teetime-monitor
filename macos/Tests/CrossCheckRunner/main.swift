import Foundation
import SQLite3
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
    if expected is NSNull { return actual is NSNull || "\(actual)" == "nil" }
    if actual is NSNull { return false }
    if type(of: actual) == Bool.self { return (expected as? Bool) == (actual as! Bool) }
    if let da = actual as? Double, let de = expected as? Double { return abs(da - de) < 1e-6 }
    if let sa = actual as? String, let se = expected as? String { return sa == se }
    if let aa = actual as? [Any], let ea = expected as? [Any] {
        return aa.count == ea.count && zip(aa, ea).allSatisfy { jsonEqual($0, $1) }
    }
    if let ma = actual as? [String: Any], let me = expected as? [String: Any] {
        return Set(ma.keys) == Set(me.keys) && ma.allSatisfy { key, value in jsonEqual(value, me[key]!) }
    }
    return "\(actual)" == "\(expected)"
}

/// An optional as its JSON shape: the value itself, or NSNull for nil (a bare
/// `x ?? NSNull()` keeps the Optional wrapper inside the `Any`).
func orNull<T>(_ value: T?) -> Any { value.map { $0 as Any } ?? NSNull() }

var ranGroups: Set<String> = []

func runGroup(_ name: String, _ compute: ([String: Any]) -> Any) {
    ranGroups.insert(name)
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
runGroup("family_name") { args in
    familyName(args["name"] as! String)
}
runGroup("whole_number") { args in
    wholeNumber(args["value"] as! Double)
}

runGroup("hours_text") { args in
    hoursText(args["minutes"] as! Int, language: args["language"] as! String)
}
runGroup("holes_from_label") { args in
    orNull(Store.holes(from: args["course"] as! String))
}

/// A `Day` holding just `args["weather"]` -- the payload `_weather_payload()` writes.
func weatherDay(_ args: [String: Any], slots: [Slot] = []) -> Day {
    let points = (args["weather"] as! [[String: Any]]).map { w in
        WeatherPoint(time: w["time"] as! String, precipitationProbability: w["p"] as? Double,
                     precipitationMM: w["mm"] as? Double, windKPH: w["wind"] as? Double,
                     temperatureC: w["temp"] as? Double, code: w["code"] as? Int)
    }
    return Day(date: "2026-10-05", slots: slots, weather: points, sunrise: nil, sunset: nil, events: [], bookedTime: nil)
}

runGroup("day_temperature_cell") { args in
    weatherDay(args).temperatureCellText(units: args["units"] as! String)
}
runGroup("day_wind_cell") { args in
    weatherDay(args).windCellText(units: args["units"] as! String)
}
runGroup("day_precipitation_cell") { args in
    AppLanguage.shared.code = args["language"] as! String
    defer { AppLanguage.shared.code = "en" }
    return weatherDay(args).precipitationCellText(units: args["units"] as! String)
}
runGroup("slot_precipitation_cell") { args in
    slotPrecipitationCellText(weatherDay(args).weather(at: args["time"] as! String), units: args["units"] as! String)
}
// The GUI draws SF Symbols where the TUI draws emoji, so the code Day picks is
// mapped through the TUI's own emoji table: same emoji <=> same severity pick.
runGroup("day_condition_code") { args in
    let icons = args["icons"] as! [String: String]
    return weatherDay(args).conditionCode.flatMap { icons[String($0)] } ?? ""
}
runGroup("severity_order") { _ in Day.severityOrder }
runGroup("condition_icon_groups") { args in
    let symbols = Set((args["codes"] as! [Int]).map { icon(for: $0) })
    return symbols.count == 1 && !symbols.contains("questionmark")
}

runGroup("closest_slot_time") { args in
    let slots = (args["times"] as! [String]).map {
        Slot(time: $0, booked: 0, capacity: 4, blockReason: nil, players: [])
    }
    let target = args["target"] as! String
    let day = Day(date: "2026-10-05", slots: slots, weather: [], sunrise: target, sunset: target,
                  events: [], bookedTime: nil)
    return orNull(day.sunriseRowTime)
}
runGroup("anonymous_players_text") { args in
    AppLanguage.shared.code = args["language"] as! String
    defer { AppLanguage.shared.code = "en" }
    return anonymousPlayersText(booked: args["booked"] as! Int, namedCount: args["named"] as! Int)
}
runGroup("render_booking_change") { args in
    AppLanguage.shared.code = args["language"] as! String
    defer { AppLanguage.shared.code = "en" }
    return orNull(renderBookingChange(kind: args["kind"] as! String, paramsJSON: args["params"] as! String))
}

runGroup("club_yaml_scalars") { args in
    let text = args["text"] as! String
    let (id, name) = Store.clubIDAndName(in: text)
    return [id ?? "", name ?? "", ClubDefaults.parseDefaultCourse(in: text) ?? ""]
}

// A database `storage.py` built with its real schema and writers, read back through
// Store's own SQL -- a renamed column or a typo there fails here rather than
// silently emptying the player directory.
runGroup("store_players") { args in
    let path = NSTemporaryDirectory() + "crosscheck-\(UUID().uuidString).db"
    defer { try? FileManager.default.removeItem(atPath: path) }
    var db: OpaquePointer?
    guard sqlite3_open(path, &db) == SQLITE_OK,
          sqlite3_exec(db, args["sql"] as! String, nil, nil, nil) == SQLITE_OK else {
        sqlite3_close(db)
        return "could not load the reference database"
    }
    sqlite3_close(db)
    let players: [[Any]] = Store.knownPlayers(dbPath: path).map {
        [$0.name, $0.lastSeen, $0.isFriend, orNull($0.gender), orNull($0.memberStatus),
         orNull($0.handicap)]
    }
    return [
        "friend_names": Store.friendNames(dbPath: path).sorted(),
        "player_genders": Store.playerGenders(dbPath: path),
        "known_players": players,
        "my_handicap": orNull(Store.myHandicap(dbPath: path)),
    ] as [String: Any]
}

/// `storage.scrape_health()`'s dict shape, from the Swift struct.
func healthDict(_ h: ScrapeHealth) -> [String: Any] {
    [
        "consecutive_failed_runs": h.consecutiveFailedRuns,
        "failing_since": orNull(h.failingSince),
        "last_error_kind": orNull(h.lastErrorKind),
        "last_error_message": orNull(h.lastErrorMessage),
        "last_run_at": orNull(h.lastRunAt),
        "last_success_at": orNull(h.lastSuccessAt),
        "login_rejected_since": orNull(h.loginRejectedSince),
    ]
}

// Scrape health (2026-10-05): databases storage.py built and summarized, read back
// through Store.scrapeHealth() -- the GUI footer must agree with the TUI's #status.
runGroup("store_scrape_health") { args in
    let path = NSTemporaryDirectory() + "crosscheck-health-\(UUID().uuidString).db"
    defer { try? FileManager.default.removeItem(atPath: path) }
    var db: OpaquePointer?
    guard sqlite3_open(path, &db) == SQLITE_OK,
          sqlite3_exec(db, args["sql"] as! String, nil, nil, nil) == SQLITE_OK else {
        sqlite3_close(db)
        return "could not load the reference database"
    }
    sqlite3_close(db)
    return healthDict(Store.scrapeHealth(dbPath: path))
}
runGroup("scrape_health_warning") { args in
    AppLanguage.shared.code = args["language"] as! String
    defer { AppLanguage.shared.code = "en" }
    let h = args["health"] as! [String: Any]
    func str(_ key: String) -> String? { h[key] as? String }
    let health = ScrapeHealth(
        lastRunAt: str("last_run_at"), lastSuccessAt: str("last_success_at"),
        lastErrorKind: str("last_error_kind"), lastErrorMessage: str("last_error_message"),
        consecutiveFailedRuns: (h["consecutive_failed_runs"] as? NSNumber)?.intValue ?? 0,
        failingSince: str("failing_since"), loginRejectedSince: str("login_rejected_since"))
    let now = ScrapeHealthRules.parse(args["now"] as? String) ?? Date()
    let interval = args["interval"] as! Int
    let status = ScrapeHealthRules.status(health, intervalMinutes: interval, now: now)
    let warning = ScrapeHealthRules.warning(health, intervalMinutes: interval, now: now)
    return [orNull(status?.0.rawValue), orNull(warning?.text)]
}
runGroup("health_i18n") { args in
    I18n.strings[args["language"] as! String]?[args["key"] as! String] ?? "<missing>"
}

// The lock badge's wording (2026-10-05): tui._lock_when_text() vs lockWhenText(), and the
// shared lock.*/weekday.* strings text-for-text.
func isoInstant(_ s: String) -> Date {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime]
    return f.date(from: s)!
}
runGroup("lock_when") { args in
    AppLanguage.shared.code = args["language"] as! String
    defer { AppLanguage.shared.code = "en" }
    return orNull(lockWhenText(opensAt: args["opens_at"] as! String, hourKnown: args["hour_known"] as! Bool,
                               now: isoInstant(args["now"] as! String)))
}
runGroup("lock_i18n") { args in
    I18n.strings[args["language"] as! String]?[args["key"] as! String] ?? "<missing>"
}

// A reference group with no runGroup here would otherwise pass by checking nothing.
for name in Set(reference.keys).subtracting(ranGroups).sorted() {
    failed += 1
    print("UNCHECKED reference group [\(name)] -- add a runGroup for it")
}

print("")
if failed == 0 {
    print("\u{2713} \(checked)/\(checked) cross-checked cases match Python")
    exit(0)
} else {
    print("\u{2717} \(failed)/\(checked) cross-checked cases DISAGREE with Python")
    exit(1)
}
