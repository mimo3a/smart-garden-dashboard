# Erfahrungsbericht Vibe Coding – Smart Garden Dashboard

**Kurs:** Current Technologies, MCI · **Autor:** Oleksandr · **Datum:** _TT.MM.2026_

## 1. Ziel und Ausgangslage
_Was sollte gebaut werden? Bezug zum Smart-Garden-Projekt (STM32, ADS1115, UART-JSON).
Welche Vorkenntnisse hatte ich in Python/FastAPI/Frontend?_

## 2. Werkzeuge
- Coding-Tool: _z. B. Claude Code / GitHub Copilot (Agent Mode) / Codex_
- Modell: _…_
- Weitere: VS Code, Git, Python _3.x_, Windows _…_
- Kontextdatei: `AGENTS.md` (bzw. `CLAUDE.md`) – siehe Repository

## 3. Vorgehen
Arbeitsschleife aus der Vorlesung: Auftrag → Kontext → kleine Änderung → prüfen → iterieren.
Alle Prompts stehen in `PROMPTS.md`; Abweichungen und Folge-Prompts im Log unten.

## 4. Prompt-Log
| # | Prompt (kurz) | Ergebnis | Nacharbeit / Folge-Prompt | Dauer |
|---|---------------|----------|---------------------------|-------|
| 1 | Projekt-Setup | | | |
| 2 | Parser + Datenmodell | | | |
| 3 | Simulator | | | |
| 4 | UART-Reader | | | |
| 5 | SQLite | | | |
| 6 | REST-API | | | |
| 7 | Dashboard | | | |
| 8 | Alarme | | | |
| 9 | KI-Review | | | |
| 10 | README | | | |

## 5. Was gut funktioniert hat
- _z. B. Boilerplate (Projektstruktur, FastAPI-Endpunkte) in Sekunden_
- _…_

## 6. Was nicht gut funktioniert hat
- _z. B. falsche Umrechnung der Feuchte (trocken = hoher Rohwert), musste korrigiert werden_
- _…_

## 7. Gefundene Probleme der KI
| Problem | Art (Halluzination / Bug / Security / Wartbarkeit) | Wie entdeckt | Lösung |
|---------|----------------------------------------------------|--------------|--------|
| | | | |

## 8. Test mit echter Hardware
_Lief der UART-Reader mit der Nucleo-Platine? COM-Port-Probleme unter Windows? Verhalten beim Abziehen._

## 9. Reflexion
- Verstehe ich den erzeugten Code? Welche Teile musste ich mir genauer ansehen?
- Wäre ich selbst schneller gewesen? Wo ja, wo nein?
- Technical Debt: Was würde ich vor einem echten Einsatz umbauen?
- Wofür würde ich Vibe Coding wieder verwenden – und wofür nicht?

## 10. Fazit
_3–5 Sätze._
