import Foundation
@testable import TeetimeMonitorCore

func runPreferencesStoreTests() {
    Harness.group("PreferencesStore") {
        testRoundTrip()
        testOmittedWindowStaysOmitted()
        testPresentWindowStaysPresent()
        testSaveOverlaysOnlyKnownKeys()
    }
}

private func withConfigDir(_ body: (TempDir) -> Void) {
    let dir = TempDir()
    setenv("TEETIME_MONITOR_CONFIG_DIR", dir.path, 1)
    body(dir)
    unsetenv("TEETIME_MONITOR_CONFIG_DIR")
}

private func testRoundTrip() {
    withConfigDir { _ in
        var p = Preferences()
        p.minOpenSpots = 3
        p.weekdayAfter = "17:00"
        p.avoidRain = true
        p.avoidRainProbabilityPercent = 30
        p.units = "imperial"
        try! p.save()

        let reloaded = Preferences.load()
        Harness.checkEqual("minOpenSpots round-trips", reloaded.minOpenSpots, 3)
        Harness.checkEqual("weekdayAfter round-trips", reloaded.weekdayAfter, "17:00")
        Harness.check("weekdayBefore still nil", reloaded.weekdayBefore == nil)
        Harness.checkEqual("avoidRain round-trips", reloaded.avoidRain, true)
        Harness.checkClose("avoidRainProbabilityPercent round-trips",
                            reloaded.avoidRainProbabilityPercent, 30, tolerance: 1e-9)
        Harness.checkEqual("units round-trips", reloaded.units, "imperial")
    }
}

/// The real bug: an *absent* weekday_window/weekend_window key means "this day type
/// isn't configured, skip it entirely" (search.SearchCriteria's own docstring); a
/// *present* `{after: null, before: null}` means "unrestricted, any time is fine"
/// (recommend.default_criteria_from_config()'s _window() closure). Writing `{}` for
/// "nothing set" would have silently turned the first into the second. Caught before
/// shipping originally; pinned here so it can't regress silently either.
private func testOmittedWindowStaysOmitted() {
    withConfigDir { _ in
        var p = Preferences()
        p.weekdayAfter = nil
        p.weekdayBefore = nil
        try! p.save()

        let raw = try! String(contentsOfFile: Preferences.path(), encoding: .utf8)
        let parsed = YAML.parse(raw)
        Harness.check("weekday_window key is absent, not {}",
                       parsed["availability"]?["weekday_window"] == nil)

        let reloaded = Preferences.load()
        Harness.check("reloaded weekdayAfter still nil", reloaded.weekdayAfter == nil)
        Harness.check("reloaded weekdayBefore still nil", reloaded.weekdayBefore == nil)
    }
}

private func testPresentWindowStaysPresent() {
    withConfigDir { _ in
        var p = Preferences()
        p.weekdayAfter = "09:00"
        p.weekdayBefore = nil
        try! p.save()

        let raw = try! String(contentsOfFile: Preferences.path(), encoding: .utf8)
        let parsed = YAML.parse(raw)
        Harness.check("weekday_window key is present when only one side is set",
                       parsed["availability"]?["weekday_window"] != nil)
        Harness.checkEqual("weekday_window.after", parsed["availability"]?["weekday_window"]?["after"]?.asString, "09:00")
    }
}

/// Fields this prototype has no widget for yet (ai_assist, scrape_interval_minutes,
/// avoid_predicted_crowd) must survive a save untouched -- the whole point of
/// starting `save()` from a re-read of the existing file rather than a blank one.
private func testSaveOverlaysOnlyKnownKeys() {
    withConfigDir { dir in
        let seed = """
        ai_assist:
          enabled: true
          model: claude-opus
        preferences:
          avoid_predicted_crowd: true
        scrape_interval_minutes: 45
        """
        try! seed.write(toFile: dir.file("preferences.yaml"), atomically: true, encoding: .utf8)

        var p = Preferences.load()
        p.minOpenSpots = 2
        try! p.save()

        let raw = try! String(contentsOfFile: dir.file("preferences.yaml"), encoding: .utf8)
        let parsed = YAML.parse(raw)
        Harness.checkEqual("ai_assist.enabled survives", parsed["ai_assist"]?["enabled"]?.asBool, true)
        Harness.checkEqual("ai_assist.model survives", parsed["ai_assist"]?["model"]?.asString, "claude-opus")
        Harness.checkEqual("avoid_predicted_crowd survives", parsed["preferences"]?["avoid_predicted_crowd"]?.asBool, true)
        Harness.checkEqual("scrape_interval_minutes survives", parsed["scrape_interval_minutes"]?.asInt, 45)
        Harness.checkEqual("min_open_spots was actually updated", parsed["availability"]?["min_open_spots"]?.asInt, 2)
    }
}
