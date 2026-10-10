# Teetime Monitor für Linux — portabel, ohne Installation

*[English version](LINUX-APP.md)*

Ein Tarball zum Entpacken und Starten im Terminal. Kein Python, kein Paketmanager, keine Root-Rechte.

## Starten

1. **TeetimeMonitor-…-linux-x86_64.tar.gz** vom
   [aktuellen Release](https://github.com/ltdan-88/teetime-monitor/releases/latest) herunterladen.
2. Irgendwo entpacken: `tar xzf TeetimeMonitor-*-linux-x86_64.tar.gz`
3. Ein Terminal im neuen Ordner `TeetimeMonitor` öffnen und `./TeetimeMonitor.sh` ausführen.

**Browser-Version:** `./TeetimeMonitor-Web.sh` startet die App stattdessen in einem Browserfenster (siehe
[WEBUI.de.md](WEBUI.de.md)); sie kann alles, was die Terminal-Version kann.

Den ersten Club und den pc-caddie-Login legst du in der App an; sonst funktioniert alles wie in der
Terminal-App aus dem [README](../README.de.md). Ein modernes Terminal (GNOME Terminal, Konsole,
kitty, …) mit Farben und UTF-8 sieht am besten aus.

## Wo deine Daten liegen

Alles — Einstellungen, Logins, Startzeiten-Verlauf — liegt im Ordner **`userdata`** in
`TeetimeMonitor` und sonst nirgends. Wer den Ordner löscht, entfernt jede Spur.

- **Aktualisieren:** neue Version entpacken, dann den alten `userdata`-Ordner hineinkopieren.
- **Passwort:** Dein pc-caddie-Passwort steht als Klartext in `userdata/config/.env`, nur für deinen
  Benutzer lesbar angelegt. Lege den Ordner nicht auf ein gemeinsames Laufwerk.

## Wenn etwas nicht klappt

- `./TeetimeMonitor.sh --doctor` prüft Ordner, Netzwerk, Zertifikate und Login und sagt, was fehlt.
- Gebraucht wird ein 64-Bit-Linux auf Intel/AMD mit **glibc 2.28 oder neuer** (Debian 10, Ubuntu
  20.04, RHEL/Alma 8 oder neuer). **Nicht** für Alpine (musl) und **nicht** für ARM (Raspberry Pi) —
  dort die Homebrew-/pip-Installation aus dem README benutzen.
- Die portable Version hat keinen Hintergrund-Scraper: Bei geschlossener App läuft nichts.

## Was drin steckt (für Neugierige)

`app/python` ist das verschiebbare CPython 3.12 von python-build-standalone plus die Bibliotheken der
App; `TeetimeMonitor.sh` setzt `TEETIME_MONITOR_CONFIG_DIR` und `TEETIME_MONITOR_DATA_DIR` auf
`userdata/` und startet sie im isolierten Modus. Der Release-Job baut sie, prüft sie in einer sauberen
Umgebung (`linux/verify_portable.py`) und startet sie einmal in AlmaLinux 8 (der glibc-Untergrenze);
siehe [RELEASING.md](RELEASING.md).
