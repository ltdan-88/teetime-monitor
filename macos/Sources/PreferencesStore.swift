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
    // Added 2026-09-27, direct follow-up: "would it make sense to have the option to
    // choose to play with similar HCP or with better HCP for better pace?" — same
    // "off" opt-in default as prioritizeFriends, see settings_screen.py's own FIELDS
    // comment on this field for why. "off" | "similar" | "better".
    var hcpPreference = "off"

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

    /// Top-level `show_handicaps` (2026-10-05): "(18,4)" after player names in the slot
    /// rows. On unless switched off; Settings -> Display in both apps.
    var showHandicaps = true

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

    /// What the Preferences sheet opens on: the file, group size included (2026-10-09).
    /// The singleton behind the overview's Group picker may be stale -- the TUI can have
    /// saved a different size since -- and Save would write that stale value back over
    /// it; the sheet's `.onAppear` brings the singleton up to the file instead.
    static func withSharedPartySize() -> Preferences {
        load()
    }

    static func load(from root: YAMLValue) -> Preferences {
        var p = Preferences()
        let avail = root["availability"]
        p.minOpenSpots = avail?["min_open_spots"]?.asInt ?? p.minOpenSpots
        p.weekdayAfter = avail?["weekday_window"]?["after"]?.asString
        p.weekdayBefore = avail?["weekday_window"]?["before"]?.asString
        p.weekendAfter = avail?["weekend_window"]?["after"]?.asString
        p.weekendBefore = avail?["weekend_window"]?["before"]?.asString
        // Falls back to the old single `buffer_minutes` key, same as
        // `search.resolve_buffer_minutes()` -- otherwise a pre-split file showed 0/0
        // here and the next save wrote those zeros over a real buffer.
        let legacyBuffer = avail?["buffer_minutes"]?.asInt
        p.bufferBeforeMinutes = avail?["buffer_before_minutes"]?.asInt ?? legacyBuffer ?? p.bufferBeforeMinutes
        p.bufferAfterMinutes = avail?["buffer_after_minutes"]?.asInt ?? legacyBuffer ?? p.bufferAfterMinutes

        let prefs = root["preferences"]
        p.avoidRain = prefs?["avoid_rain"]?.asBool ?? p.avoidRain
        p.avoidRainProbabilityPercent = prefs?["avoid_rain_probability_percent"]?.asDouble ?? p.avoidRainProbabilityPercent
        p.avoidRainMM = prefs?["avoid_rain_mm"]?.asDouble ?? p.avoidRainMM
        p.avoidWind = prefs?["avoid_wind"]?.asBool ?? p.avoidWind
        p.avoidWindKPH = prefs?["avoid_wind_kph"]?.asDouble ?? p.avoidWindKPH
        p.avoidTempBelowC = prefs?["avoid_temp_below_c"]?.asDouble
        p.avoidTempAboveC = prefs?["avoid_temp_above_c"]?.asDouble
        p.prioritizeFriends = prefs?["prioritize_friends"]?.asBool ?? p.prioritizeFriends
        p.hcpPreference = prefs?["hcp_preference"]?.asString ?? p.hcpPreference

        p.units = root["units"]?.asString ?? p.units
        p.showHandicaps = root["show_handicaps"]?.asBool ?? p.showHandicaps
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

        // Merged into the existing availability map like `preferences`/`ai_assist`
        // below, so a key this struct doesn't model survives a save.
        var availabilityPairs: [(String, YAMLValue)] = existing["availability"]?.asMap ?? []
        func setAvail(_ key: String, _ value: YAMLValue?) {
            let i = availabilityPairs.firstIndex(where: { $0.0 == key })
            switch (i, value) {
            case let (i?, value?): availabilityPairs[i].1 = value
            case let (nil, value?): availabilityPairs.append((key, value))
            case let (i?, nil): availabilityPairs.remove(at: i)
            case (nil, nil): break
            }
        }
        setAvail("min_open_spots", .int(minOpenSpots))
        // Omitted entirely, not written as `{}`, when both sides are unset --
        // verified against recommend.default_criteria_from_config()'s own _window()
        // closure: an *absent* key returns None (day type not configured, skipped),
        // while a *present* {after: null, before: null} would build a real
        // unrestricted TimeWindow (any time matches). Those are different outcomes,
        // and writing `{}` here would have silently turned "no weekend rules set"
        // into "any weekend time is fine" -- caught before shipping, not after.
        setAvail("weekday_window", weekdayAfter != nil || weekdayBefore != nil
                 ? .map(windowPairs(after: weekdayAfter, before: weekdayBefore)) : nil)
        setAvail("weekend_window", weekendAfter != nil || weekendBefore != nil
                 ? .map(windowPairs(after: weekendAfter, before: weekendBefore)) : nil)
        setAvail("buffer_before_minutes", .int(bufferBeforeMinutes))
        setAvail("buffer_after_minutes", .int(bufferAfterMinutes))
        // Both directions are written explicitly now, so the pre-split key is
        // dropped -- what settings_screen.widget_values_to_config() does too.
        setAvail("buffer_minutes", nil)
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
        setPref("hcp_preference", .string(hcpPreference))
        // avoid_predicted_crowd lives here too but has no widget on this screen (it's
        // Settings -> AI ranking, same as the Python split) -- left untouched by
        // starting `prefsPairs` from what was already on disk.
        setTop("preferences", .map(prefsPairs))

        setTop("units", .string(units))
        setTop("show_handicaps", .bool(showHandicaps))
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

    /// Changes only `availability.min_open_spots` (2026-10-09, the overview's quick Group
    /// picker): the rest of the file -- other availability values, unknown keys -- is
    /// written back exactly as it was read, unlike `save()`, which also rewrites every
    /// key this struct models.
    static func setMinOpenSpots(_ spots: Int) throws {
        let existing = (try? String(contentsOfFile: path(), encoding: .utf8)).map(YAML.parse) ?? .map([])
        var root = existing.asMap ?? []
        var availability: [(String, YAMLValue)] = existing["availability"]?.asMap ?? []
        if let i = availability.firstIndex(where: { $0.0 == "min_open_spots" }) {
            availability[i].1 = .int(spots)
        } else {
            availability.append(("min_open_spots", .int(spots)))
        }
        if let i = root.firstIndex(where: { $0.0 == "availability" }) {
            root[i].1 = .map(availability)
        } else {
            root.append(("availability", .map(availability)))
        }
        let dir = (path() as NSString).deletingLastPathComponent
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        try YAML.dump(.map(root)).write(toFile: path(), atomically: true, encoding: .utf8)
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
