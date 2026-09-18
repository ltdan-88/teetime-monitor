import Foundation

/// Reads only the *username* half of `.env` -- never the password. Mirrors
/// `CredentialsScreen`'s own rule (see its docstring): the password field is never
/// pre-filled, since a blank password on save means "keep what's already there," so
/// there's never a need to display or retype one that already works. Username isn't
/// secret, so showing it (same as the TUI does) is fine.
enum EnvStore {
    static func path() -> String {
        let home = NSHomeDirectory() as NSString
        let configEnv = ProcessInfo.processInfo.environment["TEETIME_MONITOR_CONFIG_DIR"]
        let configDir = (configEnv as NSString?)?.expandingTildeInPath
            ?? home.appendingPathComponent(".config/teetime-monitor")
        return configDir + "/.env"
    }

    private static func value(for key: String) -> String? {
        guard let text = try? String(contentsOfFile: path(), encoding: .utf8) else { return nil }
        for line in text.split(separator: "\n", omittingEmptySubsequences: false) {
            let t = line.trimmingCharacters(in: .whitespaces)
            guard !t.hasPrefix("#"), t.contains("=") else { continue }
            let parts = t.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            guard parts.first == Substring(key) else { continue }
            let raw = parts.count > 1 ? String(parts[1]).trimmingCharacters(in: .whitespaces) : ""
            return raw.isEmpty ? nil : raw
        }
        return nil
    }

    static func currentUsername() -> String? { value(for: "PCC_USER") }
    static func hasSavedPassword() -> Bool { value(for: "PCC_PASS") != nil }
}

/// The `teetime-monitor-login` console script's stdout, parsed -- see
/// `src/login_cli.py`'s own docstring for the exact JSON contract this mirrors.
/// `verified` is three-valued on purpose: `true`/`false` are a real answer from pc
/// caddie, `nil` means no answer was attempted or reachable (no club to verify
/// against yet, or a network hiccup) -- not the same as "wrong password."
struct LoginResult {
    let saved: Bool
    let verified: Bool?
    let reason: String?
    let error: String?

    /// One line for the status caption -- doesn't depend on this project's own i18n
    /// strings (the CLI deliberately doesn't emit any), just the same underlying
    /// outcomes `CredentialsScreen`'s status line shows.
    var statusText: String {
        if !saved {
            switch reason {
            case "username_required": return t("login.username_required")
            case "password_required": return t("login.password_required")
            default: return t("login.save_failed")
            }
        }
        switch verified {
        case true: return t("login.verified")
        case false: return t("login.rejected")
        case nil where reason == "network_error": return t("login.unverified")
        default: return t("login.saved")
        }
    }
}

/// Shells out to `teetime-monitor-login`, the Tier 2 console script this prototype's
/// login uses instead of reimplementing pc caddie's login form or `.env` writing
/// itself (see that script's own docstring) -- same hybrid split `Scraper` already
/// follows for scraping. Credentials go over the child process's stdin as one JSON
/// object, never argv or an inherited environment variable, so they never show up in
/// `ps` for this process or its parent.
enum LoginClient {
    static func executable() -> String? {
        for candidate in ["/opt/homebrew/bin/teetime-monitor-login", "/usr/local/bin/teetime-monitor-login"]
        where FileManager.default.isExecutableFile(atPath: candidate) {
            return candidate
        }
        let which = Process()
        which.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        which.arguments = ["which", "teetime-monitor-login"]
        let pipe = Pipe(); which.standardOutput = pipe; which.standardError = Pipe()
        try? which.run(); which.waitUntilExit()
        let found = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return found.isEmpty ? nil : found
    }

    /// `clubID` is optional, same reason it's optional in `CredentialsScreen` and in
    /// `login_cli.py` itself -- a fresh install with no saved club yet still has a
    /// real save to make, just without a live pc caddie check against it.
    static func run(username: String, password: String, clubID: String?,
                     done: @escaping (LoginResult?, String?) -> Void) {
        guard let exe = executable() else {
            done(nil, t("error.login_missing"))
            return
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let task = Process()
            task.executableURL = URL(fileURLWithPath: exe)
            task.arguments = clubID.map { ["--club-id", $0] } ?? []
            let stdin = Pipe(), stdout = Pipe(), stderr = Pipe()
            task.standardInput = stdin; task.standardOutput = stdout; task.standardError = stderr
            do { try task.run() } catch {
                DispatchQueue.main.async { done(nil, error.localizedDescription) }
                return
            }
            let payload: [String: String] = ["username": username, "password": password]
            if let data = try? JSONSerialization.data(withJSONObject: payload) {
                stdin.fileHandleForWriting.write(data)
            }
            stdin.fileHandleForWriting.closeFile()
            task.waitUntilExit()
            let outData = stdout.fileHandleForReading.readDataToEndOfFile()
            let errData = stderr.fileHandleForReading.readDataToEndOfFile()
            DispatchQueue.main.async {
                guard let json = try? JSONSerialization.jsonObject(with: outData) as? [String: Any] else {
                    let stderrText = String(data: errData, encoding: .utf8) ?? ""
                    done(nil, stderrText.isEmpty ? "login failed (exit \(task.terminationStatus))" : stderrText)
                    return
                }
                done(LoginResult(
                    saved: json["saved"] as? Bool ?? false,
                    verified: json["verified"] as? Bool,
                    reason: json["reason"] as? String,
                    error: json["error"] as? String
                ), nil)
            }
        }
    }
}
