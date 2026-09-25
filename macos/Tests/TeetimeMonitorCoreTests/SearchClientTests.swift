import Foundation
@testable import TeetimeMonitorCore

func runSearchClientTests() {
    Harness.group("SearchClient") {
        testOmittedWindowHasNoKey()
        testPresentWindowKeepsNullSides()
        testAlwaysIncludesTheScalarFields()
    }
}

/// The same "omitted vs. present-but-empty means something different" rule
/// `PreferencesStoreTests` pins for `preferences.yaml` -- here it's
/// `search_cli.py`'s own `_criteria_from_payload()` on the receiving end. Getting
/// this wrong would silently turn "search weekdays only" into "search every day,
/// unrestricted."
private func testOmittedWindowHasNoKey() {
    let payload = SearchCriteriaPayload(
        minOpenSpots: 1, weekdayAfter: nil, weekdayBefore: nil,
        weekendAfter: nil, weekendBefore: nil, bufferBeforeMinutes: 0, bufferAfterMinutes: 0)
    Harness.check("weekday_window key is absent when both sides are nil", payload.json["weekday_window"] == nil)
    Harness.check("weekend_window key is absent when both sides are nil", payload.json["weekend_window"] == nil)
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
