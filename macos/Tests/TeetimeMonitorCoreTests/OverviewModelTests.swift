import Foundation
@testable import TeetimeMonitorCore

/// Review fixes in OverviewModel and the overview's small pure helpers -- each test
/// pins the decision itself, no subprocess or live database needed.
func runOverviewModelTests() {
    Harness.group("OverviewModel") {
        testRepicksWhenTheShownClubWasRemoved()
        testClearClubStateBlanksEveryPerClubField()
        testFreshnessThresholdFollowsScrapeInterval()
        testShorterRoundClickSwitchesCourseThenJumps()
    }
    Harness.group("Overview helpers") {
        testBannerCaptionNamesTheDay()
        testUnknownConditionCodeDrawsNothing()
        testHeatmapHolidayYearsSpanTheHistory()
    }
}

/// Removing the club on screen in Settings left the overview bound to its DB.
private func testRepicksWhenTheShownClubWasRemoved() {
    Harness.check("nothing chosen yet -> pick one",
                  OverviewModel.needsClubRepick(clubPath: "", clubs: ["/a.db"], isPreviewing: false))
    Harness.check("shown club removed -> pick another",
                  OverviewModel.needsClubRepick(clubPath: "/gone.db", clubs: ["/a.db"], isPreviewing: false))
    Harness.check("shown club still saved -> keep it",
                  !OverviewModel.needsClubRepick(clubPath: "/a.db", clubs: ["/a.db"], isPreviewing: false))
    Harness.check("a preview is never in the saved list -> keep it",
                  !OverviewModel.needsClubRepick(clubPath: "/preview.db", clubs: ["/a.db"], isPreviewing: true))
}

/// Switching to a never-scraped club kept the previous club's banners, hint and
/// "updated N min ago" on screen.
private func testClearClubStateBlanksEveryPerClubField() {
    let model = OverviewModel()
    model.windowHint = WindowHint(windowAfter: "17:00", latestStart: "15:30", sunset: "19:30", roundMinutes: 240)
    model.verdicts = ["2026-10-04": DayVerdict(windowAfter: "17:00", windowBefore: nil, unplayable: ["daylight"])]
    model.alternatives = ["2026-10-04": ShorterRound(course: "9 Loch", time: "16:10", holes: 9)]
    model.lastScrape = Date()
    model.banners = [Banner(id: 1, course: "18 Loch", date: "2026-10-04", time: "14:20",
                            kind: "weather_worsened", paramsJSON: "{}", message: "x")]
    model.picksRequestKey = ("/a.db", "18 Loch")
    let generation = model.picksGeneration
    model.clubPath = "/b.db"; model.course = ""
    model.reload()
    Harness.check("hint cleared", model.windowHint == nil)
    Harness.check("verdicts cleared", model.verdicts.isEmpty)
    Harness.check("shorter-round alternatives cleared", model.alternatives.isEmpty)
    Harness.check("banners cleared", model.banners.isEmpty)
    Harness.check("last scrape cleared", model.lastScrape == nil)
    Harness.check("picks request key cleared", model.picksRequestKey == nil)
    Harness.check("an in-flight picks result for the old club is invalidated",
                  model.picksGeneration > generation)
}

/// A 45-minute constant turned the dot amber for most of a healthy 6 h cadence.
private func testFreshnessThresholdFollowsScrapeInterval() {
    Harness.checkEqual("default 360 min, no booking: 7 h 45 min",
                       OverviewModel.freshnessThreshold(intervalMinutes: 360, bookedIntervalMinutes: 60, anyBooked: false),
                       (360 * 1.25 + 15) * 60)
    Harness.checkEqual("a booked day uses the shorter booked interval",
                       OverviewModel.freshnessThreshold(intervalMinutes: 360, bookedIntervalMinutes: 60, anyBooked: true),
                       (60 * 1.25 + 15) * 60)
    let model = OverviewModel()
    model.lastScrape = Date().addingTimeInterval(-2 * 3600)
    Harness.check("2 h after a scrape on the default cadence is still fresh (green)",
                  model.freshnessColor(now: Date()) == .green)
}

/// The TUI prefixes each banner with its weekday + date; the GUI named only the time.
private func testBannerCaptionNamesTheDay() {
    let banner = Banner(id: 1, course: "18 Loch", date: "2026-10-04", time: "14:20",
                        kind: "weather_worsened", paramsJSON: "{}", message: "x")
    let caption = bannerCaption(banner)
    Harness.check("caption starts with the weekday label", caption.hasPrefix(weekday("2026-10-04")))
    Harness.check("caption still names the course", caption.hasSuffix("18 Loch"))
    let clubWide = Banner(id: 2, course: "", date: "2026-10-04", time: nil,
                          kind: "reservations_sync_failed", paramsJSON: "{}", message: "x")
    Harness.checkEqual("a club-wide notice shows just the day", bannerCaption(clubWide), weekday("2026-10-04"))
}

/// tui._condition_cell() leaves the cell blank with no forecast; the GUI drew "?".
private func testUnknownConditionCodeDrawsNothing() {
    Harness.check("no code -> no icon", knownConditionIcon(nil) == nil)
    Harness.check("unrecognised code -> no icon", knownConditionIcon(42) == nil)
    Harness.checkEqual("known code keeps its icon", knownConditionIcon(0), "sun.max.fill")
}

/// Holidays were fetched for the current year only, so last December's history
/// counted as ordinary weekdays.
private func testHeatmapHolidayYearsSpanTheHistory() {
    Harness.checkEqual("every year from oldest to newest scraped date",
                       heatmapHolidayYears(dates: ["2025-12-25", "2026-01-02", "2027-01-05"], currentYear: 2027),
                       [2025, 2026, 2027])
    Harness.checkEqual("no history -> the current year",
                       heatmapHolidayYears(dates: [], currentYear: 2026), [2026])
}

/// Clicking a shorter-round badge (2026-10-05): the course switches (collapsing
/// every day, like a manual switch), and the jump waits until that course's days
/// are loaded -- `applyPendingJump()`, which `reload()` calls once they are.
private func testShorterRoundClickSwitchesCourseThenJumps() {
    let model = OverviewModel()
    model.courses = ["18 Loch Tee 1", "9 Loch Tee 1"]
    model.course = "18 Loch Tee 1"
    model.expanded = ["2026-10-05"]
    let alternative = ShorterRound(course: "9 Loch Tee 1", time: "16:10", holes: 9)
    model.jumpToShorterRound(on: "2026-10-05", alternative)
    Harness.check("switches the course", model.course == "9 Loch Tee 1")
    Harness.check("collapses every day", model.expanded.isEmpty)
    Harness.check("no jump before the new course's days load", model.scrollRequest == nil)
    model.applyPendingJump()
    Harness.check("jumps to the slot once loaded",
                  model.scrollRequest == OverviewModel.ScrollTarget(date: "2026-10-05", time: "16:10"))
    Harness.check("only once", model.pendingJump == nil)

    model.scrollRequest = nil
    model.course = "18 Loch Tee 1"
    model.jumpToShorterRound(on: "2026-10-05", alternative)
    model.course = "18 Loch Tee 1"  // switched straight back before the load landed
    model.applyPendingJump()
    Harness.check("a stale jump is dropped", model.scrollRequest == nil && model.pendingJump == nil)

    model.course = "18 Loch Tee 1"
    model.jumpToShorterRound(on: "2026-10-05", ShorterRound(course: "Gone", time: "16:10", holes: 9))
    Harness.check("an unknown course does nothing", model.course == "18 Loch Tee 1" && model.pendingJump == nil)
}
