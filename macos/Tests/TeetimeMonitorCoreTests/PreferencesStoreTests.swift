import Foundation
@testable import TeetimeMonitorCore

func runPreferencesStoreTests() {
    Harness.group("PreferencesStore") {
        testRoundTrip()
        testOmittedWindowStaysOmitted()
        testPresentWindowStaysPresent()
        testSaveOverlaysOnlyKnownKeys()
        testScrapeIntervalAndAIAssistRoundTrip()
        testHcpPreferenceRoundTrip()
        testLegacyBufferMinutesFallsBackAndMigrates()
        testClearedWindowIsRemovedOnSave()
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

/// A field this whole struct genuinely has no widget for anywhere (a hand-set
/// `ai_assist.model`, or the pre-move legacy `preferences.avoid_predicted_crowd`
/// path settings_screen.py's own comment says needs no migration) must still
/// survive a save untouched -- the whole point of starting `save()` from a
/// re-read of the existing file rather than a blank one, and (2026-09-19 on,
/// once ai_assist/scrape_interval_minutes gained real widgets) of merging into
/// ai_assist's existing map rather than replacing it wholesale.
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
        Harness.checkEqual("ai_assist.enabled round-trips", parsed["ai_assist"]?["enabled"]?.asBool, true)
        Harness.checkEqual("a hand-set ai_assist.model this struct has no field for survives",
                            parsed["ai_assist"]?["model"]?.asString, "claude-opus")
        Harness.checkEqual("the pre-move legacy preferences.avoid_predicted_crowd path survives",
                            parsed["preferences"]?["avoid_predicted_crowd"]?.asBool, true)
        Harness.checkEqual("scrape_interval_minutes round-trips", parsed["scrape_interval_minutes"]?.asInt, 45)
        Harness.checkEqual("min_open_spots was actually updated", parsed["availability"]?["min_open_spots"]?.asInt, 2)
    }
}

/// Direct request, 2026-09-19 ("implement scrape-interval and ai settings in
/// GUI"): scrapeIntervalMinutes/scrapeIntervalMinutesBooked (top-level, like
/// daylightBufferMinutes) and aiAssistEnabled/avoidPredictedCrowd (nested under
/// ai_assist, matching settings_screen.py's own FIELDS paths exactly) now
/// round-trip for real, not just pass through untouched.
private func testScrapeIntervalAndAIAssistRoundTrip() {
    withConfigDir { _ in
        var p = Preferences()
        p.scrapeIntervalMinutes = 15
        p.scrapeIntervalMinutesBooked = 30
        p.aiAssistEnabled = true
        p.avoidPredictedCrowd = true
        try! p.save()

        let reloaded = Preferences.load()
        Harness.checkEqual("scrapeIntervalMinutes round-trips", reloaded.scrapeIntervalMinutes, 15)
        Harness.checkEqual("scrapeIntervalMinutesBooked round-trips", reloaded.scrapeIntervalMinutesBooked, 30)
        Harness.checkEqual("aiAssistEnabled round-trips", reloaded.aiAssistEnabled, true)
        Harness.checkEqual("avoidPredictedCrowd round-trips", reloaded.avoidPredictedCrowd, true)
    }
}

/// Direct request, 2026-09-27 ("would it make sense to have the option to choose to
/// play with similar HCP or with better HCP for better pace?") -- same nested
/// preferences.hcp_preference path settings_screen.py's own FIELDS entry uses.
private func testHcpPreferenceRoundTrip() {
    withConfigDir { _ in
        Harness.checkEqual("defaults to off", Preferences().hcpPreference, "off")

        var p = Preferences()
        p.hcpPreference = "similar"
        try! p.save()

        let reloaded = Preferences.load()
        Harness.checkEqual("hcpPreference round-trips", reloaded.hcpPreference, "similar")
    }
}

/// A pre-split `availability.buffer_minutes` (one value for both directions) reads
/// as both buffers, the same fallback `search.resolve_buffer_minutes()` has, and a
/// save writes the two explicit keys in its place -- not 0/0 over a real buffer.
/// Unknown availability keys survive the save.
private func testLegacyBufferMinutesFallsBackAndMigrates() {
    withConfigDir { dir in
        let seed = """
        availability:
          min_open_spots: 2
          buffer_minutes: 15
          some_future_key: 7
        """
        try! seed.write(toFile: dir.file("preferences.yaml"), atomically: true, encoding: .utf8)

        var p = Preferences.load()
        Harness.checkEqual("legacy buffer_minutes -> before", p.bufferBeforeMinutes, 15)
        Harness.checkEqual("legacy buffer_minutes -> after", p.bufferAfterMinutes, 15)

        p.units = "imperial"  // an unrelated edit
        try! p.save()
        let parsed = YAML.parse(try! String(contentsOfFile: dir.file("preferences.yaml"), encoding: .utf8))
        Harness.checkEqual("buffer_before_minutes written", parsed["availability"]?["buffer_before_minutes"]?.asInt, 15)
        Harness.checkEqual("buffer_after_minutes written", parsed["availability"]?["buffer_after_minutes"]?.asInt, 15)
        Harness.check("legacy buffer_minutes dropped", parsed["availability"]?["buffer_minutes"] == nil)
        Harness.checkEqual("unknown availability key survives", parsed["availability"]?["some_future_key"]?.asInt, 7)

        let explicit = Preferences.load(from: YAML.parse("""
        availability:
          buffer_minutes: 15
          buffer_before_minutes: 5
        """))
        Harness.checkEqual("an explicit direction key wins over the legacy one", explicit.bufferBeforeMinutes, 5)
        Harness.checkEqual("the other direction still falls back", explicit.bufferAfterMinutes, 15)
    }
}

/// Merging into the existing availability map must still drop a window you cleared.
private func testClearedWindowIsRemovedOnSave() {
    withConfigDir { dir in
        let seed = """
        availability:
          weekday_window:
            after: '17:00'
        """
        try! seed.write(toFile: dir.file("preferences.yaml"), atomically: true, encoding: .utf8)
        var p = Preferences.load()
        p.weekdayAfter = nil
        try! p.save()
        let parsed = YAML.parse(try! String(contentsOfFile: dir.file("preferences.yaml"), encoding: .utf8))
        Harness.check("cleared weekday_window removed", parsed["availability"]?["weekday_window"] == nil)
    }
}
