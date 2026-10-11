# Die Browser-Version (Web-Oberfläche)

*[English version](WEBUI.md)*

Eine grafische Version von Teetime Monitor, die in einem Browserfenster läuft, für Windows und Linux (der
Mac hat seine eigene native App; es läuft auch auf dem Mac). Dieselben Daten und Empfehlungen wie die Terminal-App, im dunklen
Karten-Layout der Mac-App (hell, wenn dein System hell ist), auf Deutsch oder Englisch.

**Stand: vollständig.** Alles, was die Mac-App kann, ist hier:

- **Übersicht:** Club und Platz wählen; jeder Tag mit Wetter, empfohlener Auswahl, deiner Buchung oder der Zeit,
  zu der die Buchung öffnet, und Belegungsbalken. Die Tage starten eingeklappt (wie in der Mac-App); ein geöffneter Tag zeigt jede Startzeit mit Spielern (Freunde mit
  ★, Namen nach Geschlecht gefärbt, auf Wunsch mit Handicap), Wetter je Zeit und Sonnenauf-/-untergang. Eine Zeit
  anklicken markiert sie als deine Buchung, deine Buchung anklicken storniert sie. Hinweise („ein Spieler ist
  deinem Flight beigetreten“) erscheinen oben.
  Beginnt dein Zeitfenster an mehreren Tagen zu spät für eine ganze Runde, sagt das eine Zeile (mit den Zahlen
  und einem Knopf zu den Präferenzen); an einem Tag, an dem nur eine kürzere Runde auf einem anderen Platz
  passt, erscheint diese Zeit als Badge – ein Klick wechselt zu diesem Platz. In **Spieler** springt der
  Knopf „Nächste Tee-Zeit“ (oder ein Doppelklick) zur Tee-Zeit dieses Spielers, bei Bedarf mit Platzwechsel. Die
  Wetterspalten haben Überschriften (°C, Regen, Wind) und Tooltips, die Einstellungs-Karten gleichen ihre Spalten aus.
- **Suche**, **Crowd-Heatmap**, **Spieler** (Freunde), **Präferenzen** (Verfügbarkeit, Wetter, Tempo, Prioritäten),
  **Einstellungen** (Clubs, pc-caddie-Login, Sprache, Einheiten, Scraping, KI-Ranking) und **Club hinzufügen**
  (Clubverzeichnis durchsuchen, Club hinzufügen oder nur zum Ansehen öffnen).
- Das Scrollen funktioniert wie in der Mac-App: Ein geöffneter Tag behält seine Kopfzeile oben, während seine Zeiten
  scrollen, öffnet bei seiner empfohlenen Zeit (Zeiten außerhalb deines Zeitfensters sind abgedunkelt), und die
  Spielerliste scrollt unter einer festen Suche mit A–Z-Index. **Einstellungen > Skalierung** macht die ganze Seite
  kleiner oder größer (nur in diesem Browser; der Browser-Zoom, Strg +/-, geht auch).
- **Aktualisieren** lädt neue Startzeiten; beim Öffnen der Seite wird auch geladen, was fällig ist.
- Ein Menü **Ansicht** in der Werkzeugleiste (Taste `v`) mit allem, was Aussehen und Sprache der Seite ändert, einen
  Klick von der Übersicht entfernt: Sprache (Deutsch oder Englisch), dieselben elf Farbthemen wie in Terminal- und
  Mac-App (ohne Auswahl folgt es dem Dunkel/Hell deines Systems), Skalierung, Einheiten und Handicaps. Dazu Einzeltasten wie in
  der Terminal-App: `r` aktualisieren, `s` suchen, `h` Heatmap, `p` Spieler, `e` Präferenzen, `,` Einstellungen,
  `a` Club hinzufügen, `v` Ansicht, `?` Legende, Esc schließt ein Fenster.

Was bewusst anders ist als in der Mac-App: keine Menüleiste (alles steht in der Werkzeugleiste), Benachrichtigungen
nur bei geöffneter Seite und kein Hintergrund-Scraper (bei geschlossenem Fenster läuft nichts) – außer als Server: `teetime-monitor-web --serve`
(Passwort, ruft selbstständig ab, für das ganze Heimnetz) steht in [RASPBERRY-PI.de.md](RASPBERRY-PI.de.md).

## Aktualisierungen

Alle paar Stunden fragt das Programm GitHubs öffentliche Release-Liste ab (eine einzelne Anfrage, die nichts über dich
sendet); gibt es eine neuere Version, steht unten **Version X ist verfügbar** mit Link zu den Release-Notes und dem
Befehl für deine Installationsart (`brew upgrade teetime-monitor`, `scoop update teetime-monitor`). Auf einem
Raspberry-Pi-Server gibt es einen Knopf **Jetzt aktualisieren** ([RASPBERRY-PI.de.md](RASPBERRY-PI.de.md)). Die
portablen Downloads und die Mac-App aktualisierst du mit dem neuen Download. `TEETIME_MONITOR_NO_UPDATE_CHECK=1`
schaltet die Abfrage aus.

## Starten

- **Portabler Windows-/Linux-Download:** `TeetimeMonitor-Web.cmd` doppelklicken (Windows) bzw.
  `./TeetimeMonitor-Web.sh` ausführen (Linux). Siehe [WINDOWS-APP.de.md](WINDOWS-APP.de.md) und
  [LINUX-APP.de.md](LINUX-APP.de.md).
- **Mit Scoop, Homebrew oder pip installiert:** `teetime-monitor-web` im Terminal ausführen.

Es öffnet sich ein Fenster (Edge, Chrome oder Chromium ohne Tabs und Adressleiste, falls installiert, sonst
dein Standardbrowser). Öffnet sich nichts, kopiere den im Terminal angezeigten Link in einen Browser.
**Das Schließen des Fensters beendet das Programm** (ein bis zwei Minuten später); mit `--keep-running`
läuft es weiter, Strg+C beendet es immer. Weitere Optionen: `--no-browser` (nur den Link ausgeben),
`--port N`, `--help`.

Beim Öffnen fragt es wie die Terminal-App auch den Scraper nach allem, was fällig ist; die Fußzeile zeigt
währenddessen *Aktualisiere…*. **Aktualisieren** lädt alles sofort.

## Smartphone und Tablet

Die Seite passt sich dem Bildschirm in drei Stufen an: auf einem **Tablet** (etwa 640 bis 1200 px, etwa ein iPad im
Hochformat) behält jeder Tag seine ganze Tabelle (Wetter, freie Plätze, Regen und Wind, mit Spaltenüberschriften),
lange Namenslisten umbrechen in ihrer Spalte, und jede Zeile ist fingergroß und gleich hoch; auf einem **Smartphone**
verteilt sich die Werkzeugleiste auf zwei Zeilen, die Formulare stapeln sich, und jede Startzeit belegt zwei Zeilen
(Zeit, Plätze, frei und Temperatur, dann die Namen); am Computer bekommst du die volle Breite. (Geprüft bei 390, 640,
744, 834 und 1100 px.)

Das Programm selbst läuft nicht auf einem Smartphone oder Tablet. Betreibe es auf einem Raspberry Pi (oder einem
anderen dauerhaft laufenden Computer) mit `teetime-monitor-web --serve` und öffne dessen Adresse im Browser des
Geräts: [RASPBERRY-PI.de.md](RASPBERRY-PI.de.md).

## Ist das sicher?

Dein pc-caddie-Login steckt dahinter, deshalb ist es vorsichtig gebaut:

- Es lauscht **nur auf 127.0.0.1**, auf einem zufälligen Port, nie im Netzwerk (nur `--serve` für einen
  Raspberry-Pi-Server öffnet es für dein Heimnetz, und dann verlangt es ein Passwort:
  [RASPBERRY-PI.de.md](RASPBERRY-PI.de.md)).
- Jede Anfrage braucht ein zufälliges **Token**, das nur der ausgegebene Link enthält; die Seite hält es in
  einem Cookie, das Skripte nicht lesen können. Andere Programme und andere Webseiten können den Server nicht
  benutzen.
- Es weist Anfragen für einen anderen Hostnamen oder von einer anderen Webseite ab, und die Seite darf nichts
  aus dem Internet laden (strenge Content-Security-Policy). Keine Schriften, Skripte oder Bilder von
  anderswo.
- Es braucht keine neue Software: reines Python aus der Standardbibliothek plus eine kleine mitgelieferte
  JavaScript-Bibliothek (Preact, siehe `src/webui/static/vendor/LICENSES.txt`).

## Die Seite ändern

Die Seite besteht aus einfachen JavaScript-Modulen in `src/webui/static/` (Preact + htm, mitgeliefert; kein Build-Schritt);
ihre Texte stehen in `strings.json` (Deutsch und Englisch) plus im Katalog der App (`src/i18n.py`).
`tests/test_webui_strings.py` prüft, dass jeder Text, den die Skripte benutzen, in beiden Sprachen existiert, und
`tests/test_webui_e2e.py` (nur auf Wunsch: `TEETIME_E2E=1`, braucht Chrome, Chromium oder Edge) klickt alle Fenster
eines Demo-Servers in einem echten Browser durch.

## Für Entwickler

`src/webui/data.py` baut das JSON (mit `storage`, `pipeline` und `picks_cli.compute_picks`),
`src/webui/server.py` liefert es mit `src/webui/static/` aus (kein Build-Schritt). Zum Ansehen ohne
pc-caddie-Login: `python scripts/webui_demo.py /tmp/demo --serve` legt einen Fake-Club an und startet es.
