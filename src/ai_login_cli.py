"""Headless AI-provider credential save+verify — the Swift GUI's counterpart to
`login_cli.py`, for the `ai_credentials_screen.py` flow (2026-09-26).

Same shape and same reasoning as `login_cli.py`'s own docstring: `AICredentialsScreen`
is the TUI's answer to "set up an AI provider from the UI," and this is the exact same
save-then-verify flow exposed as a `teetime-monitor-ai-login` console script the Swift
app can shell out to instead of reimplementing `.env` writing or any of the four
providers' SDKs itself. Same hybrid rule every other Tier 2 feature follows (see
macos/README.md): real backend logic stays in Python; the Swift app only invokes it and
renders the result.

The API key never passes through argv or an environment variable this process's own
parent could see in `ps` — read from stdin instead, one JSON object
(`{"provider": str, "api_key": str}`). This module doesn't print, log, or echo the key
back either.

Result is one JSON object on stdout, not translated i18n text — same reasoning
`login_cli.py` gives for its own contract:

    {"saved": true, "verified": true}
    {"saved": true, "verified": false, "reason": "invalid_key"}
    {"saved": true, "verified": false, "reason": "network_error", "error": "..."}
    {"saved": false, "reason": "provider_required"}
    {"saved": false, "reason": "unknown_provider"}
    {"saved": false, "reason": "api_key_required"}
    {"saved": false, "reason": "bad_input"}

`provider` is required every call (there's no "keep the existing provider" concept —
picking a provider *is* the action). `api_key` is only required the first time for that
provider; a blank key on a later call means "keep what's already saved for this
provider, just make it the active one" — same as `login_cli.py`'s password field,
applied to "switch to a provider you've already configured before without retyping the
key." Saving still updates the active-provider preference and still runs verification
even when the key itself wasn't rewritten.

Exit code is 0 whenever `saved` is true, regardless of `verified` — matches
`login_cli.py`: verification is informational, not a gate on whether the save
"counts."
"""

import json
import os
import sys

from . import ai_assist, env_file, global_preferences, paths


def main(argv: list[str] | None = None) -> None:
    _ = argv if argv is not None else sys.argv[1:]  # no flags of its own, unlike login_cli.py's --club-id

    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, UnicodeDecodeError):
        print(json.dumps({"saved": False, "reason": "bad_input"}))
        sys.exit(1)

    provider = (payload.get("provider") or "").strip()
    api_key = payload.get("api_key") or ""

    if not provider:
        print(json.dumps({"saved": False, "reason": "provider_required"}))
        sys.exit(1)
    if provider not in ai_assist.PROVIDERS:
        print(json.dumps({"saved": False, "reason": "unknown_provider"}))
        sys.exit(1)

    env_var = ai_assist.PROVIDER_ENV_VARS[provider]
    has_existing_key = bool(env_file.load_env_value(env_var))
    if not api_key and not has_existing_key:
        print(json.dumps({"saved": False, "reason": "api_key_required"}))
        sys.exit(1)

    paths.ensure_dirs()
    if api_key:
        env_file.set_env_values({env_var: api_key})

    prefs = global_preferences.load_preferences()
    ai_config = dict(prefs.get("ai_assist", {}))
    ai_config["provider"] = provider
    prefs["ai_assist"] = ai_config
    global_preferences.save_preferences(prefs)

    # verify_api_key() builds its SDK client from `os.environ`, but this process never
    # loads .env into its own environment (nothing here imports club_config, the only
    # module that calls load_dotenv() -- and even that wouldn't see a key written to
    # the file microseconds ago in *this* run). Same gotcha CredentialsScreen's own
    # docstring calls out for PCC_USER/PCC_PASS, just needed here too since (unlike
    # scraper.login()) the SDK clients read their key from the environment, not a
    # function argument.
    effective_key = api_key or (env_file.load_env_value(env_var) or "")
    os.environ[env_var] = effective_key

    ok, error = ai_assist.verify_api_key(provider)
    if ok:
        print(json.dumps({"saved": True, "verified": True}))
        return
    if error is None:
        print(json.dumps({"saved": True, "verified": False, "reason": "invalid_key"}))
        return
    print(json.dumps({"saved": True, "verified": False, "reason": "network_error", "error": error}))


if __name__ == "__main__":
    main()
