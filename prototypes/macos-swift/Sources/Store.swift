import Foundation
import SQLite3

// SQLITE_TRANSIENT tells SQLite to copy a bound string; the Swift constant isn't
// exposed by the C shim, so it's spelled out here the way every Swift/SQLite
// wrapper does.
private let SQLITE_TRANSIENT = unsafeBitCast(
    -1, to: (@convention(c) (UnsafeMutableRawPointer?) -> Void).self)

struct Slot: Identifiable {
    var id: String { time }
    let time: String
    let booked: Int
    let capacity: Int
    let blockReason: String?
    var isBlocked: Bool { blockReason != nil }
    var fill: Double { capacity > 0 ? Double(booked) / Double(capacity) : 0 }
}

struct WeatherPoint {
    let time: String
    let precipitationProbability: Double?
    let precipitationMM: Double?
    let windKPH: Double?
    let temperatureC: Double?
    let code: Int?
}

struct Day: Identifiable {
    var id: String { date }
    let date: String
    let slots: [Slot]
    let weather: [WeatherPoint]
    let sunrise: String?
    let sunset: String?
    let events: [String]
    let bookedTime: String?

    /// Hourly lookup, so a 09:10 slot picks up the 09:00 forecast point.
    func weather(at time: String) -> WeatherPoint? {
        let hour = String(time.prefix(2))
        return weather.first { $0.time.hasPrefix(hour) }
    }

    /// Six two-hour buckets across 08:00-20:00 -- the same heat strip the TUI draws.
    var heatStrip: [Double?] {
        stride(from: 8, to: 20, by: 2).map { start in
            let real = slots.filter {
                guard let h = Int($0.time.prefix(2)) else { return false }
                return h >= start && h < start + 2 && !$0.isBlocked
            }
            let capacity = real.reduce(0) { $0 + $1.capacity }
            guard capacity > 0 else { return nil }
            return Double(real.reduce(0) { $0 + $1.booked }) / Double(capacity)
        }
    }

    /// 08:00-20:00 only -- the exact window `tui._temperature_cell()`/
    /// `_precipitation_cell()`/`_wind_cell()`/`_condition_cell()` all use for a
    /// day-level summary, so the collapsed row's numbers match what those would show.
    private var daytimeWeather: [WeatherPoint] { weather.filter { $0.time >= "08:00" && $0.time < "20:00" } }

    /// The single most severe WMO code among the day's daytime hours -- mirrors
    /// `weather_icons.worst_icon()`'s own severity order exactly (a day that's sunny
    /// all morning and thunderstorms in the afternoon is a thunderstorm day, not a
    /// "mostly sunny" one), not just whatever happened to be forecast at noon.
    var conditionCode: Int? {
        let known = daytimeWeather.compactMap(\.code).filter { Day.severityOrder.contains($0) }
        return known.min { Day.severityOrder.firstIndex(of: $0)! < Day.severityOrder.firstIndex(of: $1)! }
    }
    private static let severityOrder = [
        95, 96, 99, 85, 86, 71, 73, 75, 77, 66, 67, 61, 63, 65, 80, 81, 82,
        56, 57, 51, 53, 55, 45, 48, 3, 2, 1, 0,
    ]

    /// (high, low) across daytime -- `_temperature_cell()`'s own "24/14", not an
    /// instantaneous reading.
    var tempHighLow: (high: Double, low: Double)? {
        let t = daytimeWeather.compactMap(\.temperatureC)
        guard let hi = t.max(), let lo = t.min() else { return nil }
        return (hi, lo)
    }

    /// Average daytime rain probability -- `_precipitation_cell()`'s own figure
    /// (the per-slot cell shows one hour's real number; this is the day's summary).
    var precipAvg: Double? {
        let p = daytimeWeather.compactMap(\.precipitationProbability)
        return p.isEmpty ? nil : p.reduce(0, +) / Double(p.count)
    }

    /// Peak daytime wind -- `_wind_cell()`'s own "worst case across the window", not
    /// an average.
    var windPeak: Double? { daytimeWeather.compactMap(\.windKPH).max() }

    /// The slot row nearest sunrise/sunset -- mirrors `tui._closest_slot_time()`
    /// exactly, including its tie-break: `slots` is already chronological (loaded
    /// `ORDER BY time`), and `min(by:)` keeps the first-seen minimum on a tie the
    /// same way Python's own `min()` does, so an equal-distance tie resolves to the
    /// earlier time in both.
    private func closestSlotTime(to target: String?) -> String? {
        guard let target, !slots.isEmpty else { return nil }
        func minutes(_ t: String) -> Int {
            (Int(t.prefix(2)) ?? 0) * 60 + (Int(t.dropFirst(3).prefix(2)) ?? 0)
        }
        let goal = minutes(target)
        return slots.map(\.time).min { abs(minutes($0) - goal) < abs(minutes($1) - goal) }
    }
    var sunriseRowTime: String? { closestSlotTime(to: sunrise) }
    var sunsetRowTime: String? { closestSlotTime(to: sunset) }
}

/// One unacknowledged notice from `booking_changes` -- a friend joined your flight,
/// your buffer shrank, a "My Reservations" sync failed, etc.
///
/// Shown via `renderBookingChange(kind:paramsJSON:)` -- the Swift port of
/// `i18n.render_booking_change()` (see I18n.swift) -- falling back to `message`
/// (plain English, stored specifically "as a fallback/for any non-TUI consumer"
/// per storage.py's own schema comment) only for a `kind` that function doesn't
/// recognize. Direct report, 2026-09-20 ("why is the notification not
/// translated?"): this used to always show `message`, which is rendered once in
/// English at scrape time regardless of which language this app is actually
/// showing everything else in.
struct Banner: Identifiable {
    let id: Int
    let course: String
    let date: String
    let time: String?
    let kind: String
    let paramsJSON: String
    let message: String

    var text: String { renderBookingChange(kind: kind, paramsJSON: paramsJSON) ?? message }
}

/// Reads (and, as of Tier 1, writes some of) the database the Python scraper already
/// maintains. Never scrapes, never logs in -- the existing launchd agent keeps the
/// data fresh; writes here are limited to local-only facts (a manual confirm/cancel,
/// acknowledging a banner) that were always just SQLite rows, never a live pc caddie
/// interaction, on the Python side either.
enum Store {
    /// "18 Loch Tee 1" -> 18, "Kurzplatz" -> nil. Mirrors
    /// `scraper._holes_from_course_label()` exactly: leading digits only, no
    /// assumption for a name that has none.
    static func holes(from course: String) -> Int? {
        var digits = ""
        for ch in course { if ch.isNumber { digits.append(ch) } else { break } }
        return Int(digits)
    }

    /// Records a confirmed tee time -- the manual fallback path
    /// `storage.save_confirmed_booking()` backs, same `source: "manual"` the TUI's
    /// own `ConfirmBookingScreen` writes. Never overwrites: `confirmed_bookings` is
    /// deliberately append-only (see storage.py's own module docstring -- analytics
    /// needs the full history), and `load_latest_schedule()`/this prototype's own Day
    /// both already read "latest row wins."
    static func confirmBooking(dbPath: String, course: String, date: String, time: String) {
        let holes = holes(from: course)
        write(dbPath, "INSERT INTO confirmed_bookings (course, date, time, holes, source, confirmed_at) "
              + "VALUES (?, ?, ?, ?, 'manual', ?)",
              [course, date, time, holes.map(String.init) ?? nil, isoNow()])
    }

    /// Marks a date as "confirmed not playing" -- mirrors `CancelBookingScreen`'s own
    /// write exactly: `time`/`holes` both NULL, same manual source. A new row, not a
    /// delete or update, same append-only reasoning as `confirmBooking()` above.
    static func cancelBooking(dbPath: String, course: String, date: String) {
        write(dbPath, "INSERT INTO confirmed_bookings (course, date, time, holes, source, confirmed_at) "
              + "VALUES (?, ?, NULL, NULL, 'manual', ?)",
              [course, date, isoNow()])
    }

    static func banners(dbPath: String) -> [Banner] {
        var db: OpaquePointer?
        guard sqlite3_open_v2(dbPath, &db, SQLITE_OPEN_READWRITE, nil) == SQLITE_OK, let db else { return [] }
        defer { sqlite3_close(db) }
        var out: [Banner] = []
        query(db, "SELECT id, course, date, time, kind, params, message FROM booking_changes "
              + "WHERE acknowledged = 0 ORDER BY id") { s in
            out.append(Banner(
                id: Int(sqlite3_column_int(s, 0)),
                course: column(s, 1) ?? "",
                date: column(s, 2) ?? "",
                time: column(s, 3),
                kind: column(s, 4) ?? "",
                paramsJSON: column(s, 5) ?? "{}",
                message: column(s, 6) ?? ""))
        }
        return out
    }

    /// Marks banners seen -- an UPDATE, not a delete, same as
    /// `storage.acknowledge_booking_changes()`: the row stays as a historical record,
    /// it just stops showing again.
    static func acknowledgeBanners(dbPath: String, ids: [Int]) {
        guard !ids.isEmpty else { return }
        var db: OpaquePointer?
        guard sqlite3_open_v2(dbPath, &db, SQLITE_OPEN_READWRITE, nil) == SQLITE_OK, let db else { return }
        defer { sqlite3_close(db) }
        for id in ids {
            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, "UPDATE booking_changes SET acknowledged = 1 WHERE id = ?", -1, &stmt, nil)
                == SQLITE_OK else { continue }
            sqlite3_bind_int(stmt, 1, Int32(id))
            sqlite3_step(stmt)
            sqlite3_finalize(stmt)
        }
    }

    private static func isoNow() -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.string(from: Date())
    }

    private static func write(_ dbPath: String, _ sql: String, _ binds: [String?]) {
        var db: OpaquePointer?
        guard sqlite3_open_v2(dbPath, &db, SQLITE_OPEN_READWRITE, nil) == SQLITE_OK, let db else { return }
        defer { sqlite3_close(db) }
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return }
        defer { sqlite3_finalize(stmt) }
        for (i, b) in binds.enumerated() {
            if let b {
                sqlite3_bind_text(stmt, Int32(i + 1), b, -1, SQLITE_TRANSIENT)
            } else {
                sqlite3_bind_null(stmt, Int32(i + 1))
            }
        }
        sqlite3_step(stmt)
    }

    private static func column(_ s: OpaquePointer?, _ i: Int32) -> String? {
        guard let c = sqlite3_column_text(s, i) else { return nil }
        return String(cString: c)
    }

    private static func query(
        _ db: OpaquePointer, _ sql: String, _ binds: [String] = [],
        _ row: (OpaquePointer?) -> Void
    ) {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return }
        defer { sqlite3_finalize(stmt) }
        for (i, b) in binds.enumerated() {
            sqlite3_bind_text(stmt, Int32(i + 1), b, -1, SQLITE_TRANSIENT)
        }
        while sqlite3_step(stmt) == SQLITE_ROW { row(stmt) }
    }

    /// `<dataDir>/<clubID>.db` -- the same fixed-name database every reader here
    /// (`days()`, `courses()`, ...) already reads for *any* club file that
    /// exists, favorited or not (only `clubs()` below cares about `clubs/*.yaml`
    /// specifically). Exposed on its own for `OverviewModel.startPreview()`,
    /// which needs this same path for a club that has no saved YAML to read it
    /// back out of the way `clubs()` does for a favorited one.
    static func dbPath(clubID: String) -> String {
        let home = NSHomeDirectory() as NSString
        let env = ProcessInfo.processInfo.environment["TEETIME_MONITOR_DATA_DIR"]
        let dataDir = (env as NSString?)?.expandingTildeInPath
            ?? home.appendingPathComponent(".local/share/teetime-monitor")
        return "\(dataDir)/\(clubID).db"
    }

    /// One entry per **saved** club, newest-scraped first.
    ///
    /// Driven by `~/.config/teetime-monitor/clubs/*.yaml` — the same favourites the TUI
    /// lists — rather than by whatever `*.db` files happen to exist. Two bugs came out
    /// of the database-enumeration version (2026-09-17, from a direct "why does the app
    /// have more clubs than plausible?"):
    ///
    /// - A database is created for *any* club you ever opened, including ones you only
    ///   browsed and never saved. This install had five databases for two saved clubs.
    /// - Picking the alphabetically-first one landed on `0000001.db`, a leftover test
    ///   club with no scrapes at all, so the app looked permanently empty.
    ///
    /// A saved club with no database yet is still listed (it just has nothing to show),
    /// which is the honest state for a club favourited before its first scrape.
    static func clubs() -> [(path: String, id: String, slug: String, name: String, lastScrape: String)] {
        let home = NSHomeDirectory() as NSString
        let env = ProcessInfo.processInfo.environment["TEETIME_MONITOR_DATA_DIR"]
        let dataDir = (env as NSString?)?.expandingTildeInPath
            ?? home.appendingPathComponent(".local/share/teetime-monitor")
        let configEnv = ProcessInfo.processInfo.environment["TEETIME_MONITOR_CONFIG_DIR"]
        let clubsDir = ((configEnv as NSString?)?.expandingTildeInPath
            ?? home.appendingPathComponent(".config/teetime-monitor")) + "/clubs"

        var out: [(String, String, String, String, String)] = []
        for file in ((try? FileManager.default.contentsOfDirectory(atPath: clubsDir)) ?? []).sorted()
        where file.hasSuffix(".yaml") && file != "club.example.yaml" {
            guard let text = try? String(contentsOfFile: "\(clubsDir)/\(file)", encoding: .utf8)
            else { continue }
            var id: String?, name: String?
            for line in text.split(separator: "\n") {
                let t = line.trimmingCharacters(in: .whitespaces)
                if t.hasPrefix("club_id:") {
                    id = t.dropFirst("club_id:".count).trimmingCharacters(in: CharacterSet(charactersIn: " '\""))
                } else if t.hasPrefix("name:") {
                    name = t.dropFirst("name:".count).trimmingCharacters(in: CharacterSet(charactersIn: " '\""))
                }
            }
            guard let id, !id.isEmpty else { continue }
            // `name:` is optional (a club favourited before a directory search could
            // supply one has none), so fall back to the filename slug -- the same
            // "name or slug" rule tui.py's own _favorite_clubs() uses.
            let slug = file.replacingOccurrences(of: ".yaml", with: "")
            let display = name ?? slug.replacingOccurrences(of: "-", with: " ").capitalized
            let path = "\(dataDir)/\(id).db"
            var last = ""
            var db: OpaquePointer?
            if FileManager.default.fileExists(atPath: path),
               sqlite3_open_v2(path, &db, SQLITE_OPEN_READONLY, nil) == SQLITE_OK, let db {
                query(db, "SELECT MAX(scraped_at) FROM scrapes") { s in last = column(s, 0) ?? "" }
                sqlite3_close(db)
            }
            out.append((path, id, slug, display, last))
        }
        return out.sorted { $0.4 > $1.4 }
            .map { (path: $0.0, id: $0.1, slug: $0.2, name: $0.3, lastScrape: $0.4) }
    }

    /// Un-favorite a club -- direct request, 2026-09-19 ("implement removing/
    /// unfavoriting club in GUI"), mirroring `club_config.remove_favorite()`
    /// exactly: deletes `clubs/<slug>.yaml` and nothing else. Scraped history in
    /// `data/<club_id>.db` is intentionally left alone (kept by club id, not
    /// slug), so re-adding the same club later still has its history -- same
    /// Tier 1 "delete the file Python already owns directly" pattern `clubs()`
    /// above already reads that same file with, not a new console script for
    /// what's genuinely just an unlink.
    static func removeClub(slug: String) {
        let home = NSHomeDirectory() as NSString
        let configEnv = ProcessInfo.processInfo.environment["TEETIME_MONITOR_CONFIG_DIR"]
        let clubsDir = ((configEnv as NSString?)?.expandingTildeInPath
            ?? home.appendingPathComponent(".config/teetime-monitor")) + "/clubs"
        try? FileManager.default.removeItem(atPath: "\(clubsDir)/\(slug).yaml")
    }

    /// When this club was last scraped, for the freshness line in the toolbar.
    static func lastScrape(dbPath: String) -> Date? {
        var db: OpaquePointer?
        guard sqlite3_open_v2(dbPath, &db, SQLITE_OPEN_READONLY, nil) == SQLITE_OK,
              let db else { return nil }
        defer { sqlite3_close(db) }
        var iso: String?
        query(db, "SELECT MAX(scraped_at) FROM scrapes") { s in iso = column(s, 0) }
        guard let iso else { return nil }
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.date(from: iso) ?? ISO8601DateFormatter().date(from: iso)
    }

    /// Every date this course has ever been scraped for, oldest first -- mirrors
    /// `storage.distinct_scraped_dates()` exactly. The heatmap (see Analytics.swift)
    /// needs the *whole* history, unlike `days()` below, which only ever loads a
    /// bounded window for the day list.
    static func distinctScrapedDates(dbPath: String, course: String) -> [String] {
        var db: OpaquePointer?
        guard sqlite3_open_v2(dbPath, &db, SQLITE_OPEN_READONLY, nil) == SQLITE_OK, let db else { return [] }
        defer { sqlite3_close(db) }
        var out: [String] = []
        query(db, "SELECT DISTINCT date FROM scrapes WHERE course = ? ORDER BY date", [course]) { s in
            if let d = column(s, 0) { out.append(d) }
        }
        return out
    }

    /// Just enough for `analytics._crowd_buckets()`'s own narrow needs -- occupancy
    /// and whether the day had a tournament -- not the full weather/sunrise shape
    /// `days()` builds, since a heatmap walks every historical date rather than a
    /// bounded window and has no use for any of that here.
    static func occupancySample(dbPath: String, course: String, date: String) -> (slots: [Slot], hasTournament: Bool)? {
        var db: OpaquePointer?
        guard sqlite3_open_v2(dbPath, &db, SQLITE_OPEN_READONLY, nil) == SQLITE_OK, let db else { return nil }
        defer { sqlite3_close(db) }
        var scrapeID: Int64 = -1
        var eventsJSON: String?
        query(db,
              "SELECT id, events FROM scrapes WHERE course = ? AND date = ? ORDER BY id DESC LIMIT 1",
              [course, date]) { s in
            scrapeID = sqlite3_column_int64(s, 0)
            eventsJSON = column(s, 1)
        }
        guard scrapeID >= 0 else { return nil }
        var slots: [Slot] = []
        query(db,
              "SELECT time, booked, capacity, block_reason FROM slots WHERE scrape_id = \(scrapeID) ORDER BY time") { s in
            slots.append(Slot(time: column(s, 0) ?? "", booked: Int(sqlite3_column_int(s, 1)),
                               capacity: Int(sqlite3_column_int(s, 2)), blockReason: column(s, 3)))
        }
        var hasTournament = false
        if let json = eventsJSON, let data = json.data(using: .utf8),
           let parsed = try? JSONDecoder().decode([String].self, from: data) {
            hasTournament = !parsed.isEmpty
        }
        return (slots, hasTournament)
    }

    /// `~/.config/teetime-monitor/clubs/<slug>.yaml` -- same env-var-overridable
    /// resolution `clubs()` already does internally, exposed here since the heatmap
    /// needs a specific club's own file (for `calendar.country_code`) rather than
    /// the whole directory listing.
    static func clubYAMLPath(slug: String) -> String {
        let home = NSHomeDirectory() as NSString
        let configEnv = ProcessInfo.processInfo.environment["TEETIME_MONITOR_CONFIG_DIR"]
        let clubsDir = ((configEnv as NSString?)?.expandingTildeInPath
            ?? home.appendingPathComponent(".config/teetime-monitor")) + "/clubs"
        return "\(clubsDir)/\(slug).yaml"
    }

    static func courses(dbPath: String) -> [String] {
        var db: OpaquePointer?
        guard sqlite3_open_v2(dbPath, &db, SQLITE_OPEN_READONLY, nil) == SQLITE_OK,
              let db else { return [] }
        defer { sqlite3_close(db) }
        // Only courses still being scraped for today or later.
        //
        // `SELECT DISTINCT course` returns every course name ever written to this
        // database, and that is not the same as the club's current lineup. Hetzenhof's
        // database really does hold eight: its own five, plus three of *Niederreutin's*
        // names written between 2026-09-07 and 2026-09-12, back when the scraper used
        // one hardcoded course list for every club (see scraper.py's COURSE_ALIASES
        // note and `fetch_course_aliases()`, the fix). Those rows are inert history, but
        // listing them offered courses this club has never had.
        //
        // A live `fetch_course_aliases()` would be authoritative, but this prototype is
        // deliberately offline -- and "has upcoming scrapes" separates them exactly:
        // a retired or bogus course stops accumulating future dates the moment the
        // scraper stops asking for it.
        let today: String = {
            let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"
            return f.string(from: Date())
        }()
        var out: [String] = []
        query(db, "SELECT DISTINCT course FROM scrapes WHERE date >= ? ORDER BY course", [today]) { s in
            if let c = column(s, 0) { out.append(c) }
        }
        if out.isEmpty {
            // Nothing scraped for an upcoming date -- the scraper may simply not have
            // run for a while. Fall back to everything rather than showing no courses
            // at all, which would look broken.
            query(db, "SELECT DISTINCT course FROM scrapes ORDER BY course") { s in
                if let c = column(s, 0) { out.append(c) }
            }
        }
        return out
    }

    static func days(dbPath: String, course: String, from today: String, limit: Int = 6) -> [Day] {
        var db: OpaquePointer?
        guard sqlite3_open_v2(dbPath, &db, SQLITE_OPEN_READONLY, nil) == SQLITE_OK,
              let db else { return [] }
        defer { sqlite3_close(db) }

        var dates: [String] = []
        query(db,
              "SELECT DISTINCT date FROM scrapes WHERE course = ? AND date >= ? ORDER BY date LIMIT \(limit)",
              [course, today]) { s in
            if let d = column(s, 0) { dates.append(d) }
        }

        return dates.compactMap { date -> Day? in
            var scrapeID: Int64 = -1
            var sunrise: String?, sunset: String?, eventsJSON: String?
            query(db,
                  "SELECT id, sunrise, sunset, events FROM scrapes WHERE course = ? AND date = ? ORDER BY id DESC LIMIT 1",
                  [course, date]) { s in
                scrapeID = sqlite3_column_int64(s, 0)
                sunrise = column(s, 1); sunset = column(s, 2); eventsJSON = column(s, 3)
            }
            guard scrapeID >= 0 else { return nil }

            var slots: [Slot] = []
            query(db,
                  "SELECT time, booked, capacity, block_reason FROM slots WHERE scrape_id = \(scrapeID) ORDER BY time") { s in
                slots.append(Slot(time: column(s, 0) ?? "",
                                  booked: Int(sqlite3_column_int(s, 1)),
                                  capacity: Int(sqlite3_column_int(s, 2)),
                                  blockReason: column(s, 3)))
            }

            // Mirrors the Python read path (storage.load_latest_schedule, v0.30.1): when
            // the newest scrape has no weather -- an upstream fetch failure -- fall back
            // to the most recent earlier scrape of the same course/date that does, so a
            // transient outage doesn't blank the column.
            var weatherScrapeID = scrapeID
            var hasWeather = false
            query(db, "SELECT 1 FROM weather_points WHERE scrape_id = \(scrapeID) LIMIT 1") { _ in hasWeather = true }
            if !hasWeather {
                query(db,
                      """
                      SELECT s.id, s.sunrise, s.sunset FROM scrapes s
                      WHERE s.course = ? AND s.date = ? AND s.id < \(scrapeID)
                        AND EXISTS (SELECT 1 FROM weather_points w WHERE w.scrape_id = s.id)
                      ORDER BY s.id DESC LIMIT 1
                      """, [course, date]) { s in
                    weatherScrapeID = sqlite3_column_int64(s, 0)
                    if sunrise == nil { sunrise = column(s, 1); sunset = column(s, 2) }
                }
            }

            var weather: [WeatherPoint] = []
            query(db,
                  """
                  SELECT time, precipitation_probability, precipitation_mm, wind_speed_kph,
                         temperature_c, weather_code
                  FROM weather_points WHERE scrape_id = \(weatherScrapeID) ORDER BY time
                  """) { s in
                weather.append(WeatherPoint(
                    time: column(s, 0) ?? "",
                    precipitationProbability: sqlite3_column_type(s, 1) == SQLITE_NULL ? nil : sqlite3_column_double(s, 1),
                    precipitationMM: sqlite3_column_type(s, 2) == SQLITE_NULL ? nil : sqlite3_column_double(s, 2),
                    windKPH: sqlite3_column_type(s, 3) == SQLITE_NULL ? nil : sqlite3_column_double(s, 3),
                    temperatureC: sqlite3_column_type(s, 4) == SQLITE_NULL ? nil : sqlite3_column_double(s, 4),
                    code: sqlite3_column_type(s, 5) == SQLITE_NULL ? nil : Int(sqlite3_column_int(s, 5))))
            }

            var bookedTime: String?
            query(db,
                  "SELECT time FROM confirmed_bookings WHERE course = ? AND date = ? ORDER BY id DESC LIMIT 1",
                  [course, date]) { s in
                bookedTime = column(s, 0)
            }

            var events: [String] = []
            if let json = eventsJSON, let data = json.data(using: .utf8),
               let parsed = try? JSONDecoder().decode([String].self, from: data) {
                events = parsed
            }

            return Day(date: date, slots: slots, weather: weather, sunrise: sunrise,
                       sunset: sunset, events: events, bookedTime: bookedTime)
        }
    }
}
