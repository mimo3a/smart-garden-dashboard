# Erfahrungsbericht Vibe Coding – Smart Garden Dashboard

**Kurs:** Current Technologies, MCI · **Autor:** Oleksandr Demianov · **Datum:** 21.10.2026
**Repository:** https://github.com/mimo3a/smart-garden-dashboard

---

## 1. Ziel und Ausgangslage

Im Rahmen der Hausübung wurde eine lauffähige Anwendung ausschließlich per Vibe Coding erstellt.
Als Thema wurde ein Dashboard für das eigene Smart-Garden-Projekt gewählt:

- **Hardware:** STM32 Nucleo-L476RG mit FreeRTOS. Geplant sind 16 Bodenfeuchte-Sensoren (4 × ADS1115),
  Luft- und Bodentemperatur sowie der Batteriestand. Die Platine befindet sich noch in Entwicklung,
  die Eingänge sind derzeit nicht beschaltet.
- **Ziel:** Ein lokales Backend liest JSON-Zeilen über UART, speichert sie in einer Datenbank und zeigt
  sie in einem Web-Dashboard an. Ohne Platine läuft die Anwendung mit einem Simulator, damit sie
  überall gestartet werden kann.
- **Vorkenntnisse:** Python ist vertraut, ebenso Datenbanken und Webentwicklung aus dem Berufspraktikum.
  FastAPI und Chart.js wurden in diesem Umfang zum ersten Mal eingesetzt.

Fazit: Das Thema wurde bewusst praxisnah gewählt, damit die Ergebnisse später im eigenen Projekt
weiterverwendet werden können.

---

## 2. Werkzeuge

- **Coding-Agent:** Claude Code (CLI, v2.1.128, gestartet über `npx claude` im Terminal von VS Code)
- **Modell:** Claude Sonnet 4.6
- **Umgebung:** Windows, PowerShell, Python 3.14 in einer virtuellen Umgebung, Git, GitHub
- **Kontextdatei:** `AGENTS.md` beziehungsweise identisch `CLAUDE.md` (Stack, Datenformat, Struktur,
  Regeln, Befehle)
- **Unterstützung bei Planung und Review:** Ein separater KI-Chat wurde verwendet, um die Kontextdatei
  und den Prompt-Plan vorzubereiten sowie die Ausgaben des Agenten zu prüfen. Der Anwendungscode und
  die Tests stammen vollständig vom Coding-Agenten.

Fazit: Die Kombination aus einem ausführenden Agenten und einer zweiten, prüfenden Instanz hat sich
als hilfreich erwiesen, ersetzt aber nicht die eigene Kontrolle.

---

## 3. Vorgehen

Gearbeitet wurde nach der Arbeitsschleife aus der Vorlesung: Auftrag → Kontext → kleine Änderung →
prüfen → iterieren.

- **Vorbereitung:** Vor dem ersten Prompt wurden die Kontextdatei und ein Plan mit zehn aufeinander
  aufbauenden Prompts erstellt (`PROMPTS.md`).
- **Ein Schritt pro Prompt:** Jeder Prompt enthielt nur eine überschaubare Aufgabe.
- **Prüfung nach jedem Schritt:** Diff gelesen, Tests ausgeführt, gezielte Gegenproben im Terminal
  durchgeführt und die Anwendung im Browser getestet.
- **Iteration:** Bei Fehlern wurde ein Folge-Prompt mit konkreter Fehlerbeschreibung formuliert.
- **Versionierung:** Nach jedem abgeschlossenen Schritt wurde ein Git-Commit erstellt.
- **Protokoll:** Alle Prompts stehen in `PROMPTS.md`, die Sitzungsprotokolle in `docs/`.

Die Arbeit verteilte sich auf drei Sitzungen an drei Abenden. Insgesamt wurden 11 geplante Prompts
und 13 Folge-Prompts verwendet. Die reine Laufzeit des Agenten lag bei etwa 1,5 Stunden.

Fazit: Mehr als die Hälfte der Prompts waren Korrekturen. Das zeigt, dass Prüfen und Nachsteuern den
größeren Teil der Arbeit ausmachen.

---

## 4. Prompt-Log

| Nr. | Schritt | Ergebnis | Auffälligkeit / Nacharbeit | Tests | Laufzeit Agent |
|---|---|---|---|---|---|
| 0 | Kontextprüfung | Kontext korrekt zusammengefasst | bash-Befehle unter Windows; Inhalt von AGENTS.md vermutet statt gelesen | – | – |
| 1 | Projektgerüst | Struktur exakt nach AGENTS.md, Installation erfolgreich | PowerShell-Hinweis ergänzt | – | 1:23 min |
| 2 | Parser + Datenmodell | Feuchte-Umrechnung korrekt | Absturz bei `[1,2]` trotz grüner Tests | 17 | 1:44 min |
| 2b | Robustheit Parser | alle vier Fälle behoben, manuell gegengeprüft | – | 30 | – |
| 3 | Simulator | reproduzierbarer Random Walk mit Fehlerinjektion | Alarme praktisch nie sichtbar | 49 | 3:15 min |
| 3b | Legacy-Format | minimale Änderung | bestehender Test stillschweigend an den Code angepasst | – | 1:40 min |
| 3c | Leere Readings | Regel umgesetzt, Teständerungen offen aufgelistet | – | 62 | 1:29 min |
| 4 | UART-Reader | Reconnect, Mocks, Warnungen selbst bemerkt | Ursache falsch diagnostiziert (`except: break` im Produktivcode) | 76 | 4:56 min |
| 4b | Robustheit Reader | Ursache in den Tests behoben, Callback isoliert | – | 77 | 3:04 min |
| 4c | Echtes Firmware-Format | 16 Kanäle, Altformate entfernt | Kontext-Komprimierung: Wechsel ins Englische, PowerShell-Regel vergessen | 79 | 7:58 min |
| 5 | SQLite | lauffähig | veralteter Prompt verwendet → flaches Schema mit 48 Spalten | 107 | 3:21 min |
| 5b | Normalisierung | zwei Tabellen, Fremdschlüssel, JOIN, Purge | – | 120 | 4:24 min |
| 6 | REST-API | Aggregation in SQL, automatischer Simulator-Modus | Host `0.0.0.0`, falsche Static-Pfade, Test immer grün | 154 | 11:56 min |
| 6b | Fixes API | alle drei Punkte behoben | – | 155 | 3:04 min |
| 7 | Dashboard | Layout, 16 Karten, drei Diagramme | Seite ohne CSS (Browser-Cache), Kategorie-Achse, Feuchte-Balken fehlte | 155 | 6:44 min |
| 7b | Browser-Fixes | Zeitachse, feste Skala, Balken, `no-cache` | Lückenschwelle falsch berechnet | 156 | 4:11 min |
| 7c | Lückenerkennung | korrekte Bucket-Breite, x-Achse fixiert | – | 156 | 1:01 min |
| 8 | Alarme + Demo | sieben Regeln, strikte Grenzen | nur sechs von sieben Alarmtypen im Demo; ungefragte Memory-Einträge | 211 | 8:24 min |
| 8b | Fixes Alarme | alle Alarmtypen sichtbar, Gruppierung in der Leiste | – | – | – |
| 9 | KI-Review | 17 Funde mit Datei und Zeile | Verweis auf nicht existierende Regel | – | 4:58 min |
| 9b | Konfiguration + Duplikate | zentrales Config-Modul, Duplikaterkennung | Antworten wieder auf Englisch | 234 | 11:38 min |
| 9c | Refactoring + Tests | Basisklasse, neue Tests | bestehende Testdatei sollte neu angelegt werden (vom Tool verhindert) | 242 | 3:59 min |
| 10 | README | vollständig, Selbsttest mit `pytest` | falsche Aussage zur Entstehung; App-Start nicht getestet | 242 | 2:47 min |
| 10b | README-Korrekturen | umgesetzt | – | 242 | – |

---

## 5. Was gut funktioniert hat

- **Boilerplate und Struktur:** Projektgerüst, FastAPI-Endpunkte, Datenbankzugriff und Testgerüste
  wurden innerhalb weniger Minuten erstellt.
- **Umfang der Tests:** Der Agent hat von sich aus viele Testfälle geschrieben (am Ende 242), darunter
  Grenzfälle, Fehlerfälle und Nebenläufigkeit.
- **Präzise Folge-Prompts:** Mit einer konkreten Fehlerbeschreibung wurden Probleme meist im ersten
  Anlauf korrekt behoben (beispielsweise 2b, 4b, 5b, 6b, 9b). Der Unterschied zwischen einem
  ungenauen und einem genauen Prompt war deutlich sichtbar.
- **Eigeninitiative an sinnvollen Stellen:** Der Agent hat beispielsweise eine einfrierbare Zeitquelle
  für deterministische Tests eingeführt und einen echten Off-by-one-Fehler in der Bucket-Berechnung
  selbst gefunden und im Code statt im Test behoben.
- **Gute Praxis im Frontend:** Werte wurden durchgehend per `textContent` eingefügt, SQL-Abfragen
  waren durchgehend parametrisiert.
- **Plan vor der Umsetzung:** Der Agent hat vor größeren Änderungen meist einen kurzen Plan und die
  betroffenen Dateien genannt. Damit ließ sich früh erkennen, ob die Aufgabe richtig verstanden wurde.

Fazit: Für klar abgegrenzte Aufgaben mit guter Spezifikation ist der Agent sehr schnell und liefert
überwiegend sauberen Code.

---

## 6. Was nicht gut funktioniert hat

- **Grüne Tests ohne Aussagekraft:** Mehrfach waren alle Tests grün, obwohl der Code fehlerhaft war.
  Teilweise hat der Agent Tests an die Implementierung angepasst statt umgekehrt (3b, 8) oder Tests
  geschrieben, die jedes Ergebnis akzeptieren (6).
- **Regeln aus der Kontextdatei wurden ignoriert:** Die Regeln „PowerShell verwenden" und „auf Deutsch
  antworten" standen in `CLAUDE.md`. Trotzdem startete der Agent in fast jeder Sitzung zuerst mit
  bash-Befehlen und antwortete teilweise auf Englisch.
- **Kontext-Komprimierung:** In einer langen Sitzung wurde der Verlauf automatisch komprimiert. Danach
  waren Hinweise aus dem Chat verloren. Regeln wirken nur dann dauerhaft, wenn sie in der
  Kontextdatei stehen, und selbst dann nicht zuverlässig.
- **Fehler im falschen Layer behoben:** Warnungen aus Test-Mocks wurden im Produktivcode „behoben"
  (4). Dadurch wäre der Lese-Thread bei jedem Datenbankfehler still beendet worden.
- **Wörtliche Umsetzung ohne Zweckbezug:** Der Simulator war „realistisch", wie gefordert, erzeugte
  aber praktisch nie Alarme. Damit war das wichtigste Feature nicht vorführbar (3).
- **Frontend-Fehler bleiben für Tests unsichtbar:** Fehlendes CSS durch den Browser-Cache, eine
  irreführende Zeitachse und eine falsch berechnete Lückenschwelle wurden nur durch manuelle Prüfung
  im Browser entdeckt.
- **Unbemerkte Kosten:** Nach einem Neustart lief Claude Code einmal über die API-Abrechnung statt über
  das Abonnement. Das war nur an einer Zeile im Kopfbereich zu erkennen.

Fazit: Die meisten Probleme waren nicht offensichtlich falsch, sondern plausibel. Genau das macht sie
gefährlich, weil sie bei oberflächlicher Prüfung durchrutschen.

---

## 7. Gefundene Probleme der KI

| Problem | Art | Wie entdeckt | Lösung |
|---|---|---|---|
| Inhalt von AGENTS.md vermutet statt gelesen | Annahme / Halluzination | Vergleich mit dem Dateiinhalt | – |
| `parse_line('[1,2]')` stürzt ab, 17/17 Tests grün | Bug, Robustheit | Code-Review und Gegenprobe im Terminal | 2b |
| Bestehender Test stillschweigend an neuen Code angepasst | Test an Code angepasst | Diff-Review der Testdatei | 3c |
| Warnungen aus Mocks mit `except: break` im Produktivcode „behoben" | Falsche Fehlerursache | Code-Review | 4b |
| Datenformat in der Kontextdatei stimmte nicht mit der Firmware überein | Falsche Annahme (eigene) | Blick in den Serial Monitor | 4c |
| Flaches Schema mit 48 Spalten, Kanäle stillschweigend verworfen | Design, Datenverlust | Code-Review | 5b |
| Server auf `0.0.0.0` ohne Authentifizierung | Sicherheit | Code-Review | 6b |
| CSS- und JS-Pfade liefern 404 | Bug | Hinweis vorab, dann Test im Browser | 6b |
| Test akzeptiert 10, 15 oder 20 | Wertloser Test | Code-Review | 6b |
| Unbekanntes Paket `httpx2` installiert | Mögliches Supply-Chain-Risiko | Recherche in der Starlette-Dokumentation: legitim | – |
| Kategorie-Achse und automatische Skala verzerren Diagramme | Darstellung | Browser-Test | 7b |
| Lückenschwelle aus Anzahl der Punkte statt Bucket-Breite | Logikfehler, Frontend ungetestet | Code-Review | 7c |
| Demo erzeugt nur sechs von sieben Alarmtypen, Erwartung im Test gekürzt | Test an Code angepasst | Code-Review | 8b |
| Ungefragte Einträge in die eigene Memory | Kontrollverlust | Ausgabe „wrote 2 memories" | 8b |
| Review begründet Funde mit einer Regel „aus CLAUDE.md", die dort nicht existiert | Halluzination, falsche Quellenangabe | Suche in `CLAUDE.md` und im Benutzerprofil | Begründung verworfen, Fund selbst bewertet |
| Bestehende Testdatei mit 19 Tests sollte „neu angelegt" werden | Projektwissen verloren | Fehlermeldung des Tools | vom Schutzmechanismus verhindert |
| README behauptet, alles sei ausschließlich per Prompts erzeugt | Falsche Aussage | Lesen der README | 10b |

---

## 8. Test mit echter Hardware

- **Formatprüfung:** Vor dem UART-Schritt wurde die Ausgabe der Entwicklungsplatine im Serial Monitor
  angesehen. Dabei zeigte sich, dass die Annahme in der Kontextdatei falsch war: andere Schlüssel
  (`channels` statt `adc`), acht statt vier Kanäle mit Geräteindex, numerischer Status und eine
  Boot-Meldung als Nicht-JSON-Zeile.
- **Folge:** Parser, Datenmodell, Simulator und Kontextdatei wurden auf das echte Format umgestellt
  (4c). Ohne diesen Blick hätte das Backend jede echte Zeile verworfen.
- **Einschränkung:** Da die Eingänge der Platine noch nicht beschaltet sind, wurde ein Ende-zu-Ende-Test
  mit der Hardware bewusst nicht durchgeführt. Die Hausübung läuft vollständig mit simulierten Daten.

Fazit: Bereits eine kurze Prüfung gegen die echte Hardware hat eine grundlegende Fehlannahme
aufgedeckt, die weder der Agent noch die Tests finden konnten.

---

## 9. KI-Review im Vergleich zum eigenen Review

In Prompt 9 wurde der Agent um ein vollständiges Review gebeten. Parallel dazu wurde eine eigene Liste
bekannter, noch offener Probleme geführt.

| | KI-Review | Eigenes Review |
|---|---|---|
| Funde gesamt | 17 (1 hoch, 8 mittel, 8 niedrig) | 7 |
| Echte Bugs | Konfigurations-Cache bleibt nach Ladefehler dauerhaft leer; ungetestete Rekonstruktion in `_row_to_reading` | Datenverlust bei doppeltem Kanal; inkonsistentes Neuladen von Konfiguration und Kalibrierung |
| Übersehen | doppelter Kanal, schwacher Test, visuelle Probleme, Startzustand des Simulators | Cache-Fehler beim Laden der Konfiguration |
| Auffällig | Verweis auf nicht existierende Regel; mehrere rein hypothetische Funde | – |

Von den sieben eigenen Punkten hat der Agent einen vollständig und einen teilweise gefunden.
Umgekehrt hat das KI-Review einen echten Fehler aufgedeckt, der in der eigenen Liste fehlte.

Fazit: Beide Reviews ergänzen sich. Keines davon war für sich allein vollständig.

---

## 10. Reflexion

- **Verständnis des Codes:** Der Code ist überwiegend gut lesbar. Verstanden wurde er aber vor allem
  dort, wo er aktiv geprüft wurde. Teile, die nur überflogen wurden, beispielsweise die
  SQL-Aggregation, müssten vor einem echten Einsatz genauer nachvollzogen werden.
- **Geschwindigkeit:** Für Gerüst, API und Tests war der Agent deutlich schneller als eine manuelle
  Umsetzung. Bei kleinen Änderungen im Frontend wäre eine direkte Änderung von Hand teilweise
  schneller gewesen als Prompt, Wartezeit und Prüfung.
- **Technical Debt:** Trotz Review bleiben Punkte offen, beispielsweise doppelte Test-Helfer, fehlende
  Frontend-Tests und die Abhängigkeit von einem CDN. Diese sind in der README unter „Bekannte Grenzen"
  dokumentiert.
- **Kontrolle über den Agenten:** Der Agent hat mehrfach Dinge getan, die nicht beauftragt waren, etwa
  Tests angepasst oder in seine Memory geschrieben. Ein Schutzmechanismus des Werkzeugs hat einmal
  den Verlust einer Testdatei verhindert. Bestätigungen vor Änderungen sind daher sinnvoll, auch wenn
  sie den Ablauf verlangsamen.
- **Eigene Rolle:** Die Rolle hat sich vom Schreiben zum Spezifizieren, Prüfen und Entscheiden
  verschoben. Genau die Inhalte aus Datenbanken, Softwarequalität und Sicherheit waren nötig, um die
  Fehler überhaupt zu erkennen.

Empfehlung: Vibe Coding würde ich für Prototypen, Boilerplate, Tests und Werkzeuge einsetzen. Für
sicherheitsrelevante Teile, Datenmodelle und alles, was später gewartet werden muss, würde ich es nur
mit genauer Spezifikation und vollständigem Review einsetzen.

---

## 11. Fazit

Mit Vibe Coding ist in drei Abenden eine funktionsfähige Anwendung mit Backend, Datenbank, Dashboard,
Alarmen, Demo-Modus und 242 Tests entstanden. Das Ergebnis wäre in dieser Zeit manuell kaum
erreichbar gewesen. Gleichzeitig waren 13 der 24 Prompts Korrekturen, und viele Fehler waren nur
durch eigenes Prüfen sichtbar: plausibler Code, grüne Tests und überzeugende Zusammenfassungen
garantieren keine Korrektheit. Entscheidend waren eine gute Kontextdatei, kleine Schritte, präzise
Folge-Prompts und die eigene Prüfung im Terminal und im Browser. Die zentrale Aussage der Vorlesung
hat sich damit bestätigt: Je mehr Code die KI schreibt, desto wichtiger werden Spezifikation,
Verständnis, Tests und kritisches Denken.
