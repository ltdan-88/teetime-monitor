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
