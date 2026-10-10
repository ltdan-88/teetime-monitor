# Die Browser-Version (Web-Oberfläche)

*[English version](WEBUI.md)*

Eine grafische Version von Teetime Monitor, die in einem Browserfenster läuft, für Windows und Linux (der
Mac hat seine eigene native App). Dieselben Daten und Empfehlungen wie die Terminal-App, im dunklen
Karten-Layout der Mac-App (hell, wenn dein System hell ist), auf Deutsch oder Englisch.

**Stand: erste Version.** Sie zeigt die **Übersicht**: Club und Platz wählen, jeden Tag mit Wetter,
empfohlener Auswahl, deiner Buchung und Belegungsbalken sehen und einen Tag öffnen, um alle Startzeiten mit
den Spielern zu sehen (Freunde mit ★). „Aktualisieren“ lädt neue Startzeiten. Suche, Crowd-Heatmap,
Spielerverzeichnis, Einstellungen, Logins und *Club hinzufügen* gibt es vorerst nur in der Terminal-App und
folgen; lege deine Clubs und Logins dort an (oder in der Mac-App).

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

## Für Entwickler

`src/webui/data.py` baut das JSON (mit `storage`, `pipeline` und `picks_cli.compute_picks`),
`src/webui/server.py` liefert es mit `src/webui/static/` aus (kein Build-Schritt). Zum Ansehen ohne
pc-caddie-Login: `python scripts/webui_demo.py /tmp/demo --serve` legt einen Fake-Club an und startet es.
