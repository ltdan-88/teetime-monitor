# Teetime Monitor auf einem Raspberry Pi (Webserver für zu Hause)

*[English version](RASPBERRY-PI.md)*

Ein Raspberry Pi, der immer läuft, kann Teetime Monitor für den ganzen Haushalt betreiben: Er holt die
Tee-Sheets selbstständig ab (wie der Hintergrund-Agent auf dem Mac), und jedes Handy, Tablet und jeder Computer
im Heimnetz öffnet dieselbe [Web-Oberfläche](WEBUI.de.md) im Browser, hinter einem Passwort. Auf diesen Geräten
läuft nichts.

**Voraussetzungen:** ein Raspberry Pi 3, 4, 5 oder Zero 2 W mit **64-Bit**-Raspberry-Pi-OS „Bookworm“ (12) oder
neuer (Python 3.11+) im Netzwerk, und die Zeitzone des Pi passend zum Club (`sudo raspi-config` >
Localisation). Etwa 400 MB Speicher. Jeder andere dauerhaft laufende Debian-/Ubuntu-Rechner geht genauso.

## Installieren

Auf dem Pi (per SSH oder Terminal), als normaler Benutzer:

```bash
curl -fsSL https://raw.githubusercontent.com/ltdan-88/teetime-monitor/main/deploy/raspberry-pi/install.sh | bash
```

Das Skript installiert die neueste Version in eine eigene Python-Umgebung
(`~/.local/share/teetime-monitor-server`), fragt nach einem **Passwort** und richtet einen Dienst ein, der beim
Start des Pi hochfährt und nach einem Absturz neu startet. Am Ende nennt es die Adressen, etwa
`http://raspberrypi.local:8765`. Optionen: `--port 9000`, `--version v0.78.0`, `--no-service` (selbst starten),
`--no-password`. Zum Aktualisieren einfach noch einmal ausführen.

Danach von einem beliebigen Gerät im Netz: Adresse öffnen, mit dem Passwort anmelden und wie auf jedem Computer
einrichten: **Einstellungen > pc-caddie-Login**, Clubs hinzufügen (**Club hinzufügen**), optional den KI-Schlüssel.
Der erste Abruf läuft innerhalb weniger Minuten; **Aktualisieren** startet ihn sofort. Einstellungen liegen auf
dem Pi in `~/.config/teetime-monitor`, die Daten in `~/.local/share/teetime-monitor`.

## So funktioniert es

- `teetime-monitor-web --serve` lauscht im Netzwerk (Standard-Port 8765) und läuft dauerhaft. Alle paar Minuten
  prüft es jeden gespeicherten Club und holt, was nach dessen Abruf-Intervallen (Einstellungen > Abruf) fällig
  ist, erkennt Buchungsänderungen und legt die Tagessicherung an (die neuesten 7 bleiben).
- Handy oder Tablet öffnen einfach die Adresse; zum Startbildschirm hinzugefügt, wirkt es wie eine App. Das
  Layout passt sich an Handys und Tablets an.
- Das Passwort setzt `teetime-monitor-web --set-password`, später änderst du es unter **Einstellungen > Server-Passwort**. Es wird nur als gesalzener Hash in
  `~/.config/teetime-monitor/web_auth.json` gespeichert (nur für dich lesbar). Eine Anmeldung gilt im Browser 30
  Tage (**Ansicht > Abmelden** beendet sie); ein neues Passwort meldet alle Browser ab. Fünf falsche Versuche
  sperren das Gerät 30 Sekunden, jedes weitere Mal doppelt so lange.

## Aktualisierungen

Einmal am Tag schaut der Server in GitHubs öffentliche Release-Liste (eine einfache Anfrage, nichts über dich wird
gesendet). Gibt es eine neuere Version, zeigt jede Seite unten **Version X ist verfügbar** mit einem Link zu den
Release-Notes. Auf dem Pi installiert **Jetzt aktualisieren** (in derselben Zeile) diese Version in die eigene
Umgebung des Servers und startet den Dienst neu; die Seite verbindet sich von selbst wieder. Installiert wird nur
die Version, die der Server selbst gefunden hat, von der GitHub-Seite dieses Projekts. Schlägt eine Aktualisierung
fehl, läuft die alte Version weiter und die Seite nennt den Grund. Die tägliche Abfrage schaltest du aus mit
`Environment=TEETIME_MONITOR_NO_UPDATE_CHECK=1` im Dienst (`sudo systemctl edit teetime-monitor`). Ein mit 0.78.0
installierter Server bekommt den Knopf nach einem weiteren Lauf des Installationsbefehls.

## Sicherheit: bitte lesen

- Es ist **unverschlüsseltes HTTP im Heimnetz**. Jeder im WLAN erreicht die Anmeldeseite, und wer den
  WLAN-Verkehr mitlesen kann, könnte das Passwort sehen. Nimm ein Passwort, das du nirgends sonst benutzt, und
  lass Gäste im Gast-WLAN.
- Hinter dem Passwort liegen dein pc-caddie-Login und der KI-Schlüssel (der Server braucht sie zum Abrufen).
  Leite keinen Port am Router dorthin weiter.
- **Von unterwegs** erreichst du ihn über ein VPN ins Heimnetz: [Tailscale](https://tailscale.com) ist der
  einfachste Weg (auf Pi und Handy installieren, keine Router-Einstellungen), oder WireGuard.

## Alltag

| | |
|---|---|
| Läuft es? | `systemctl status teetime-monitor` |
| Protokoll | `journalctl -u teetime-monitor -n 50` (mit `-f` live) |
| Neustart / Stopp | `sudo systemctl restart teetime-monitor` / `sudo systemctl stop teetime-monitor` |
| Passwort ändern | in der Seite: **Einstellungen > Server-Passwort** (aktuelles Passwort, neues zweimal; dieser Browser bleibt angemeldet, jedes andere Gerät muss sich neu anmelden). Oder auf dem Pi: `~/.local/share/teetime-monitor-server/venv/bin/teetime-monitor-web --set-password` (auch bei vergessenem Passwort) |
| Aktualisieren | Die Seite zeigt unten „Version X ist verfügbar · Jetzt aktualisieren“; ein Klick installiert sie und startet den Server neu (ein bis zwei Minuten). Oder den Installationsbefehl noch einmal ausführen |
| Entfernen | `sudo systemctl disable --now teetime-monitor; sudo rm /etc/systemd/system/teetime-monitor.service; rm -rf ~/.local/share/teetime-monitor-server` (Einstellungen und Daten bleiben in `~/.config` und `~/.local/share`) |

**Sichern:** `~/.config/teetime-monitor` (Einstellungen, Logins) und `~/.local/share/teetime-monitor` (Verlauf);
beide Ordner zu kopieren ist eine vollständige Sicherung. Die SD-Karte ist der Schwachpunkt jedes Pi: eine gute
Karte (oder eine SSD) und gelegentlich eine Kopie der Ordner lohnen sich.

## Wenn etwas nicht klappt

- **Die Adresse öffnet sich nicht.** Die Zahlen-Adresse aus dem Installer probieren (`http://192.168.x.x:8765`);
  `raspberrypi.local` braucht mDNS (in macOS, iOS und neuem Windows/Android eingebaut, in manchen Netzen
  nicht). Dienst prüfen: `systemctl status teetime-monitor`.
- **„Address already in use“.** Ein anderes Programm belegt den Port: mit `--port 9000` installieren.
- **Falsche Uhrzeiten.** Zeitzone des Pi einstellen (siehe oben).
- **„Login abgelehnt“ oder keine Spielernamen.** Das ist der pc-caddie-Login: Einstellungen > pc-caddie-Login.
- **Neueres Python nötig** (älteres Raspberry-Pi-OS): Betriebssystem auf Bookworm oder neuer aktualisieren.
