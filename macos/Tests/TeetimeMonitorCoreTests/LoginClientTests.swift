@testable import TeetimeMonitorCore

func runLoginClientTests() {
    Harness.group("LoginClient") {
        AppLanguage.shared.code = "en"  // statusText is translated -- pin the language
        // so this test doesn't depend on what another test group left it as.
        testStatusTextForEveryReasonCode()
        testEnvValuesAreUnquotedLikeDotenv()
    }
}

/// env_file.py single-quotes values python-dotenv would otherwise mangle; the
/// username shown in Settings must be the plain string, not the quoted form.
private func testEnvValuesAreUnquotedLikeDotenv() {
    Harness.checkEqual("a bare value is untouched", EnvStore.unquoted("me@example.com"), "me@example.com")
    Harness.checkEqual("single quotes are removed", EnvStore.unquoted("'golf club'"), "golf club")
    Harness.checkEqual("escaped quote and backslash decode",
                       EnvStore.unquoted(#"'it\'s a\\b'"#), #"it's a\b"#)
    Harness.checkEqual("a lone quote is not a quoted value", EnvStore.unquoted("'"), "'")
}

/// One case per branch of `LoginResult.statusText` -- mirrors the exact outcomes
/// `login_cli.py` can emit (see that script's own JSON contract) and
/// `CredentialsScreen`'s own status line on the Python side.
private func testStatusTextForEveryReasonCode() {
    Harness.checkEqual("missing username",
                        LoginResult(saved: false, verified: nil, reason: "username_required", error: nil).statusText,
                        t("login.username_required"))
    Harness.checkEqual("missing password",
                        LoginResult(saved: false, verified: nil, reason: "password_required", error: nil).statusText,
                        t("login.password_required"))
    Harness.checkEqual("an unrecognized save failure still resolves to something readable",
                        LoginResult(saved: false, verified: nil, reason: "bad_input", error: nil).statusText,
                        t("login.save_failed"))
    Harness.checkEqual("saved and verified",
                        LoginResult(saved: true, verified: true, reason: nil, error: nil).statusText,
                        t("login.verified"))
    Harness.checkEqual("saved but rejected",
                        LoginResult(saved: true, verified: false, reason: "login_failed", error: nil).statusText,
                        t("login.rejected"))
    Harness.checkEqual("saved, network hiccup during verification -- distinct from a rejection",
                        LoginResult(saved: true, verified: nil, reason: "network_error", error: "timeout").statusText,
                        t("login.unverified"))
    Harness.checkEqual("saved, no club to verify against -- plain success",
                        LoginResult(saved: true, verified: nil, reason: nil, error: nil).statusText,
                        t("login.saved"))
}
