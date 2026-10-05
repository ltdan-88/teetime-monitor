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

`TAP_GITHUB_TOKEN`: a fine-grained personal access token with *Contents: read and
write* on `ltdan-88/homebrew-teetime-monitor`, stored under Settings → Secrets and
variables → Actions.
