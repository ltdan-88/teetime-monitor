import Foundation
@testable import TeetimeMonitorCore

func runPlayerDirectoryTests() {
    Harness.group("PlayerDirectory") {
        testGroupsAdjacentSameLetterNamesTogether()
        testGroupingIsCaseInsensitiveAndUsesFamilyName()
        testNonLetterFamilyNamesFallToHashBucket()
        testEmptyListGroupsToNoSections()
    }
    Harness.group("OverviewModel.picksRequestChanged") {
        testSwitchingCourseCountsAsChanged()
        testReloadingSameCourseDoesNotCountAsChanged()
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
/// picks subprocess took to return -- `reload()` only ever overwrote `windowHint`
/// once that async fetch actually landed, never cleared it up front.
///
/// Tests `OverviewModel.picksRequestChanged(from:to:)` directly, the pure decision
/// `reload()` itself now gates its synchronous clear on, rather than driving a real
/// `reload()` + `PicksClient.run()` subprocess call -- that function's own docstring
/// explains why: its completion fires genuinely asynchronously on a machine with
/// `teetime-monitor-picks` actually installed, but *synchronously*, with an empty
/// result, on a clean CI runner that has no such binary, which made an earlier,
/// reload()-driven version of this exact test pass locally and fail in CI.
private func testSwitchingCourseCountsAsChanged() {
    Harness.check("no prior request at all counts as changed (first load)",
                   OverviewModel.picksRequestChanged(from: nil, to: ("/club.db", "18 Loch Tee 1")))
    Harness.check("a different course, same club, counts as changed",
                   OverviewModel.picksRequestChanged(from: ("/club.db", "18 Loch Tee 1"),
                                                      to: ("/club.db", "9 Loch Tee 1")))
    Harness.check("a different club, same course name, counts as changed",
                   OverviewModel.picksRequestChanged(from: ("/club-a.db", "18 Loch Tee 1"),
                                                      to: ("/club-b.db", "18 Loch Tee 1")))
}

/// The other half of the same fix: a routine reload() of the *same* club/course
/// (the 2-second DB-mtime watcher, or a confirm/cancel) must NOT blank `picks`/
/// `windowHint` -- that would flash the pick badges/hint to empty and back on every
/// single background refresh, a real regression clearing unconditionally would
/// have caused.
private func testReloadingSameCourseDoesNotCountAsChanged() {
    Harness.check("the exact same (club, course) is not a change",
                   !OverviewModel.picksRequestChanged(from: ("/club.db", "18 Loch Tee 1"),
                                                       to: ("/club.db", "18 Loch Tee 1")))
}
