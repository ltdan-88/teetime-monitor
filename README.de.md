<h1 align="center">teetime-monitor</h1>

<p align="center">
  <strong>Eine Tee-Zeit zu buchen dauert eine Minute. Die richtige zu finden die ganze Woche.</strong><br>
  Die Startliste deines Golfclubs im Terminal — hält sich selbst aktuell, rechnet Wetter,
  Tageslicht und deine eigenen Vorgaben gleich mit ein und markiert die Zeit, die sich
  lohnt, bevor du überhaupt suchst.
</p>

<p align="center">
  <a href="https://github.com/ltdan-88/teetime-monitor/releases"><img alt="Version" src="https://img.shields.io/github/v/tag/ltdan-88/teetime-monitor?label=version&color=89b4fa"></a>
  <a href="LICENSE"><img alt="Lizenz" src="https://img.shields.io/badge/license-MIT-a6e3a1"></a>
  <img alt="Plattform" src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux-cba6f7">
  <img alt="Sprachen" src="https://img.shields.io/badge/UI-English%20%7C%20Deutsch-f9e2af">
</p>

<p align="center"><a href="README.md">🇬🇧 English</a> · 🇩🇪 <strong>Deutsch</strong></p>

<p align="center"><img src="assets/de/overview.png" alt="Die Wochenübersicht: eine Zeile pro buchbarem Tag, mit Wetter, Auslastung, Terminen und einer Empfehlung"></p>

## Worum es geht

Golfclubs im deutschsprachigen Raum veröffentlichen ihre Startlisten — wer auf
welcher Zeit steht, welche Zeiten noch frei sind — über die Buchungsplattform
**pc caddie**. Diese Listen sind öffentlich, zum Lesen braucht es keinen Login.

`teetime-monitor` liest genau diese Liste und bringt sie ins Terminal. Im Hintergrund
ruft er sie regelmäßig neu ab, ergänzt, was auf der Clubseite selbst fehlt — die
Vorhersage für die einzelne Startzeit, ob die Runde vor Einbruch der Dunkelheit noch
fertig wird, wie voll dieser Wochentag erfahrungsgemäß ist — und hebt die Zeiten
hervor, die zu den Vorgaben passen, die du einmal hinterlegt hast.

**Gebucht wird nichts.** Das Buchen bleibt auf der pc-caddie-Seite. Hier geht es um
den Schritt davor: die passende Zeit überhaupt zu finden — und mitzubekommen, wenn
sich an ihr etwas ändert.

## Wie man damit arbeitet

1. **Starten.** Du landest auf den nächsten buchbaren Tagen, einer pro Zeile.
2. **Spalte „Empf." lesen.** Jeder Tag sagt bereits, was Sache ist: eine empfohlene
   Zeit mit ★, deine bestätigte Buchung, oder warum dort nichts infrage kommt
   („zu dunkel zum Fertigspielen", „keine trockene Tee-Zeit").
3. **Enter auf einem Tag** klappt dessen Startzeiten direkt auf; Enter auf einer Zeit
   markiert sie als deine, sobald du sie auf pc caddie gebucht hast.
4. **Laufen lassen.** Der Rest passiert im Hintergrund. Kommt jemand in deinen Flight,
   füllt sich die Zeit direkt daneben, oder dreht die Vorhersage für deine Runde,
   wartet beim nächsten Start ein Hinweis auf dich.

## Schnellstart

```bash
brew install ltdan-88/teetime-monitor/teetime-monitor
teetime-monitor
```

Club-ID eintippen (oder den pc-caddie-Buchungslink einfügen) — fertig, die Startliste
steht da. Vorher ist nichts einzurichten, und ein Konto braucht es auch nicht: die
Startliste ist öffentlich.

<details>
<summary><strong>Was optional dazukommt — und wofür</strong></summary>

Alles oben funktioniert ohne jede dieser Zutaten. Jede bringt nur etwas dazu:

| Zusatz | Bringt |
|---|---|
| pc-caddie-Login (`l` in der Club-Suche) | Clubs nach Namen durchsuchen, und eigene Buchungen automatisch übernehmen statt sie selbst zu markieren |
| [Anthropic](https://www.anthropic.com/)-API-Key | KI-bewertete Empfehlungen (standardmäßig aus, kostenpflichtig pro Empfehlung) |

**Voraussetzungen:** macOS oder Linux und [Homebrew](https://brew.sh/).

</details>

## Was drin steckt

### Eine Zeile pro Tag, schon ausgewertet

Wetter in eigenen Spalten (Bewölkung, Temperatur, Regen, Wind — über
[Open-Meteo](https://open-meteo.com/), ohne API-Key), ein sechsteiliger Balken für die
Auslastung zwischen 08:00 und 20:00 Uhr, die Termine und Sperrungen des Tages, und die
**Empfehlung**: das Fazit für diesen Tag.

**Enter** klappt einen Tag an Ort und Stelle auf, statt die Wochenansicht zu verlassen.

<p align="center"><img src="assets/de/expanded.png" alt="Ein aufgeklappter Tag mit allen einzelnen Startzeiten und deren Auslastung"></p>

### Vorgaben, die du einmal festlegst

Gruppengröße, die Zeitfenster, die unter der Woche bzw. am Wochenende passen, wie viel
Abstand du zur Gruppe davor und dahinter haben willst. Zeiten, auf die alles zutrifft,
bekommen automatisch ein ★ — für den Normalfall musst du nie suchen. Das gilt global,
nicht pro Club: wann du kannst, hängt schließlich nicht davon ab, welchen Platz du
gerade anschaust.

Ein 🌙 markiert jede Startzeit, deren Runde vor Sonnenuntergang nicht mehr fertig wird —
gerechnet mit deinem eigenen Tempo für 9 oder 18 Loch.

<p align="center"><img src="assets/de/settings.png" alt="Die Einstellungen, nach Verfügbarkeit und Wetter gruppiert"></p>

### Suche für die Ausnahmen

Wenn die üblichen Vorgaben mal nicht gelten — „heute ausnahmsweise zu dritt, ab 15:00
Uhr" — durchsuchst du die bereits geladenen Tage. Die Maske ist aus deinen Vorgaben
vorbelegt, du änderst also ein Feld statt alles neu einzutippen.

<p align="center"><img src="assets/de/search.png" alt="Die Suchmaske mit Treffern, vorbelegt aus den gespeicherten Vorgaben"></p>

### Deine Buchung bleibt im Blick

Sobald eine Zeit als deine markiert ist, wird sie weiter beobachtet: Spieler, die in
deinen Flight dazukommen, die Nachbarzeit, die sich füllt und deinen Abstand auffrisst,
die Vorhersage für genau diese Runde, die sich verschlechtert. Jede dieser Änderungen
wartet beim nächsten Start als Hinweis auf dich; **x** blendet sie aus.

### Eine Auslastungs-Heatmap, sobald Verlauf da ist

Jeder Abruf wird gespeichert, über Wochen entsteht daraus ein Muster: welche Stunden an
welchem Wochentag tatsächlich voll werden. Turnier-, Feiertags- und Ferientage zählen
dabei getrennt, damit ein Montag in den Ferien mit anderen Ferientagen verglichen wird
und nicht mit gewöhnlichen Montagen.

Das Raster stellt Stunden gegen Wochentage: voll eingefärbt, sobald genug Messwerte für
eine Aussage da sind, gedimmt, solange es noch zu wenige sind, leer, wo noch nichts
erfasst wurde. Die Tabellen darüber zeigen, wie weit jeder Wochentag schon ist.

<p align="center"><img src="assets/de/heatmap.png" alt="Die Auslastungs-Heatmap: Datenstand-Tabellen über dem farbigen Raster aus Stunden und Wochentagen"></p>

### Ein Menü, zwei Sprachen, zehn Designs

**t** öffnet die **Aktionen** — Club suchen, Suchen, Auslastung, Einstellungen, Sprache,
Design. Die gesamte Oberfläche läuft auf Deutsch oder Englisch (inklusive dieses Menüs
und aller Hinweise) und bringt dieselben zehn Farbdesigns mit wie
[`brew-launcher`](https://github.com/ltdan-88/brew-launcher).

<p align="center"><img src="assets/de/actions.png" alt="Das Aktionen-Menü: Club suchen, Suchen, Auslastung, Einstellungen"></p>

## Tasten

Fast alles steckt hinter **t**. Diese Tasten lohnt es sich zu kennen:

| Taste | Wirkung | Wo |
|---|---|---|
| **Enter** | Tag aufklappen · Tee-Zeit als gebucht oder storniert markieren | Übersicht |
| **r** | Das gesamte geladene Fenster sofort neu abrufen | Übersicht |
| **x** | Hinweise ausblenden | Übersicht |
| **t** / **Strg+P** | Aktionen — alles Weitere | Übersicht |
| **Esc** | Zurück (zu den Aktionen, wenn du von dort kamst) | überall |
| **q** | Beenden | überall |
| **f** · **r** · **l** | Club favorisieren · Verzeichnis aktualisieren · Login einrichten | Club-Suche |

`teetime-monitor --version` gibt die Version aus; sie steht außerdem durchgehend im Kopf
der Anwendung.

## Konfiguration

Nichts davon ist nötig — der Schnellstart oben kommt ohne Einrichtung aus.

<details>
<summary><strong>Dateien, geplanter Abruf, Start aus dem Quellcode</strong></summary>

Der Zustand liegt an zwei festen Orten — die Anwendung läuft damit aus jedem
Verzeichnis, und eine grafische Oberfläche findet ihn ebenfalls (eine App, die aus
dem Finder gestartet wird, hat kein brauchbares Arbeitsverzeichnis). Beide lassen
sich mit `TEETIME_MONITOR_CONFIG_DIR` / `TEETIME_MONITOR_DATA_DIR` überschreiben.

```
~/.config/teetime-monitor/
    clubs/<club-id>.yaml    # pro Club: Koordinaten, overview_days, Standardplatz
    .env                    # PCC_USER / PCC_PASS / ANTHROPIC_API_KEY
    preferences.yaml        # Verfügbarkeit, Wetter, KI, Tempo, Intervall
    config                  # THEME=, LANG=

~/.local/share/teetime-monitor/
    <club_id>.db            # Abruf-Verlauf, bestätigte Buchungen (SQLite)
    club-directory.json     # zwischengespeicherte Clubliste
```

Umstieg von vor v0.31.0? Beim ersten Start werden `./clubs`, `./data` und `./.env`
automatisch übernommen — mit Hinweis, was kopiert wurde. Kopiert, nicht verschoben:
das alte Verzeichnis bleibt als Sicherung liegen, bis du es löschst.

Verfügbarkeit und Vorgaben bearbeitest du über **Aktionen → Einstellungen**, nicht von
Hand. `f` auf einem Club legt dessen YAML an; `clubs/club.example.yaml` ist die
kommentierte Vorlage (Wetter-Koordinaten, Länderkürzel für Feiertage, Ferienzeiträume).

### Damit der Verlauf lückenlos bleibt

Solange die Anwendung läuft, ruft sie selbst ab — pc caddie löscht vergangene
Startlisten allerdings, jeder Tag ohne Abruf ist also eine dauerhafte Lücke in der
Heatmap. Für den Abruf im Hintergrund (macOS, alle 15 Minuten, pro Club selbst
gedrosselt):

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
    <key>StandardOutPath</key><string>~/Library/Logs/teetime-monitor.log</string>
    <key>StandardErrorPath</key><string>~/Library/Logs/teetime-monitor.log</string>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.teetimemonitor.scrape.plist
```

Kein `WorkingDirectory` nötig: seit v0.31.0 liest und schreibt der Scraper dieselben
festen Orte wie die App — `~/.config/teetime-monitor/` (Clubs, Login) und
`~/.local/share/teetime-monitor/` (Verlauf) — er läuft also von überall.

Leeres Log heißt: keine Fehler. Entfernen mit `launchctl unload …` und dem Löschen der
plist-Datei.

### Aus dem Quellcode

```bash
pip install -e .
python -m src.tui
```

</details>

## Projektstruktur

<details>
<summary><strong>Aufbau der Module</strong></summary>

```
src/
├── tui.py                    # die Anwendung -- Club-Suche, Übersicht, Suche, Heatmap
├── scraper.py                # Abruf, Login, Auswertung der Startliste
├── scrape_once.py            # geplanter Abruf + Abgleich mit „Meine Reservierungen"
├── storage.py                # SQLite-Persistenz
├── search.py / recommend.py  # harte Filter, dann Wetter/Tageslicht + KI-Bewertung
├── ai_assist.py              # die drei Claude-Aufrufe (einordnen, bewerten, zusammenfassen)
├── weather.py                # Open-Meteo-Client
├── booking_watch.py          # hat sich an einer bestätigten Buchung etwas geändert?
├── playability.py            # wird diese Runde vor Sonnenuntergang fertig?
├── analytics.py              # Auslastungs-Heatmap + Datenstand
├── calendar_context.py       # Feiertage + Ferien -> Tagtyp
├── settings_screen.py        # Einstellungen (in der App oder eigenständig)
├── credentials_screen.py     # Login (in der App oder eigenständig)
├── club_config.py            # Favoriten
├── club_directory.py         # Club-Verzeichnis im Cache + ID-Erkennung
├── geocode.py                # Standortsuche für einen neuen Club
├── global_preferences.py     # die gemeinsame Vorgaben-Datei
├── theme.py / i18n.py        # Designs; deutsche/englische Oberflächentexte
├── units.py                  # metrisch/imperial
└── models.py                 # Slot / Schedule / WeatherPoint / ConfirmedBooking
```

`ROADMAP.md` enthält die vollständige Entstehungsgeschichte, inklusive der Gründe, warum
einiges so gebaut wurde, wie es gebaut ist.

</details>

## Wenn etwas klemmt

**„No tee sheet found" bei einem Club, den es wirklich gibt.** Manche Clubs
veröffentlichen über pc caddie schlicht keine Startliste — das wird sauber gemeldet und
nicht als Fehler. Club-ID am besten mit dem eigenen Buchungslink abgleichen.

**Das Wetter stimmt nicht.** Die Koordinaten stammen aus einer Namenssuche bei
OpenStreetMap und werden nach dem ersten Treffer zwischengespeichert — nah dran, aber
nicht zwingend das Clubhaus selbst. Exakt wird es über `location:` in
`clubs/<id>.yaml`.

**Eine Buchung taucht nicht auf.** Bestätigte Buchungen kommen bei jedem geplanten
Abruf aus „Meine Reservierungen", nicht in Echtzeit — **r** erzwingt es sofort. Eine
Stornierung auf der echten Seite wird genauso erkannt.

**Die KI-Bewertung tut nichts.** Sie ist standardmäßig aus (Einstellungen →
KI-Bewertung) und braucht ohnehin `ANTHROPIC_API_KEY` in der `.env`.

**In der Heatmap steht überall „Noch keine Daten".** Auf einer frischen Installation
normal — sie braucht ein paar Wochen Abrufe. Die Tabellen zeigen, wie weit es ist.

## Zugangsdaten

Die `.env` steht in `.gitignore`, und die Zugangsdaten gehen ausschließlich an das
Login-Formular von pc caddie. Ein Login deckt alle Clubs desselben Kontos ab. Die
club-eigenen Dateien unter `clubs/` sind ebenfalls ausgenommen, bis auf die versionierte
Vorlage.

## Lizenz

[MIT](LICENSE)
