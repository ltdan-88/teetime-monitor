# Die teetime-monitor Mac-App — Download und Benutzung

*[English version](MAC-APP.md)*

Eine ganz normale Mac-App, um die Startliste deines Golfclubs anzusehen: eine Karte pro
buchbarem Tag mit Wetter, Auslastung und der Zeit, die sich lohnt. Du musst nichts weiter
installieren — kein Homebrew, kein Python, kein Terminal. Alles, was die App braucht, steckt
in ihr.

**Voraussetzung:** ein Mac mit Apple-Chip (M1 oder neuer) und macOS 14 (Sonoma) oder neuer.

**So prüfst du das mit drei Klicks:** Klicke oben links auf das Apple-Menü , dann auf **Über
diesen Mac** und schau auf zwei Zeilen: Bei **Chip** sollte *Apple M1* (oder M2, M3, M4 …)
stehen, und die macOS-Version sollte **14** oder höher sein. Steht dort *Intel*, ist dieser
Download nicht für diesen Mac.

(Freunde mit Windows oder Linux: Für euch gibt es die Terminal-Version von teetime-monitor —
siehe [README](../README.de.md).)

## 1. Herunterladen

Öffne das [neueste Release](https://github.com/ltdan-88/teetime-monitor/releases/latest) und
lade die Datei **TeetimeMonitor-…-arm64.zip** herunter (unter *Assets*). Sie ist etwa 60 MB
groß.

## 2. Entpacken und in „Programme“ ablegen

1. Doppelklicke die Zip-Datei im Ordner „Downloads“. Daneben erscheint **TeetimeMonitor**
   (die App).
2. Ziehe **TeetimeMonitor** in deinen Ordner **Programme**.

## 3. Das erste Öffnen

macOS warnt, dass es die App nicht überprüfen kann. **Das ist normal und
bedeutet nicht, dass etwas nicht stimmt.** macOS vertraut ohne Nachfrage nur Apps aus dem
App Store oder von Entwicklern, die Apple für eine zusätzliche Prüfung bezahlen (die
sogenannte Notarisierung). Diese App ist ein kostenloses Hobbyprojekt und hat beides nicht.
Der gesamte Quellcode ist öffentlich unter
[github.com/ltdan-88/teetime-monitor](https://github.com/ltdan-88/teetime-monitor), und die
App liest nur die Startliste deines Clubs — sie bucht nie etwas.

Du sagst deinem Mac einmalig, dass du ihr vertraust:

**Ab macOS 15 (Sequoia)**

1. Öffne die App per Doppelklick. Es erscheint eine Meldung; klicke auf **Fertig** (nicht auf
   *In den Papierkorb legen*).
2. Öffne das Apple-Menü  → **Systemeinstellungen** → **Datenschutz & Sicherheit**.
3. Scrolle zum Abschnitt **Sicherheit**. Dort steht *„TeetimeMonitor“ wurde blockiert …*.
   Klicke auf **Dennoch öffnen**, gib dein Mac-Passwort ein (oder nutze Touch ID) und klicke
   noch einmal auf **Dennoch öffnen**.

**Unter macOS 14 (Sonoma)**

1. Halte im Ordner „Programme“ die **ctrl-Taste** gedrückt und klicke auf die App (oder
   klicke mit der rechten Maustaste) und wähle **Öffnen**.
2. Es erscheint eine Meldung, diesmal mit einem Knopf **Öffnen**. Klicke darauf.

Danach öffnet sich die App jedes Mal ganz normal per Doppelklick. Falls sie sich trotzdem
nicht öffnen lässt, nimm den Weg über „Datenschutz & Sicherheit“ — er funktioniert in jeder
Version.

**Wenn sich die App öffnet, aber nie Daten zeigt.** macOS kann seine Markierung „aus dem
Internet geladen“ auch auf die Teile im Inneren der App setzen. Wenn nach **Aktualisieren**
nichts erscheint, öffne das **Terminal** (Spotlight: ⌘Leertaste, *Terminal* eintippen), füge die
folgende Zeile ein, drücke die Eingabetaste und öffne die App erneut:

```
xattr -dr com.apple.quarantine /Applications/TeetimeMonitor.app
```

(Hast du die App nicht nach „Programme“ gezogen, nimm ihren tatsächlichen Ort.)

## 4. Club hinzufügen

Öffne in der Menüleiste oben am Bildschirm das Menü **Aktionen** und wähle **Club
hinzufügen…** (⌘N), oder öffne die **Einstellungen** (das Zahnrad in der Symbolleiste) und
nutze den Bereich **Clubs**. Suche deinen Club nach Namen und drücke **Hinzufügen**. (Der
Knopf **Öffnen** neben einem Club zeigt nur eine Vorschau seiner Startliste, ohne den Club zu
speichern.)

Das Hinzufügen speichert den Club nur; Startzeiten werden dabei noch nicht geladen. Drücke
einmal **Aktualisieren** (⌘R), um die ersten Startzeiten zu laden — das dauert ein paar
Sekunden.

## 5. Optional: bei pc caddie anmelden

Auch ohne Anmeldung zeigt die App Startzeiten, Wetter und Auslastung. Mit Anmeldung
(**Einstellungen → pc caddie Anmeldung**) kann sie zusätzlich deine eigenen bestätigten
Buchungen zeigen und — wenn dein Club sie freigibt — Spielernamen, und sie kann Zeiten mit
deinen Freunden bevorzugen.

Benutzername und Passwort werden in einer Datei auf deinem eigenen Mac gespeichert und nur
verwendet, um mit pc caddie zu sprechen. Sie gehen nirgendwo anders hin, und auch nicht an
die Entwickler der App. (Sie liegen in einer einfachen Datei in dem unten genannten Ordner,
nicht im macOS-Schlüsselbund.)

## Was du siehst — und was die App nicht tut

Jeder buchbare Tag ist eine Karte mit Wetter, Auslastung der Startliste und der empfohlenen
Zeit (★); ein Klick auf den Tag zeigt alle Startzeiten. Die App **liest nur** die
öffentliche Startliste des Clubs (und, wenn du dich angemeldet hast, deine Buchungen) — sie
**bucht nie** und ändert nichts.

Sie aktualisiert sich nicht von selbst im Hintergrund. Drücke **Aktualisieren** (⌘R), wenn du
die neuesten Startzeiten willst; die Tagesliste zeigt die neuen Daten, sobald sie da sind,
und der kleine Punkt unten im Fenster (neben der Angabe, wann zuletzt aktualisiert wurde)
wird orange, wenn die Daten älter werden.

## Wo deine Daten liegen — und wie du alles entfernst

Die App legt gespeicherte Clubs und Einstellungen in zwei Ordnern in deinem Benutzerordner
ab. Sie sind unsichtbar; so öffnest du einen: Wähle im Finder **Gehe zu → Gehe zu Ordner …**
(⇧⌘G) und füge ein:

- `~/.config/teetime-monitor` — deine Clubs, Präferenzen, Anmeldung
- `~/.local/share/teetime-monitor` — der Verlauf der Startlisten, den die App gesammelt hat

Zum vollständigen Entfernen: App beenden, **TeetimeMonitor** aus „Programme“ in den
Papierkorb ziehen und die beiden Ordner ebenfalls in den Papierkorb ziehen. (macOS legt
eventuell noch ein paar Byte Fenstereinstellungen an anderer Stelle ab; sie schaden nicht.)

## Etwas klappt nicht?

Schick einen Screenshot des Fensters und die **App-Version** — die kleine graue Zahl unten im
Fenster, zum Beispiel *v0.71.2* — sowie deine macOS-Version (Apple-Menü → Über diesen Mac).
Meist reicht das, um das Problem zu finden. Schick bitte nie dein Passwort mit.

Wenn die App einmal meldet, ein Hilfsprogramm sei *„nicht gefunden — mit Homebrew
installieren“*, ignoriere den Homebrew-Teil: Dann ist deine Kopie der App beschädigt. Lösche
sie und lade sie erneut herunter (Schritt 1).
