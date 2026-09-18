import Foundation

/// One (club_id, name) pair from the platform directory.
struct DirectoryEntry: Identifiable {
    var id: String { clubID }
    let clubID: String
    let name: String
}

/// Reads the platform club directory Python already maintains -- the live cache
/// (`club-directory.json` under `~/.local/share/teetime-monitor/`, written by
/// `teetime-monitor-directory-refresh`) or, if that doesn't exist yet, the bundled
/// `club_directory_seed.json` snapshot (copied into this app's own `Resources` by
/// `build.sh` -- a static data file, not logic, so it's copied rather than ported).
/// `search()`/`looksLikeClubID()` below are plain, stable functions over that
/// already-loaded data -- ported directly from `club_directory.py`'s own `search()`/
/// `looks_like_club_id()`, the same "small enough to verify byte-for-byte" call this
/// prototype already made for the day-card weather aggregation formulas. Only the
/// *live, authenticated fetch* that produces the cache stays Python-owned (see
/// `DirectoryClient`) -- searching what's already local needs no subprocess.
enum ClubDirectoryStore {
    enum Source { case live, seed, none }

    private static func cachePath() -> String {
        let home = NSHomeDirectory() as NSString
        let env = ProcessInfo.processInfo.environment["TEETIME_MONITOR_DATA_DIR"]
        let dataDir = (env as NSString?)?.expandingTildeInPath
            ?? home.appendingPathComponent(".local/share/teetime-monitor")
        return dataDir + "/club-directory.json"
    }

    private static func parse(_ path: String) -> (fetchedAt: String?, clubs: [DirectoryEntry])? {
        guard let data = FileManager.default.contents(atPath: path),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        let fetchedAt = obj["fetched_at"] as? String
        let rawClubs = obj["clubs"] as? [[Any]] ?? []
        let clubs = rawClubs.compactMap { pair -> DirectoryEntry? in
            guard pair.count == 2 else { return nil }
            return DirectoryEntry(clubID: "\(pair[0])", name: "\(pair[1])")
        }
        return (fetchedAt, clubs)
    }

    /// A real fetch always wins over the bundled seed -- same precedence
    /// `ClubBrowserScreen.on_mount()` uses (`load_cached_directory()` first,
    /// `load_seed_directory()` only as a fallback when that's empty).
    static func directory() -> (source: Source, fetchedAt: String?, clubs: [DirectoryEntry]) {
        if let (fetchedAt, clubs) = parse(cachePath()), !clubs.isEmpty {
            return (.live, fetchedAt, clubs)
        }
        if let seedPath = Bundle.main.path(forResource: "club_directory_seed", ofType: "json"),
           let (_, clubs) = parse(seedPath), !clubs.isEmpty {
            return (.seed, nil, clubs)
        }
        return (.none, nil, [])
    }

    /// Case-insensitive substring match on the name -- mirrors `search()` exactly,
    /// including "a blank query returns nothing" (the picker shows favorites
    /// instead in that case; this app shows a placeholder, see `AddClubSheet`).
    static func search(_ directory: [DirectoryEntry], query: String, limit: Int = 50) -> [DirectoryEntry] {
        let needle = query.trimmingCharacters(in: .whitespaces).lowercased()
        guard !needle.isEmpty else { return [] }
        return Array(directory.filter { $0.name.lowercased().contains(needle) }.prefix(limit))
    }

    /// A normalized club id if `query` looks like one (bare digits, zero-padded to
    /// 7) or contains a pasted `/clubs/<id>/` URL segment -- mirrors
    /// `looks_like_club_id()`/`_CLUB_ID_RE`/`_CLUB_ID_IN_URL_RE` exactly, letting a
    /// typed id or booking link jump straight to a club with no directory search
    /// and no login needed (the tee sheet for any id is public).
    static func looksLikeClubID(_ query: String) -> String? {
        let candidate = query.trimmingCharacters(in: .whitespaces)
        if let match = firstMatch(in: candidate, pattern: "^\\d{6,7}$") {
            return zfill7(match)
        }
        if let digits = firstCapturedGroup(in: candidate, pattern: "/clubs/(\\d{6,7})(?:/|$|\\?)") {
            return zfill7(digits)
        }
        return nil
    }

    private static func zfill7(_ s: String) -> String {
        String(repeating: "0", count: max(0, 7 - s.count)) + s
    }

    private static func firstMatch(in text: String, pattern: String) -> String? {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return nil }
        let range = NSRange(text.startIndex..., in: text)
        guard let m = regex.firstMatch(in: text, range: range), let r = Range(m.range, in: text) else { return nil }
        return String(text[r])
    }

    private static func firstCapturedGroup(in text: String, pattern: String) -> String? {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return nil }
        let range = NSRange(text.startIndex..., in: text)
        guard let m = regex.firstMatch(in: text, range: range), m.numberOfRanges > 1,
              let r = Range(m.range(at: 1), in: text) else { return nil }
        return String(text[r])
    }
}

/// Shells out to `teetime-monitor-directory-refresh` -- the one genuinely
/// Python-owned piece of add-a-club (a live, authenticated pc caddie fetch). No
/// stdin: nothing here is secret, `--club-id` (when given) is just a hint for which
/// saved credentials to authenticate with, same optional fallback
/// `directory_cli.py` itself documents.
enum DirectoryClient {
    static func executable() -> String? {
        for candidate in ["/opt/homebrew/bin/teetime-monitor-directory-refresh",
                          "/usr/local/bin/teetime-monitor-directory-refresh"]
        where FileManager.default.isExecutableFile(atPath: candidate) {
            return candidate
        }
        let which = Process()
        which.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        which.arguments = ["which", "teetime-monitor-directory-refresh"]
        let pipe = Pipe(); which.standardOutput = pipe; which.standardError = Pipe()
        try? which.run(); which.waitUntilExit()
        let found = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return found.isEmpty ? nil : found
    }

    static func refresh(fallbackClubID: String?, done: @escaping (Int?, String?) -> Void) {
        guard let exe = executable() else {
            done(nil, "teetime-monitor-directory-refresh not found — install it with Homebrew.")
            return
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let task = Process()
            task.executableURL = URL(fileURLWithPath: exe)
            task.arguments = fallbackClubID.map { ["--club-id", $0] } ?? []
            let stdout = Pipe(), stderr = Pipe()
            task.standardOutput = stdout; task.standardError = stderr
            do { try task.run() } catch {
                DispatchQueue.main.async { done(nil, error.localizedDescription) }
                return
            }
            task.waitUntilExit()
            let outData = stdout.fileHandleForReading.readDataToEndOfFile()
            DispatchQueue.main.async {
                guard let obj = try? JSONSerialization.jsonObject(with: outData) as? [String: Any] else {
                    let stderrText = String(data: stderr.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                    done(nil, stderrText.isEmpty ? "refresh failed (exit \(task.terminationStatus))" : stderrText)
                    return
                }
                if obj["ok"] as? Bool == true {
                    done(obj["count"] as? Int ?? 0, nil)
                    return
                }
                switch obj["reason"] as? String {
                case "needs_login": done(nil, "No pc caddie login configured yet — add one in Settings first.")
                case "needs_a_club": done(nil, "Type a club id above, or save a club first, to authenticate with.")
                case "fetch_failed": done(nil, "Couldn't refresh: \(obj["error"] as? String ?? "unknown error")")
                default: done(nil, "Couldn't refresh directory.")
                }
            }
        }
    }
}

/// Shells out to `teetime-monitor-add-club` -- the other genuinely Python-owned
/// piece (saving a favorite includes a best-effort geocoding lookup, see that
/// script's own docstring).
enum AddClubClient {
    static func executable() -> String? {
        for candidate in ["/opt/homebrew/bin/teetime-monitor-add-club", "/usr/local/bin/teetime-monitor-add-club"]
        where FileManager.default.isExecutableFile(atPath: candidate) {
            return candidate
        }
        let which = Process()
        which.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        which.arguments = ["which", "teetime-monitor-add-club"]
        let pipe = Pipe(); which.standardOutput = pipe; which.standardError = Pipe()
        try? which.run(); which.waitUntilExit()
        let found = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return found.isEmpty ? nil : found
    }

    static func add(clubID: String, name: String, done: @escaping (String?, String?) -> Void) {
        guard let exe = executable() else {
            done(nil, "teetime-monitor-add-club not found — install it with Homebrew.")
            return
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let task = Process()
            task.executableURL = URL(fileURLWithPath: exe)
            task.arguments = ["--club-id", clubID, "--name", name]
            let stdout = Pipe(), stderr = Pipe()
            task.standardOutput = stdout; task.standardError = stderr
            do { try task.run() } catch {
                DispatchQueue.main.async { done(nil, error.localizedDescription) }
                return
            }
            task.waitUntilExit()
            let outData = stdout.fileHandleForReading.readDataToEndOfFile()
            DispatchQueue.main.async {
                guard let obj = try? JSONSerialization.jsonObject(with: outData) as? [String: Any] else {
                    let stderrText = String(data: stderr.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                    done(nil, stderrText.isEmpty ? "add failed (exit \(task.terminationStatus))" : stderrText)
                    return
                }
                if obj["ok"] as? Bool == true, let slug = obj["slug"] as? String {
                    done(slug, nil)
                } else {
                    done(nil, "Couldn't save this club.")
                }
            }
        }
    }
}
