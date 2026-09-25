import Foundation

/// Shells out to `teetime-monitor-preview-club` -- closes the one Tier 2 gap this
/// prototype's own README explicitly flagged as still open ("browsing a club's
/// schedule before saving it, the way `ClubBrowserScreen` can -- is still open;
/// adding a club still means favoriting it first").
///
/// This is the *only* new piece "browse before saving" needs on the Swift side:
/// `Store.days()`/`Store.courses()` etc. already read any `<club_id>.db` that
/// exists, favorited or not (only `Store.clubs()` -- the toolbar's own favorites
/// list -- cares about `clubs/*.yaml`), so once a real scrape lands there via
/// this script, `OverviewModel` can point its existing `clubPath`/`course` at it
/// and every other view (day list, weather, search, heatmap, confirm/cancel)
/// already works unchanged. See `OverviewModel.startPreview()` in App.swift.
enum PreviewClient {
    static func executable() -> String? {
        for candidate in ["/opt/homebrew/bin/teetime-monitor-preview-club",
                          "/usr/local/bin/teetime-monitor-preview-club"]
        where FileManager.default.isExecutableFile(atPath: candidate) {
            return candidate
        }
        let which = Process()
        which.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        which.arguments = ["which", "teetime-monitor-preview-club"]
        let pipe = Pipe(); which.standardOutput = pipe; which.standardError = Pipe()
        try? which.run(); which.waitUntilExit()
        let found = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return found.isEmpty ? nil : found
    }

    /// `done(nil)` on success (something real is now in `<clubID>.db`); a
    /// user-facing message otherwise. Reasons mirror `preview_club_cli.py`'s own
    /// documented JSON contract exactly, same "translate each known `reason`,
    /// fall back to a generic message" shape `DirectoryClient.refresh()` already
    /// uses for its own script.
    static func run(clubID: String, clubName: String, done: @escaping (String?) -> Void) {
        guard let exe = executable() else {
            done(t("error.preview_missing"))
            return
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let task = Process()
            task.executableURL = URL(fileURLWithPath: exe)
            task.arguments = ["--club-id", clubID, "--club-name", clubName]
            let stdout = Pipe(), stderr = Pipe()
            task.standardOutput = stdout; task.standardError = stderr
            do { try task.run() } catch {
                DispatchQueue.main.async { done(error.localizedDescription) }
                return
            }
            task.waitUntilExit()
            let outData = stdout.fileHandleForReading.readDataToEndOfFile()
            DispatchQueue.main.async {
                guard let obj = try? JSONSerialization.jsonObject(with: outData) as? [String: Any] else {
                    let stderrText = String(data: stderr.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                    done(stderrText.isEmpty ? "preview failed (exit \(task.terminationStatus))" : stderrText)
                    return
                }
                if obj["ok"] as? Bool == true {
                    done(nil)
                    return
                }
                switch obj["reason"] as? String {
                case "missing_club_id": done(t("error.generic"))
                case "no_tee_sheet": done(t("error.preview_no_tee_sheet"))
                case "course_fetch_failed":
                    done(t("error.preview_fetch_failed", ["error": obj["error"] as? String ?? "?"]))
                default: done(t("error.generic"))
                }
            }
        }
    }
}
