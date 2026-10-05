import Foundation
@testable import TeetimeMonitorCore

func runPlayerDirectoryTests() {
    Harness.group("PlayerDirectory") {
        testGroupsAdjacentSameLetterNamesTogether()
        testGroupingIsCaseInsensitiveAndUsesFamilyName()
        testNonLetterFamilyNamesFallToHashBucket()
        testEmptyListGroupsToNoSections()
        testFriendSortPutsFriendsFirst()
    }
    Harness.group("OverviewModel.picksRequestChanged") {
        testSwitchingCourseCountsAsChanged()
        testReloadingSameCourseDoesNotCountAsChanged()
    }
    Harness.group("playerSlotHits") {
        testFindsEveryHitAcrossMultipleDays()
        testNoHitsForAPlayerNotInAnyLoadedDay()
        testDoesNotMatchAPartialNameSubstring()
        testIgnoresBlockedSlotsWithNoRealPlayers()
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

private func slot(_ time: String, players: [String] = [], blockReason: String? = nil) -> Slot {
    Slot(time: time, booked: players.count, capacity: 4, blockReason: blockReason, players: players)
}

private func day(_ date: String, slots: [Slot]) -> Day {
    Day(date: date, slots: slots, weather: [], sunrise: nil, sunset: nil, events: [], bookedTime: nil)
}

/// Direct request, 2026-09-28: "would it be possible to double click a player in
/// the directory and focus on their booked tee time or tee times?" -- the "or
/// times" plural is exactly what this pins: a player showing up in more than one
/// loaded day's slots is a real, expected case (multiple hits get a small picker
/// in the sheet itself), not something `playerSlotHits` should collapse to one.
private func testFindsEveryHitAcrossMultipleDays() {
    let days = [
        day("2026-09-28", slots: [slot("09:00", players: ["Anna Bauer"]), slot("09:20")]),
        day("2026-09-29", slots: [slot("14:00", players: ["Max Mustermann", "Anna Bauer"])]),
    ]
    let hits = playerSlotHits(for: "Anna Bauer", in: days)
    Harness.checkEqual("one hit per day she's actually in",
                        Set(hits.map { "\($0.date) \($0.time)" }),
                        Set(["2026-09-28 09:00", "2026-09-29 14:00"]))
}

private func testNoHitsForAPlayerNotInAnyLoadedDay() {
    let days = [day("2026-09-28", slots: [slot("09:00", players: ["Anna Bauer"])])]
    Harness.checkEqual("nobody by that name in the loaded window",
                        playerSlotHits(for: "Someone Else", in: days).count, 0)
}

private func testDoesNotMatchAPartialNameSubstring() {
    // Slot.players holds exact names pc caddie's own markup gave -- a substring
    // match here would silently conflate "Anna Bauer" with e.g. "Anna Bauer-Klein".
    let days = [day("2026-09-28", slots: [slot("09:00", players: ["Anna Bauer-Klein"])])]
    Harness.checkEqual("a real name that merely contains the query isn't a hit",
                        playerSlotHits(for: "Anna Bauer", in: days).count, 0)
}

private func testIgnoresBlockedSlotsWithNoRealPlayers() {
    // A blocked slot (event/closure) carries no real players regardless of what's
    // passed for `players:` here -- this fixture makes that explicit rather than
    // relying on Store's own real query never producing one, since this function
    // takes whatever Day/Slot data it's handed.
    let days = [day("2026-09-28", slots: [slot("09:00", players: [], blockReason: "Clubmeisterschaft")])]
    Harness.checkEqual("a block with no real players is never a hit",
                        playerSlotHits(for: "Anna Bauer", in: days).count, 0)
}

/// Direct report, 2026-09-29: "sorting by friends somehow did not have any effect."
private func testFriendSortPutsFriendsFirst() {
    let anna = KnownPlayer(name: "Anna Zeller", lastSeen: "2026-09-27T10:00:00+00:00", isFriend: true,
                           gender: nil, memberStatus: nil, handicap: nil)
    let players = [player("Bernd Adler"), anna, player("Claus Bauer")]
    let field = PlayerSortField.friend
    let ascending = players.sorted { field.key($0) < field.key($1) }
    Harness.checkEqual("friend sort: friends first, then family-name order",
                       ascending.map { $0.name }, ["Anna Zeller", "Bernd Adler", "Claus Bauer"])
    Harness.check("reversed friend sort puts friends last", Array(ascending.reversed()).last?.name == "Anna Zeller")
}

private func hcpPlayer(_ name: String, _ handicap: Double?, gender: String? = nil) -> KnownPlayer {
    KnownPlayer(name: name, lastSeen: "2026-09-27T10:00:00+00:00", isFriend: false,
                gender: gender, memberStatus: nil, handicap: handicap)
}

func runPlayerDirectoryReviewFixTests() {
    Harness.group("PlayerDirectory review fixes") {
        // Descending HCP flips the values only; no-handicap players stay last.
        let players = [hcpPlayer("Abel A", 20), hcpPlayer("Nil N", nil), hcpPlayer("Mia M", 10)]
        Harness.checkEqual("ascending HCP: nil last",
                           sortedPlayers(players, by: .handicap, reversed: false).map(\.name),
                           ["Mia M", "Abel A", "Nil N"])
        Harness.checkEqual("descending HCP: highest first, nil still last",
                           sortedPlayers(players, by: .handicap, reversed: true).map(\.name),
                           ["Abel A", "Mia M", "Nil N"])
        Harness.checkEqual("other fields still reverse wholesale",
                           sortedPlayers(players, by: .name, reversed: true).map(\.name),
                           ["Nil N", "Mia M", "Abel A"])

        // ß folds to "ss" like Python's casefold(): Heßlinger before Heusel, Weiß
        // beside Weiss rather than after Weiss-Freisinger.
        let names = [hcpPlayer("Martin Heusel", nil), hcpPlayer("Thomas Heßlinger", nil),
                     hcpPlayer("Reinhilde Weiss-Freisinger", nil), hcpPlayer("Cornelie Weiß", nil)]
        Harness.checkEqual("A-Z order matches the TUI's casefold",
                           sortedPlayers(names, by: .name, reversed: false).map(\.name),
                           ["Thomas Heßlinger", "Martin Heusel", "Cornelie Weiß", "Reinhilde Weiss-Freisinger"])

        // A player with no gender groups first, not mixed in by family name.
        let gendered = [hcpPlayer("Anna Adler", nil, gender: "male"), hcpPlayer("Zoe Zimmer", nil),
                        hcpPlayer("Bea Bauer", nil, gender: "female")]
        Harness.checkEqual("gender sort: unknown gender first, then by gender",
                           sortedPlayers(gendered, by: .gender, reversed: false).map(\.name),
                           ["Zoe Zimmer", "Bea Bauer", "Anna Adler"])

        Harness.checkEqual("uniqueLetters keeps first occurrences",
                           uniqueLetters(["#", "A", "B", "A", "#"]), ["#", "A", "B"])

        // A booking before the sunrise row has no rendered row to jump to.
        let d = Day(date: "2026-12-20",
                    slots: [Slot(time: "08:00", booked: 1, capacity: 4, blockReason: nil, players: ["Anna Bauer"]),
                            Slot(time: "08:10", booked: 0, capacity: 4, blockReason: nil, players: []),
                            Slot(time: "09:00", booked: 1, capacity: 4, blockReason: nil, players: ["Anna Bauer"])],
                    weather: [], sunrise: "08:12", sunset: "16:30", events: [], bookedTime: nil)
        Harness.checkEqual("only hits on rendered (sunrise..sunset) rows",
                           playerSlotHits(for: "Anna Bauer", in: [d]).map(\.time), ["09:00"])
    }
}
