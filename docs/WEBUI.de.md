# Die Browser-Version (Web-Oberfläche)

*[English version](WEBUI.md)*

Eine grafische Version von Teetime Monitor, die in einem Browserfenster läuft, für Windows und Linux (der
Mac hat seine eigene native App; es läuft auch auf dem Mac). Dieselben Daten und Empfehlungen wie die Terminal-App, im dunklen
Karten-Layout der Mac-App (hell, wenn dein System hell ist), auf Deutsch oder Englisch.

**Stand: vollständig.** Alles, was die Mac-App kann, ist hier:

- **Übersicht:** Club und Platz wählen; jeder Tag mit Wetter, empfohlener Auswahl, deiner Buchung oder der Zeit,
  zu der die Buchung öffnet, und Belegungsbalken. Einen Tag öffnen zeigt jede Startzeit mit Spielern (Freunde mit
  ★, Namen nach Geschlecht gefärbt, auf Wunsch mit Handicap), Wetter je Zeit und Sonnenauf-/-untergang. Eine Zeit
  anklicken markiert sie als deine Buchung, deine Buchung anklicken storniert sie. Hinweise („ein Spieler ist
  deinem Flight beigetreten“) erscheinen oben.
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
nur bei geöffneter Seite und kein Hintergrund-Scraper (bei geschlossenem Fenster läuft nichts).

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

## Ist das sicher?

Dein pc-caddie-Login steckt dahinter, deshalb ist es vorsichtig gebaut:

- Es lauscht **nur auf 127.0.0.1**, auf einem zufälligen Port, nie im Netzwerk.
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
