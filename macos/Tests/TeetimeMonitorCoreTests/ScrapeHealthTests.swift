import Foundation
import SwiftUI
@testable import TeetimeMonitorCore

// Scrape health (2026-10-05): Store.scrapeHealth() over `scrape_runs`, and the footer
// warning built from it. CrossCheckRunner pins both against the Python originals
// (storage.scrape_health() / scrape_health.health_warning()); these cover the cases
// that need no Python -- an old database, the streak edges, the dot colour.

func runScrapeHealthTests() {
    Harness.group("ScrapeHealth") {
        testMissingTableReadsAsEmpty()
        testMissingFileReadsAsEmpty()
        testHealthyHistory()
        testFailureStreak()
        testLoginRejectedStreakAndUnknownOutcome()
        testLoginStreakEndsAtAGoodLogin()
        testIdlePassesDuringALoginOutage()
        testWarningThresholdsAndText()
        testStaleLastSuccess()
        testFailingOutranksLoginRejected()
        testGermanWarning()
        testFreshnessDotFollowsHealth()
    }
}

private let t0: Date = ISO8601DateFormatter().date(from: "2026-10-03T16:45:00Z")!

private func iso(_ minutes: Double) -> String {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return f.string(from: t0.addingTimeInterval(minutes * 60))
}

/// One run `minutes` after t0, a minute long -- mirrors test_storage.py's own `_run()`.
private func insertRun(_ db: String, _ minutes: Double, saved: Int = 1, attempted: Int? = nil,
                       authenticated: Int? = nil, errorKind: String? = nil, message: String? = nil) {
    func sql(_ value: String?) -> String { value.map { "'\($0)'" } ?? "NULL" }
    exec(db, """
        INSERT INTO scrape_runs (started_at, finished_at, source, attempted, saved, failed, authenticated,
                                 error_kind, error_message)
        VALUES ('\(iso(minutes))', '\(iso(minutes + 1))', 'agent', \(attempted ?? saved), \(saved),
                \(saved == 0 ? 1 : 0), \(authenticated.map(String.init) ?? "NULL"), \(sql(errorKind)), \(sql(message)));
        """)
}

private func freshDB(_ dir: TempDir) -> String {
    let db = dir.file("club.db")
    makeTestDB(db)
    return db
}

private func testMissingTableReadsAsEmpty() {
    let dir = TempDir()
    let db = freshDB(dir)
    exec(db, "DROP TABLE scrape_runs;")  // a database from before 2026-10-05
    Harness.checkEqual("no scrape_runs table -> empty health, no crash", Store.scrapeHealth(dbPath: db), .empty)
    Harness.check("empty health is never a warning",
                  ScrapeHealthRules.warning(.empty, intervalMinutes: 360, now: Date()) == nil)
}

private func testMissingFileReadsAsEmpty() {
    let dir = TempDir()
    Harness.checkEqual("no database at all -> empty health",
                       Store.scrapeHealth(dbPath: dir.file("never.db")), .empty)
}

private func testHealthyHistory() {
    let dir = TempDir()
    let db = freshDB(dir)
    insertRun(db, 0, saved: 6)
    insertRun(db, 15, saved: 0, attempted: 0)  // nothing due -- still a success
    let health = Store.scrapeHealth(dbPath: db)
    Harness.checkEqual("last run", health.lastRunAt, iso(16))
    Harness.checkEqual("a no-op run is the last success", health.lastSuccessAt, iso(16))
    Harness.checkEqual("no failures", health.consecutiveFailedRuns, 0)
    Harness.check("no streaks", health.failingSince == nil && health.loginRejectedSince == nil)
}

private func testFailureStreak() {
    let dir = TempDir()
    let db = freshDB(dir)
    insertRun(db, 0, saved: 6)
    insertRun(db, 15, saved: 0, errorKind: "network")
    insertRun(db, 30, saved: 6)
    insertRun(db, 45, saved: 0, attempted: 0, errorKind: "no_tee_sheet")
    insertRun(db, 60, saved: 0, attempted: 0, errorKind: "no_tee_sheet")
    insertRun(db, 75, saved: 0, errorKind: "network", message: "timed out")
    let health = Store.scrapeHealth(dbPath: db)
    Harness.checkEqual("only the current streak counts", health.consecutiveFailedRuns, 3)
    Harness.checkEqual("streak start", health.failingSince, iso(45))
    Harness.checkEqual("last success before it", health.lastSuccessAt, iso(31))
    Harness.checkEqual("newest error kind", health.lastErrorKind, "network")
    Harness.checkEqual("newest error message", health.lastErrorMessage, "timed out")
}

private func testLoginRejectedStreakAndUnknownOutcome() {
    let dir = TempDir()
    let db = freshDB(dir)
    insertRun(db, 0, saved: 6, authenticated: 1)
    insertRun(db, 15, saved: 6, authenticated: 0, errorKind: "login_rejected")
    insertRun(db, 30, saved: 0, authenticated: 0, errorKind: "network")  // offline blip
    insertRun(db, 45, saved: 6, authenticated: 0, errorKind: "login_rejected")
    let health = Store.scrapeHealth(dbPath: db)
    Harness.checkEqual("the streak survives a run that couldn't tell", health.loginRejectedSince, iso(15))
    Harness.checkEqual("anonymous saves still count as success", health.consecutiveFailedRuns, 0)
}

private func testLoginStreakEndsAtAGoodLogin() {
    let dir = TempDir()
    let db = freshDB(dir)
    insertRun(db, 0, saved: 6, authenticated: 0, errorKind: "login_rejected")
    insertRun(db, 15, saved: 6, authenticated: 1)
    Harness.check("a good login ends it", Store.scrapeHealth(dbPath: db).loginRejectedSince == nil)
    insertRun(db, 30, saved: 6, errorKind: nil)  // credentials removed (NULL)
    insertRun(db, 45, saved: 6, authenticated: 0, errorKind: "login_rejected")
    Harness.checkEqual("a new streak starts fresh", Store.scrapeHealth(dbPath: db).loginRejectedSince, iso(45))
}

/// 2026-10-05 review: the agent's idle passes (nothing due) during a login outage are
/// successes -- four of them used to read as "Scrapes failing" -- while a course-list
/// failure in the middle is a failure that leaves the login streak alone.
private func testIdlePassesDuringALoginOutage() {
    Harness.check("an idle pass with only a rejected login succeeded",
                  ScrapeHealth.runSucceeded(saved: 0, attempted: 0, errorKind: "login_rejected"))
    Harness.check("an idle pass with any other error did not",
                  !ScrapeHealth.runSucceeded(saved: 0, attempted: 0, errorKind: "no_tee_sheet"))
    Harness.check("a pass that tried and saved nothing did not",
                  !ScrapeHealth.runSucceeded(saved: 0, attempted: 2, errorKind: "login_rejected"))
    let dir = TempDir()
    let db = freshDB(dir)
    insertRun(db, 0, saved: 6, authenticated: 0, errorKind: "login_rejected")
    for minutes in [15.0, 30, 45, 60] {
        insertRun(db, minutes, saved: 0, attempted: 0, authenticated: 0, errorKind: "login_rejected")
    }
    var health = Store.scrapeHealth(dbPath: db)
    Harness.checkEqual("idle login-rejected passes are no failure streak", health.consecutiveFailedRuns, 0)
    Harness.checkEqual("the login streak starts at the first rejection", health.loginRejectedSince, iso(0))
    let now = t0.addingTimeInterval(62 * 60)
    Harness.checkEqual("so the amber login line shows, not the red one",
                       ScrapeHealthRules.status(health, intervalMinutes: 360, now: now)?.0, .loginRejected)
    insertRun(db, 75, saved: 0, attempted: 0, authenticated: 0, errorKind: "no_tee_sheet")
    health = Store.scrapeHealth(dbPath: db)
    Harness.checkEqual("a course-list failure is one", health.consecutiveFailedRuns, 1)
    Harness.checkEqual("and keeps the login streak", health.loginRejectedSince, iso(0))
}

private func healthy(now: Date) -> ScrapeHealth {
    let f = ISO8601DateFormatter()
    let last = f.string(from: now.addingTimeInterval(-300))
    return ScrapeHealth(lastRunAt: last, lastSuccessAt: last)
}

private func testWarningThresholdsAndText() {
    AppLanguage.shared.code = "en"
    let now = t0.addingTimeInterval(48 * 3600)
    var health = healthy(now: now)
    Harness.check("healthy -> nothing", ScrapeHealthRules.warning(health, intervalMinutes: 360, now: now) == nil)
    health.consecutiveFailedRuns = 2
    health.failingSince = iso(0)
    health.lastErrorKind = "no_tee_sheet"
    Harness.check("two failures -> still nothing", ScrapeHealthRules.warning(health, intervalMinutes: 360, now: now) == nil)
    health.consecutiveFailedRuns = 3
    health.lastErrorMessage = "Club 0497758 doesn't publish an online tee sheet"
    let warning = ScrapeHealthRules.warning(health, intervalMinutes: 360, now: now)
    Harness.checkEqual("three failures -> failing", warning?.status, .failing)
    Harness.checkEqual("text", warning?.text,
                       "⚠ Scrapes failing since \(ScrapeHealthRules.sinceText(iso(0), now: now)): pc caddie showed no tee sheet")
    Harness.check("tooltip carries the raw error", warning?.detail.hasSuffix("online tee sheet") == true)

    var login = healthy(now: now)
    login.loginRejectedSince = iso(0)
    Harness.checkEqual("login text", ScrapeHealthRules.warning(login, intervalMinutes: 360, now: now)?.text,
                       "⚠ Login rejected since \(ScrapeHealthRules.sinceText(iso(0), now: now)) — player names unavailable; check Settings → Login")
}

private func testStaleLastSuccess() {
    AppLanguage.shared.code = "en"
    let now = t0.addingTimeInterval(48 * 3600)
    let last = ISO8601DateFormatter().string(from: now.addingTimeInterval(-Double(360 * 3 + 1) * 60))
    let stale = ScrapeHealth(lastRunAt: last, lastSuccessAt: last)
    let warning = ScrapeHealthRules.warning(stale, intervalMinutes: 360, now: now)
    Harness.checkEqual("the agent stopped -> failing", warning?.status, .failing)
    Harness.check("reason: no recent scrape", warning?.text.hasSuffix(": no recent scrape") == true)
    Harness.check("a shorter interval doesn't matter inside the window",
                  ScrapeHealthRules.warning(healthy(now: now), intervalMinutes: 60, now: now) == nil)
}

private func testFailingOutranksLoginRejected() {
    let now = t0.addingTimeInterval(48 * 3600)
    var health = healthy(now: now)
    health.loginRejectedSince = iso(0)
    health.consecutiveFailedRuns = 4
    health.failingSince = iso(60)
    Harness.checkEqual("failing first", ScrapeHealthRules.status(health, intervalMinutes: 360, now: now)?.0, .failing)
}

private func testGermanWarning() {
    AppLanguage.shared.code = "de"
    defer { AppLanguage.shared.code = "en" }
    let now = t0.addingTimeInterval(3600)
    var health = healthy(now: now)
    health.loginRejectedSince = iso(0)
    let text = ScrapeHealthRules.warning(health, intervalMinutes: 360, now: now)?.text ?? ""
    Harness.check("German login text", text.hasPrefix("⚠ Login abgelehnt seit ")
                  && text.hasSuffix("— keine Spielernamen; Einstellungen → pc caddie Anmeldung prüfen"))
    let weekday = ScrapeHealthRules.sinceText(iso(0), now: now).split(separator: " ").first.map(String.init) ?? ""
    Harness.check("German weekday", ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"].contains(weekday))
    Harness.check("weekday-only within six days",
                  ScrapeHealthRules.sinceText(iso(0), now: now).split(separator: " ").count == 2)
    Harness.check("date added beyond six days",
                  ScrapeHealthRules.sinceText(iso(0), now: t0.addingTimeInterval(9 * 86400)).split(separator: " ").count == 3)
}

private func testFreshnessDotFollowsHealth() {
    let model = OverviewModel()
    let now = Date()
    model.lastScrape = now.addingTimeInterval(-600)
    model.scrapeHealth = healthy(now: now)
    Harness.check("healthy and recent -> green", model.freshnessColor(now: now) == .green)
    model.scrapeHealth.loginRejectedSince = ISO8601DateFormatter().string(from: now.addingTimeInterval(-7200))
    Harness.check("login rejected -> amber", model.freshnessColor(now: now) == .orange)
    model.scrapeHealth.consecutiveFailedRuns = 3
    model.scrapeHealth.failingSince = ISO8601DateFormatter().string(from: now.addingTimeInterval(-3600))
    Harness.check("failing -> red", model.freshnessColor(now: now) == .red)
    model.clearClubState()
    Harness.check("cleared with the club", model.scrapeHealth == .empty)
}
