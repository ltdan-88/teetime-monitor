# Advanced: where things live, scheduled fetching, other ways to install

*[Deutsche Version](ADVANCED.de.md)* · [Back to the README](../README.md)

You don't need any of this to get started. It is here for when you want more.

## Where your data lives

Two fixed folders, so it works from any directory:

```
~/.config/teetime-monitor/            your settings
    clubs/<club-name>.yaml            one file per saved club (club id, weather location, default course, ...)
    .env                              your pc caddie login (readable by you only)
    preferences.yaml                  your rules: hours, party size, weather limits, pace
    config                            theme and language

~/.local/share/teetime-monitor/       what it has collected
    <club_id>.db                      the tee-sheet history, your bookings (SQLite)
    club-directory.json               the cached club list
    backups/                          one gzipped copy per day, the newest seven kept (restore: gunzip)
```

On Windows the same two folders are `%APPDATA%\teetime-monitor` and `%LOCALAPPDATA%\teetime-monitor`. The
portable Windows and Linux downloads keep both inside their own **`userdata`** folder instead, and nowhere
else. `TEETIME_MONITOR_CONFIG_DIR` and `TEETIME_MONITOR_DATA_DIR` move them anywhere you like.

A backup is just a copy of those two folders. Edit your rules in the app (**Preferences**, **Settings**), not by
hand; `clubs/club.example.yaml` in the project documents every setting a club file understands.

Your pc caddie password is stored as plain text in `.env`, readable by your user only — keep that in mind on a
shared or managed computer.

## Keeping the history complete

The app fetches while it is open. But pc caddie deletes past tee sheets, so a day nobody opens the app is a
permanent hole in the crowd heatmap. To fetch unattended as well, run `teetime-monitor-scrape` every 15
minutes (it throttles itself per club, so running it often is fine). The easiest way is a
[Raspberry Pi](RASPBERRY-PI.md), which does it for you. Otherwise:

**Mac** (a launchd agent; adjust the path to what `which teetime-monitor-scrape` prints):

```bash
cat > ~/Library/LaunchAgents/com.teetimemonitor.scrape.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.teetimemonitor.scrape</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/teetime-monitor-scrape</string>
    </array>
    <key>StartInterval</key><integer>900</integer>
    <key>RunAtLoad</key><true/>
    <key>StandardOutPath</key><string>/tmp/teetime-monitor.log</string>
    <key>StandardErrorPath</key><string>/tmp/teetime-monitor.log</string>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.teetimemonitor.scrape.plist
```

An empty log means no errors. Remove it with `launchctl unload ~/Library/LaunchAgents/com.teetimemonitor.scrape.plist`
and delete the file.

**Linux** (cron; use the path `which teetime-monitor-scrape` prints):

```bash
( crontab -l 2>/dev/null; echo '*/15 * * * * /home/you/.local/bin/teetime-monitor-scrape >> /tmp/teetime-monitor.log 2>&1' ) | crontab -
```

**Windows** (a per-user scheduled task, no administrator rights; it runs while you are logged in).
This is for the Scoop/uv install below; the portable download has no background fetching.

```powershell
$exe = Join-Path (uv tool dir --bin) "teetime-monitor-scrape.exe"
$log = Join-Path $env:LOCALAPPDATA "teetime-monitor\scrape.log"
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
$action   = New-ScheduledTaskAction -Execute "conhost.exe" `
              -Argument "--headless cmd.exe /s /c `"`"$exe`" >> `"$log`" 2>&1`""
$trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date) `
              -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
              -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "teetime-monitor-scrape" -Action $action `
    -Trigger $trigger -Settings $settings
# remove again: Unregister-ScheduledTask -TaskName "teetime-monitor-scrape" -Confirm:$false
```

If scraping goes wrong for a while (pc caddie rejects your login, or the tee sheet won't load several times in
a row) the app says so next to "updated … ago". Nothing extra shows while all is well.

## Other ways to install

**Windows with Scoop** (everything in your user profile, no administrator rights):

```powershell
scoop install git uv
uv tool install git+https://github.com/ltdan-88/teetime-monitor
teetime-monitor-web          # the browser version
teetime-monitor              # the terminal version (looks best in Windows Terminal: scoop bucket add extras; scoop install windows-terminal)
```

Update with `uv tool upgrade teetime-monitor`.

**Linux or Mac with pip or uv:**

```bash
uv tool install git+https://github.com/ltdan-88/teetime-monitor
```

**From a copy of the source** (to try changes): `pip install -e .`, then `python -m src.tui` or
`python -m src.webui.server`.

**The portable downloads** (Windows `.zip`, Linux `.tar.gz`) hold their own Python and need no install. To update,
unpack the new version and copy your old `userdata` folder into it. If the Windows download won't start: a
company security product may block programs run from user folders — ask IT to allow the folder, or use a
private PC. Run `TeetimeMonitor.cmd --doctor` (Linux: `./TeetimeMonitor.sh --doctor`) to see what is wrong.
The Linux download needs a 64-bit Intel/AMD system with glibc 2.28 or newer (Debian 10, Ubuntu 20.04, Alma 8
or newer) — not Alpine, not ARM; use Homebrew or pip there.

## Company networks

The app trusts your operating system's certificate store (Windows, macOS), so a company that inspects HTTPS
traffic with its own certificate usually needs nothing extra. Only if you still get a certificate error, point
it at a bundle: on Windows
`[Environment]::SetEnvironmentVariable("SSL_CERT_FILE", "C:\path\to\ca-bundle.pem", "User")` (then open a new
window), elsewhere `export SSL_CERT_FILE=/path/to/ca-bundle.pem`. `teetime-monitor --doctor` shows which
certificate source is in use.

## Health check

`teetime-monitor --doctor` prints a one-page report — version, folders, certificate source, connection to
pc caddie, each club's last fetch, login status (set / not set, never the values) — ready to paste
into a bug report. `--doctor --offline` skips the network check; `--doctor --login-check` also logs in and
compares what a logged-in and an anonymous tee sheet show (for "login works but no player names").

## Privacy and safety

- Your pc caddie login only ever goes to pc caddie's own login form. Weather comes from Open-Meteo (no key,
  nothing about you), club locations from OpenStreetMap, the update check is one plain request to GitHub's
  public release list (switch it off with `TEETIME_MONITOR_NO_UPDATE_CHECK=1`). The weather site you can choose
  under Settings → Display (off unless you choose one) is opened by your browser with the club's coordinates. The
  calendar there (also off until chosen) gets a booking's course, club and times only when you tap its button
  and save the event; a calendar file never leaves your device.
- The browser version on your own computer listens on **127.0.0.1 only**, on a random port. Every request needs
  a random token that only the printed link contains (the page keeps it in a cookie scripts cannot read),
  other host names and other websites are refused, and the page may load nothing from the internet.
- `teetime-monitor-web --serve` (the Raspberry Pi mode) opens it to your home network and asks for a password
  instead. It is plain HTTP: read the security notes in the [Raspberry Pi guide](RASPBERRY-PI.md) and never
  forward a port on your router to it.
- `--keep-running` keeps the browser version alive after you close its window, `--no-browser` only prints the
  link, `--port N` picks the port.
