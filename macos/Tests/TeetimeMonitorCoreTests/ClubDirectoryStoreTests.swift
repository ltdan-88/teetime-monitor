@testable import TeetimeMonitorCore

func runClubDirectoryStoreTests() {
    Harness.group("ClubDirectoryStore") {
        testSearchIsCaseInsensitiveSubstring()
        testSearchBlankQueryReturnsNothing()
        testSearchRespectsLimit()
        testLooksLikeClubID()
    }
}

private let directory = [
    DirectoryEntry(clubID: "0352001", name: "Golf Club Grand Ducal de Luxembourg"),
    DirectoryEntry(clubID: "0491605", name: "1. Golfclub Leipzig e.V."),
    DirectoryEntry(clubID: "0000001", name: "Golfclub Dom\u{e4}ne Musterhausen e.V."),
]

private func testSearchIsCaseInsensitiveSubstring() {
    // Mirrors club_directory.search() exactly, including its own test's own case.
    let results = ClubDirectoryStore.search(directory, query: "leipzig")
    Harness.checkEqual("one match", results.map(\.clubID), ["0491605"])
    let upper = ClubDirectoryStore.search(directory, query: "LEIPZIG")
    Harness.checkEqual("case-insensitive", upper.map(\.clubID), ["0491605"])
}

private func testSearchBlankQueryReturnsNothing() {
    Harness.check("blank query returns nothing", ClubDirectoryStore.search(directory, query: "   ").isEmpty)
}

private func testSearchRespectsLimit() {
    let results = ClubDirectoryStore.search(directory, query: "golf", limit: 2)
    Harness.checkEqual("limit is honored", results.count, 2)
}

/// Mirrors club_directory.looks_like_club_id()/_CLUB_ID_RE/_CLUB_ID_IN_URL_RE
/// exactly, including the zero-pad-to-7 and pasted-URL cases.
private func testLooksLikeClubID() {
    Harness.checkEqual("bare 6-digit id zero-pads to 7", ClubDirectoryStore.looksLikeClubID("491605"), "0491605")
    Harness.checkEqual("already-7-digit id passes through", ClubDirectoryStore.looksLikeClubID("0491605"), "0491605")
    Harness.checkEqual("pasted booking URL extracts the id",
                        ClubDirectoryStore.looksLikeClubID("https://pccaddie.net/clubs/0491605/booking"), "0491605")
    Harness.checkEqual("6-digit id inside a URL still zero-pads",
                        ClubDirectoryStore.looksLikeClubID("https://pccaddie.net/clubs/491605/booking"), "0491605")
    Harness.check("a club name is not a club id", ClubDirectoryStore.looksLikeClubID("Golfclub Leipzig") == nil)
    Harness.check("too few digits is not a club id", ClubDirectoryStore.looksLikeClubID("12345") == nil)
    Harness.check("too many digits is not a club id", ClubDirectoryStore.looksLikeClubID("12345678") == nil)
}
