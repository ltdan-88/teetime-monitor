# Releasing

1. Work on a branch, open a PR. `main` is protected: **lint**, **pytest**
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
6. The same workflow's **windows-app** and **linux-app** jobs then build the portable downloads (below)
   and attach them to the Release. If one fails the Release and the tap are already out; fix the cause and
   re-run the failed job (they use `gh release upload --clobber`, so re-running is safe).

`TAP_GITHUB_TOKEN`: a fine-grained personal access token with *Contents: read and
write* on `ltdan-88/homebrew-teetime-monitor`, stored under Settings → Secrets and
variables → Actions.

## The portable Windows app

`python windows/build_portable.py` builds `windows/dist/TeetimeMonitor-<version>-windows-x64.zip`
(+ `.sha256`), the download described in the [README](../README.md#get-started): python.org's embeddable
CPython 3.12 (pinned by URL and SHA-256) plus the `uv.lock` dependencies as `win_amd64` wheels and
this project, with `TeetimeMonitor.cmd` pointing config and data at `userdata\` beside it. It
needs only `uv` and Python, so the assembly can be checked on a Mac; the bytecode step runs on
Windows only. `python windows/verify_portable.py` (Windows only) unpacks the zip into a temp folder
and runs it with a scrubbed PATH and a fake user profile: version, doctor, every module importable,
the TUI starting headless, nothing written outside the folder, x64 binaries only.

The **windows-app** job of the release workflow does both and attaches the zip and its `.sha256` to
the Release (re-running it is safe). The **windows-portable** workflow runs the same
build and verify on demand and on pull requests touching `windows/`. What neither can check: the
Mark-of-the-Web / SmartScreen prompt, AppLocker or antivirus policy on a real company PC, and the
interactive console.

## The portable Linux app

`python linux/build_portable.py` builds `linux/dist/TeetimeMonitor-<version>-linux-x86_64.tar.gz`
(+ `.sha256`), the download described in the [README](../README.md#get-started): python-build-standalone's
CPython 3.12 (pinned by URL and SHA-256) plus the `uv.lock` dependencies as manylinux x86_64 wheels
and this project, with `TeetimeMonitor.sh` pointing config and data at `userdata/` beside it (the
bytecode step runs on Linux only). `python linux/verify_portable.py` (Linux only) unpacks it with a
scrubbed environment and checks version, doctor, imports, a headless TUI start, that nothing is
written outside the folder and that every ELF file is x86-64.

The **linux-app** job of the release workflow does both, runs the launcher once inside AlmaLinux 8
(glibc 2.28, the oldest system the wheels support) and attaches the tarball and its `.sha256` to the
Release. The **linux-portable** workflow does the same on demand and on pull requests touching
`linux/`. Not covered: other distributions, and the interactive terminal.
