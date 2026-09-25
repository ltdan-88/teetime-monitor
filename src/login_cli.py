"""Headless credential save+verify — the Swift prototype's Tier 2 login (2026-09-18).

`CredentialsScreen` (see its own docstring) is the TUI's answer to "I want to setup
credentials from UI" — this is the exact same save-then-optionally-verify flow,
exposed as a `teetime-monitor-login` console script the Swift app can shell out to
instead of reimplementing the save/verify logic itself. Same hybrid rule every other
Tier 2 feature follows (see macos/README.md): real backend logic —
talking to pc caddie, writing `.env` — stays in Python; the Swift app only invokes it
and renders the result.

Credentials never pass through argv or an environment variable this process's own
parent could see in `ps` — read from stdin instead, one JSON object
(`{"username": str, "password": str}`). Same "the tooling never sees or handles the
raw value" rule `credentials_screen.py` already documents; this module doesn't print,
log, or echo either one back either.

Result is one JSON object on stdout, not translated i18n text — so a Swift caller
doesn't need this project's own translation strings to know what happened:

    {"saved": true, "verified": true}
    {"saved": true, "verified": false, "reason": "login_failed"}
    {"saved": true, "verified": null, "reason": "network_error", "error": "..."}
    {"saved": false, "reason": "username_required"}
    {"saved": false, "reason": "password_required"}
    {"saved": false, "reason": "bad_input"}

`saved` mirrors `CredentialsScreen._save()` exactly: username is required every
call; password is only required the first time — a blank password on a later call
means "keep what's already saved," same as the TUI's own password field never
being pre-filled. A rejected or unreachable verification attempt does not roll back
the save — credentials stay written either way, exactly like the TUI, since a failed
verification might just be pc caddie or the network, not proof the credentials
themselves are wrong.

`--club-id` is optional, same reason it's optional in `CredentialsScreen.__init__`
(see its own "verify_against_club_id" docstring note): a genuinely fresh install has
no favorited club yet to verify against, and saving without verifying is still a
real, useful save.

Exit code is 0 whenever `saved` is true, regardless of `verified` — verification is
informational here, same as the TUI showing "Saved" even when verification is
skipped or inconclusive. Exit code 1 only when `saved` is false.
"""

import json
import sys

from . import env_file, paths, scraper


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    club_id = None
    if "--club-id" in argv:
        idx = argv.index("--club-id")
        if idx + 1 < len(argv):
            club_id = argv[idx + 1]

    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, UnicodeDecodeError):
        print(json.dumps({"saved": False, "reason": "bad_input"}))
        sys.exit(1)

    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""

    if not username:
        print(json.dumps({"saved": False, "reason": "username_required"}))
        sys.exit(1)

    has_existing_password = bool(env_file.load_env_value("PCC_PASS"))
    if not password and not has_existing_password:
        print(json.dumps({"saved": False, "reason": "password_required"}))
        sys.exit(1)

    paths.ensure_dirs()
    env_file.set_env_values({"PCC_USER": username, "PCC_PASS": password})

    if club_id is None:
        print(json.dumps({"saved": True, "verified": None}))
        return

    # A blank password here means "keep the existing one" (see module docstring) --
    # re-read what set_env_values() above just left in place so verification tests
    # the credentials that are actually now saved, not an empty string.
    effective_password = password or (env_file.load_env_value("PCC_PASS") or "")
    try:
        client = scraper.login(club_id, username, effective_password)
    except scraper.LoginError:
        print(json.dumps({"saved": True, "verified": False, "reason": "login_failed"}))
        return
    except Exception as exc:  # noqa: BLE001 -- mirrors CredentialsScreen._save()'s own
        # broad catch: a network hiccup isn't the same thing as bad credentials.
        print(json.dumps({"saved": True, "verified": None, "reason": "network_error", "error": str(exc)}))
        return
    client.close()
    print(json.dumps({"saved": True, "verified": True}))


if __name__ == "__main__":
    main()
