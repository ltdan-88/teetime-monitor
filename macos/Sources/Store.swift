import Foundation
import SQLite3

// SQLITE_TRANSIENT tells SQLite to copy a bound string; the Swift constant isn't
// exposed by the C shim, so it's spelled out here the way every Swift/SQLite
// wrapper does.
private let SQLITE_TRANSIENT = unsafeBitCast(
    -1, to: (@convention(c) (UnsafeMutableRawPointer?) -> Void).self)

/// `storage.py` JSON-encodes both `scrapes.events` and `slots.players` as a plain
/// `list[str]` -- one shared decoder for both, same as the two call sites below
/// already shared their (until now, inlined-per-call-site) events decode.
private func decodeStringArray(_ json: String?) -> [String] {
    guard let json, let data = json.data(using: .utf8),
          let parsed = try? JSONDecoder().decode([String].self, from: data) else { return [] }
    return parsed
}

struct Slot: Identifiable {
    var id: String { time }
    let time: String
    let booked: Int
    let capacity: Int
    let blockReason: String?
    /// Real names, only ever non-empty when scrape_once.py's own authenticated fetch
    /// was used (2026-09-27) -- pc caddie shows real names only to a logged-in member
    /// whose own privacy setting opts into reciprocal name-sharing; an anonymous
    /// fetch (the only kind before this) never sees one. Deliberately never sent to
    /// any AI provider -- see ai_assist.py's own `_describe_candidate()` docstring.
    let players: [String]
    var isBlocked: Bool { blockReason != nil }
    var fill: Double { capacity > 0 ? Double(booked) / Double(capacity) : 0 }
}

/// The last whitespace-separated token of `name` -- a free function (not a
/// `KnownPlayer` property) so `CrossCheckRunner` can call it directly against
/// `models.family_name()`'s own reference cases. Same heuristic, same acknowledged
/// gap on nobility particles -- see that function's own docstring.
func familyName(_ name: String) -> String {
    let trimmed = name.trimmingCharacters(in: .whitespaces)
    guard !trimmed.isEmpty else { return name }
    return trimmed.split(separator: " ").last.map(String.init) ?? trimmed
}

/// Mirrors `models.KnownPlayer` -- a real name seen in some `Slot.players` list
/// (2026-09-27, only possible from an authenticated scrape), browsable in the
/// directory sheet with `isFriend` the one field a person actually edits.
///
/// `gender`/`memberStatus`/`handicap` (2026-09-27, direct follow-up: "are there any
/// further scrapable information... worth to display?" -- checked live against the
/// real authenticated tee sheet HTML) are each the most recently seen value, any of
/// which can be `nil` -- see `models.PlayerSighting`'s own docstring.
struct KnownPlayer: Identifiable {
    var id: String { name }
    let name: String
    let lastSeen: String
    let isFriend: Bool
    let gender: String?
    let memberStatus: String?
    let handicap: Double?
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
    var daytimeWeather: [WeatherPoint] { weather.filter { $0.time >= "08:00" && $0.time < "20:00" } }

    /// The single most severe WMO code among the day's daytime hours -- mirrors
    /// `weather_icons.worst_icon()`'s own severity order exactly (a day that's sunny
    /// all morning and thunderstorms in the afternoon is a thunderstorm day, not a
    /// "mostly sunny" one), not just whatever happened to be forecast at noon.
    var conditionCode: Int? {
        let known = daytimeWeather.compactMap(\.code).filter { Day.severityOrder.contains($0) }
        return known.min { Day.severityOrder.firstIndex(of: $0)! < Day.severityOrder.firstIndex(of: $1)! }
    }
    /// `weather_icons._SEVERITY_ORDER` -- pinned by the `severity_order` cross-check.
    static let severityOrder = [
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
    /// A point with no probability counts as 0 and stays in the count, as Python's
    /// `(w.precipitation_probability or 0)` over `len(daytime)` does; dropping it
    /// showed 6x60% + 6xnull as 60% where the TUI shows 30%. nil only with no
    /// daytime points at all.
    var precipAvg: Double? {
        let points = daytimeWeather
        guard !points.isEmpty else { return nil }
        return points.reduce(0) { $0 + ($1.precipitationProbability ?? 0) } / Double(points.count)
    }

    /// Total daytime rain amount -- the "/2.4mm" half of `_precipitation_cell()`.
    var precipTotalMM: Double { daytimeWeather.reduce(0) { $0 + ($1.precipitationMM ?? 0) } }

    /// Every daytime point at >= 70% -- `tui._is_rain_all_day()`, which replaces the
    /// day's rain figure with "rain all day".
    var isRainAllDay: Bool {
        let points = daytimeWeather
        return !points.isEmpty && points.allSatisfy { ($0.precipitationProbability ?? 0) >= 70 }
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

    /// The slots an expanded day shows: from the sunrise row through the sunset
    /// row, both kept since they carry the sunrise/sunset notes -- the same rule
    /// as `tui._compute_slot_rows()` (2026-09-27, bundle C of the TUI/GUI
    /// consistency audit). Replaces a fixed 07:00-19:30 clip that only this app
    /// had, while the TUI listed every slot from 06:00: a tee time in the dark
    /// isn't one anyone books, whatever the season. Every slot without sun
    /// times to measure against.
    var visibleSlots: [Slot] {
        slots.filter { slot in
            if let first = sunriseRowTime, slot.time < first { return false }
            if let last = sunsetRowTime, slot.time > last { return false }
            return true
        }
    }
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
    /// "18 Loch Tee 1" -> 18, "Tee 10 (9 Loch)" -> 9, "Kurzplatz" -> nil. Mirrors
    /// `scraper._holes_from_course_label()` exactly: the smallest explicit
    /// "N Loch"/"N-Loch" mention wins, else the leading digits, else no guess.
    static func holes(from course: String) -> Int? {
        let regex = try! NSRegularExpression(pattern: "(\\d+)\\s*-?\\s*Loch", options: [.caseInsensitive])
        let range = NSRange(course.startIndex..., in: course)
        let mentions = regex.matches(in: course, range: range).compactMap { match -> Int? in
            guard let r = Range(match.range(at: 1), in: course) else { return nil }
            return Int(course[r])
        }
        if let smallest = mentions.min() { return smallest }
        var digits = ""
        for ch in course { if ch.isNumber { digits.append(ch) } else { break } }
        return Int(digits)
    }

    /// `recommend.holes_for_course()`: the club's `course_holes` override (exact label,
    /// case-insensitive, trimmed; `ClubDefaults.courseHoles`) wins over the name
    /// heuristic above, which is the fallback; nil when neither knows. `overrides` is in
    /// file order and the first match wins (Python's rule), so a hand-edited file with
    /// "Kurz: 9" and "kurz: 18" resolves the same way in both apps.
    static func holes(from course: String, overrides: [(String, Int)]) -> Int? {
        let wanted = ClubDefaults.normalizedCourseKey(course)
        for (label, holes) in overrides where holes > 0 && ClubDefaults.normalizedCourseKey(label) == wanted {
            return holes
        }
        return holes(from: course)
    }

    /// Records a confirmed tee time -- the manual fallback path
    /// `storage.save_confirmed_booking()` backs, same `source: "manual"` the TUI's
    /// own `ConfirmBookingScreen` writes. Never overwrites: `confirmed_bookings` is
    /// deliberately append-only (see storage.py's own module docstring -- analytics
    /// needs the full history), and `load_latest_schedule()`/this prototype's own Day
    /// both already read "latest row wins."
    /// `false` when the row wasn't written (database locked past the busy timeout,
    /// missing table, ...), so the caller doesn't report a booking that isn't there.
    @discardableResult
    static func confirmBooking(dbPath: String, course: String, date: String, time: String,
                               courseHoles: [(String, Int)] = []) -> Bool {
        let holes = holes(from: course, overrides: courseHoles)
        return write(dbPath, "INSERT INTO confirmed_bookings (course, date, time, holes, source, confirmed_at) "
                     + "VALUES (?, ?, ?, ?, 'manual', ?)",
                     [course, date, time, holes.map(String.init) ?? nil, isoNow()])
    }

    /// Marks a date as "confirmed not playing" -- mirrors `CancelBookingScreen`'s own
    /// write exactly: `time`/`holes` both NULL, same manual source. A new row, not a
    /// delete or update, same append-only reasoning as `confirmBooking()` above.
    @discardableResult
    static func cancelBooking(dbPath: String, course: String, date: String) -> Bool {
        write(dbPath, "INSERT INTO confirmed_bookings (course, date, time, holes, source, confirmed_at) "
              + "VALUES (?, ?, NULL, NULL, 'manual', ?)",
              [course, date, isoNow()])
    }

    /// Every real name this club's own scrapes have ever seen, sorted alphabetically
    /// by family name (2026-09-27, direct request; "better: make the player directory
    /// sortable and searchable" -- this is just the default order the sheet loads
    /// with, before any in-sheet re-sort) -- mirrors `storage.load_known_players()`'s
    /// own default order exactly. Sorted here in Swift, not SQL, for the same reason
    /// that function sorts in Python: `familyName`'s last-whitespace-token rule isn't
    /// a plain `ORDER BY`. Silently empty (not an error) for a database that predates
    /// this feature -- `known_players` won't exist yet, and `query()`'s own guard
    /// already degrades a failed prepare to "no rows" rather than crashing.
    static func friendNames(dbPath: String) -> Set<String> {
        guard let db = openDB(dbPath) else { return [] }
        defer { sqlite3_close(db) }
        var names: Set<String> = []
        query(db, "SELECT name FROM known_players WHERE is_friend = 1") { s in
            if let name = column(s, 0) { names.insert(name) }
        }
        return names
    }

    /// Name -> "male"/"female" for every player with a recorded gender -- colours names
    /// in the overview (the site's own "unknown" marker is left out).
    static func playerGenders(dbPath: String) -> [String: String] {
        guard let db = openDB(dbPath) else { return [:] }
        defer { sqlite3_close(db) }
        var genders: [String: String] = [:]
        query(db, "SELECT name, gender FROM known_players WHERE gender IN ('male', 'female')") { s in
            if let name = column(s, 0), let gender = column(s, 1) { genders[name] = gender }
        }
        return genders
    }

    /// Name -> handicap for every player with one recorded (NULL left out) -- the
    /// "(18,4)" after a name in the overview. Mirrors `storage.load_player_handicaps()`.
    static func playerHandicaps(dbPath: String) -> [String: Double] {
        guard let db = openDB(dbPath) else { return [:] }
        defer { sqlite3_close(db) }
        var handicaps: [String: Double] = [:]
        query(db, "SELECT name, handicap FROM known_players WHERE handicap IS NOT NULL") { s in
            if let name = column(s, 0) { handicaps[name] = sqlite3_column_double(s, 1) }
        }
        return handicaps
    }

    /// Name -> "member"/"guest" where the club's data says -- the hover text of the
    /// players cell. (The TUI has no hover, so nothing on the Python side mirrors it.)
    static func playerMemberStatuses(dbPath: String) -> [String: String] {
        guard let db = openDB(dbPath) else { return [:] }
        defer { sqlite3_close(db) }
        var statuses: [String: String] = [:]
        query(db, "SELECT name, member_status FROM known_players WHERE member_status IS NOT NULL") { s in
            if let name = column(s, 0), let status = column(s, 1) { statuses[name] = status }
        }
        return statuses
    }

    static func knownPlayers(dbPath: String) -> [KnownPlayer] {
        guard let db = openDB(dbPath) else { return [] }
        defer { sqlite3_close(db) }
        var players: [KnownPlayer] = []
        query(db, "SELECT name, last_seen, is_friend, gender, member_status, handicap FROM known_players") { s in
            players.append(KnownPlayer(
                name: column(s, 0) ?? "",
                lastSeen: column(s, 1) ?? "",
                isFriend: sqlite3_column_int(s, 2) != 0,
                gender: column(s, 3),
                memberStatus: column(s, 4),
                handicap: sqlite3_column_type(s, 5) == SQLITE_NULL ? nil : sqlite3_column_double(s, 5)
            ))
        }
        // casefold, not lowercased(): `load_known_players()` sorts with casefold(),
        // which folds ß to "ss" (pinned by the `store_players` cross-check).
        return players.sorted {
            (casefold(familyName($0.name)), casefold($0.name))
                < (casefold(familyName($1.name)), casefold($1.name))
        }
    }

    /// Marks (or unmarks) one known name as a friend -- the directory sheet's own
    /// selection action, same "just do it, no separate Save step" shape a toggle
    /// implies. A no-op if `name` was never actually seen, mirroring
    /// `storage.set_player_friend()`'s own stance exactly.
    @discardableResult
    static func setPlayerFriend(dbPath: String, name: String, isFriend: Bool) -> Bool {
        write(dbPath, "UPDATE known_players SET is_friend = ? WHERE name = ?", [isFriend ? "1" : "0", name])
    }

    /// Your own live handicap index, as `storage.load_my_handicap()` cached it --
    /// same `club_meta` key-value table `save_location()`/`load_location()` already
    /// use on the Python side, read here rather than through a new CLI script since
    /// this is a single scalar read, same reasoning as `knownPlayers()` above.
    /// `nil` if it's never been synced yet (or this club has no db file yet at all).
    /// The stored value is JSON (`json.dumps(handicap)`, e.g. "43.8") -- a bare
    /// `Double(string:)` parse handles that exactly, same as any plain float literal.
    static func myHandicap(dbPath: String) -> Double? {
        guard let db = openDB(dbPath) else { return nil }
        defer { sqlite3_close(db) }
        var raw: String?
        query(db, "SELECT value FROM club_meta WHERE key = 'my_handicap'") { s in raw = column(s, 0) }
        return raw.flatMap { Double($0) }
    }

    static func banners(dbPath: String) -> [Banner] {
        guard let db = openDB(dbPath, SQLITE_OPEN_READWRITE) else { return [] }
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
    @discardableResult
    static func acknowledgeBanners(dbPath: String, ids: [Int]) -> Bool {
        guard !ids.isEmpty else { return true }
        guard let db = openDB(dbPath, SQLITE_OPEN_READWRITE) else { return false }
        defer { sqlite3_close(db) }
        var ok = true
        for id in ids {
            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, "UPDATE booking_changes SET acknowledged = 1 WHERE id = ?", -1, &stmt, nil)
                == SQLITE_OK else { ok = false; continue }
            sqlite3_bind_int(stmt, 1, Int32(id))
            if sqlite3_step(stmt) != SQLITE_DONE { ok = false }
            sqlite3_finalize(stmt)
        }
        return ok
    }

    private static func isoNow() -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.string(from: Date())
    }

    /// How long a read or write waits for the scraper's lock before giving up --
    /// the same 5000 ms as `storage.BUSY_TIMEOUT_MS`. With SQLite's own default of 0 a
    /// GUI write that landed inside a scraper commit failed at once with SQLITE_BUSY.
    static let busyTimeoutMS: Int32 = 5000

    /// The schema version this build knows -- `storage.SCHEMA_VERSION`. A database
    /// stamped with a *newer* one (an updated scraper ran first) is still read as
    /// before: nothing here refuses or warns on a higher number.
    static let knownSchemaVersion = 1

    /// `PRAGMA user_version` of the database (0 when it predates the stamp), nil when
    /// it can't be opened. Informational only -- no reader branches on it.
    static func schemaVersion(dbPath: String) -> Int? {
        guard let db = openDB(dbPath) else { return nil }
        defer { sqlite3_close(db) }
        var version: Int?
        query(db, "PRAGMA user_version") { s in version = Int(sqlite3_column_int(s, 0)) }
        return version
    }

    /// The databases run in WAL mode (2026-10-05, `storage._open()`), so a reader and
    /// the scraper's writer no longer block each other. A read-only connection on a WAL
    /// database still needs the `-shm` index: SQLite reads or creates it itself as long
    /// as the directory is writable. When it can't (a read-only volume, a restored
    /// backup in a locked folder) the first read fails with CANTOPEN/READONLY; this then
    /// falls back to `immutable=1`, which skips locking and the sidecar entirely and
    /// reads the main file as of its last checkpoint -- slightly stale at worst, never
    /// an error and never a write.
    private static func openDB(_ path: String, _ flags: Int32 = SQLITE_OPEN_READONLY) -> OpaquePointer? {
        var db: OpaquePointer?
        guard sqlite3_open_v2(path, &db, flags, nil) == SQLITE_OK, let db else {
            sqlite3_close(db)
            return nil
        }
        sqlite3_busy_timeout(db, busyTimeoutMS)
        guard flags & SQLITE_OPEN_READWRITE == 0 else { return db }
        // Touch the schema: this is where a WAL database without a usable -shm fails.
        let rc = sqlite3_exec(db, "SELECT 1 FROM sqlite_master LIMIT 1", nil, nil, nil)
        if rc == SQLITE_OK { return db }
        sqlite3_close(db)
        guard rc & 0xFF != SQLITE_BUSY, rc & 0xFF != SQLITE_NOTADB, rc & 0xFF != SQLITE_CORRUPT else { return nil }
        return openImmutable(path)
    }

    private static func openImmutable(_ path: String) -> OpaquePointer? {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "?#%")
        guard let escaped = path.addingPercentEncoding(withAllowedCharacters: allowed) else { return nil }
        var db: OpaquePointer?
        guard sqlite3_open_v2("file:\(escaped)?immutable=1", &db,
                              SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, nil) == SQLITE_OK, let db else {
            sqlite3_close(db)
            return nil
        }
        guard sqlite3_exec(db, "SELECT 1 FROM sqlite_master LIMIT 1", nil, nil, nil) == SQLITE_OK else {
            sqlite3_close(db)
            return nil
        }
        return db
    }

    /// `true` once the statement really ran (SQLITE_DONE), so a caller can tell a
    /// saved booking/friend flag from one that was dropped.
    @discardableResult
    private static func write(_ dbPath: String, _ sql: String, _ binds: [String?]) -> Bool {
        guard let db = openDB(dbPath, SQLITE_OPEN_READWRITE) else { return false }
        defer { sqlite3_close(db) }
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return false }
        defer { sqlite3_finalize(stmt) }
        for (i, b) in binds.enumerated() {
            if let b {
                sqlite3_bind_text(stmt, Int32(i + 1), b, -1, SQLITE_TRANSIENT)
            } else {
                sqlite3_bind_null(stmt, Int32(i + 1))
            }
        }
        return sqlite3_step(stmt) == SQLITE_DONE
    }

    /// Both sun times or neither -- `storage.load_latest_schedule()`'s own `if
    /// sunrise and sunset`. `weather.fetch_sun_times()` stores "" for an empty
    /// Open-Meteo response; kept as a value, "" parsed as 00:00 and collapsed an
    /// expanded day to its first slot.
    static func sunTimes(_ sunrise: String?, _ sunset: String?) -> (String?, String?) {
        guard let sunrise, let sunset, !sunrise.isEmpty, !sunset.isEmpty else { return (nil, nil) }
        return (sunrise, sunset)
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
            let (id, name) = clubIDAndName(in: text)
            guard let id, !id.isEmpty else { continue }
            // `name:` is optional (a club favourited before a directory search could
            // supply one has none), so fall back to the filename slug -- the same
            // "name or slug" rule tui.py's own _favorite_clubs() uses.
            let slug = file.replacingOccurrences(of: ".yaml", with: "")
            let display = name ?? slug.replacingOccurrences(of: "-", with: " ").capitalized
            let path = "\(dataDir)/\(id).db"
            var last = ""
            if FileManager.default.fileExists(atPath: path), let db = openDB(path) {
                query(db, "SELECT MAX(scraped_at) FROM scrapes") { s in last = column(s, 0) ?? "" }
                sqlite3_close(db)
            }
            out.append((path, id, slug, display, last))
        }
        return out.sorted { $0.4 > $1.4 }
            .map { (path: $0.0, id: $0.1, slug: $0.2, name: $0.3, lastScrape: $0.4) }
    }

    /// A club file's `club_id:` and `name:` values, decoded the way `yaml.safe_load`
    /// would -- a club saved before `allow_unicode=True` has `name: "Golfclub
    /// W\xFCrzburg"`, which used to reach the toolbar as literal escape text.
    static func clubIDAndName(in text: String) -> (id: String?, name: String?) {
        var id: String?, name: String?
        for line in text.split(separator: "\n") {
            let t = line.trimmingCharacters(in: .whitespaces)
            if t.hasPrefix("club_id:") {
                id = YAML.scalarText(String(t.dropFirst("club_id:".count)))
            } else if t.hasPrefix("name:") {
                name = YAML.scalarText(String(t.dropFirst("name:".count)))
            }
        }
        return (id, name)
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
        guard let db = openDB(dbPath) else { return nil }
        defer { sqlite3_close(db) }
        var iso: String?
        query(db, "SELECT MAX(scraped_at) FROM scrapes") { s in iso = column(s, 0) }
        guard let iso else { return nil }
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.date(from: iso) ?? ISO8601DateFormatter().date(from: iso)
    }

    /// This club's `scrape_runs`, summarized exactly as `storage.scrape_health()` does
    /// (2026-10-05, see ScrapeHealth.swift). Read-only, and `.empty` -- no warning --
    /// for a database that predates the table (or doesn't exist yet): `query()`
    /// treats the failed prepare as "no rows".
    static func scrapeHealth(dbPath: String) -> ScrapeHealth {
        guard let db = openDB(dbPath) else { return .empty }
        defer { sqlite3_close(db) }
        var runs: [ScrapeHealth.Run] = []
        query(db, "SELECT started_at, finished_at, attempted, saved, authenticated, error_kind, error_message "
              + "FROM scrape_runs ORDER BY started_at DESC, id DESC") { s in
            runs.append(ScrapeHealth.Run(
                startedAt: column(s, 0) ?? "",
                finishedAt: column(s, 1) ?? "",
                attempted: Int(sqlite3_column_int(s, 2)),
                saved: Int(sqlite3_column_int(s, 3)),
                authenticated: sqlite3_column_type(s, 4) == SQLITE_NULL ? nil : Int(sqlite3_column_int(s, 4)),
                errorKind: column(s, 5),
                errorMessage: column(s, 6)))
        }
        return ScrapeHealth.summarize(runs)
    }

    /// Every date this course has ever been scraped for, oldest first -- mirrors
    /// `storage.distinct_scraped_dates()` exactly. The heatmap (see Analytics.swift)
    /// needs the *whole* history, unlike `days()` below, which only ever loads a
    /// bounded window for the day list.
    static func distinctScrapedDates(dbPath: String, course: String) -> [String] {
        guard let db = openDB(dbPath) else { return [] }
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
        guard let db = openDB(dbPath) else { return nil }
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
              "SELECT time, booked, capacity, block_reason, players FROM slots WHERE scrape_id = \(scrapeID) ORDER BY time") { s in
            slots.append(Slot(time: column(s, 0) ?? "", booked: Int(sqlite3_column_int(s, 1)),
                               capacity: Int(sqlite3_column_int(s, 2)), blockReason: column(s, 3),
                               players: decodeStringArray(column(s, 4))))
        }
        var events: [String] = []
        if let json = eventsJSON, let data = json.data(using: .utf8),
           let parsed = try? JSONDecoder().decode([String].self, from: data) {
            events = parsed
        }
        return (slots, CalendarContext.isTournamentDay(events: events, slots: slots))
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
        guard let db = openDB(dbPath) else { return [] }
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
        let today = ISODate.today()
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

    /// The scraped days in the calendar window [today, today + `days`) -- the same
    /// dates `OverviewScreen._local_dates()` lists (`overview_days`, default 5; see
    /// `ClubDefaults.overviewDays()`). A calendar window, not "the next N scraped
    /// dates": a date with no scrape used to pull in one past the window that
    /// picks_cli was never asked about.
    static func days(dbPath: String, course: String, from today: String,
                     days: Int = ClubDefaults.defaultOverviewDays) -> [Day] {
        guard let db = openDB(dbPath) else { return [] }
        defer { sqlite3_close(db) }

        let end = ISODate.adding(days: max(days, 0), to: today) ?? today
        var dates: [String] = []
        query(db,
              "SELECT DISTINCT date FROM scrapes WHERE course = ? AND date >= ? AND date < ? ORDER BY date",
              [course, today, end]) { s in
            if let d = column(s, 0) { dates.append(d) }
        }

        return dates.compactMap { date -> Day? in
            var scrapeID: Int64 = -1
            var sunrise: String?, sunset: String?, eventsJSON: String?
            query(db,
                  "SELECT id, sunrise, sunset, events FROM scrapes WHERE course = ? AND date = ? ORDER BY id DESC LIMIT 1",
                  [course, date]) { s in
                scrapeID = sqlite3_column_int64(s, 0)
                (sunrise, sunset) = sunTimes(column(s, 1), column(s, 2))
                eventsJSON = column(s, 3)
            }
            guard scrapeID >= 0 else { return nil }

            var slots: [Slot] = []
            query(db,
                  "SELECT time, booked, capacity, block_reason, players FROM slots WHERE scrape_id = \(scrapeID) ORDER BY time") { s in
                slots.append(Slot(time: column(s, 0) ?? "",
                                  booked: Int(sqlite3_column_int(s, 1)),
                                  capacity: Int(sqlite3_column_int(s, 2)),
                                  blockReason: column(s, 3),
                                  players: decodeStringArray(column(s, 4))))
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
                    if sunrise == nil { (sunrise, sunset) = sunTimes(column(s, 1), column(s, 2)) }
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


/// A club's `default_course` in `clubs/<slug>.yaml` -- the same key the TUI's club
/// settings and course picker use. Edited as plain text on purpose: club files carry
/// lists (vacation ranges) that this app's small YAML codec can't round-trip, so only
/// the one `default_course:` line is ever read or rewritten.
enum ClubDefaults {
    static func defaultCourse(slug: String) -> String? {
        guard let text = try? String(contentsOfFile: Store.clubYAMLPath(slug: slug), encoding: .utf8) else { return nil }
        return parseDefaultCourse(in: text)
    }

    /// `OverviewScreen._local_dates()`'s own `config.get("overview_days", 5)`.
    static let defaultOverviewDays = 5

    /// How many calendar days the overview, picks and search cover -- the club's
    /// `overview_days`, with `preferences.yaml` winning the same way
    /// `_resolved_config()`'s `{**club_settings, **global}` merge lets it. A
    /// browsed (unsaved) club has no YAML of its own, so `slug` is optional.
    static func overviewDays(slug: String?) -> Int {
        func read(_ path: String) -> Int? {
            guard let text = try? String(contentsOfFile: path, encoding: .utf8) else { return nil }
            return parseOverviewDays(in: text)
        }
        let days = read(Preferences.path()) ?? slug.flatMap { read(Store.clubYAMLPath(slug: $0)) }
        return days.map { max($0, 1) } ?? defaultOverviewDays
    }

    /// The top-level `overview_days:` line, read as plain text for the same reason
    /// `default_course:` is (club files carry lists `YAML.parse` doesn't model).
    static func parseOverviewDays(in text: String) -> Int? {
        for line in text.split(separator: "\n", omittingEmptySubsequences: false) where line.hasPrefix("overview_days:") {
            var value = line.dropFirst("overview_days:".count)
            if let hash = value.firstIndex(of: "#") { value = value[..<hash] }
            return Int(value.trimmingCharacters(in: .whitespaces))
        }
        return nil
    }

    static func setDefaultCourse(slug: String, course: String) {
        let path = Store.clubYAMLPath(slug: slug)
        guard let text = try? String(contentsOfFile: path, encoding: .utf8) else { return }
        try? replacingDefaultCourse(course, in: text).write(toFile: path, atomically: true, encoding: .utf8)
    }

    static func parseDefaultCourse(in text: String) -> String? {
        for line in text.split(separator: "\n", omittingEmptySubsequences: false) where line.hasPrefix("default_course:") {
            let value = YAML.scalarText(String(line.dropFirst("default_course:".count)))
            return value.isEmpty ? nil : value
        }
        return nil
    }

    /// `text` with its `default_course:` line set to `course` (quoted), or the line
    /// appended when the file has none. Every other line is left byte-for-byte alone.
    static func replacingDefaultCourse(_ course: String, in text: String) -> String {
        let newLine = "default_course: '" + course.replacingOccurrences(of: "'", with: "''") + "'"
        var lines = text.components(separatedBy: "\n")
        if let i = lines.firstIndex(where: { $0.hasPrefix("default_course:") }) {
            lines[i] = newLine
            return lines.joined(separator: "\n")
        }
        let body = text.hasSuffix("\n") || text.isEmpty ? text : text + "\n"
        return body + newLine + "\n"
    }

    // MARK: course_holes (2026-10-05)

    /// The club's `course_holes:` mapping (course label -> hole count), for courses whose
    /// name doesn't say how many holes they have ("Kurzplatz": 9). Read and written as
    /// plain text like the keys above, and for a stronger reason: it is a *mapping*, which
    /// `YAML.parse` doesn't round-trip either. In file order (first match wins when two
    /// labels collide, like Python); empty for a missing file or key.
    static func courseHoles(slug: String?) -> [(String, Int)] {
        guard let slug, let text = try? String(contentsOfFile: Store.clubYAMLPath(slug: slug), encoding: .utf8)
        else { return [] }
        return parseCourseHoles(in: text)
    }

    static func setCourseHoles(slug: String, course: String, holes: Int?) {
        let path = Store.clubYAMLPath(slug: slug)
        guard let text = try? String(contentsOfFile: path, encoding: .utf8) else { return }
        try? replacingCourseHoles(course, holes: holes, in: text).write(toFile: path, atomically: true, encoding: .utf8)
    }

    /// Case-insensitive, whitespace-trimmed label comparison -- `holes_for_course()`'s rule.
    static func normalizedCourseKey(_ label: String) -> String {
        label.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    /// The top-level `course_holes:` entries in file order, from either YAML form the
    /// block can take (PyYAML and this app write the indented block; a hand-edited file
    /// may use `{"Kurzplatz": 9}`). Entries that aren't `label: positive int` are skipped.
    static func parseCourseHoles(in text: String) -> [(String, Int)] {
        guard let block = courseHolesBlock(in: text.components(separatedBy: "\n")) else { return [] }
        return block.entries
    }

    /// `text` with `course`'s entry in `course_holes:` set to `holes`, or removed when
    /// `holes` is nil (the whole key goes when that was the last one -- "Auto" leaves no
    /// trace). The block is rewritten in the indented form; every line outside it
    /// (vacation-range lists, comments, other keys) is left byte-for-byte alone. An
    /// existing entry for the same label (any case) is replaced in place.
    static func replacingCourseHoles(_ course: String, holes: Int?, in text: String) -> String {
        var lines = text.components(separatedBy: "\n")
        let existing = courseHolesBlock(in: lines)
        var entries = existing?.entries ?? []
        let wanted = normalizedCourseKey(course)
        if let i = entries.firstIndex(where: { normalizedCourseKey($0.0) == wanted }) {
            if let holes, holes > 0 { entries[i] = (course, holes) } else { entries.remove(at: i) }
        } else if let holes, holes > 0 {
            entries.append((course, holes))
        }
        let newLines = entries.isEmpty ? [] : ["course_holes:"] + entries.map { label, holes in
            "  '" + label.replacingOccurrences(of: "'", with: "''") + "': \(holes)"
        }
        if let existing {
            // A CRLF file keeps its endings on the lines this rewrites too.
            let eol = lines[existing.range.lowerBound].hasSuffix("\r") ? "\r" : ""
            lines.replaceSubrange(existing.range, with: newLines.map { $0 + eol })
            return lines.joined(separator: "\n")
        }
        if newLines.isEmpty { return text }
        let body = text.hasSuffix("\n") || text.isEmpty ? text : text + "\n"
        return body + newLines.joined(separator: "\n") + "\n"
    }

    /// Where the `course_holes:` key sits (its line plus the indented lines under it, or
    /// the lines of a flow `{...}` mapping) and what it holds. nil when the key is absent.
    private static func courseHolesBlock(in rawLines: [String]) -> (range: Range<Int>, entries: [(String, Int)])? {
        // CRLF files: a trailing "\r" is invisible to YAML, so it must be to the parse too
        // (the rewrite only replaces whole lines, so the other lines keep their endings).
        let lines = rawLines.map { $0.hasSuffix("\r") ? String($0.dropLast()) : $0 }
        guard let start = lines.firstIndex(where: { $0.hasPrefix("course_holes:") }) else { return nil }
        let rest = stripYAMLComment(String(lines[start].dropFirst("course_holes:".count)))
            .trimmingCharacters(in: .whitespaces)
        var end = start + 1
        var entries: [(String, Int)] = []
        if rest.hasPrefix("{") {
            var flow = rest
            while !flow.contains("}"), end < lines.count {
                flow += " " + stripYAMLComment(lines[end]).trimmingCharacters(in: .whitespaces)
                end += 1
            }
            if let close = flow.lastIndex(of: "}") {
                let inner = String(flow[flow.index(after: flow.startIndex)..<close])
                for piece in splitOutsideQuotes(inner, on: ",") {
                    if let entry = courseHolesEntry(piece) { entries.append(entry) }
                }
            }
        } else {
            // Blank and column-0 comment lines don't end a YAML block while an indented
            // line still follows them (hand edits; PyYAML accepts them), so they belong to
            // the replaced range -- otherwise the later entries would be orphaned.
            var scan = end
            while scan < lines.count {
                let line = lines[scan]
                if let first = line.first, first == " " || first == "\t" {
                    if !line.trimmingCharacters(in: .whitespaces).isEmpty {
                        if let entry = courseHolesEntry(line) { entries.append(entry) }
                        end = scan + 1
                    }
                } else if !(line.isEmpty || line.hasPrefix("#")) {
                    break
                }
                scan += 1
            }
        }
        return (start..<end, entries)
    }

    /// One `label: 9` pair (quoted or bare label), nil unless the value is a positive int.
    private static func courseHolesEntry(_ raw: String) -> (String, Int)? {
        let text = stripYAMLComment(raw).trimmingCharacters(in: .whitespaces)
        guard let first = text.first else { return nil }
        var label: String
        var rest: Substring
        if first == "'" || first == "\"" {
            var i = text.index(after: text.startIndex)
            var closed: String.Index?
            while i < text.endIndex {
                let ch = text[i]
                if first == "\"", ch == "\\" {
                    i = text.index(i, offsetBy: 2, limitedBy: text.endIndex) ?? text.endIndex
                    continue
                }
                if ch == first {
                    let next = text.index(after: i)
                    if first == "'", next < text.endIndex, text[next] == "'" { i = text.index(after: next); continue }
                    closed = i
                    break
                }
                i = text.index(after: i)
            }
            guard let closed else { return nil }
            label = YAML.scalarText(String(text[text.startIndex...closed]))
            rest = text[text.index(after: closed)...]
        } else {
            guard let colon = text.range(of: ": ")?.lowerBound ?? (text.hasSuffix(":") ? text.index(before: text.endIndex) : nil)
            else { return nil }
            label = text[text.startIndex..<colon].trimmingCharacters(in: .whitespaces)
            rest = text[colon...]
        }
        rest = rest.drop(while: { $0 == " " })
        guard rest.first == ":" else { return nil }
        guard let holes = Int(rest.dropFirst().trimmingCharacters(in: .whitespaces)), holes > 0,
              !label.isEmpty else { return nil }
        return (label, holes)
    }

    /// `text` up to a ` #` comment, ignoring `#` inside quotes.
    private static func stripYAMLComment(_ text: String) -> String {
        var quote: Character?
        var previous: Character = " "
        for i in text.indices {
            let ch = text[i]
            if let q = quote {
                if ch == q { quote = nil }
            } else if ch == "'" || ch == "\"" {
                quote = ch
            } else if ch == "#", previous == " " || previous == "\t" {
                return String(text[..<i])
            }
            previous = ch
        }
        return text
    }

    private static func splitOutsideQuotes(_ text: String, on separator: Character) -> [String] {
        var parts: [String] = []
        var current = ""
        var quote: Character?
        for ch in text {
            if let q = quote {
                if ch == q { quote = nil }
            } else if ch == "'" || ch == "\"" {
                quote = ch
            } else if ch == separator {
                parts.append(current)
                current = ""
                continue
            }
            current.append(ch)
        }
        parts.append(current)
        return parts
    }
}
