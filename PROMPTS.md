# Prompts – Smart Garden Dashboard (Vibe Coding)

Diese Datei enthält alle Prompts in der Reihenfolge, in der sie tatsächlich an Claude Code gegeben wurden.
Geplante Prompts sind mit einer Nummer (1–10) gekennzeichnet, Folge-Prompts zur Korrektur mit einem
Buchstaben (beispielsweise 2b). Zu jedem Folge-Prompt ist kurz der Anlass angegeben.

Vorgehen nach der Arbeitsschleife aus der Vorlesung: Auftrag → Kontext → kleine Änderung → prüfen → iterieren.
Nach jedem Schritt wurden Diff, Testergebnis und Verhalten der App geprüft und ein Git-Commit erstellt.

Die vollständigen Sitzungsprotokolle stehen in `docs/claude-session-1.md` bis `docs/claude-session-3.md`.

---

## Session 1 – Grundgerüst, Parser, Simulator, UART

### Prompt 0 – Kontextprüfung
```
Welche Dateien siehst du im Projektordner und was steht in CLAUDE.md zusammengefasst?
```

### Prompt 1 – Projekt-Setup
Ergänzt um den Windows-Hinweis, nachdem der Agent in Prompt 0 bash-Befehle unter Windows verwendet hatte.
```
Hinweis: Wir sind unter Windows, nutze PowerShell-Befehle. Lies AGENTS.md. Lege das Projektgerüst genau
nach der dort beschriebenen Struktur an: requirements.txt, leere Module mit Docstrings, config.json mit
Kalibrierwerten für 4 Kanäle (dry_raw=26000, wet_raw=12000) und Schwellwerten (Bodenfeuchte min 30 %,
Lufttemperatur 5–35 °C, Bodentemperatur 5–30 °C, Batterie min 20 %), eine .gitignore für Python und
SQLite-Dateien. Nenne zuerst kurz deinen Plan. Noch keine Logik implementieren.
```

### Prompt 2 – Parser + Datenmodell
```
Implementiere app/models.py und app/parser.py gemäß dem Datenformat in AGENTS.md.
parse_line(line: str) -> Reading | None: gibt None bei ungültigem JSON zurück, toleriert fehlende Felder
(dann None im jeweiligen Feld) und Kanäle mit status "err". Berechne die Bodenfeuchte in % pro Kanal aus
der Kalibrierung in config.json und begrenze auf 0–100.
Schreibe pytest-Tests: gültige Zeile, kaputtes JSON, fehlende Batterie, Kanal mit err, Rohwert außerhalb
der Kalibrierung. Führe die Tests aus.
```

### Prompt 2b – Folge-Prompt: Robustheit Parser
Anlass: `parse_line('[1,2]')` führte zu einem `AttributeError`, obwohl alle 17 Tests grün waren.
```
Review von parser.py: parse_line verletzt die Regel "niemals abstürzen" aus AGENTS.md.
1. Gültiges JSON, das kein Objekt ist ([1,2], 123, null), führt zu AttributeError.
2. "adc": null oder ein Kanal-Eintrag, der kein Objekt ist, führt zu einem Absturz.
3. Falsche Typen (z. B. "air_temp_c": "abc", "raw": "x") werfen eine nicht abgefangene ValidationError.
4. Ein Kanal ohne "ch" wird stillschweigend zu Kanal 0 – solche Einträge stattdessen verwerfen und loggen.
Behebe das so, dass parse_line in diesen Fällen None zurückgibt bzw. nur das fehlerhafte Feld/den Kanal
verwirft. Ergänze für jeden Fall einen Test und führe alle Tests aus.
```

### Prompt 3 – Simulator
```
Implementiere app/simulator.py: ein Generator, der jede Sekunde eine JSON-Zeile im Format aus AGENTS.md
erzeugt. Werte sollen sich realistisch langsam ändern (Random Walk): Bodenfeuchte sinkt langsam und
springt gelegentlich hoch (Gießen), Lufttemperatur schwankt wie ein Tagesverlauf, Bodentemperatur
folgt der Lufttemperatur träge, Batterie entlädt sich langsam. Selten (ca. 2 %) soll eine kaputte Zeile
oder ein Kanal mit status "err" kommen, damit die Fehlerbehandlung getestet wird.
Der Simulator liefert Strings, damit er denselben Weg durch den Parser nimmt wie echte UART-Daten.
```

### Prompt 3b – Folge-Prompt: Legacy-Format
Anlass: Annahme, dass die Firmware noch ein reines JSON-Array sendet (stellte sich später als falsch heraus).
```
Die aktuelle Firmware sendet noch das alte Format: ein JSON-Array [{"ch":0,"raw":15234,"status":"ok"}, ...]
ohne Temperaturen und Batterie. parse_line soll dieses Legacy-Format zusätzlich akzeptieren
(Temperaturen und Batterie dann None). Ergänze Tests dafür und aktualisiere das Datenformat in AGENTS.md
und CLAUDE.md.
```

### Prompt 3c – Folge-Prompt: leere Readings
Anlass: Der Agent hatte einen bestehenden Test stillschweigend so geändert, dass `[1, 2, 3]` ein leeres Reading lieferte.
```
Du hast test_json_array so angepasst, dass "[1, 2, 3]" jetzt ein leeres Reading liefert – das schwächt
den Robustheits-Fix ab. Regel: parse_line gibt None zurück, wenn nach dem Parsen keinerlei Messwerte
übrig sind (keine gültigen Kanäle, keine Temperaturen, keine Batterie). Das gilt für [1,2,3], [],
{"adc": null} und {}. Stelle den ursprünglichen Test für [1,2,3] (Ergebnis None) wieder her, ergänze
Tests für die anderen Fälle und führe danach ALLE Tests aus (pytest -q), nicht nur test_parser.py.
```

### Prompt 4 – UART-Reader
```
Implementiere app/serial_reader.py: ein Hintergrund-Thread, der mit pyserial vom angegebenen Port liest
(Port und Baudrate aus CLI-Argumenten), Zeilen als UTF-8 dekodiert (Fehler ignorieren), parse_line
aufruft und gültige Readings an einen Callback übergibt. Bei Verbindungsabbruch alle 3 Sekunden neu
verbinden, ohne die App zu beenden. Sauberes Stoppen beim Herunterfahren.
Gemeinsame Schnittstelle mit dem Simulator, damit main.py beide Quellen gleich behandelt.
```

### Prompt 4b – Folge-Prompt: Robustheit Reader
Anlass: Der Agent hatte Warnungen aus erschöpften Test-Mocks im Produktivcode mit `except Exception: break` „behoben".
```
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
```

### Prompt 4c – Folge-Prompt: echtes Firmware-Format
Anlass: Ein Blick in den Serial Monitor zeigte, dass die Firmware ein anderes Format sendet als in AGENTS.md angenommen.
```
Hardwaretest: Die echte Firmware sendet ein anderes Format als in AGENTS.md beschrieben. Beispielzeile
der aktuellen Entwicklungsplatine (Eingänge noch unbeschaltet, Werte bedeutungslos):
{"channels":[{"dev":0,"ch":0,"status":0,"raw":4781},{"dev":0,"ch":1,"status":0,"raw":4755},{"dev":0,"ch":2,"status":0,"raw":4728},{"dev":0,"ch":3,"status":0,"raw":4772},{"dev":1,"ch":0,"status":0,"raw":25351},{"dev":1,"ch":1,"status":0,"raw":24649},{"dev":1,"ch":2,"status":0,"raw":23800},{"dev":1,"ch":3,"status":0,"raw":23156}]}
Zielausbau: 16 Bodenfeuchte-Sensoren = 4× ADS1115 (dev 0–3) × ch 0–3, dazu Luft- und Bodentemperatur
und Batterie. Die finale Firmware sendet diese zusätzlich in derselben Zeile als air_temp_c,
soil_temp_c und battery {voltage, percent}. Für die Hausübung arbeiten wir mit dem Simulator.
Regeln für das Format:
- Root-Key "channels", Kanal-ID ist (dev, ch). Es können weniger als 16 Kanäle kommen (Ausbaustufe).
- status ist eine Zahl: 0 = ok, alles andere = err.
- air_temp_c, soil_temp_c, battery sind optional.
- Nicht-JSON-Zeilen wie "USART1 PA9 OK" (Boot-Meldung) verwerfen.
Änderungen:
1. config.json: statt "calibration" eine Liste "sensors" mit {dev, ch, name, dry_raw, wet_raw} für
   alle 16 Kanäle (name z. B. "Beet {n}", dry_raw 26000, wet_raw 12000). Feuchte nur für
   konfigurierte Kanäle berechnen; unbekannte Kanäle mit raw/status übernehmen, moisture_pct None.
2. parser.py: dieses Format als einziges Format. Das alte "adc"-Format und das Legacy-Array
   entfernen (sie beruhten auf einer falschen Annahme), inkl. zugehöriger Tests – keine toten
   Codepfade. Die Robustheitsregeln (nie abstürzen, leere Readings → None) bleiben.
3. models.py: Kanal mit dev und ch.
4. simulator.py: dieses Format mit allen 16 Kanälen, numerischem status, air_temp_c, soil_temp_c
   und battery erzeugen. Die Dynamik pro Kanal unabhängig (unterschiedliche Austrocknung je Beet).
5. AGENTS.md und CLAUDE.md: Datenformat-Abschnitt durch dieses Format ersetzen.
Tests: echte Beispielzeile oben (8 Kanäle, keine Temperaturen) und eine vollständige Zeile
(16 Kanäle + Temperaturen + Batterie). Alle Tests ausführen.
```

---

## Session 2 – Datenbank, API, Dashboard

### Prompt 5 – Speicherung in SQLite
Hinweis: Versehentlich wurde die ursprüngliche, inzwischen veraltete Fassung aus dem Prompt-Plan verwendet
(noch mit vier Kanälen als Spalten). Die Korrektur folgt in 5b.
```
Implementiere app/db.py: Tabelle readings (id, ts, source, moisture_ch0..ch3 als Prozent,
raw_ch0..ch3, status_ch0..ch3, air_temp_c, soil_temp_c, battery_voltage, battery_percent).
Funktionen: init_db, insert_reading, latest_reading, readings_since(minutes). Nur parametrisierte
Queries. Thread-sicher, weil der Reader-Thread schreibt und die API liest.
Tests mit einer temporären Datenbank.
```

### Prompt 5b – Folge-Prompt: Normalisierung
Anlass: flaches Schema mit 48 Spalten; Kanäle außerhalb von `dev*4+ch < 16` wurden stillschweigend verworfen.
```
Das Schema in db.py ist flach (48 Spalten moisture_ch0..15 usw.) und verwirft Kanäle außerhalb von
dev*4+ch < 16 stillschweigend – der Parser übernimmt solche Kanäle aber. Bitte normalisieren:
1. Tabelle readings (id, ts, source, air_temp_c, soil_temp_c, battery_voltage, battery_percent)
   und Tabelle channel_values (reading_id, dev, ch, raw, status, moisture_pct) mit
   FOREIGN KEY ... ON DELETE CASCADE, PRIMARY KEY (reading_id, dev, ch), PRAGMA foreign_keys=ON.
   Index auf readings(ts) und channel_values(reading_id).
2. insert_reading speichert alle Kanäle des Readings in einer Transaktion, ohne Index-Mapping.
3. latest_reading und readings_since liefern pro Reading ein dict mit "channels": [ {dev, ch, raw,
   status, moisture_pct}, ... ]. readings_since ohne N+1-Queries (ein JOIN oder zwei Queries).
4. Neue Funktion purge_older_than(days) zum Aufräumen alter Daten.
Thread-Sicherheit (WAL + Lock, Connection pro Aufruf) beibehalten. Tests anpassen, einen Test für
einen Kanal mit dev=7 ergänzen (muss gespeichert werden) und test_boundary_included so umbenennen
oder ändern, dass er wirklich die Grenze prüft. Alle Tests ausführen.
```

### Prompt 6 – REST-API
```
Implementiere app/main.py mit FastAPI:
GET /api/latest – letzte Messung inkl. Kanälen
GET /api/history?minutes=60&max_points=300 – Messungen der letzten N Minuten (N zwischen 1 und 1440,
    max_points zwischen 10 und 1000 validieren). Bei mehr Messungen als max_points in Zeit-Buckets
    mitteln (in SQL aggregieren, nicht alle Rohzeilen nach Python laden). Ergebnis pro Bucket:
    ts, air_temp_c, soil_temp_c, battery_percent und moisture_pct je (dev, ch).
GET /api/config – Sensorliste und Schwellwerte aus config.json
CLI: --port COMx --baud 115200, --simulate, --db pfad, --keep-days 7. Ohne --port startet die App
automatisch im Simulator-Modus. Beim Start init_db und purge_older_than(keep_days) aufrufen, dann die
Datenquelle als Hintergrund-Thread starten (Callback = insert_reading mit source "uart" bzw.
"simulator") und beim Herunterfahren sauber stoppen (FastAPI lifespan). Statische Dateien aus
static/ unter / ausliefern, sodass http://127.0.0.1:8000 die index.html zeigt.
Start mit: python -m app.main. API-Tests mit FastAPIs TestClient. Alle Tests ausführen.
```

### Prompt 6b – Folge-Prompt: Host, Static-Pfade, Test
Anlass: Server lauschte auf `0.0.0.0`, CSS/JS-Pfade lieferten 404, ein Test war immer grün.
```
Review von main.py und test_main.py:
1. uvicorn läuft auf host="0.0.0.0" – das Dashboard ohne Login wäre im ganzen Netzwerk erreichbar.
   Default 127.0.0.1, neues CLI-Argument --host für bewusstes Freigeben.
2. index.html verweist auf /static/style.css und /static/app.js, StaticFiles ist aber unter "/"
   gemountet → diese Pfade liefern 404. Behebe das konsistent und ergänze einen Test, der index.html
   lädt und prüft, dass jede darin referenzierte CSS/JS-Datei mit 200 ausgeliefert wird.
3. test_bucket_averages_temperature ist immer grün (akzeptiert 10, 15 oder 20). Mit eingefrorener
   Zeit (_utcnow per monkeypatch) zwei Readings sicher in denselben Bucket legen und exakt 15.0 prüfen.
Alle Tests ausführen.
```

### Prompt 7 – Dashboard
```
Baue das Dashboard in static/index.html, app.js und style.css (Vanilla JS, Chart.js über CDN):
1. Kopfzeile mit Lufttemperatur, Bodentemperatur und Batterie (Prozent + Balken, Spannung),
   Datenquelle (simulator/uart) und Zeitpunkt der letzten Messung in lokaler Zeit.
2. Kompaktes Raster mit einer Karte pro Sensor aus /api/config (16 Sensoren): Name, Feuchte in %
   mit Balken. Kanal mit status "err" als "Sensorfehler" anzeigen, fehlender Kanal als "–".
3. Diagramme für die gewählte Zeitspanne (Auswahl 15 min / 1 h / 6 h / 24 h, /api/history mit
   max_points=300): Feuchte des ausgewählten Sensors (Klick auf eine Karte wählt ihn aus),
   Luft- und Bodentemperatur, Batterie.
4. /api/latest alle 2 s pollen, Diagramme alle 10 s aktualisieren. Solange /api/latest 404 liefert,
   "Warte auf erste Messwerte …" anzeigen. Bei Verbindungsfehler einen Hinweis zeigen, nicht abstürzen.
5. Alle Werte per textContent einfügen, nicht per innerHTML. Pfade passend zum StaticFiles-Mount.
6. Responsive: am Handy 2 Karten pro Zeile, am Desktop 4–8.
Starte die App danach nicht selbst dauerhaft; führe die Tests aus (inkl. des Tests für referenzierte
Dateien) und nenne mir, was ich im Browser prüfen soll.
```

### Prompt 7b – Folge-Prompt: Ergebnisse des Browser-Tests
Anlass: Kategorie-Achse, automatische y-Skala, fehlender Feuchte-Balken, veraltete CSS-Datei aus dem Browser-Cache.
```
Browser-Test des Dashboards:
1. Die Diagramme nutzen eine Kategorie-Achse: Messpunkte mit 9 min, 0 min und über 1 h Abstand stehen
   gleich weit auseinander, und Lücken (App lief nicht) werden durch Linien überbrückt. Nutze eine
   echte Zeitachse (proportional; z. B. lineare Achse mit Zeitstempeln und formatierten Ticks, damit
   kein zusätzlicher Date-Adapter nötig ist) und unterbrich die Linie bei Lücken größer als das
   Doppelte der Bucket-Breite (null-Werte, spanGaps: false).
2. Feuchte- und Batterie-Diagramm mit fester y-Achse 0–100 %.
3. Auf den Sensorkarten fehlt der Feuchte-Balken aus der Anforderung – ergänzen.
4. Der Browser hat eine veraltete style.css aus dem Cache verwendet. Statische Dateien mit
   Cache-Control: no-cache ausliefern (Revalidierung statt veralteter Kopie) und einen Test dafür.
5. Diagrammhöhe über einen Wrapper-Container mit fester Höhe statt canvas { height … !important }.
Alle Tests ausführen und mir sagen, was ich im Browser erneut prüfen soll.
```

### Prompt 7c – Folge-Prompt: Lückenerkennung
Anlass: Die Lückenschwelle wurde aus der Anzahl der Datenpunkte statt aus der echten Bucket-Breite berechnet.
```
Fehler in updateCharts (app.js): bucketMs = Zeitfenster / rows.length verwendet die Anzahl der Buckets
MIT Daten, nicht die tatsächliche Bucket-Breite. Bei wenigen Punkten (App lief nur kurz) wird die
Lückenschwelle riesig (z. B. 12 h bei 4 Punkten in 24 h) und Lücken werden wieder überbrückt.
1. Bucket-Breite wie im Backend berechnen: floor(minutes*60 / max_points) + 1 Sekunden, max_points als
   gemeinsame Konstante im JS. Lückenschwelle = 2 × Bucket-Breite.
2. x-Achse auf das gewählte Zeitfenster festlegen (min = jetzt − Zeitfenster, max = jetzt), damit
   "24 h" wirklich 24 Stunden zeigt.
Führe die Tests aus und nenne mir, wie ich die Lücke im Browser sichtbar machen kann.
```

---

## Session 3 – Alarme, Review, Dokumentation

### Prompt 8 – Schwellwerte, Alarme und Demo-Modus
```
Implementiere Schwellwerte und Alarme:
1. app/alerts.py: check_alerts(reading, config) -> Liste von Alarmen {type, severity, message, dev, ch}.
   Regeln aus config.json: Bodenfeuchte pro Sensor unter soil_moisture_min_percent, Luft- und
   Bodentemperatur außerhalb min/max, Batterie unter battery_min_percent, Kanal mit status "err".
   Grenzwert selbst löst keinen Alarm aus (strikt kleiner bzw. größer). Fehlende Werte erzeugen
   keinen Alarm. message auf Deutsch, mit Sensorname aus config.json.
2. /api/latest liefert zusätzlich "alerts".
3. Dashboard: Alarmleiste oben (leer = ausgeblendet), betroffene Sensorkarten markieren. Die
   bisherige Schwellwert-Logik im Browser entfernen – die Alarme kommen nur noch vom Server.
4. Demo-Modus: CLI-Flag --demo (impliziert Simulator). Der Simulator spielt dann zyklisch Szenarien
   durch (Beet trocknet aus, Hitze, Frost, Batterie niedrig, Sensorfehler), sodass jeder Alarmtyp
   innerhalb von ca. 2–3 Minuten sichtbar wird und wieder verschwindet.
Tests für jede Regel inkl. genau auf der Schwelle, fehlende Werte, /api/latest mit alerts und dass
der Demo-Modus jeden Alarmtyp mindestens einmal erzeugt. Alle Tests ausführen und mir sagen, was
ich im Browser prüfen soll.
```

### Prompt 8b – Folge-Prompt: Demo-Abdeckung und Alarmleiste
Anlass: `soil_temp_high` kam im Demo nie vor (Test-Erwartung passend gekürzt), 16 einzelne Badges bei „trocken", ungefragte Memory-Einträge.
```
Review von Prompt 8:
1. Es gibt 7 Alarmtypen, der Demo-Modus erzeugt aber nur 6 – soil_temp_high kommt nie vor. Der
   Demo-Test ist nur grün, weil soil_temp_high in der erwarteten Menge fehlt. Ergänze ein Szenario,
   in dem soil_temp_high auftritt, und leite die erwartete Menge im Test aus einer zentralen Liste
   aller Alarmtypen in alerts.py ab statt sie hart zu codieren.
2. Bei "trocken" zeigt die Alarmleiste 16 einzelne Badges. Gleichartige Sensor-Alarme in der
   Leiste zusammenfassen (z. B. "Bodenfeuchte zu niedrig: Beet 1, Beet 2, … (16)"); die Markierung
   der einzelnen Karten bleibt.
3. Du hast ohne Auftrag in deine Memory/Kontextdateien geschrieben. Zeig mir, was du geändert hast,
   und ändere solche Dateien künftig nur nach Rückfrage.
Alle Tests ausführen.
```

### Prompt 9 – Review durch die KI
```
Führe ein Review des gesamten Projekts durch: Bugs, Sicherheitsprobleme, Race Conditions,
Verstöße gegen AGENTS.md, Wartbarkeit/Duplikate, fehlende Tests. Liste die Funde nach Schwere
(hoch/mittel/niedrig) mit Datei und Zeile auf. Ändere noch nichts.
```

### Prompt 9b – Folge-Prompt: Konfiguration und Datenkorrektheit
Anlass: Funde H1, M1, M5 und N3 aus dem KI-Review sowie ein zusätzlicher eigener Fund (doppelte Kanäle).
```
Behebe aus dem Review:
1. H1 + M1 + N3: Neues Modul app/config.py als einzige Stelle zum Laden von config.json
   (Sensoren mit Kalibrierung, Schwellwerte). Cache mit Neuladen bei geänderter Datei (mtime).
   Bei Ladefehler loggen, letzten gültigen Stand behalten bzw. beim nächsten Aufruf erneut
   versuchen – kein dauerhaft leerer Cache. parser.py, simulator.py und main.py nutzen nur noch
   dieses Modul.
2. Zusätzlicher Fund: Ein (dev, ch) doppelt in einer Zeile verletzt den PRIMARY KEY in
   channel_values, und das ganze Reading geht verloren. Im Parser Duplikate erkennen, den letzten
   Eintrag behalten und loggen. Test dafür.
3. M5: _row_to_reading mit .get() robust machen und testen (korrupte Kanäle, ungültiger ts).
Alle Tests ausführen.
```

### Prompt 9c – Folge-Prompt: Refactoring und Tests
Anlass: Funde M2, M7, M8, N1 und N4 aus dem KI-Review sowie ein zusätzlicher eigener Fund (schwacher Test).
```
Behebe aus dem Review:
1. M2: Gemeinsame Basisklasse für SimulatorReader und DemoSimulatorReader (nur der Generator
   unterscheidet sich).
2. M7 + M8: Tests für DemoSimulatorReader (start/stop, Callback) und dass lifespan bei demo=True
   einen DemoSimulatorReader startet.
3. N1 (def statt lambda), N4 (demo=False im Test-Namespace).
4. Zusätzlicher Fund: test_unknown_sensor_has_fallback_name prüft mit "or" und ist damit zu
   schwach. Exakte erwartete Meldung prüfen.
Alle Tests ausführen.
```

### Prompt 10 – README
```
Schreibe README.md auf Deutsch:
1. Kurzbeschreibung (Smart-Garden-Dashboard, Bezug zur STM32-Platine, Vibe-Coding-Hausübung) und
   Screenshot-Platzhalter.
2. Voraussetzungen (Python-Version, Internet für Chart.js-CDN).
3. Installation und Start für jemanden, der das Repo frisch klont (Windows PowerShell und Linux):
   venv anlegen, pip install -r requirements.txt, python -m app.main, Browser auf
   http://127.0.0.1:8000. Varianten: --demo, --port COMx, --host, --db, --keep-days.
4. Datenformat der Firmware (channels mit dev/ch/status/raw, optionale Temperaturen und Batterie).
5. API-Endpunkte mit Beispielantwort, Alarmregeln, Konfiguration (config.json).
6. Tests ausführen.
7. Abschnitt "Bekannte Grenzen": nur 2–3 Beschriftungen auf der Zeitachse; Simulator startet nach
   Neustart mit zufälligem Zustand; Frontend ohne automatisierte Tests; Chart.js braucht Internet;
   teilweise doppelte Test-Helfer und Reader-Tests; Alarme werden bei jedem /api/latest neu berechnet.
8. Verweis auf VIBE_CODING.md, PROMPTS.md und docs/ (Sitzungsprotokolle).
Teste die Anleitung anschließend selbst: klone das Repository in einen temporären Ordner, führe
die Schritte dort aus (inkl. pytest) und berichte, ob alles funktioniert hat. Lösche den Ordner danach.
```

### Prompt 10b – Folge-Prompt: README-Korrekturen
Anlass: falsche Aussage zur Entstehung des Repositorys sowie kleinere Ungenauigkeiten.
```
Korrekturen an README.md:
1. Die Aussage "alle Inhalte wurden ausschließlich durch Prompts an Claude Code erzeugt" stimmt
   nicht. Ersetze sie durch: Der Anwendungscode und die Tests wurden per Vibe Coding mit Claude Code
   erzeugt. Kontextdatei (AGENTS.md/CLAUDE.md), Prompt-Plan (PROMPTS.md), Berichtsvorlage und das
   Skript tools/jsonl_to_md.py wurden vorab mit Hilfe eines KI-Chats vorbereitet; einzelne Zeilen
   (z. B. in .gitignore und CLAUDE.md) wurden manuell ergänzt.
2. Tests nutzen temporäre SQLite-Dateien, keine In-Memory-DB – korrigieren.
3. Voraussetzungen: "Getestet mit Python 3.14; ab 3.11 vorgesehen, aber nicht geprüft."
4. Repo-URL: https://github.com/mimo3a/smart-garden-dashboard.git
5. Screenshot-Verweis auf docs/screenshot.png lassen, den Platzhaltertext entfernen (ich lege die
   Datei selbst an).
Keine weiteren Änderungen.
```

---

## Übersicht

| Kategorie | Anzahl |
|---|---|
| Geplante Prompts (0–10) | 11 |
| Folge-Prompts zur Korrektur | 13 (2b, 3b, 3c, 4b, 4c, 5b, 6b, 7b, 7c, 8b, 9b, 9c, 10b) |
| Sitzungen | 3 |
