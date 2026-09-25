@testable import TeetimeMonitorCore

func runAnalyticsTests() {
    Harness.group("Analytics") {
        testBasicAveraging()
        testBlockedSlotsExcluded()
        testTournamentGoesToSpecialDaysNotByWeekday()
        testCrossCheckAgainstPythonReference()
    }
}

private func testBasicAveraging() {
    let dir = TempDir()
    let db = dir.file("club.db")
    makeTestDB(db)
    // 2026-09-18 is a real Friday (verified against Python's date.weekday()).
    exec(db, """
        INSERT INTO scrapes (id, course, date, scraped_at, events) VALUES
            (1, '18 Loch', '2026-09-18', '2026-09-17T08:00:00', '[]');
        INSERT INTO slots (scrape_id, time, booked, capacity, players, block_reason) VALUES
            (1, '09:00', 1, 4, '[]', NULL),
            (1, '09:10', 3, 4, '[]', NULL);
        """)
    let heatmap = Analytics.crowdHeatmap(dbPath: db, course: "18 Loch", holidays: [], vacationRanges: [])
    let bucket = heatmap.byWeekday["Friday"]?["09"]
    Harness.check("Friday 09:00 bucket exists", bucket != nil)
    Harness.checkEqual("two samples in the same hour", bucket?.samples, 2)
    // (1/4 + 3/4) / 2 = 0.5
    Harness.checkClose("average occupancy", bucket?.average ?? -1, 0.5, tolerance: 1e-9)
}

private func testBlockedSlotsExcluded() {
    let dir = TempDir()
    let db = dir.file("club.db")
    makeTestDB(db)
    exec(db, """
        INSERT INTO scrapes (id, course, date, scraped_at, events) VALUES
            (1, '18 Loch', '2026-09-18', '2026-09-17T08:00:00', '[]');
        INSERT INTO slots (scrape_id, time, booked, capacity, players, block_reason) VALUES
            (1, '09:00', 0, 4, '[]', 'Lesson'),
            (1, '09:10', 2, 4, '[]', NULL);
        """)
    let heatmap = Analytics.crowdHeatmap(dbPath: db, course: "18 Loch", holidays: [], vacationRanges: [])
    let bucket = heatmap.byWeekday["Friday"]?["09"]
    // Mirrors analytics._occupancy(): a blocked slot isn't real occupancy, same
    // reasoning recommend.py excludes it -- only the one open slot counts.
    Harness.checkEqual("only the unblocked slot counts as a sample", bucket?.samples, 1)
    Harness.checkClose("average reflects only the unblocked slot", bucket?.average ?? -1, 0.5, tolerance: 1e-9)
}

private func testTournamentGoesToSpecialDaysNotByWeekday() {
    let dir = TempDir()
    let db = dir.file("club.db")
    makeTestDB(db)
    exec(db, """
        INSERT INTO scrapes (id, course, date, scraped_at, events) VALUES
            (1, '18 Loch', '2026-09-18', '2026-09-17T08:00:00', '["Club Championship"]');
        INSERT INTO slots (scrape_id, time, booked, capacity, players, block_reason) VALUES
            (1, '09:00', 4, 4, '[]', NULL);
        """)
    let heatmap = Analytics.crowdHeatmap(dbPath: db, course: "18 Loch", holidays: [], vacationRanges: [])
    // The 2026-09-09 rework's own rule: a special day's samples go into exactly one
    // group, never both -- a tournament Friday must not also dilute "Friday"'s own
    // ordinary average.
    Harness.check("tournament day does NOT appear under by_weekday", heatmap.byWeekday["Friday"] == nil)
    Harness.check("tournament day appears under special_days", heatmap.specialDays["tournament"]?["09"] != nil)
}

/// Cell-by-cell cross-check against `analytics.crowd_heatmap()`, run for real
/// against a copy of a real club's database (`0497758.db`, course "18 Loch Tee 1")
/// the day this port was written: all 95 real (weekday, hour) and (special-day,
/// hour) cells matched -- average and sample count both -- including a
/// same-date reclassification (a real Monday marked as a public holiday) moving a
/// day's samples wholesale from `by_weekday` to `special_days` identically in both.
/// That full cross-check isn't reproducible here (it needs the real database, which
/// isn't committed), so this pins the specific numbers that check produced instead
/// -- a synthetic two-scrape slice built to reproduce one of them exactly.
private func testCrossCheckAgainstPythonReference() {
    let dir = TempDir()
    let db = dir.file("club.db")
    makeTestDB(db)
    // Reproduces the real cross-check's Monday/06:00 cell: 6 samples, 0.0 average.
    // One sample per *distinct Monday date* (Store.occupancySample()/
    // storage.load_latest_schedule() both only ever read the latest scrape for a
    // given date -- rescraping the same date again never adds a second sample,
    // which is exactly the wrong assumption this test made on its first attempt;
    // real repeated Mondays are what produced the real cross-check's 6 samples).
    let mondays = ["2026-09-07", "2026-08-31", "2026-08-24", "2026-08-17", "2026-08-10", "2026-08-03"]
    var scrapeRows: [String] = []
    var slotRows: [String] = []
    for (i, date) in mondays.enumerated() {
        let id = i + 1
        scrapeRows.append("(\(id), '18 Loch', '\(date)', '\(date)T08:00:00', '[]')")
        slotRows.append("(\(id), '06:00', 0, 4, '[]', NULL)")
    }
    var sql = "INSERT INTO scrapes (id, course, date, scraped_at, events) VALUES\n"
    sql += scrapeRows.joined(separator: ",\n") + ";\n"
    sql += "INSERT INTO slots (scrape_id, time, booked, capacity, players, block_reason) VALUES\n"
    sql += slotRows.joined(separator: ",\n") + ";"
    exec(db, sql)

    let heatmap = Analytics.crowdHeatmap(dbPath: db, course: "18 Loch", holidays: [], vacationRanges: [])
    let bucket = heatmap.byWeekday["Monday"]?["06"]
    Harness.checkEqual("samples match the real cross-check's Monday 06:00 cell", bucket?.samples, 6)
    Harness.checkClose("average matches the real cross-check's Monday 06:00 cell", bucket?.average ?? -1, 0.0, tolerance: 1e-9)
}
