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
}

/// Reads the database the Python scraper already maintains. Deliberately read-only:
/// this prototype does no scraping, no login and no writing at all -- the existing
/// launchd agent keeps the data fresh and this just renders it.
enum Store {
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

    /// One entry per club database found, newest-scraped first.
    ///
    /// Picking the *alphabetically* first database was a real bug (found 2026-09-17,
    /// straight from a "no luck" report): this install has five, and the first by name
    /// is `0000001.db` -- a leftover test club with no scrapes at all -- so the app
    /// showed "No scraped days yet" permanently no matter what the scraper did.
    /// Ordering by the most recent scrape puts the club you actually use first, and
    /// listing them all makes the rest reachable rather than hidden.
    ///
    /// The display name comes from the club's own YAML in the config directory when
    /// one exists (`name:`), read with a plain line scan rather than a YAML dependency
    /// -- one key, one line, and a wrong guess just means showing the numeric id.
    static func clubs() -> [(path: String, id: String, name: String, lastScrape: String)] {
        let home = NSHomeDirectory() as NSString
        let env = ProcessInfo.processInfo.environment["TEETIME_MONITOR_DATA_DIR"]
        let dataDir = (env as NSString?)?.expandingTildeInPath
            ?? home.appendingPathComponent(".local/share/teetime-monitor")
        let configEnv = ProcessInfo.processInfo.environment["TEETIME_MONITOR_CONFIG_DIR"]
        let clubsDir = ((configEnv as NSString?)?.expandingTildeInPath
            ?? home.appendingPathComponent(".config/teetime-monitor")) + "/clubs"

        var names: [String: String] = [:]
        for file in (try? FileManager.default.contentsOfDirectory(atPath: clubsDir)) ?? []
        where file.hasSuffix(".yaml") {
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
            // `name:` is optional in a club YAML (a club favorited before the
            // directory search could supply one has none), so fall back to the
            // filename slug, prettified -- same "name or slug" rule tui.py's own
            // _favorite_clubs() uses. Showing a bare numeric id is the last resort.
            if let id {
                let slug = file.replacingOccurrences(of: ".yaml", with: "")
                    .replacingOccurrences(of: "-", with: " ")
                    .capitalized
                names[id] = name ?? slug
            }
        }

        var out: [(String, String, String, String)] = []
        for file in ((try? FileManager.default.contentsOfDirectory(atPath: dataDir)) ?? [])
            .filter({ $0.hasSuffix(".db") }) {
            let path = "\(dataDir)/\(file)"
            let id = file.replacingOccurrences(of: ".db", with: "")
            var last = ""
            var db: OpaquePointer?
            if sqlite3_open_v2(path, &db, SQLITE_OPEN_READONLY, nil) == SQLITE_OK, let db {
                query(db, "SELECT MAX(scraped_at) FROM scrapes") { s in last = column(s, 0) ?? "" }
                sqlite3_close(db)
            }
            out.append((path, id, names[id] ?? id, last))
        }
        return out.sorted { $0.3 > $1.3 }.map { (path: $0.0, id: $0.1, name: $0.2, lastScrape: $0.3) }
    }

    static func courses(dbPath: String) -> [String] {
        var db: OpaquePointer?
        guard sqlite3_open_v2(dbPath, &db, SQLITE_OPEN_READONLY, nil) == SQLITE_OK,
              let db else { return [] }
        defer { sqlite3_close(db) }
        var out: [String] = []
        query(db, "SELECT DISTINCT course FROM scrapes ORDER BY course") { s in
            if let c = column(s, 0) { out.append(c) }
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
