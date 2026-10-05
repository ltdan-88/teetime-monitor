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
        testDaysIsACalendarWindow()
        testEmptySunTimesReadAsNone()
        testKnownPlayersReaders()
        testMyHandicap()
        testWritesReportFailure()
        testWriteWaitsOutABusyLock()
        testClubIDAndNameDecodeEscapes()
        testOverviewDays()
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
/// (`CrossCheckRunner`'s `store_players` group runs the same readers against a
/// database Python itself built, so a column drift fails there too.)
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
    CREATE TABLE club_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE known_players (
        name TEXT PRIMARY KEY,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        is_friend INTEGER NOT NULL DEFAULT 0,
        gender TEXT,
        member_status TEXT,
        handicap REAL
    );
    CREATE TABLE scrape_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT NOT NULL,
        finished_at TEXT NOT NULL,
        source TEXT NOT NULL,
        attempted INTEGER NOT NULL DEFAULT 0,
        saved INTEGER NOT NULL DEFAULT 0,
        failed INTEGER NOT NULL DEFAULT 0,
        authenticated INTEGER,
        error_kind TEXT,
        error_message TEXT
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
    // Mirrors calendar_context.is_tournament_day(): a competition-like event name
    // counts (a routine group/lesson name is covered in CalendarContextTests).
    Harness.checkEqual("a competition event means hasTournament", sample?.hasTournament, true)

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
    let day1 = Store.days(dbPath: db, course: "18 Loch", from: "2026-09-20", days: 1).first
    Harness.checkEqual("confirming sets bookedTime", day1?.bookedTime, "10:30")

    Store.cancelBooking(dbPath: db, course: "18 Loch", date: "2026-09-20")
    let day2 = Store.days(dbPath: db, course: "18 Loch", from: "2026-09-20", days: 1).first
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

/// [today, today + N) in calendar days, not "the next N scraped dates": a gap in the
/// scrapes must not pull in a date past the window (picks_cli never computed it).
private func testDaysIsACalendarWindow() {
    let dir = TempDir()
    let db = dir.file("club.db")
    makeTestDB(db)
    exec(db, """
        INSERT INTO scrapes (course, date, scraped_at) VALUES
            ('18 Loch', '2026-10-30', 'x'), ('18 Loch', '2026-10-31', 'x'),
            ('18 Loch', '2026-11-02', 'x'), ('18 Loch', '2026-11-03', 'x'),
            ('18 Loch', '2026-10-29', 'x');
        """)
    let dates = Store.days(dbPath: db, course: "18 Loch", from: "2026-10-30", days: 4).map(\.date)
    Harness.checkEqual("only dates inside the 4-day calendar window, across a month end",
                        dates, ["2026-10-30", "2026-10-31", "2026-11-02"])
    Harness.checkEqual("default window is overview_days' own default of 5",
                        Store.days(dbPath: db, course: "18 Loch", from: "2026-10-30").count, 4)
}

/// `weather.fetch_sun_times()` stores "" for an empty response; Python reads that
/// as no sun times, so every slot shows -- not one slot carrying both notes.
private func testEmptySunTimesReadAsNone() {
    let dir = TempDir()
    let db = dir.file("club.db")
    makeTestDB(db)
    exec(db, """
        INSERT INTO scrapes (id, course, date, scraped_at, sunrise, sunset) VALUES
            (1, '18 Loch', '2026-09-20', 'x', '', '');
        INSERT INTO slots (scrape_id, time, booked, capacity, players) VALUES
            (1, '07:00', 0, 4, '[]'), (1, '12:00', 0, 4, '[]'), (1, '18:00', 0, 4, '[]');
        """)
    let day = Store.days(dbPath: db, course: "18 Loch", from: "2026-09-20").first
    Harness.check("empty sunrise reads as nil", day?.sunrise == nil)
    Harness.check("empty sunset reads as nil", day?.sunset == nil)
    Harness.checkEqual("every slot stays visible", day?.visibleSlots.count, 3)
    Harness.check("only one of the two set also reads as none",
                   Store.sunTimes("07:10", nil) == (nil, nil) && Store.sunTimes("07:10", "") == (nil, nil))
}

private func testKnownPlayersReaders() {
    let dir = TempDir()
    let db = dir.file("club.db")
    makeTestDB(db)
    exec(db, """
        INSERT INTO known_players (name, first_seen, last_seen, is_friend, gender, member_status, handicap) VALUES
            ('Max Mustermann', 'a', '2026-09-20', 1, 'male', 'member', 12.5),
            ('Erika Beispiel', 'a', '2026-09-21', 0, 'female', 'guest', NULL),
            ('Al Unknown', 'a', '2026-09-22', 0, 'unknown', NULL, NULL);
        """)
    Harness.checkEqual("friendNames", Store.friendNames(dbPath: db), ["Max Mustermann"])
    Harness.checkEqual("playerGenders leaves out 'unknown'", Store.playerGenders(dbPath: db),
                        ["Max Mustermann": "male", "Erika Beispiel": "female"])
    let players = Store.knownPlayers(dbPath: db)
    Harness.checkEqual("knownPlayers sorted by family name", players.map(\.name),
                        ["Erika Beispiel", "Max Mustermann", "Al Unknown"])
    Harness.checkEqual("handicap read", players.first { $0.name == "Max Mustermann" }?.handicap, 12.5)
    Harness.check("missing handicap is nil", players.first { $0.name == "Erika Beispiel" }?.handicap == nil)
    Harness.checkEqual("memberStatus read", players.first?.memberStatus, "guest")

    Harness.check("setPlayerFriend reports success",
                   Store.setPlayerFriend(dbPath: db, name: "Erika Beispiel", isFriend: true))
    Harness.checkEqual("setPlayerFriend lands", Store.friendNames(dbPath: db), ["Max Mustermann", "Erika Beispiel"])
}

private func testMyHandicap() {
    let dir = TempDir()
    let db = dir.file("club.db")
    makeTestDB(db)
    Harness.check("nil before any sync", Store.myHandicap(dbPath: db) == nil)
    exec(db, "INSERT INTO club_meta (key, value) VALUES ('my_handicap', '43.8');")
    Harness.checkEqual("reads the JSON-encoded value", Store.myHandicap(dbPath: db), 43.8)
}

/// A write that didn't happen must say so -- the Search sheet used to report
/// "Booked ..." for a row that was never inserted.
private func testWritesReportFailure() {
    let dir = TempDir()
    let db = dir.file("club.db")
    makeTestDB(db)
    Harness.check("a real write reports success",
                   Store.confirmBooking(dbPath: db, course: "18 Loch", date: "2026-09-20", time: "10:30"))
    exec(db, "DROP TABLE confirmed_bookings;")
    Harness.check("a failed write reports failure",
                   !Store.confirmBooking(dbPath: db, course: "18 Loch", date: "2026-09-20", time: "10:30"))
    Harness.check("no database at all reports failure",
                   !Store.cancelBooking(dbPath: dir.file("missing/none.db"), course: "x", date: "2026-09-20"))
}

/// The scraper holds its write lock only for a few milliseconds per commit; with
/// SQLite's default busy timeout of 0 a GUI write landing inside one was dropped.
private func testWriteWaitsOutABusyLock() {
    let dir = TempDir()
    let db = dir.file("club.db")
    makeTestDB(db)
    var holder: OpaquePointer?
    sqlite3_open(db, &holder)
    sqlite3_exec(holder, "BEGIN IMMEDIATE; INSERT INTO club_meta (key, value) VALUES ('k', '1');", nil, nil, nil)
    DispatchQueue.global().asyncAfter(deadline: .now() + 0.3) {
        sqlite3_exec(holder, "COMMIT;", nil, nil, nil)
        sqlite3_close(holder)
    }
    Harness.check("a write during someone else's transaction waits and then succeeds",
                   Store.confirmBooking(dbPath: db, course: "18 Loch", date: "2026-09-20", time: "10:30"))
}

/// A club saved before `allow_unicode=True` has PyYAML escapes in it.
private func testClubIDAndNameDecodeEscapes() {
    let legacy = Store.clubIDAndName(in: """
        club_id: '0497758'
        name: "Golfclub W\\xFCrzburg Dom\\u0308ne"
        """)
    Harness.checkEqual("quoted club_id", legacy.id, "0497758")
    Harness.checkEqual("\\xXX and \\uXXXX decoded", legacy.name, "Golfclub Würzburg Dom\u{0308}ne")
    let plain = Store.clubIDAndName(in: "club_id: 0000001\nname: Golfclub 'Am See'\n")
    Harness.checkEqual("a plain value keeps its inner quotes", plain.name, "Golfclub 'Am See'")
    Harness.checkEqual("escaped default_course", ClubDefaults.parseDefaultCourse(in: "default_course: \"\\xDCbungsplatz\"\n"),
                        "Übungsplatz")
}

private func testOverviewDays() {
    Harness.checkEqual("parsed", ClubDefaults.parseOverviewDays(in: "club_id: '1'\noverview_days: 10 # two weeks\n"), 10)
    Harness.check("absent", ClubDefaults.parseOverviewDays(in: "club_id: '1'\n") == nil)
    let dir = TempDir()
    setenv("TEETIME_MONITOR_CONFIG_DIR", dir.path, 1)
    defer { unsetenv("TEETIME_MONITOR_CONFIG_DIR") }
    try? FileManager.default.createDirectory(atPath: dir.file("clubs"), withIntermediateDirectories: true)
    Harness.checkEqual("default 5 with nothing configured", ClubDefaults.overviewDays(slug: "x"), 5)
    try! "club_id: '1'\noverview_days: 8\n".write(toFile: dir.file("clubs/x.yaml"), atomically: true, encoding: .utf8)
    Harness.checkEqual("the club's own value", ClubDefaults.overviewDays(slug: "x"), 8)
    Harness.checkEqual("a browsed club gets the default", ClubDefaults.overviewDays(slug: nil), 5)
    try! "overview_days: 3\n".write(toFile: dir.file("preferences.yaml"), atomically: true, encoding: .utf8)
    Harness.checkEqual("preferences.yaml wins, as in _resolved_config()", ClubDefaults.overviewDays(slug: "x"), 3)
}
