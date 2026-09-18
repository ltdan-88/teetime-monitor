import Foundation

/// Mirrors `user_config.py`'s `load_value()`/`save_value()` exactly — a flat
/// `KEY=value` file, one key updated in place, every other line (including ones this
/// prototype doesn't know about, like `LAST_CLUB_ID=`) left untouched.
enum UserConfig {
    static func path() -> String {
        let env = ProcessInfo.processInfo.environment["TEETIME_MONITOR_CONFIG_DIR"]
        let base = (env as NSString?)?.expandingTildeInPath
            ?? (NSHomeDirectory() as NSString).appendingPathComponent(".config/teetime-monitor")
        return "\(base)/config"
    }

    static func value(_ key: String) -> String? {
        guard let text = try? String(contentsOfFile: path(), encoding: .utf8) else { return nil }
        let prefix = "\(key)="
        for line in text.split(separator: "\n", omittingEmptySubsequences: false) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.hasPrefix(prefix) {
                let v = String(trimmed.dropFirst(prefix.count)).trimmingCharacters(in: .whitespaces)
                return v.isEmpty ? nil : v
            }
        }
        return nil
    }

    static func setValue(_ key: String, _ value: String) throws {
        let prefix = "\(key)="
        // Matches Python's `str.splitlines()`, not a plain split on "\n" -- a file
        // ending in a newline (every file this ever writes) has no trailing empty
        // element in splitlines()'s output, but `split(omittingEmptySubsequences:
        // false)` does produce one. Missing this grew one extra blank line on every
        // single save, caught by writing THEME= twice and diffing the byte count.
        var lines = (try? String(contentsOfFile: path(), encoding: .utf8))?
            .split(separator: "\n", omittingEmptySubsequences: false).map(String.init) ?? []
        if lines.last == "" { lines.removeLast() }
        var replaced = false
        for i in lines.indices where lines[i].trimmingCharacters(in: .whitespaces).hasPrefix(prefix) {
            lines[i] = "\(key)=\(value)"
            replaced = true
        }
        if !replaced { lines.append("\(key)=\(value)") }

        let dir = (path() as NSString).deletingLastPathComponent
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        try (lines.joined(separator: "\n") + "\n").write(toFile: path(), atomically: true, encoding: .utf8)
    }
}
