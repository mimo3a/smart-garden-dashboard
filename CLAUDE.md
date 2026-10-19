# Projekt: Smart Garden Dashboard

## Zweck
Lokales Backend + Web-Dashboard für das Smart-Garden-Projekt (STM32 Nucleo-L476RG, FreeRTOS).
Die Platine sendet Messwerte als JSON über UART. Das Backend liest sie ein, speichert sie in SQLite,
stellt sie über eine REST-API bereit und zeigt sie in einem Dashboard an.
Ohne Platine läuft die App im Simulator-Modus (`--simulate`), damit sie überall startbar ist.

## Stack
- Python 3.11+, FastAPI, Uvicorn, pyserial, SQLite (Standardbibliothek `sqlite3`), pytest
- Frontend: statisches HTML/CSS/Vanilla-JS, ausgeliefert von FastAPI, Chart.js über CDN
- Läuft unter Windows (COM-Ports, z. B. `COM5`) und Linux (`/dev/ttyACM0`)

## Datenformat (UART, 115200 Baud, eine JSON-Zeile pro Messung, `\n`-terminiert)
```json
{"channels":[{"dev":0,"ch":0,"status":0,"raw":15234},{"dev":0,"ch":1,"status":0,"raw":14980},
             {"dev":0,"ch":2,"status":1,"raw":0},    {"dev":0,"ch":3,"status":0,"raw":16012},
             ...bis zu 16 Kanäle (dev 0–3, ch 0–3)...],
 "air_temp_c":22.4,"soil_temp_c":18.1,"battery":{"voltage":3.91,"percent":76}}
```
- `channels`: bis zu 16 Bodenfeuchte-Sensoren (4× ADS1115, `dev` 0–3, `ch` 0–3).  
  Weniger Kanäle sind erlaubt (Ausbaustufen).
- `status`: **Ganzzahl** — `0` = ok, alles andere = err (Sensor fehlerhaft/nicht angeschlossen).
- `raw`: ADS1115-Rohwert 0–32767.
- `air_temp_c`: Lufttemperatur in °C (optional).
- `soil_temp_c`: Bodentemperatur in °C (optional).
- `battery.voltage` in V, `battery.percent` 0–100 (optional).
- Nicht-JSON-Zeilen (z. B. Boot-Meldung `USART1 PA9 OK`) werden verworfen.
- Fehlende Felder oder Kanäle mit `status ≠ 0` dürfen die App nicht abstürzen lassen.
- Der Zeitstempel wird beim Empfang im Backend gesetzt (UTC, ISO 8601).
- Feuchte in %: lineare Umrechnung aus `raw` mit `dry_raw`/`wet_raw` pro (dev, ch) aus `config.json` (`sensors`-Liste).  
  Unbekannte (dev, ch)-Kombinationen → `moisture_pct = None`.

## Projektstruktur
```
app/
  main.py          # FastAPI-App, Start, CLI-Argumente (--simulate, --port, --baud)
  parser.py        # JSON-Zeile -> Reading (Validierung)
  models.py        # Datenklassen / Pydantic-Modelle
  serial_reader.py # Hintergrund-Thread, liest UART, Reconnect
  simulator.py     # erzeugt realistische Fake-Messwerte
  db.py            # SQLite-Zugriff
  alerts.py        # Schwellwerte prüfen
static/            # index.html, app.js, style.css
tests/
config.json        # Kalibrierung + Schwellwerte
```

## Leitplanken
- Bestehende Struktur und Abhängigkeiten beibehalten; keine neuen Frameworks ohne Nachfrage.
- Keine Anmeldung, keine Cloud-Dienste, keine externen APIs außer dem Chart.js-CDN.
- Ungültige UART-Zeilen loggen und überspringen, niemals abstürzen.
- SQL nur mit Parametern (`?`), nie per String-Verkettung.
- Werte im Frontend als Text einfügen (`textContent`), nicht als HTML (`innerHTML`).
- Keine Secrets, Pfade oder COM-Ports hart codieren — über CLI-Argumente oder `config.json`.
- Änderungen klein halten; vor größeren Umbauten erst nachfragen.

## Arbeitsweise
- Vor Änderungen kurz Plan und betroffene Dateien nennen.
- Zu neuer Logik passende pytest-Tests ergänzen; Tests nach jeder Änderung ausführen.
- Nach der Änderung Testergebnis und bekannte Grenzen nennen.
- Code-Stil: PEP 8, Type Hints, kurze Funktionen, Docstrings für öffentliche Funktionen.

## Befehle
- Installieren: `pip install -r requirements.txt`
- Start mit Simulator: `python -m app.main --simulate`
- Start mit Platine: `python -m app.main --port COM5 --baud 115200`
- Dashboard: http://127.0.0.1:8000
- Tests: `pytest -q`

- Umgebung: Windows, PowerShell. Python immer über .\.venv\Scripts\python.exe aufrufen.
- Antworten und Zusammenfassungen auf Deutsch.
