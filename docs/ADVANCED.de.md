# Fortgeschritten: wo die Daten liegen, geplanter Abruf, andere Installationen

*[English version](ADVANCED.md)* · [Zurück zur README](../README.de.md)

Für den Anfang brauchst du davon nichts. Es ist für den Fall, dass du mehr willst.

## Wo deine Daten liegen

Zwei feste Ordner, damit es aus jedem Verzeichnis funktioniert:

```
~/.config/teetime-monitor/            deine Einstellungen
    clubs/<club-name>.yaml            eine Datei pro gespeichertem Club (Club-ID, Wetterort, Standardplatz, ...)
    .env                              dein pc-caddie-Login und KI-Schlüssel (nur für dich lesbar)
    preferences.yaml                  deine Vorgaben: Zeiten, Gruppengröße, Wettergrenzen, Tempo
    config                            Farbschema und Sprache

~/.local/share/teetime-monitor/       was gesammelt wurde
    <club_id>.db                      der Verlauf der Startlisten, deine Buchungen (SQLite)
    club-directory.json               die gespeicherte Clubliste
    backups/                          eine Kopie pro Tag, die neuesten sieben bleiben
```

Unter Windows sind es `%APPDATA%\teetime-monitor` und `%LOCALAPPDATA%\teetime-monitor`. Die portablen Downloads für
Windows und Linux legen beides stattdessen in ihren eigenen Ordner **`userdata`** und sonst nirgends hin.
`TEETIME_MONITOR_CONFIG_DIR` und `TEETIME_MONITOR_DATA_DIR` verschieben sie, wohin du willst.

Eine Sicherung ist einfach eine Kopie dieser beiden Ordner. Deine Vorgaben änderst du in der App (**Präferenzen**,
**Einstellungen**), nicht von Hand; `clubs/club.example.yaml` im Projekt beschreibt jede Einstellung, die eine
Club-Datei kennt.

Dein pc-caddie-Passwort steht im Klartext in der `.env`, nur für deinen Benutzer lesbar — denk daran auf einem
gemeinsam genutzten oder verwalteten Rechner.

## Den Verlauf lückenlos halten

Die App ruft ab, solange sie offen ist. Aber pc caddie löscht vergangene Startlisten, ein Tag, an dem niemand die App
öffnet, ist also eine dauerhafte Lücke in der Heatmap. Um auch unbeaufsichtigt abzurufen, lass `teetime-monitor-scrape`
alle 15 Minuten laufen (es bremst sich pro Club selbst, häufiges Starten ist also in Ordnung). Am einfachsten macht das
ein [Raspberry Pi](RASPBERRY-PI.de.md). Sonst:

**Mac** (ein launchd-Agent; den Pfad anpassen an die Ausgabe von `which teetime-monitor-scrape`):

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

Ein leeres Log heißt: keine Fehler. Entfernen mit `launchctl unload ~/Library/LaunchAgents/com.teetimemonitor.scrape.plist`
und die Datei löschen.

**Linux** (cron; den Pfad nehmen, den `which teetime-monitor-scrape` ausgibt):

```bash
( crontab -l 2>/dev/null; echo '*/15 * * * * /home/du/.local/bin/teetime-monitor-scrape >> /tmp/teetime-monitor.log 2>&1' ) | crontab -
```

**Windows** (ein geplanter Auftrag pro Benutzer, ohne Administratorrechte; er läuft, solange du angemeldet bist).
Das gilt für die Scoop/uv-Installation unten; der portable Download ruft nicht im Hintergrund ab.

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
# wieder entfernen: Unregister-ScheduledTask -TaskName "teetime-monitor-scrape" -Confirm:$false
```

Geht beim Abruf länger etwas schief (pc caddie lehnt deinen Login ab, oder die Startliste lädt mehrere Male hintereinander
nicht), sagt die App das neben „aktualisiert vor …“. Solange alles gut ist, steht dort nichts Extra.

## Andere Wege der Installation

**Windows mit Scoop** (alles in deinem Benutzerprofil, ohne Administratorrechte):

```powershell
scoop install git uv
uv tool install git+https://github.com/ltdan-88/teetime-monitor
teetime-monitor-web          # die Browser-Version
teetime-monitor              # die Terminal-Version (sieht im Windows Terminal am besten aus: scoop bucket add extras; scoop install windows-terminal)
```

Aktualisieren mit `uv tool upgrade teetime-monitor`.

**Linux oder Mac mit pip oder uv:**

```bash
uv tool install git+https://github.com/ltdan-88/teetime-monitor
```

**Aus einer Kopie des Quelltexts** (um Änderungen auszuprobieren): `pip install -e .`, dann `python -m src.tui` oder
`python -m src.webui.server`.

**Die portablen Downloads** (Windows `.zip`, Linux `.tar.gz`) bringen ihr eigenes Python mit und brauchen keine Installation.
Zum Aktualisieren die neue Version entpacken und den alten Ordner `userdata` hineinkopieren. Startet der Windows-Download
nicht: Ein Sicherheitsprodukt der Firma blockiert vielleicht Programme aus Benutzerordnern — die IT bitten, den Ordner
freizugeben, oder einen privaten PC nehmen. `TeetimeMonitor.cmd --doctor` (Linux: `./TeetimeMonitor.sh --doctor`) zeigt,
was nicht stimmt. Der Linux-Download braucht ein 64-Bit-Intel/AMD-System mit glibc 2.28 oder neuer (Debian 10, Ubuntu 20.04,
Alma 8 oder neuer) — nicht Alpine, nicht ARM; dort Homebrew oder pip nehmen.

## Firmennetze

Die App vertraut dem Zertifikatsspeicher deines Betriebssystems (Windows, macOS); eine Firma, die HTTPS-Verkehr mit einem
eigenen Zertifikat prüft, braucht deshalb meist nichts Zusätzliches. Nur wenn du trotzdem einen Zertifikatsfehler bekommst,
zeige auf ein Bündel: unter Windows
`[Environment]::SetEnvironmentVariable("SSL_CERT_FILE", "C:\pfad\ca-bundle.pem", "User")` (danach ein neues Fenster öffnen),
sonst `export SSL_CERT_FILE=/pfad/ca-bundle.pem`. `teetime-monitor --doctor` zeigt, welche Zertifikatsquelle gilt.

## Gesundheitscheck

`teetime-monitor --doctor` gibt einen Ein-Seiten-Bericht aus — Version, Ordner, Zertifikatsquelle, Verbindung zu pc caddie,
der letzte Abruf jedes Clubs, Stand von Login und KI-Schlüssel (gesetzt / nicht gesetzt, nie die Werte) — bereit zum Einfügen
in eine Fehlermeldung. `--doctor --offline` überspringt die Netzwerkprüfung; `--doctor --login-check` meldet sich zusätzlich an
und vergleicht, was eine angemeldete und eine anonyme Startliste zeigen (für „Login klappt, aber keine Spielernamen“).

## Datenschutz und Sicherheit

- Dein pc-caddie-Login geht nur an das Anmeldeformular von pc caddie selbst. Das Wetter kommt von Open-Meteo (ohne Schlüssel,
  nichts über dich), Club-Standorte von OpenStreetMap, die Update-Prüfung ist eine einfache Anfrage an GitHubs öffentliche
  Release-Liste (abschalten mit `TEETIME_MONITOR_NO_UPDATE_CHECK=1`). Ein KI-Anbieter wird nur gefragt, wenn du die
  KI-Sortierung einschaltest und einen Schlüssel angibst.
- Die Browser-Version auf deinem eigenen Rechner hört **nur auf 127.0.0.1**, an einem zufälligen Port. Jede Anfrage braucht
  ein zufälliges Token, das nur der ausgegebene Link enthält (die Seite hält es in einem Cookie, das Skripte nicht lesen
  können); andere Hostnamen und andere Websites werden abgewiesen, und die Seite darf nichts aus dem Internet laden.
- `teetime-monitor-web --serve` (der Raspberry-Pi-Modus) öffnet sie für dein Heimnetz und fragt stattdessen nach einem Passwort.
  Es ist einfaches HTTP: lies die Sicherheitshinweise in der [Raspberry-Pi-Anleitung](RASPBERRY-PI.de.md) und leite nie einen
  Port deines Routers dorthin weiter.
- `--keep-running` hält die Browser-Version am Leben, wenn du das Fenster schließt, `--no-browser` gibt nur den Link aus,
  `--port N` wählt den Port.
