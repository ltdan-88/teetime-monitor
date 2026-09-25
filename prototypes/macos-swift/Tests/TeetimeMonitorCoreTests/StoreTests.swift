import Foundation
import SQLite3
@testable import TeetimeMonitorCore

func runStoreTests() {
    Harness.group("Store") {
        testDistinctScrapedDatesOrdersOldestFirst()
        testOccupancySampleReadsLatestScrape()
        testOccupancySampleTournamentFlag()
        testConfirmAndCancelBookingAreAppendOnly()
        testBannersAcknowledge()
        testDbPathMirrorsTheFixedClubIDNamingConvention()
        testDbPathHonorsDataDirEnvOverride()
    }
}

/// `dbPath(clubID:)` -- added for `OverviewModel.startPreview()`, which needs the
/// exact same `<dataDir>/<clubID>.db` path `clubs()` already derives per favorited
/// club, but for a club with no clubs/*.yaml to derive it from.
private func testDbPathMirrorsTheFixedClubIDNamingConvention() {
    let path = Store.dbPath(clubID: "0000001")
    Harness.check("ends with the fixed <club_id>.db naming convention",
                   path.hasSuffix("/0000001.db"))
    Harness.check("lives under .local/share/teetime-monitor by default",
                   path.contains(".local/share/teetime-monitor/0000001.db"))
}

private func testDbPathHonorsDataDirEnvOverride() {
    setenv("TEETIME_MONITOR_DATA_DIR", "/tmp/tt-preview-test", 1)
    defer { unsetenv("TEETIME_MONITOR_DATA_DIR") }
    Harness.checkEqual("honors TEETIME_MONITOR_DATA_DIR, same as clubs()/cachePath()",
                        Store.dbPath(clubID: "0000001"), "/tmp/tt-preview-test/0000001.db")
}

/// A hand-written schema matching `storage.SCHEMA` in `src/storage.py` exactly --
/// this test suite has no Python to shell out to `storage.init_db()` with, so the
/// schema is reproduced by hand and has to be kept in sync if that one changes.
func makeTestDB(_ path: String) {
    var db: OpaquePointer?
    sqlite3_open(path, &db)
    let schema = """
    CREATE TABLE scrapes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course TEXT NOT NULL,
        date TEXT NOT NULL,
        scraped_at TEXT NOT NULL,
        sunrise TEXT,
        sunset TEXT,
        events TEXT
    );
    CREATE TABLE slots (
        scrape_id INTEGER NOT NULL REFERENCES scrapes(id),
        time TEXT NOT NULL,
        booked INTEGER NOT NULL,
        capacity INTEGER NOT NULL,
        players TEXT NOT NULL,
        block_reason TEXT
    );
    CREATE TABLE weather_points (
        scrape_id INTEGER NOT NULL REFERENCES scrapes(id),
        time TEXT NOT NULL,
        precipitation_probability REAL,
        precipitation_mm REAL,
        wind_speed_kph REAL,
        temperature_c REAL,
        weather_code INTEGER
    );
    CREATE TABLE confirmed_bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course TEXT NOT NULL,
        date TEXT NOT NULL,
        time TEXT,
        holes INTEGER,
        source TEXT NOT NULL,
        confirmed_at TEXT NOT NULL
    );
    CREATE TABLE booking_changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course TEXT NOT NULL,
        date TEXT NOT NULL,
        time TEXT,
        kind TEXT NOT NULL,
        message TEXT NOT NULL,
        params TEXT NOT NULL DEFAULT '{}',
        detected_at TEXT NOT NULL,
        acknowledged INTEGER NOT NULL DEFAULT 0
    );
    """
    sqlite3_exec(db, schema, nil, nil, nil)
    sqlite3_close(db)
}

func exec(_ path: String, _ sql: String) {
    var db: OpaquePointer?
    sqlite3_open(path, &db)
    var errmsg: UnsafeMutablePointer<Int8>?
    if sqlite3_exec(db, sql, nil, nil, &errmsg) != SQLITE_OK {
        print("SQL error: \(String(cString: errmsg!))\n  \(sql)")
    }
    sqlite3_close(db)
}

private func testDistinctScrapedDatesOrdersOldestFirst() {
    let dir = TempDir()
    let db = dir.file("club.db")
    makeTestDB(db)
    exec(db, """
        INSERT INTO scrapes (course, date, scraped_at) VALUES
            ('18 Loch', '2026-09-20', '2026-09-19T10:00:00'),
            ('18 Loch', '2026-09-18', '2026-09-17T10:00:00'),
            ('18 Loch', '2026-09-19', '2026-09-18T10:00:00'),
            ('9 Loch', '2026-09-25', '2026-09-24T10:00:00');
        """)
    let dates = Store.distinctScrapedDates(dbPath: db, course: "18 Loch")
    Harness.checkEqual("only this course's dates, oldest first", dates, ["2026-09-18", "2026-09-19", "2026-09-20"])
}

private func testOccupancySampleReadsLatestScrape() {
    let dir = TempDir()
    let db = dir.file("club.db")
    makeTestDB(db)
    exec(db, """
        INSERT INTO scrapes (id, course, date, scraped_at, events) VALUES
            (1, '18 Loch', '2026-09-20', '2026-09-19T08:00:00', '[]'),
            (2, '18 Loch', '2026-09-20', '2026-09-19T14:00:00', '[]');
        INSERT INTO slots (scrape_id, time, booked, capacity, players, block_reason) VALUES
            (1, '09:00', 1, 4, '[]', NULL),
            (2, '09:00', 3, 4, '[]', NULL);
        """)
    let sample = Store.occupancySample(dbPath: db, course: "18 Loch", date: "2026-09-20")
    Harness.check("sample exists", sample != nil)
    Harness.checkEqual("reads the newer scrape's occupancy, not the older one",
                        sample?.slots.first?.booked, 3)
    Harness.checkEqual("no tournament by default", sample?.hasTournament, false)
}

private func testOccupancySampleTournamentFlag() {
    let dir = TempDir()
    let db = dir.file("club.db")
    makeTestDB(db)
    exec(db, """
        INSERT INTO scrapes (id, course, date, scraped_at, events) VALUES
            (1, '18 Loch', '2026-09-20', '2026-09-19T08:00:00', '["Club Championship"]');
        INSERT INTO slots (scrape_id, time, booked, capacity, players, block_reason) VALUES
            (1, '09:00', 4, 4, '[]', NULL);
        """)
    let sample = Store.occupancySample(dbPath: db, course: "18 Loch", date: "2026-09-20")
    // Mirrors analytics._crowd_buckets()'s own has_tournament=bool(schedule.events):
    // a non-empty events list means yes, regardless of what it actually says.
    Harness.checkEqual("a non-empty events list means hasTournament", sample?.hasTournament, true)

    Harness.check("missing date returns nil, not a crash",
                   Store.occupancySample(dbPath: db, course: "18 Loch", date: "2099-01-01") == nil)
}

/// Mirrors storage.py's own append-only rule: confirming, then cancelling, adds a
/// second row rather than mutating the first -- the latest row wins for display,
/// but the history stays intact for analytics.
private func testConfirmAndCancelBookingAreAppendOnly() {
    let dir = TempDir()
    let db = dir.file("club.db")
    makeTestDB(db)
    exec(db, "INSERT INTO scrapes (id, course, date, scraped_at) VALUES (1, '18 Loch', '2026-09-20', '2026-09-19T08:00:00');")
    exec(db, "INSERT INTO slots (scrape_id, time, booked, capacity, players) VALUES (1, '10:30', 1, 4, '[]');")

    Store.confirmBooking(dbPath: db, course: "18 Loch", date: "2026-09-20", time: "10:30")
    let day1 = Store.days(dbPath: db, course: "18 Loch", from: "2026-09-20", limit: 1).first
    Harness.checkEqual("confirming sets bookedTime", day1?.bookedTime, "10:30")

    Store.cancelBooking(dbPath: db, course: "18 Loch", date: "2026-09-20")
    let day2 = Store.days(dbPath: db, course: "18 Loch", from: "2026-09-20", limit: 1).first
    Harness.check("cancelling clears bookedTime for display", day2?.bookedTime == nil)

    var count: Int32 = 0
    var stmt: OpaquePointer?
    var conn: OpaquePointer?
    sqlite3_open(db, &conn)
    sqlite3_prepare_v2(conn, "SELECT COUNT(*) FROM confirmed_bookings", -1, &stmt, nil)
    if sqlite3_step(stmt) == SQLITE_ROW { count = sqlite3_column_int(stmt, 0) }
    sqlite3_finalize(stmt); sqlite3_close(conn)
    Harness.checkEqual("both the confirm and the cancel are separate rows, not one mutated row", count, 2)
}

private func testBannersAcknowledge() {
    let dir = TempDir()
    let db = dir.file("club.db")
    makeTestDB(db)
    exec(db, """
        INSERT INTO booking_changes (id, course, date, time, kind, message, detected_at, acknowledged) VALUES
            (1, '18 Loch', '2026-09-20', '10:30', 'friend_joined', 'A friend joined', '2026-09-19T09:00:00', 0),
            (2, '18 Loch', '2026-09-21', NULL, 'sync_failed', 'Sync failed', '2026-09-19T09:00:00', 1);
        """)
    let unacked = Store.banners(dbPath: db)
    Harness.checkEqual("only unacknowledged banners are returned", unacked.count, 1)
    Harness.checkEqual("the right one", unacked.first?.id, 1)

    Store.acknowledgeBanners(dbPath: db, ids: [1])
    Harness.check("acknowledged banner no longer returned", Store.banners(dbPath: db).isEmpty)
}
