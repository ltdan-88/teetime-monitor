# Teetime Monitor für Windows — portabel, ohne Installation

*[English version](WINDOWS-APP.md)*

Eine Zip-Datei zum Entpacken und Starten. Kein Python, kein Scoop, keine Administratorrechte, kein
Installationsprogramm. Läuft auch von einem USB-Stick oder aus einem Ordner auf einem
eingeschränkten Firmen-PC.

## Starten

1. **TeetimeMonitor-…-windows-x64.zip** vom
   [aktuellen Release](https://github.com/ltdan-88/teetime-monitor/releases/latest) herunterladen.
2. Falls Windows den Download als „aus dem Internet“ markiert: Rechtsklick auf die Zip →
   **Eigenschaften** → **Zulassen** ankreuzen → OK. Das muss *vor* dem Entpacken geschehen
   (sonst erben alle Dateien die Markierung und Windows fragt immer wieder nach).
3. Rechtsklick auf die Zip → **Alle extrahieren…** und einen beliebigen Ordner wählen (Desktop,
   Dokumente, USB-Stick).
4. Den Ordner **TeetimeMonitor** öffnen und **TeetimeMonitor.cmd** doppelklicken.
5. Meldet Windows *„Der Computer wurde durch Windows geschützt“*: **Weitere Informationen →
   Trotzdem ausführen**. Die App ist nicht mit einem kostenpflichtigen Zertifikat signiert, deshalb
   kennt Windows sie noch nicht.

**Browser-Version:** Doppelklicke stattdessen **TeetimeMonitor-Web.cmd**, um die App in einem normalen Fenster mit
Schaltflächen zu bekommen (siehe [WEBUI.de.md](WEBUI.de.md)); es kann alles, was die Terminal-Version kann.

Es öffnet sich ein schwarzes Fenster, in dem die App läuft. Im **Windows Terminal** sieht sie
schöner aus (öffnen, `TeetimeMonitor.cmd` hineinziehen, Enter). Den ersten Club und den pc-caddie-
Login legst du in der App an (die Tasten stehen unten im Fenster); sonst funktioniert alles wie in
der Terminal-App aus dem [README](../README.de.md).

## Wo deine Daten liegen

Alles — Einstellungen, Logins, Startzeiten-Verlauf — liegt im Ordner **`userdata`** neben
`TeetimeMonitor.cmd` und sonst nirgends auf dem PC. Wer den Ordner löscht, entfernt jede Spur.

- **Aktualisieren:** neue Version herunterladen und entpacken, dann den alten `userdata`-Ordner
  hineinkopieren.
- **Passwort:** Dein pc-caddie-Passwort steht als Klartext in `userdata\config\.env`. Lege den Ordner
  nur auf ein Laufwerk, das nur du lesen kannst.

## Wenn etwas nicht klappt

- In dem Ordner eine Eingabeaufforderung öffnen und `TeetimeMonitor.cmd --doctor` ausführen: Das
  prüft Ordner, Netzwerk, Zertifikate (es nutzt den Windows-Zertifikatsspeicher, ein Firmen-Proxy
  ist also kein Problem) und den Login und sagt, was fehlt.
- **Das Fenster schließt sich oder nichts passiert:** Ein Sicherheitsprogramm der Firma kann
  Programme blockieren, die aus Benutzerordnern laufen (AppLocker, Virenscanner). Die IT kann den
  Ordner freigeben, oder du nutzt die App auf einem privaten PC. Die Laufzeit ist das signierte
  Python von python.org, keine eigene `.exe` — das hilft bei Freigabelisten, umgeht aber keine
  Richtlinie, die alles blockiert.
- **Komische Kästchen statt Linien:** das Windows Terminal statt des alten Konsolenfensters benutzen.
- Windows 10 oder 11, 64 Bit (auch auf ARM-PCs, die es emulieren). Die portable Version hat
  keinen Hintergrund-Scraper: Bei geschlossenem Fenster läuft nichts.

## Was drin steckt (für Neugierige)

`app\` enthält das eingebettete CPython 3.12 von python.org und die Bibliotheken der App;
`TeetimeMonitor.cmd` setzt `TEETIME_MONITOR_CONFIG_DIR` und `TEETIME_MONITOR_DATA_DIR` auf
`userdata\` und startet `app\python.exe`. Der Release-Job baut sie und prüft sie auf einem sauberen
Windows-Runner (`windows/verify_portable.py`); wie man sie selbst baut, steht in
[RELEASING.md](RELEASING.md).
