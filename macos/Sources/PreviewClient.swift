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
    static func executable() -> String? { Subprocess.resolve("teetime-monitor-preview-club") }

    /// `done(nil)` on success (something real is now in `<clubID>.db`); a
    /// user-facing message otherwise. Reasons mirror `preview_club_cli.py`'s own
    /// documented JSON contract exactly, same "translate each known `reason`,
    /// fall back to a generic message" shape `DirectoryClient.refresh()` already
    /// uses for its own script.
    /// Returns a handle: `cancel()` terminates the child and `done` is never called.
    @discardableResult
    static func run(clubID: String, clubName: String, timeout: TimeInterval = Subprocess.Timeout.preview,
                    done: @escaping (String?) -> Void) -> SubprocessHandle {
        let handle = SubprocessHandle()
        guard let exe = executable() else {
            done(t("error.preview_missing"))
            return handle
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let result: SubprocessResult
            do {
                result = try Subprocess.run(exe, ["--club-id", clubID, "--club-name", clubName],
                                            timeout: timeout, handle: handle)
            } catch SubprocessError.cancelled {
                return
            } catch {
                DispatchQueue.main.async { done(error.localizedDescription) }
                return
            }
            let message = parse(result)
            DispatchQueue.main.async { done(message) }
        }
        return handle
    }

    /// Split out of `run()` so it's testable without a subprocess. The result JSON
    /// is the *last* line of stdout: `scrape_once._log()` prints a best-effort
    /// failure (a weather fetch, one course/date) ahead of it, and parsing the whole
    /// of stdout reported "preview failed (exit 0)" for a preview that worked.
    static func parse(_ result: SubprocessResult) -> String? {
        guard let obj = Subprocess.jsonObject(from: result.stdout) as? [String: Any] else {
            let stderrText = result.stderrText
            return stderrText.isEmpty ? "preview failed (exit \(result.status))" : stderrText
        }
        if obj["ok"] as? Bool == true { return nil }
        switch obj["reason"] as? String {
        case "missing_club_id": return t("error.generic")
        case "no_tee_sheet": return t("error.preview_no_tee_sheet")
        case "course_fetch_failed":
            return t("error.preview_fetch_failed", ["error": obj["error"] as? String ?? "?"])
        default: return t("error.generic")
        }
    }
}
