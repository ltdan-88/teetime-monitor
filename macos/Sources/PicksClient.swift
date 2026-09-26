import Foundation

/// One day's recommended pick -- mirrors `picks_cli.py`'s own per-date object shape
/// exactly (see that script's docstring for the contract). `reasons` is empty
/// whenever AI ranking is off, same as the TUI's own Pick column.
struct DayPick {
    let time: String
    let score: Double
    let reasons: [String]
}

/// Shells out to `teetime-monitor-picks`, the Tier 2 console script wrapping
/// `tui._availability_pipeline()` -- same hybrid split `SearchClient` already
/// follows, for the same reason: the pick selection (hard filters, weather/daylight
/// playability, AI ranking) is real, non-trivial business logic this app doesn't
/// reimplement, and reusing the exact function `_day_pick_text()` itself calls means
/// this can never disagree with what the TUI would show for the same data.
///
/// Added 2026-09-27, direct follow-up to the GUI's Overview never showing an
/// AI-ranked pick at all (only the ad hoc Search sheet did) -- see `App.swift`'s
/// `OverviewModel.reload()` (where this is called, fire-and-forget, alongside the
/// synchronous SQLite reload) and `DayCardHeader`'s pick badge.
enum PicksClient {
    static func executable() -> String? {
        for candidate in ["/opt/homebrew/bin/teetime-monitor-picks", "/usr/local/bin/teetime-monitor-picks"]
        where FileManager.default.isExecutableFile(atPath: candidate) {
            return candidate
        }
        let which = Process()
        which.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        which.arguments = ["which", "teetime-monitor-picks"]
        let pipe = Pipe(); which.standardOutput = pipe; which.standardError = Pipe()
        try? which.run(); which.waitUntilExit()
        let found = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return found.isEmpty ? nil : found
    }

    /// `clubSlug` is optional, same reason `SearchClient.run()`'s own is: an
    /// unsaved/browsed club still gets a pick, just without that club's own
    /// availability/AI-ranking overrides layered in. Silently does nothing on
    /// failure (no executable, bad exit, unparseable output) -- this is a
    /// best-effort enhancement over the core Overview, which already rendered
    /// correctly before this existed and must keep doing so if the call fails for
    /// any reason (same stance `_availability_pipeline()` itself takes).
    static func run(dbPath: String, course: String, clubSlug: String?, from: String, days: Int,
                     done: @escaping ([String: DayPick]) -> Void) {
        guard let exe = executable() else { done([:]); return }
        DispatchQueue.global(qos: .utility).async {
            let task = Process()
            task.executableURL = URL(fileURLWithPath: exe)
            var args = ["--db-path", dbPath, "--course", course, "--from", from, "--days", String(days)]
            if let clubSlug { args += ["--club-slug", clubSlug] }
            task.arguments = args
            let stdout = Pipe(), stderr = Pipe()
            task.standardOutput = stdout; task.standardError = stderr
            do { try task.run() } catch {
                DispatchQueue.main.async { done([:]) }
                return
            }
            task.waitUntilExit()
            let outData = stdout.fileHandleForReading.readDataToEndOfFile()
            DispatchQueue.main.async {
                guard let obj = try? JSONSerialization.jsonObject(with: outData) as? [String: Any] else {
                    done([:])
                    return
                }
                var picks: [String: DayPick] = [:]
                for (date, value) in obj {
                    guard let row = value as? [String: Any], let time = row["time"] as? String else { continue }
                    picks[date] = DayPick(
                        time: time,
                        score: row["score"] as? Double ?? 0,
                        reasons: row["reasons"] as? [String] ?? []
                    )
                }
                done(picks)
            }
        }
    }
}
