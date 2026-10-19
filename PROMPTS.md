# Prompts – Smart Garden Dashboard (Vibe Coding)

Vorgehen nach der Arbeitsschleife aus der Vorlesung: Auftrag → Kontext → kleine Änderung → prüfen → iterieren.
Jeder Prompt = ein Schritt. Nach jedem Schritt: Diff ansehen, Tests laufen lassen, App starten, Git-Commit.
Die "Prüfen"-Punkte sind für dich, nicht für die KI. Was nicht klappt → Feedback-Prompt schreiben und im Log festhalten.

---

Welche Dateien siehst du im Projektordner und was steht in CLAUDE.md zusammengefasst?

## Prompt 1 – Projekt-Setup
```
Hinweis: Wir sind unter Windows, nutze PowerShell-Befehle.
Lies AGENTS.md. Lege das Projektgerüst genau nach der dort beschriebenen Struktur an:
requirements.txt, leere Module mit Docstrings, config.json mit Kalibrierwerten für 4 Kanäle
(dry_raw=26000, wet_raw=12000) und Schwellwerten (Bodenfeuchte min 30 %, Lufttemperatur 5–35 °C,
Bodentemperatur 5–30 °C, Batterie min 20 %), eine .gitignore für Python und SQLite-Dateien.
Nenne zuerst kurz deinen Plan. Noch keine Logik implementieren.
```
**Prüfen:** Struktur = AGENTS.md? `pip install -r requirements.txt` klappt?

## Prompt 2 – Parser + Datenmodell
```
Implementiere app/models.py und app/parser.py gemäß dem Datenformat in AGENTS.md.
parse_line(line: str) -> Reading | None: gibt None bei ungültigem JSON zurück, toleriert fehlende Felder
(dann None im jeweiligen Feld) und Kanäle mit status "err". Berechne die Bodenfeuchte in % pro Kanal aus
der Kalibrierung in config.json und begrenze auf 0–100.
Schreibe pytest-Tests: gültige Zeile, kaputtes JSON, fehlende Batterie, Kanal mit err, Rohwert außerhalb
der Kalibrierung. Führe die Tests aus.
```
**Prüfen:** Stimmt die Prozent-Umrechnung (trocken = hoher Rohwert!)? Tests decken Randfälle wirklich ab?

## Prompt 2b – Folge-Prompt (Robustheit Parser)

Review von parser.py: parse_line verletzt die Regel "niemals abstürzen" aus AGENTS.md.
1. Gültiges JSON, das kein Objekt ist ([1,2], 123, null), führt zu AttributeError.
2. "adc": null oder ein Kanal-Eintrag, der kein Objekt ist, führt zu einem Absturz.
3. Falsche Typen (z. B. "air_temp_c": "abc", "raw": "x") werfen eine nicht abgefangene ValidationError.
4. Ein Kanal ohne "ch" wird stillschweigend zu Kanal 0 – solche Einträge stattdessen verwerfen und loggen.
Behebe das so, dass parse_line in diesen Fällen None zurückgibt bzw. nur das fehlerhafte Feld/den Kanal
verwirft. Ergänze für jeden Fall einen Test und führe alle Tests aus.


## Prompt 3 – Simulator
```
Implementiere app/simulator.py: ein Generator, der jede Sekunde eine JSON-Zeile im Format aus AGENTS.md
erzeugt. Werte sollen sich realistisch langsam ändern (Random Walk): Bodenfeuchte sinkt langsam und
springt gelegentlich hoch (Gießen), Lufttemperatur schwankt wie ein Tagesverlauf, Bodentemperatur
folgt der Lufttemperatur träge, Batterie entlädt sich langsam. Selten (ca. 2 %) soll eine kaputte Zeile
oder ein Kanal mit status "err" kommen, damit die Fehlerbehandlung getestet wird.
Der Simulator liefert Strings, damit er denselben Weg durch den Parser nimmt wie echte UART-Daten.
```
**Prüfen:** Kommen die Daten wirklich durch `parse_line`? Sind die Werte plausibel?

## Prompt 3b – Folge-Prompt (Neu Format)

Die aktuelle Firmware sendet noch das alte Format: ein JSON-Array [{"ch":0,"raw":15234,"status":"ok"}, ...]
ohne Temperaturen und Batterie. parse_line soll dieses Legacy-Format zusätzlich akzeptieren
(Temperaturen und Batterie dann None). Ergänze Tests dafür und aktualisiere das Datenformat in AGENTS.md
und CLAUDE.md.

## Folge-Prompt 3c

Du hast test_json_array so angepasst, dass "[1, 2, 3]" jetzt ein leeres Reading liefert – das schwächt
den Robustheits-Fix ab. Regel: parse_line gibt None zurück, wenn nach dem Parsen keinerlei Messwerte
übrig sind (keine gültigen Kanäle, keine Temperaturen, keine Batterie). Das gilt für [1,2,3], [],
{"adc": null} und {}. Stelle den ursprünglichen Test für [1,2,3] (Ergebnis None) wieder her, ergänze
Tests für die anderen Fälle und führe danach ALLE Tests aus (pytest -q), nicht nur test_parser.py.

## Prompt 4 – UART-Reader
```
Implementiere app/serial_reader.py: ein Hintergrund-Thread, der mit pyserial vom angegebenen Port liest
(Port und Baudrate aus CLI-Argumenten), Zeilen als UTF-8 dekodiert (Fehler ignorieren), parse_line
aufruft und gültige Readings an einen Callback übergibt. Bei Verbindungsabbruch alle 3 Sekunden neu
verbinden, ohne die App zu beenden. Sauberes Stoppen beim Herunterfahren.
Gemeinsame Schnittstelle mit dem Simulator, damit main.py beide Quellen gleich behandelt.
```
**Prüfen:** Mit Platine testen (COM-Port unter Windows!). Was passiert beim Abziehen des USB-Kabels?

## Folge-Prompt 4b:

Review von serial_reader.py:
1. Die StopIteration-Warnings kamen von erschöpften Mock-side_effects in den Tests, nicht vom Produktivcode.
   Behebe das in den Tests (Mocks so aufsetzen, dass sie nicht erschöpft werden, oder stop() vorher auslösen).
2. Das neue "except Exception: break" beendet den Reader-Thread dauerhaft. Da der Callback innerhalb dieses
   try aufgerufen wird, würde z. B. ein späterer DB-Fehler im Callback das Einlesen still stoppen.
   Ändere es so: Exceptions aus dem Callback pro Reading abfangen und loggen, Reader läuft weiter.
   Unerwartete Exceptions beim Verbinden/Lesen loggen und wie SerialException behandeln (Reconnect), nicht break.
3. SimulatorReader soll ebenfalls von DataSource erben.
Ergänze einen Test: Callback wirft eine Exception, nachfolgende Readings werden trotzdem zugestellt.
Führe alle Tests aus.

## Prompt 5 – Speicherung in SQLite
```
Implementiere app/db.py: Tabelle readings (id, ts, source, moisture_ch0..ch3 als Prozent,
raw_ch0..ch3, status_ch0..ch3, air_temp_c, soil_temp_c, battery_voltage, battery_percent).
Funktionen: init_db, insert_reading, latest_reading, readings_since(minutes). Nur parametrisierte
Queries. Thread-sicher, weil der Reader-Thread schreibt und die API liest.
Tests mit einer temporären Datenbank.
```
**Prüfen:** Parametrisierte Queries? Thread-Sicherheit wirklich gelöst oder nur behauptet?

## Prompt 6 – REST-API
```
Implementiere in app/main.py die FastAPI-App mit:
GET /api/latest – letzte Messung inkl. aktiver Alarme
GET /api/history?minutes=60 – Messungen der letzten N Minuten (N zwischen 1 und 1440 validieren)
GET /api/config – Schwellwerte
CLI: --simulate | --port COMx --baud 115200, --db pfad. Beim Start DB initialisieren und die gewählte
Datenquelle als Hintergrund-Thread starten. Statische Dateien aus static/ unter / ausliefern.
API-Tests mit FastAPIs TestClient.
```
**Prüfen:** `python -m app.main --simulate` starten, `/docs` öffnen, Endpunkte manuell testen.

## Prompt 7 – Dashboard
```
Baue static/index.html, app.js und style.css: Dashboard mit Karten für aktuelle Werte
(4× Bodenfeuchte, Lufttemperatur, Bodentemperatur, Batterie mit Balken), und Liniendiagrammen mit
Chart.js für die letzte Stunde (Feuchte aller Kanäle; Luft- und Bodentemperatur; Batterie).
Alle 2 Sekunden /api/latest pollen, Diagramme alle 10 Sekunden aktualisieren. Karten mit Alarm rot
markieren. Kanal mit status "err" als "Sensorfehler" anzeigen. Werte nur per textContent einfügen.
Responsive, funktioniert auch am Handy.
```
**Prüfen:** Im Browser ansehen, Handy-Breite testen, kaputte Werte aus dem Simulator beobachten.

## Prompt 8 – Schwellwerte und Alarme
```
Implementiere app/alerts.py: check_alerts(reading, config) -> Liste von Alarmen
(z. B. "Boden trocken Kanal 2", "Batterie niedrig", "Lufttemperatur zu hoch"). Grenzen aus config.json.
Fehlende Werte erzeugen keinen falschen Alarm. Im Dashboard oben eine Alarmleiste anzeigen.
Tests für jede Regel inkl. Grenzwerte (genau auf der Schwelle).
```
**Prüfen:** Grenzfälle (genau 30 %, genau 20 % Batterie) – wie entscheidet der Code? So gewollt?

## Prompt 9 – Review durch die KI
```
Führe ein Review des gesamten Projekts durch: Bugs, Sicherheitsprobleme, Race Conditions,
Verstöße gegen AGENTS.md, fehlende Tests. Liste die Funde nach Schwere auf, ändere noch nichts.
```
Danach gezielt einzelne Funde beheben lassen. **Prüfen:** Sind die Funde echt oder halluziniert?

## Prompt 10 – README
```
Schreibe README.md: Projektbeschreibung, Screenshot-Platzhalter, Installation, Start mit Simulator und
mit Platine (Windows und Linux), Datenformat, API-Endpunkte, Tests, bekannte Grenzen.
```

---

## Optionale Erweiterungen (wenn Zeit bleibt)
- CSV-Export der Historie (`GET /api/export.csv`)
- Schwellwerte im Dashboard ändern und in config.json speichern
- Docker-Container (Bezug zur Vorlesung 04-Docker)
