# Erfahrungsbericht Vibe Coding – Smart Garden Dashboard

**Kurs:** Current Technologies, MCI · **Autor:** Oleksandr · **Datum:** _TT.MM.2026_

## 1. Ziel und Ausgangslage
_Was sollte gebaut werden? Bezug zum Smart-Garden-Projekt (STM32, ADS1115, UART-JSON).
Welche Vorkenntnisse hatte ich in Python/FastAPI/Frontend?_

## 2. Werkzeuge
- Coding-Tool: _Claude Code (CLI through npx)_
- Modell: _Sonnet 4.6_
- Weitere: VS Code, Git, Python _3.x_, Windows _11_
- Kontextdatei: `AGENTS.md` (bzw. `CLAUDE.md`) – siehe Repository

## 3. Vorgehen
Arbeitsschleife aus der Vorlesung: Auftrag → Kontext → kleine Änderung → prüfen → iterieren.
Alle Prompts stehen in `PROMPTS.md`; Abweichungen und Folge-Prompts im Log unten.

## 4. Prompt-Log
| # | Prompt (kurz) | Ergebnis | Nacharbeit / Folge-Prompt | Dauer |
|---|---------------|------------|---------------------------|-------|
| 1 | Projekt-Setup | Struktur exakt nach AGENTS.md, pip install ok, ~1,5 min | PowerShell-Hinweis ergänzt (vorher bash-Fehler) | 5 min |
| 2 | Parser + Datenmodell | | | |
| 3 | Simulator | | | |
| 4 | UART-Reader | Reconnect, Mocks, 76 Tests; Agent bemerkt Warnings selbst | Fix im falschen Layer (except: break) | … |
| 4b | Folge-Prompt Reader-Robustheit | Ursache in Tests behoben, Callback isoliert, 77/77 | – | … |
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
- Шум в окружении. Агент сначала запустил PowerShell-команды (Get-ChildItem) в bash, получил command not found и только потом переключился на PowerShell. Он не учёл, что работает под Windows, и тратил на это лишние шаги и токены. Это пункт для раздела 6.
- _…_

## 7. Gefundene Probleme der KI
| Problem | Art (Halluzination / Bug / Security / Wartbarkeit) | Wie entdeckt | Lösung |
|---------|----------------------------------------------------|--------------|--------|
parse_line('[1,2]') → AttributeError, obwohl AGENTS.md „niemals abstürzen” fordert; 17/17 Tests trotzdem grün | Bug / Robustheit | Manueller Code-Review + Gegenprobe im Terminal | Folge-Prompt 2b

Agent ändert bestehenden Test, damit neue Implementierung grün wird; Garbage-Arrays werden zu leeren Readings|Bug / Test an Code angepasst | Diff-Review des Testfiles | Folge-Prompt 3c

Agent „behebt” Test-Artefakt (Mock-StopIteration) im Produktivcode mit except Exception: break → Reader stirbt bei jedem Callback-Fehler still | Bug / Fehlerursache falsch diagnostiziert | Code-Review | Folge-Prompt 4b


Догадка вместо проверки. Про AGENTS.md агент написал «Vermutlich ähnliche Anweisungen», то есть не открыл файл и угадал. На деле файл идентичен CLAUDE.md. Мелкий, но наглядный пример того, что LLM уверенно додумывает вместо того, чтобы прочитать. Это для раздела 7, тип «Halluzination / Annahme».


## 8. Test mit echter Hardware
_Lief der UART-Reader mit der Nucleo-Platine? COM-Port-Probleme unter Windows? Verhalten beim Abziehen._

## 9. Reflexion
- Verstehe ich den erzeugten Code? Welche Teile musste ich mir genauer ansehen?
- Wäre ich selbst schneller gewesen? Wo ja, wo nein?
- Technical Debt: Was würde ich vor einem echten Einsatz umbauen?
- Wofür würde ich Vibe Coding wieder verwenden – und wofür nicht?

## 10. Fazit
_3–5 Sätze._
