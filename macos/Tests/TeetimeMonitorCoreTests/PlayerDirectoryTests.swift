import Foundation
@testable import TeetimeMonitorCore

func runPlayerDirectoryTests() {
    Harness.group("PlayerDirectory") {
        testGroupsAdjacentSameLetterNamesTogether()
        testGroupingIsCaseInsensitiveAndUsesFamilyName()
        testNonLetterFamilyNamesFallToHashBucket()
        testEmptyListGroupsToNoSections()
    }
    Harness.group("OverviewModel.reload course switch") {
        testSwitchingCourseClearsStalePicksSynchronously()
        testReloadingSameCourseKeepsExistingPicks()
    }
}

private func player(_ name: String) -> KnownPlayer {
    KnownPlayer(name: name, lastSeen: "2026-09-27T10:00:00+00:00", isFriend: false,
                gender: nil, memberStatus: nil, handicap: nil)
}

/// Direct request, 2026-09-28: "make the player directory a feature similar to
/// common contact directories (e.g. alphabet letters as separators)". Mirrors a
/// real Contacts-style index: one section per distinct family-name initial, in
/// the order the (already-sorted) input arrives in.
private func testGroupsAdjacentSameLetterNamesTogether() {
    let players = [player("Anna Bauer"), player("Max Bauer"), player("Petra Claus")]
    let groups = groupPlayersByFamilyNameLetter(players)
    Harness.checkEqual("two letter groups", groups.map(\.letter), ["B", "C"])
    Harness.checkEqual("B group keeps both Bauers in order",
                        groups[0].players.map(\.name), ["Anna Bauer", "Max Bauer"])
    Harness.checkEqual("C group has the one Claus", groups[1].players.map(\.name), ["Petra Claus"])
}

private func testGroupingIsCaseInsensitiveAndUsesFamilyName() {
    // familyName() takes the *last* whitespace token -- "von" here is a first/middle
    // token, not the family name, so this groups under "M" (Mustermann), not "V".
    let groups = groupPlayersByFamilyNameLetter([player("erika mustermann")])
    Harness.checkEqual("lowercase family name still groups under its uppercased initial",
                        groups.map(\.letter), ["M"])
}

private func testNonLetterFamilyNamesFallToHashBucket() {
    let groups = groupPlayersByFamilyNameLetter([player("Team 42")])
    Harness.checkEqual("a digit-led family name falls to the # bucket, not its own digit",
                        groups.map(\.letter), ["#"])
}

private func testEmptyListGroupsToNoSections() {
    Harness.checkEqual("no players means no groups at all", groupPlayersByFamilyNameLetter([]).count, 0)
}

/// Direct report, 2026-09-28: switching from an 18-hole course to a 9-hole one kept
/// showing the 18-hole course's own "window opens too late" hint (a real ~4h-round
/// number) attached to the 9-hole day list, for as long as the new course's own
/// picks subprocess took to return -- reload() only ever overwrote `windowHint`
/// once that async fetch actually landed, never cleared it up front. This checks
/// the synchronous portion of reload() only (no RunLoop spin, no waiting on the
/// real teetime-monitor-picks subprocess this dev machine happens to have
/// installed) -- exactly the property that was missing: switching course must
/// blank stale state immediately, not eventually.
private func testSwitchingCourseClearsStalePicksSynchronously() {
    let dir = TempDir()
    let dbPath = dir.file("club.db")
    makeTestDB(dbPath)

    let model = OverviewModel()
    model.clubPath = dbPath
    model.course = "18 Loch Tee 1"
    // Simulates a previous, already-completed fetch for the 18-hole course --
    // exactly the state a real prior reload() would have left behind.
    model.windowHint = WindowHint(windowAfter: "16:00", latestStart: "14:40", sunset: "19:10", roundMinutes: 240)
    model.picks = ["2026-09-28": DayPick(time: "16:00", score: 0, reasons: [])]
    model.verdicts = ["2026-09-28": DayVerdict(windowAfter: "16:00", windowBefore: "18:00", unplayable: [])]

    model.course = "9 Loch Tee 1"
    model.reload()

    Harness.check("windowHint cleared the instant the course changes, not left stale",
                   model.windowHint == nil)
    Harness.check("picks cleared the instant the course changes", model.picks.isEmpty)
    Harness.check("verdicts cleared the instant the course changes", model.verdicts.isEmpty)
}

/// The other half of the same fix: a routine reload() of the *same* club/course
/// (the 2-second DB-mtime watcher, or a confirm/cancel) must NOT blank `picks`/
/// `windowHint` -- that would flash the pick badges/hint to empty and back on every
/// single background refresh, a real regression clearing unconditionally would
/// have caused.
private func testReloadingSameCourseKeepsExistingPicks() {
    let dir = TempDir()
    let dbPath = dir.file("club.db")
    makeTestDB(dbPath)

    let model = OverviewModel()
    model.clubPath = dbPath
    model.course = "18 Loch Tee 1"
    // A real prior reload()'s completion handler would have set this alongside
    // the picks/hint it fetched -- seeded directly here so this test doesn't need
    // to wait on a real subprocess round trip to reach the same state.
    model.picksRequestKey = (dbPath, "18 Loch Tee 1")
    let hint = WindowHint(windowAfter: "16:00", latestStart: "14:40", sunset: "19:10", roundMinutes: 240)
    model.windowHint = hint
    model.picks = ["2026-09-28": DayPick(time: "16:00", score: 0, reasons: [])]

    model.reload()  // same club/course as already set above -- not a switch

    Harness.check("windowHint survives a same-course reload's synchronous portion",
                   model.windowHint != nil)
    Harness.check("picks survive a same-course reload's synchronous portion", !model.picks.isEmpty)
}
