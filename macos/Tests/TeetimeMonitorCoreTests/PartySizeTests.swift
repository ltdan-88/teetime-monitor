import Combine
import Foundation
@testable import TeetimeMonitorCore

/// The overview's quick Group picker (2026-10-09): the preference write, the shared
/// singleton behind it and Preferences' own row, and the picks refresh it triggers.
func runPartySizeTests() {
    Harness.group("PartySize") {
        testSetMinOpenSpotsKeepsEveryOtherKey()
        testSetMinOpenSpotsOnAFreshInstall()
        testChoosePersistsThenPublishes()
        testAFailedWriteKeepsTheOldValue()
        testPreferencesStartsFromTheSharedValue()
        testRefreshFromFileFollowsAnOutsideChange()
        testReloadFollowsAnOutsideChange()
        testPartySizeChangeRefetchesThePicks()
        testGroupLabelExistsInBothLanguages()
    }
}

private func withConfigDir(_ body: (TempDir) -> Void) {
    let dir = TempDir()
    setenv("TEETIME_MONITOR_CONFIG_DIR", dir.path, 1)
    body(dir)
    unsetenv("TEETIME_MONITOR_CONFIG_DIR")
}

private func testSetMinOpenSpotsKeepsEveryOtherKey() {
    withConfigDir { _ in
        var p = Preferences()
        p.minOpenSpots = 1
        p.weekdayAfter = "17:00"
        p.weekendAfter = "10:00"
        p.bufferBeforeMinutes = 20
        p.units = "imperial"
        try! p.save()
        // Keys this app has no field for, at the top level and inside availability.
        var text = try! String(contentsOfFile: Preferences.path(), encoding: .utf8)
        text += "something_unknown:\n  keep:\n  - me\n"
        text = text.replacingOccurrences(of: "availability:\n", with: "availability:\n  hand_edited: 7\n")
        try! text.write(toFile: Preferences.path(), atomically: true, encoding: .utf8)

        try! Preferences.setMinOpenSpots(3)

        let root = YAML.parse(try! String(contentsOfFile: Preferences.path(), encoding: .utf8))
        Harness.checkEqual("min_open_spots written", root["availability"]?["min_open_spots"]?.asInt, 3)
        Harness.checkEqual("weekday window kept", root["availability"]?["weekday_window"]?["after"]?.asString, "17:00")
        Harness.checkEqual("weekend window kept", root["availability"]?["weekend_window"]?["after"]?.asString, "10:00")
        Harness.checkEqual("buffer kept", root["availability"]?["buffer_before_minutes"]?.asInt, 20)
        Harness.checkEqual("unknown availability key kept", root["availability"]?["hand_edited"]?.asInt, 7)
        Harness.checkEqual("units kept", root["units"]?.asString, "imperial")
        Harness.check("unknown top-level key kept", root["something_unknown"]?["keep"] != nil)
        Harness.checkEqual("reloads as 3", Preferences.load().minOpenSpots, 3)
    }
}

private func testSetMinOpenSpotsOnAFreshInstall() {
    withConfigDir { _ in
        try! Preferences.setMinOpenSpots(2)
        Harness.checkEqual("created the file with just that value", Preferences.load().minOpenSpots, 2)
        let root = YAML.parse(try! String(contentsOfFile: Preferences.path(), encoding: .utf8))
        Harness.check("no window keys invented", root["availability"]?["weekday_window"] == nil)
    }
}

private func testChoosePersistsThenPublishes() {
    withConfigDir { _ in
        let shared = AppPartySize.shared
        let original = (shared.persist, shared.loadSaved, shared.value)
        defer { shared.persist = original.0; shared.loadSaved = original.1; shared.value = original.2 }
        shared.value = 1
        var written: [Int] = []
        var seen: [Int] = []
        shared.persist = { written.append($0) }
        shared.loadSaved = { written.last ?? 1 }
        let sub = shared.$value.dropFirst().sink { seen.append($0) }
        Harness.check("choosing a new size reports success", shared.choose(3))
        Harness.checkEqual("published", shared.value, 3)
        Harness.checkEqual("persisted once", written, [3])
        _ = shared.choose(3)
        Harness.checkEqual("choosing the shown size writes nothing", written, [3])
        Harness.checkEqual("observers (the toolbar picker, Preferences) saw 3 once", seen, [3])
        sub.cancel()
    }
}

private func testAFailedWriteKeepsTheOldValue() {
    struct Boom: Error {}
    let shared = AppPartySize.shared
    let original = (shared.persist, shared.loadSaved, shared.value)
    defer { shared.persist = original.0; shared.loadSaved = original.1; shared.value = original.2 }
    shared.value = 2
    shared.persist = { _ in throw Boom() }
    shared.loadSaved = { 2 }
    Harness.check("failure reported", !shared.choose(4))
    Harness.checkEqual("old value stays", shared.value, 2)
}

private func testPreferencesStartsFromTheSharedValue() {
    // 2026-10-09 review: the singleton can be stale against the file (the TUI saved
    // another size). Preferences must open on the file's value and Save must keep it.
    withConfigDir { _ in
        var p = Preferences()
        p.minOpenSpots = 1
        try! p.save()
        try! Preferences.setMinOpenSpots(3)  // the TUI's write, behind the singleton's back
        let shared = AppPartySize.shared
        let original = shared.value
        defer { shared.value = original }
        shared.value = 1  // stale

        var opened = Preferences.withSharedPartySize()
        Harness.checkEqual("the sheet opens on the saved size, not the stale singleton", opened.minOpenSpots, 3)
        Harness.checkEqual("every other field still comes from the file", opened.units, Preferences.load().units)
        shared.refreshFromFile()  // the sheet's onAppear
        Harness.checkEqual("the singleton follows the file", shared.value, 3)
        try! opened.save()  // the user never touched the field
        Harness.checkEqual("Save keeps what the TUI saved", Preferences.load().minOpenSpots, 3)
        opened.minOpenSpots = 2
        try! opened.save()
        Harness.checkEqual("an edit still saves", Preferences.load().minOpenSpots, 2)
    }
}

private func testRefreshFromFileFollowsAnOutsideChange() {
    withConfigDir { _ in
        try! Preferences.setMinOpenSpots(2)
        let shared = AppPartySize.shared
        let original = (shared.persist, shared.value)
        defer { shared.persist = original.0; shared.value = original.1 }
        shared.value = 2
        var seen: [Int] = []
        let sub = shared.$value.dropFirst().sink { seen.append($0) }
        shared.refreshFromFile()
        Harness.checkEqual("an unchanged file publishes nothing", seen, [])
        try! Preferences.setMinOpenSpots(4)
        shared.refreshFromFile()
        Harness.checkEqual("a changed file is picked up and published once", seen, [4])
        // The picker still showed 4 when the TUI saved 3: picking 4 is a real write.
        try! Preferences.setMinOpenSpots(3)
        Harness.check("choosing the stale shown size is not a silent no-op", shared.choose(4))
        Harness.checkEqual("it was written", Preferences.load().minOpenSpots, 4)
        Harness.checkEqual("and shown", shared.value, 4)
        sub.cancel()
    }
}

private func testReloadFollowsAnOutsideChange() {
    withConfigDir { _ in
        try! Preferences.setMinOpenSpots(3)
        let shared = AppPartySize.shared
        let original = shared.value
        defer { shared.value = original }
        shared.value = 1
        let model = OverviewModel()
        model.clubPath = "/nonexistent-party-size.db"
        model.course = "18 Loch"
        model.reload()
        Harness.checkEqual("a reload re-reads the saved group size", shared.value, 3)
        model.clubPath = ""
        model.reload()
    }
}

private func testPartySizeChangeRefetchesThePicks() {
    let model = OverviewModel()
    let before = model.picksGeneration
    model.partySizeChanged()
    Harness.checkEqual("nothing to fetch without a club and course", model.picksGeneration, before)

    model.clubPath = "/nonexistent-party-size.db"
    model.course = "18 Loch"
    model.picks = ["2026-10-10": DayPick(time: "10:00", score: 1, reasons: [], aiReasons: [])]
    model.partySizeChanged()
    Harness.check("a picks request started", model.picksGeneration > before)
    Harness.check("the badges stay until the new result lands (no flash to empty)", !model.picks.isEmpty)
    // Cancel the request just started (a subprocess, if the picks CLI is installed here).
    model.clubPath = ""
    model.reload()
}

private func testGroupLabelExistsInBothLanguages() {
    Harness.checkEqual("en", I18n.strings["en"]?["overview.group"], "Group")
    Harness.checkEqual("de", I18n.strings["de"]?["overview.group"], "Gruppe")
}
