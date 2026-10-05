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
    static func executable() -> String? { Subprocess.resolve("teetime-monitor-directory-refresh") }

    /// Returns a handle: `cancel()` terminates the child and `done` is never called.
    @discardableResult
    static func refresh(fallbackClubID: String?, timeout: TimeInterval = Subprocess.Timeout.directory,
                        done: @escaping (Int?, String?) -> Void) -> SubprocessHandle {
        let handle = SubprocessHandle()
        guard let exe = executable() else {
            done(nil, t("error.directory_missing"))
            return handle
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let result: SubprocessResult
            do {
                result = try Subprocess.run(exe, fallbackClubID.map { ["--club-id", $0] } ?? [],
                                            timeout: timeout, handle: handle)
            } catch SubprocessError.cancelled {
                return
            } catch {
                DispatchQueue.main.async { done(nil, error.localizedDescription) }
                return
            }
            DispatchQueue.main.async {
                guard let obj = Subprocess.jsonObject(from: result.stdout) as? [String: Any] else {
                    let stderrText = result.stderrText
                    done(nil, stderrText.isEmpty ? "refresh failed (exit \(result.status))" : stderrText)
                    return
                }
                if obj["ok"] as? Bool == true {
                    done(obj["count"] as? Int ?? 0, nil)
                    return
                }
                switch obj["reason"] as? String {
                case "needs_login": done(nil, t("error.needs_login"))
                case "needs_a_club": done(nil, t("error.needs_a_club"))
                case "fetch_failed": done(nil, t("error.refresh_failed", ["error": obj["error"] as? String ?? "?"]))
                default: done(nil, t("error.generic"))
                }
            }
        }
        return handle
    }
}

/// Shells out to `teetime-monitor-add-club` -- the other genuinely Python-owned
/// piece (saving a favorite includes a best-effort geocoding lookup, see that
/// script's own docstring).
enum AddClubClient {
    static func executable() -> String? { Subprocess.resolve("teetime-monitor-add-club") }

    /// Returns a handle: `cancel()` terminates the child and `done` is never called.
    @discardableResult
    static func add(clubID: String, name: String, timeout: TimeInterval = Subprocess.Timeout.addClub,
                    done: @escaping (String?, String?) -> Void) -> SubprocessHandle {
        let handle = SubprocessHandle()
        guard let exe = executable() else {
            done(nil, t("error.addclub_missing"))
            return handle
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let result: SubprocessResult
            do {
                result = try Subprocess.run(exe, ["--club-id", clubID, "--name", name], timeout: timeout, handle: handle)
            } catch SubprocessError.cancelled {
                return
            } catch {
                DispatchQueue.main.async { done(nil, error.localizedDescription) }
                return
            }
            DispatchQueue.main.async {
                guard let obj = Subprocess.jsonObject(from: result.stdout) as? [String: Any] else {
                    let stderrText = result.stderrText
                    done(nil, stderrText.isEmpty ? "add failed (exit \(result.status))" : stderrText)
                    return
                }
                if obj["ok"] as? Bool == true, let slug = obj["slug"] as? String {
                    done(slug, nil)
                } else {
                    done(nil, t("error.add_failed"))
                }
            }
        }
        return handle
    }
}
