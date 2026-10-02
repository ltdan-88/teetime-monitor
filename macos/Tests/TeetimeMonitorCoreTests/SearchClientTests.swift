import Foundation
@testable import TeetimeMonitorCore

func runSearchClientTests() {
    Harness.group("SearchClient") {
        testOmittedWindowHasNoKey()
        testPresentWindowKeepsNullSides()
        testAlwaysIncludesTheScalarFields()
        testFriendsOnlyAndPlayerDefaultToNoFilter()
        testFriendsOnlyAndPlayerEncodeWhenSet()
    }
}

/// The same "omitted vs. present-but-empty means something different" rule
/// `PreferencesStoreTests` pins for `preferences.yaml` -- here it's
/// `search_cli.py`'s own `_criteria_from_payload()` on the receiving end. Getting
/// this wrong would silently turn "search weekdays only" into "search every day,
/// unrestricted."
private func testOmittedWindowHasNoKey() {
    // One day type set, the other fully unset: the unset one is skipped entirely.
    let payload = SearchCriteriaPayload(
        minOpenSpots: 1, weekdayAfter: "16:00", weekdayBefore: nil,
        weekendAfter: nil, weekendBefore: nil, bufferBeforeMinutes: 0, bufferAfterMinutes: 0)
    Harness.check("weekday_window key is present when a side is set", payload.json["weekday_window"] != nil)
    Harness.check("weekend_window key is absent when both sides are nil", payload.json["weekend_window"] == nil)

    // All four unset (e.g. right after "Reset filters") means any time on any day,
    // not "skip both day types", which would always return nothing.
    let cleared = SearchCriteriaPayload(
        minOpenSpots: 1, weekdayAfter: nil, weekdayBefore: nil,
        weekendAfter: nil, weekendBefore: nil, bufferBeforeMinutes: 0, bufferAfterMinutes: 0)
    Harness.check("both windows are present (any time) when all four sides are nil",
                  cleared.json["weekday_window"] != nil && cleared.json["weekend_window"] != nil)
}

private func testPresentWindowKeepsNullSides() {
    let payload = SearchCriteriaPayload(
        minOpenSpots: 1, weekdayAfter: nil, weekdayBefore: "18:00",
        weekendAfter: nil, weekendBefore: nil, bufferBeforeMinutes: 0, bufferAfterMinutes: 0)
    Harness.check("weekday_window key is present when only one side is set", payload.json["weekday_window"] != nil)
    let window = payload.json["weekday_window"] as? [String: Any]
    Harness.checkEqual("the set side round-trips", window?["before"] as? String, "18:00")
    Harness.check("the unset side is an explicit null (NSNull), not a missing key",
                   window?["after"] is NSNull)

    // Confirm the payload actually survives real JSON serialization -- json is a
    // plain [String: Any], not itself proof it encodes.
    let data = try! JSONSerialization.data(withJSONObject: payload.json)
    let reparsed = try! JSONSerialization.jsonObject(with: data) as! [String: Any]
    let reparsedWindow = reparsed["weekday_window"] as? [String: Any]
    Harness.check("survives a real JSONSerialization round-trip", reparsedWindow?["before"] as? String == "18:00")
}

private func testAlwaysIncludesTheScalarFields() {
    let payload = SearchCriteriaPayload(
        minOpenSpots: 2, weekdayAfter: nil, weekdayBefore: nil,
        weekendAfter: nil, weekendBefore: nil, bufferBeforeMinutes: 10, bufferAfterMinutes: 5)
    Harness.checkEqual("min_open_spots", payload.json["min_open_spots"] as? Int, 2)
    Harness.checkEqual("buffer_before_minutes", payload.json["buffer_before_minutes"] as? Int, 10)
    Harness.checkEqual("buffer_after_minutes", payload.json["buffer_after_minutes"] as? Int, 5)
}

/// Direct request, 2026-09-28: "implement players or friends into the search".
/// `friends_only` always encodes (a plain bool, default false); `player` is
/// omitted entirely when empty -- mirrors the window fields' own
/// present-vs-absent convention, and matches `search_cli.py`'s own
/// `payload.get("player")` read, which treats a missing key and an empty
/// string identically anyway, so either would work, but omitting is what the
/// GUI's own "(Any)" Picker option (tagged "") naturally produces.
private func testFriendsOnlyAndPlayerDefaultToNoFilter() {
    let payload = SearchCriteriaPayload(
        minOpenSpots: 1, weekdayAfter: nil, weekdayBefore: nil,
        weekendAfter: nil, weekendBefore: nil, bufferBeforeMinutes: 0, bufferAfterMinutes: 0)
    Harness.checkEqual("friends_only defaults to false", payload.json["friends_only"] as? Bool, false)
    Harness.check("player key is absent when nothing's picked", payload.json["player"] == nil)
}

private func testFriendsOnlyAndPlayerEncodeWhenSet() {
    var payload = SearchCriteriaPayload(
        minOpenSpots: 1, weekdayAfter: nil, weekdayBefore: nil,
        weekendAfter: nil, weekendBefore: nil, bufferBeforeMinutes: 0, bufferAfterMinutes: 0)
    payload.friendsOnly = true
    payload.player = "Erika Mustermann"
    Harness.checkEqual("friends_only", payload.json["friends_only"] as? Bool, true)
    Harness.checkEqual("player", payload.json["player"] as? String, "Erika Mustermann")
}
