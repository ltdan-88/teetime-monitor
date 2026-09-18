import Foundation

/// Typed-in criteria for one ad hoc search -- the Swift-form equivalent of
/// `SearchScreen._build_criteria()`. Pre-filled from `Preferences.load()`'s own
/// window/buffer/min-open-spots fields by whoever constructs this (see
/// `SearchSheet`), same "starts from your saved defaults, edit for this one case"
/// UX the TUI's own ad hoc search shares with its Preferences screen.
struct SearchCriteriaPayload {
    var minOpenSpots: Int
    var weekdayAfter: String?
    var weekdayBefore: String?
    var weekendAfter: String?
    var weekendBefore: String?
    var bufferBeforeMinutes: Int
    var bufferAfterMinutes: Int

    /// A day type with *both* sides nil omits that window key entirely, not
    /// `{"after": null, "before": null}` -- those mean different things to
    /// `search_cli.py`'s own `_criteria_from_payload()` (mirroring
    /// `SearchCriteria`'s own docstring): omitted skips that day type from the
    /// search entirely, while a present-but-empty window means "any time is fine
    /// on this day type." Same distinction `PreferencesStore.save()` already gets
    /// right for `preferences.yaml`'s own weekday_window/weekend_window -- getting
    /// it wrong here would silently turn "search weekdays only" into "search every
    /// day, unrestricted."
    var json: [String: Any] {
        var obj: [String: Any] = [
            "min_open_spots": minOpenSpots,
            "buffer_before_minutes": bufferBeforeMinutes,
            "buffer_after_minutes": bufferAfterMinutes,
        ]
        if weekdayAfter != nil || weekdayBefore != nil {
            obj["weekday_window"] = [
                "after": weekdayAfter as Any? ?? NSNull(), "before": weekdayBefore as Any? ?? NSNull(),
            ]
        }
        if weekendAfter != nil || weekendBefore != nil {
            obj["weekend_window"] = [
                "after": weekendAfter as Any? ?? NSNull(), "before": weekendBefore as Any? ?? NSNull(),
            ]
        }
        return obj
    }
}

/// One result row -- mirrors `search_cli.py`'s own JSON shape for a `SlotMatch`
/// exactly (see that script's docstring for the contract).
struct SearchMatch: Identifiable {
    var id: String { date + course + time }
    let date: String
    let course: String
    let time: String
    let booked: Int
    let capacity: Int
    let players: [String]
    let blockReason: String?
    let score: Double
    let reasons: [String]
}

/// Shells out to `teetime-monitor-search`, the Tier 2 console script wrapping
/// `recommend.ranked_matches()` -- same hybrid split `Scraper`/`LoginClient`
/// already follow, for the same reason: `search()`/`exclude_unplayable()`/
/// `ai_assist.rank_slots()` are real, non-trivial business logic this prototype
/// doesn't reimplement. Only the small, form-typed criteria cross the process
/// boundary on stdin -- schedules are loaded by the script itself, straight from
/// the same SQLite database this app already reads directly elsewhere.
enum SearchClient {
    static func executable() -> String? {
        for candidate in ["/opt/homebrew/bin/teetime-monitor-search", "/usr/local/bin/teetime-monitor-search"]
        where FileManager.default.isExecutableFile(atPath: candidate) {
            return candidate
        }
        let which = Process()
        which.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        which.arguments = ["which", "teetime-monitor-search"]
        let pipe = Pipe(); which.standardOutput = pipe; which.standardError = Pipe()
        try? which.run(); which.waitUntilExit()
        let found = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return found.isEmpty ? nil : found
    }

    /// `clubSlug` is optional -- a search against an unsaved/browsed club still
    /// runs (see `_resolved_config(club_slug=None)`'s own fallback), just without
    /// that club's own availability/weather/AI-ranking overrides layered in.
    static func run(dbPath: String, course: String, clubSlug: String?, from: String, days: Int,
                     criteria: SearchCriteriaPayload, done: @escaping ([SearchMatch]?, String?) -> Void) {
        guard let exe = executable() else {
            done(nil, t("error.search_missing"))
            return
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let task = Process()
            task.executableURL = URL(fileURLWithPath: exe)
            var args = ["--db-path", dbPath, "--course", course, "--from", from, "--days", String(days)]
            if let clubSlug { args += ["--club-slug", clubSlug] }
            task.arguments = args
            let stdin = Pipe(), stdout = Pipe(), stderr = Pipe()
            task.standardInput = stdin; task.standardOutput = stdout; task.standardError = stderr
            do { try task.run() } catch {
                DispatchQueue.main.async { done(nil, error.localizedDescription) }
                return
            }
            if let data = try? JSONSerialization.data(withJSONObject: criteria.json) {
                stdin.fileHandleForWriting.write(data)
            }
            stdin.fileHandleForWriting.closeFile()
            task.waitUntilExit()
            let outData = stdout.fileHandleForReading.readDataToEndOfFile()
            let errData = stderr.fileHandleForReading.readDataToEndOfFile()
            DispatchQueue.main.async {
                if let rows = try? JSONSerialization.jsonObject(with: outData) as? [[String: Any]] {
                    done(rows.map { row in
                        SearchMatch(
                            date: row["date"] as? String ?? "",
                            course: row["course"] as? String ?? "",
                            time: row["time"] as? String ?? "",
                            booked: row["booked"] as? Int ?? 0,
                            capacity: row["capacity"] as? Int ?? 0,
                            players: row["players"] as? [String] ?? [],
                            blockReason: row["block_reason"] as? String,
                            score: row["score"] as? Double ?? 0,
                            reasons: row["reasons"] as? [String] ?? []
                        )
                    }, nil)
                    return
                }
                if let obj = try? JSONSerialization.jsonObject(with: outData) as? [String: Any],
                   let message = obj["error"] as? String {
                    done(nil, message)
                    return
                }
                let stderrText = String(data: errData, encoding: .utf8) ?? ""
                done(nil, stderrText.isEmpty ? "search failed (exit \(task.terminationStatus))" : stderrText)
            }
        }
    }
}
