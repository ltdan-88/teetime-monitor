# Releasing

1. Work on a branch, open a PR. `main` is protected: **lint**, **pytest**, **swift-tests**
   and the three **timezones** jobs must pass before a merge. (`pytest-windows` runs
   nightly/on demand only and is not required.)
2. Bump `version` in `pyproject.toml` (patch for fixes, minor for new user-facing
   capability) in the PR.
3. After merging, tag the merge commit and push the tag:

   ```bash
   git checkout main && git pull
   git tag v0.66.0 && git push origin v0.66.0
   ```

4. `.github/workflows/release.yml` then checks the tag matches `pyproject.toml` and is
   on `main`, publishes a GitHub Release with generated notes, and — if the repository
   secret `TAP_GITHUB_TOKEN` is set — updates the Homebrew formula. Without the secret,
   run it yourself: `scripts/update_tap.sh 0.66.0`.
5. `brew update && brew upgrade teetime-monitor`, then relaunch the app.
6. The same workflow's second job, **mac-app** (macOS runner, after `release`), builds the
   self-contained Mac app for people without Homebrew — see below. It attaches
   `TeetimeMonitor-<version>-arm64.zip` and its `.sha256` to the GitHub Release. If it fails
   the Release and the tap are already out; fix the cause and re-run the failed job (it uses
   `gh release upload --clobber`, so re-running is safe).

`TAP_GITHUB_TOKEN`: a fine-grained personal access token with *Contents: read and
write* on `ltdan-88/homebrew-teetime-monitor`, stored under Settings → Secrets and
variables → Actions.

## The standalone Mac app (no Homebrew)

`macos/build_standalone.sh` builds `macos/dist/TeetimeMonitor-<version>-arm64.zip` (+ `.sha256`),
the download described in [MAC-APP.md](MAC-APP.md): `TeetimeMonitor.app` with its own relocatable
arm64 CPython 3.12 (python-build-standalone, fetched by `uv python install`) and this project
installed into it, non-editable, with its dependencies pinned to `uv.lock` (`uv export --frozen`),
the set CI tests; verification checks the installed versions against the lock. One launcher per `[project.scripts]` entry is generated into
`Contents/Resources/bin` (derived from `pyproject.toml`, nothing hard-coded); the Swift app looks
there first (`Subprocess.resolve`), so it never needs Homebrew paths. Bytecode is precompiled at
build time and the launchers run Python with `-B`, because the signed bundle must never be written
to. The bundle is ad-hoc signed (nested Mach-O files first, then the app) and **not notarized**
(there is no Apple Developer account): the first launch on another Mac needs the Gatekeeper
step documented in MAC-APP.md.

Build and check locally (Apple Silicon Mac, Command Line Tools, [uv](https://docs.astral.sh/uv/)):

```bash
macos/build_standalone.sh      # about 30 s; wipes and rebuilds macos/build-standalone/
macos/verify_standalone.sh     # unzips the newest macos/dist zip and checks it in a clean environment
```

`verify_standalone.sh` runs with an empty `HOME`, `PATH=/usr/bin:/bin` and temporary config/data
folders, and prints a PASS/FAIL summary: signature, `--version`/`--doctor --offline` from the
bundled bin, every launcher, a fixture-database `teetime-monitor-picks` run compared against
`uv run python -m src.picks_cli`, no Homebrew/build-machine paths or non-system library links,
and that the app starts and stays up (via `open -n`, as a friend would; on a CI runner without a
usable GUI session that one check only warns instead of blocking the upload). The `mac-app` job runs both scripts and uploads only when
verification passes. What it cannot check: Gatekeeper's first-launch prompt on a downloaded
(quarantined) copy, and macOS 14 itself — try a release on a second Mac before announcing it.

## The portable Windows app

`python windows/build_portable.py` builds `windows/dist/TeetimeMonitor-<version>-windows-x64.zip`
(+ `.sha256`), the download described in [WINDOWS-APP.md](WINDOWS-APP.md): python.org's embeddable
CPython 3.12 (pinned by URL and SHA-256) plus the `uv.lock` dependencies as `win_amd64` wheels and
this project, with `TeetimeMonitor.cmd` pointing config and data at `userdata\` beside it. It
needs only `uv` and Python, so the assembly can be checked on a Mac; the bytecode step runs on
Windows only. `python windows/verify_portable.py` (Windows only) unpacks the zip into a temp folder
and runs it with a scrubbed PATH and a fake user profile: version, doctor, every module importable,
the TUI starting headless, nothing written outside the folder, x64 binaries only.

The **windows-app** job of the release workflow does both and attaches the zip and its `.sha256` to
the Release (like `mac-app`, re-running it is safe). The **windows-portable** workflow runs the same
build and verify on demand and on pull requests touching `windows/`. What neither can check: the
Mark-of-the-Web / SmartScreen prompt, AppLocker or antivirus policy on a real company PC, and the
interactive console.

The Homebrew path is untouched: `build.sh` only gains an opt-in `TEETIME_MONITOR_SWIFT_TARGET`
(set by `build_standalone.sh` so the binary targets macOS 14 whatever the build machine runs).
