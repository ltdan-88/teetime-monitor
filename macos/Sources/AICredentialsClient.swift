import Foundation

/// Reads which AI provider is currently active and whether it already has a saved
/// key -- mirrors `EnvStore`'s own username-only rule (LoginClient.swift): the key
/// itself is never read back, only whether one exists, since a blank field always
/// means "leave it as-is," never "show me the secret."
enum AICredentialsStore {
    static let providers = ["anthropic", "openai", "gemini", "grok"]

    static func providerEnvVar(_ provider: String) -> String {
        switch provider {
        case "openai": return "OPENAI_API_KEY"
        case "gemini": return "GEMINI_API_KEY"
        case "grok": return "XAI_API_KEY"
        default: return "ANTHROPIC_API_KEY"
        }
    }

    static func providerLabelKey(_ provider: String) -> String { "ai_provider.\(provider)" }

    static func activeProvider() -> String {
        guard let text = try? String(contentsOfFile: Preferences.path(), encoding: .utf8) else { return "anthropic" }
        return YAML.parse(text)["ai_assist"]?["provider"]?.asString ?? "anthropic"
    }

    static func hasSavedKey(_ provider: String) -> Bool {
        guard let text = try? String(contentsOfFile: EnvStore.path(), encoding: .utf8) else { return false }
        let envVar = providerEnvVar(provider)
        for line in text.split(separator: "\n", omittingEmptySubsequences: false) {
            let t = line.trimmingCharacters(in: .whitespaces)
            guard !t.hasPrefix("#"), t.contains("=") else { continue }
            let parts = t.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            guard parts.first == Substring(envVar) else { continue }
            let raw = parts.count > 1 ? String(parts[1]).trimmingCharacters(in: .whitespaces) : ""
            return !raw.isEmpty
        }
        return false
    }
}

/// The `teetime-monitor-ai-login` console script's stdout, parsed -- see
/// `src/ai_login_cli.py`'s own docstring for the exact JSON contract this mirrors.
/// Same three-valued `verified` as `LoginResult` and the same reasoning: `nil` means
/// no answer was attempted or reachable (a network hiccup), not the same as "the key
/// is wrong."
struct AICredentialsResult {
    let saved: Bool
    let verified: Bool?
    let reason: String?
    let error: String?

    var statusText: String {
        if !saved {
            switch reason {
            case "api_key_required": return t("ai_login.api_key_required")
            default: return t("ai_login.save_failed")
            }
        }
        switch verified {
        case true: return t("ai_login.verified")
        case false where reason == "network_error": return t("ai_login.unverified")
        case false: return t("ai_login.rejected")
        default: return t("ai_login.saved")
        }
    }
}

/// Shells out to `teetime-monitor-ai-login`, the Tier 2 console script this app's own
/// AI credentials section uses instead of reimplementing `.env` writing or any of the
/// four providers' SDKs itself (see that script's own docstring) -- same hybrid split
/// `LoginClient` already follows for pc caddie login. The API key goes over the child
/// process's stdin as one JSON object, never argv or an inherited environment
/// variable, so it never shows up in `ps` for this process or its parent.
enum AICredentialsClient {
    static func executable() -> String? { Subprocess.resolve("teetime-monitor-ai-login") }

    /// Returns a handle: `cancel()` terminates the child and `done` is never called.
    @discardableResult
    static func run(provider: String, apiKey: String, timeout: TimeInterval = Subprocess.Timeout.aiVerify,
                    done: @escaping (AICredentialsResult?, String?) -> Void) -> SubprocessHandle {
        let handle = SubprocessHandle()
        guard let exe = executable() else {
            done(nil, t("error.ai_login_missing"))
            return handle
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let payload: [String: String] = ["provider": provider, "api_key": apiKey]
            let input = (try? JSONSerialization.data(withJSONObject: payload)) ?? Data()
            let result: SubprocessResult
            do { result = try Subprocess.run(exe, [], stdin: input, timeout: timeout, handle: handle) } catch SubprocessError.cancelled {
                return
            } catch {
                DispatchQueue.main.async { done(nil, error.localizedDescription) }
                return
            }
            DispatchQueue.main.async {
                guard let json = Subprocess.jsonObject(from: result.stdout) as? [String: Any] else {
                    let stderrText = result.stderrText
                    done(nil, stderrText.isEmpty ? "save failed (exit \(result.status))" : stderrText)
                    return
                }
                done(AICredentialsResult(
                    saved: json["saved"] as? Bool ?? false,
                    verified: json["verified"] as? Bool,
                    reason: json["reason"] as? String,
                    error: json["error"] as? String
                ), nil)
            }
        }
        return handle
    }
}
