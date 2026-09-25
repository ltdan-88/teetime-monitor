import Foundation

/// Mirrors `settings_screen.FIELDS`' own shape — the "preferences describe you" half
/// specifically (Availability/Weather/Pace & daylight/Priorities, per the v0.29.0
/// menu split). Loads and saves the same `preferences.yaml` the Python app reads,
/// verified byte-for-byte round-trip against the real file before this was built on.
struct Preferences {
    var minOpenSpots = 1
    var weekdayAfter: String?
    var weekdayBefore: String?
    var weekendAfter: String?
    var weekendBefore: String?
    var bufferBeforeMinutes = 0
    var bufferAfterMinutes = 0

    var avoidRain = false
    var avoidRainProbabilityPercent = 50.0
    var avoidRainMM = 1.0
    var avoidWind = false
    var avoidWindKPH = 30.0
    var avoidTempBelowC: Double?
    var avoidTempAboveC: Double?

    var daylightBufferMinutes = 0
    var roundDurationNine = 120
    var roundDurationEighteen = 240

    var prioritizeFriends = false

    // Added 2026-09-19, direct request ("implement scrape-interval and ai
    // settings in GUI") -- both top-level `preferences.yaml` keys, same as
    // daylightBufferMinutes/roundDurationNine above, not nested under
    // "preferences". Defaults match scrape_once.py's own
    // DEFAULT_SCRAPE_INTERVAL_MINUTES/_BOOKED exactly.
    var scrapeIntervalMinutes = 360
    var scrapeIntervalMinutesBooked = 60
    // Both under the nested "ai_assist" key -- settings_screen.py moved these
    // out of clubs/*.yaml the same way daylightBufferMinutes/round_duration
    // did (one global switch, not a per-club dial); see that module's own
    // FIELDS list comment on why avoidPredictedCrowd specifically lives here
    // and not under Priorities, despite reading like a preference.
    var aiAssistEnabled = false
    var avoidPredictedCrowd = false

    /// Lives here, not in the `THEME=`/`LANG=` config file, despite being a Settings
    /// -> Display field on the Python side (v0.29.0's split): `settings_screen.py`'s
    /// own `Field("settings.field.units", ("units",), ...)` names a top-level
    /// `preferences.yaml` path, not `user_config.CONFIG_FILE` -- the split there is
    /// preferences-vs-settings *screens*, not preferences-vs-settings *files*.
    var units = "metric"

    static func path() -> String {
        let env = ProcessInfo.processInfo.environment["TEETIME_MONITOR_CONFIG_DIR"]
        let base = (env as NSString?)?.expandingTildeInPath
            ?? (NSHomeDirectory() as NSString).appendingPathComponent(".config/teetime-monitor")
        return "\(base)/preferences.yaml"
    }

    static func load() -> Preferences {
        guard let text = try? String(contentsOfFile: path(), encoding: .utf8) else { return Preferences() }
        return load(from: YAML.parse(text))
    }

    static func load(from root: YAMLValue) -> Preferences {
        var p = Preferences()
        let avail = root["availability"]
        p.minOpenSpots = avail?["min_open_spots"]?.asInt ?? p.minOpenSpots
        p.weekdayAfter = avail?["weekday_window"]?["after"]?.asString
        p.weekdayBefore = avail?["weekday_window"]?["before"]?.asString
        p.weekendAfter = avail?["weekend_window"]?["after"]?.asString
        p.weekendBefore = avail?["weekend_window"]?["before"]?.asString
        p.bufferBeforeMinutes = avail?["buffer_before_minutes"]?.asInt ?? p.bufferBeforeMinutes
        p.bufferAfterMinutes = avail?["buffer_after_minutes"]?.asInt ?? p.bufferAfterMinutes

        let prefs = root["preferences"]
        p.avoidRain = prefs?["avoid_rain"]?.asBool ?? p.avoidRain
        p.avoidRainProbabilityPercent = prefs?["avoid_rain_probability_percent"]?.asDouble ?? p.avoidRainProbabilityPercent
        p.avoidRainMM = prefs?["avoid_rain_mm"]?.asDouble ?? p.avoidRainMM
        p.avoidWind = prefs?["avoid_wind"]?.asBool ?? p.avoidWind
        p.avoidWindKPH = prefs?["avoid_wind_kph"]?.asDouble ?? p.avoidWindKPH
        p.avoidTempBelowC = prefs?["avoid_temp_below_c"]?.asDouble
        p.avoidTempAboveC = prefs?["avoid_temp_above_c"]?.asDouble
        p.prioritizeFriends = prefs?["prioritize_friends"]?.asBool ?? p.prioritizeFriends

        p.units = root["units"]?.asString ?? p.units
        p.daylightBufferMinutes = root["daylight_buffer_minutes"]?.asInt ?? p.daylightBufferMinutes
        let round = root["round_duration_minutes"]
        p.roundDurationNine = round?["nine"]?.asInt ?? p.roundDurationNine
        p.roundDurationEighteen = round?["eighteen"]?.asInt ?? p.roundDurationEighteen

        p.scrapeIntervalMinutes = root["scrape_interval_minutes"]?.asInt ?? p.scrapeIntervalMinutes
        p.scrapeIntervalMinutesBooked = root["scrape_interval_minutes_booked"]?.asInt ?? p.scrapeIntervalMinutesBooked
        let ai = root["ai_assist"]
        p.aiAssistEnabled = ai?["enabled"]?.asBool ?? p.aiAssistEnabled
        p.avoidPredictedCrowd = ai?["avoid_predicted_crowd"]?.asBool ?? p.avoidPredictedCrowd
        return p
    }

    /// Re-reads the file and overlays just this struct's own known keys, so any
    /// field genuinely unknown to this whole struct survives a save from here
    /// untouched -- the same "only touch fields you actually have a widget for"
    /// property `widget_values_to_config()` has, achieved differently: that
    /// function starts from a loaded copy and overwrites known paths, which is
    /// exactly what this does too. `ai_assist`/`scrape_interval_minutes*` are
    /// now among the *known* keys (2026-09-19 on) even though only
    /// `SettingsSheet`'s own AI/Scraping sections actually edit them --
    /// `PreferencesSheet` re-writes them unchanged on its own Save, since both
    /// sheets always start from a fresh `Preferences.load()` right before use.
    func save() throws {
        let existing = (try? String(contentsOfFile: Self.path(), encoding: .utf8)).map(YAML.parse) ?? .map([])
        var root = existing.asMap ?? []

        func setTop(_ key: String, _ value: YAMLValue) {
            if let i = root.firstIndex(where: { $0.0 == key }) { root[i].1 = value } else { root.append((key, value)) }
        }

        var availabilityPairs: [(String, YAMLValue)] = [
            ("min_open_spots", .int(minOpenSpots)),
        ]
        // Omitted entirely, not written as `{}`, when both sides are unset --
        // verified against recommend.default_criteria_from_config()'s own _window()
        // closure: an *absent* key returns None (day type not configured, skipped),
        // while a *present* {after: null, before: null} would build a real
        // unrestricted TimeWindow (any time matches). Those are different outcomes,
        // and writing `{}` here would have silently turned "no weekend rules set"
        // into "any weekend time is fine" -- caught before shipping, not after.
        if weekdayAfter != nil || weekdayBefore != nil {
            availabilityPairs.append(("weekday_window", .map(windowPairs(after: weekdayAfter, before: weekdayBefore))))
        }
        if weekendAfter != nil || weekendBefore != nil {
            availabilityPairs.append(("weekend_window", .map(windowPairs(after: weekendAfter, before: weekendBefore))))
        }
        availabilityPairs.append(("buffer_before_minutes", .int(bufferBeforeMinutes)))
        availabilityPairs.append(("buffer_after_minutes", .int(bufferAfterMinutes)))
        setTop("availability", .map(availabilityPairs))

        var prefsPairs: [(String, YAMLValue)] = existing["preferences"]?.asMap ?? []
        func setPref(_ key: String, _ value: YAMLValue) {
            if let i = prefsPairs.firstIndex(where: { $0.0 == key }) { prefsPairs[i].1 = value }
            else { prefsPairs.append((key, value)) }
        }
        setPref("avoid_rain", .bool(avoidRain))
        setPref("avoid_rain_probability_percent", .double(avoidRainProbabilityPercent))
        setPref("avoid_rain_mm", .double(avoidRainMM))
        setPref("avoid_wind", .bool(avoidWind))
        setPref("avoid_wind_kph", .double(avoidWindKPH))
        setPref("avoid_temp_below_c", avoidTempBelowC.map(YAMLValue.double) ?? .null)
        setPref("avoid_temp_above_c", avoidTempAboveC.map(YAMLValue.double) ?? .null)
        setPref("prioritize_friends", .bool(prioritizeFriends))
        // avoid_predicted_crowd lives here too but has no widget on this screen (it's
        // Settings -> AI ranking, same as the Python split) -- left untouched by
        // starting `prefsPairs` from what was already on disk.
        setTop("preferences", .map(prefsPairs))

        setTop("units", .string(units))
        setTop("daylight_buffer_minutes", .int(daylightBufferMinutes))
        setTop("round_duration_minutes", .map([
            ("nine", .int(roundDurationNine)),
            ("eighteen", .int(roundDurationEighteen)),
        ]))
        setTop("scrape_interval_minutes", .int(scrapeIntervalMinutes))
        setTop("scrape_interval_minutes_booked", .int(scrapeIntervalMinutesBooked))

        // Merged into the existing ai_assist map, not a wholesale replacement --
        // settings_screen.py itself notes a hand-edited `ai_assist.model` "still
        // works if set" as a fallback even though no widget (here or on the
        // Python side) writes one any more; overwriting the whole key would
        // silently drop that if a user ever had one set by hand.
        var aiPairs: [(String, YAMLValue)] = existing["ai_assist"]?.asMap ?? []
        func setAI(_ key: String, _ value: YAMLValue) {
            if let i = aiPairs.firstIndex(where: { $0.0 == key }) { aiPairs[i].1 = value }
            else { aiPairs.append((key, value)) }
        }
        setAI("enabled", .bool(aiAssistEnabled))
        setAI("avoid_predicted_crowd", .bool(avoidPredictedCrowd))
        setTop("ai_assist", .map(aiPairs))

        let dir = (Self.path() as NSString).deletingLastPathComponent
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        try YAML.dump(.map(root)).write(toFile: Self.path(), atomically: true, encoding: .utf8)
    }

    private func windowPairs(after: String?, before: String?) -> [(String, YAMLValue)] {
        // Python's own widget_values_to_config() drops a window key entirely once
        // both sides are unset (see search.py's SearchCriteria docstring: no window
        // configured means "skip this day type", not "any time is fine") -- an empty
        // {after: null, before: null} would mean something different. Matched here by
        // writing an empty map, which YAML.dump renders as `{}` and Preferences.load
        // then reads back as both-nil, the same empty state.
        var pairs: [(String, YAMLValue)] = []
        if let after { pairs.append(("after", .string(after))) }
        if let before { pairs.append(("before", .string(before))) }
        return pairs
    }
}
