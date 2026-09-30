# MAF-Starter – synthetische Spezifikationsprüfung

Öffentliches Übungsprojekt für das Agententraining (Copilot Studio + Microsoft Agent Framework, Python). Die Daten in `training_data/` sind synthetisch; der reale KIS-Export ist ausdrücklich **nicht** enthalten. Keine Secrets committen.

**Start:** [SETUP.md](SETUP.md) von oben nach unten ausführen; Codespace ist der Standard. Nach `az login --use-device-code` und `.env`-Konfiguration: `uv run python agent.py`. Ohne Azure-Zugang funktionieren `uv run pytest` und die lokalen Ladefunktionen bereits.

- `training_tools.py`: Spezifikation und Katalog laden (A-100; A-200/A-999 ergeben verständliche Fehler).
- `agent.py`: MAF-Agent und Foundry-Modell mit `AzureCliCredential`; zeigt jeden Toolaufruf in der Konsole. Eigene Frage: `uv run python agent.py "Welche Regel gilt für R-03?"`; OpenTelemetry-Spans zusätzlich mit `ENABLE_CONSOLE_EXPORTERS=true`.
- `pruefung.py`, `pruefworkflow.py`, `pruefen.py`: der Prüfworkflow für SPEC-001 (Tag 2, siehe unten).
- `tests/`: lokale Tests sind grün. Übungstests (Marker `exercise`) sind **absichtlich übersprungen**, bis die Übung umgesetzt ist. Ein grüner PR-Check beweist erst nach Ü11 die fachliche Prüfung.

## Tag 2: Prüfworkflow SPEC-001

```
Auftrag laden → Angaben extrahieren (LLM, strukturierte Ausgabe) → vergleichen (Python) → Prüfer je Befund → Bericht
```

- **Extraktion** (`pruefworkflow.py`): Das Modell liefert je Anforderung nur Fundstellen (Abschnitt, wörtliches Zitat, Werte) als Pydantic-Schema `Extraktion`. Es bewertet nichts (Ausnahme R-06 als Vorschlag).
- **Vergleich** (`pruefung.py`): normale Funktionen. Zitat nicht im Originaltext der geprüften Version → `unklar`. Keine Angabe → `unklar`, nie `erfüllt`. Widersprüchliche Werte → `unklar` mit allen Fundstellen. Dann die Regel aus dem Katalog (Teilmenge, Maximum, Version, Bereich).
- **Prüfer** (`request_info`): eine Frage je Befund. Der Workflow wartet mit Checkpoint in `.checkpoints/<review_id>/`, auch über einen Prozessneustart. KI-Befund und Prüferentscheidung stehen getrennt im Bericht `berichte/<review_id>.md/.json`.
- `referenz/`: geprüfte Referenz-Extraktion. `--extraktion referenz` läuft ohne Azure; die Referenztests nutzen sie, damit der PR-Check deterministisch bleibt.

```bash
uv run python pruefen.py start PR-101          # bis zum Prüferschritt; Prozess endet
uv run python pruefen.py status PR-101         # Checkpoint-Kette, offene Prüferfragen
uv run python pruefen.py fortsetzen PR-101     # neu laden, je Befund bestätigen oder korrigieren
uv run python pruefen.py bericht PR-101
uv run python pruefung.py 1                    # nur Regeln auf die Referenz-Extraktion (v1 oder 2)
```

| Übung | Aufgabe | Test freischalten |
|---|---|---|
| Ü8 | `.env`, `uv run python agent.py`, Instruktion ändern | – |
| Ü9 | `anforderungskatalog_laden` um `requirement_id` erweitern (R-03 → eine Anforderung, R-99 → klare Fehlermeldung) | `tests/test_uebung09.py` |
| Ü10 | `version_mindestens` in `pruefung.py` implementieren; danach R-03 v1 `abweichend`, v2 `erfüllt` | `tests/test_versionen.py` |
| Ü11 | Referenztests als PR-Gate: Skip-Zeilen löschen, PR öffnen | `tests/test_referenzbefunde.py` |
| Ü12 | Prüfung starten, Prozess beenden, fortsetzen, einen Befund bestätigen und einen korrigieren | – |

Die Extraktion schwankt zwischen Läufen. Die Prüfregeln sind deterministisch getestet, die Extraktion wird bewertet (Tag 3, Ü17). `EXTRAKTION_REASONING` (Standard `medium`) steuert den Denkaufwand des Modells; `low` ist schneller, verwechselt aber häufiger Raum- und Kranangaben.

## Prüfservice (Tag 3)

`pruefservice/` stellt den Prüfagenten über das **A2A-Protokoll** bereit (Agent Card unter `/.well-known/agent-card.json`, Endpunkt `/a2a`), damit Copilot Studio ihn als A2A-Agent anbinden kann (Ü13, Dispatcher Ü14).

- **Lokal:** `.env` wie oben, dann `uv run python -m pruefservice` → http://localhost:8000/.well-known/agent-card.json. Ohne `A2A_API_KEY` läuft der Endpunkt lokal ohne Schlüssel.
- **In Azure:** Jeder Merge nach `main` startet `.github/workflows/deploy.yml`: Tests → Image bauen → in die Container Registry pushen → neue Revision auf Azure Container Apps → Rauchtest. Anmeldung an Azure per OIDC über das GitHub-Environment `azure-training`, ohne Secret. Im Container meldet sich der Dienst mit seiner **Managed Identity** am Modell an; Copilot Studio schickt einen API-Key im Header `X-Api-Key`.
- **Stand v1:** Der Agent prüft per Modell und Tools. Den deterministischen Prüfworkflow aus Ü10–Ü12 bringt später ein Pull Request als neue Revision an dieselbe Stelle.

### REST-Ersatzweg für Copilot Studio

Wenn Studios ausgehende A2A-Ausführung mit `SystemError` scheitert, denselben Dienst als **REST-Tool** anbinden. A2A bleibt unverändert verfügbar; REST verwendet intern denselben Executor und Task-Speicher.

- `GET /openapi.json`: öffentliche Swagger-2.0-Beschreibung für einen Custom Connector oder „Add tool → REST API“; keine Secrets enthalten.
- `POST /pruefung`: `{"review_id":"PR-001"}` (optional `context_id` zur Korrelation). Derselbe Header `X-Api-Key` wie bei A2A. Antwort: `review_id`, `task_id`, `context_id`, `status`, `antwort` (unveränderter Prüftext) und `version`.
- `GET /pruefung/{task_id}`: gespeichertes Ergebnis/Prüfstatus **ohne neuen Modellaufruf**. Die technische `task_id` aus der vorigen Antwort verwenden, nicht `review_id`.
- Unbekannter Auftrag/Task: 404; ungültige Eingabe: 400; fehlender/falscher Schlüssel: 401; fehlgeschlagene Prüfung: 502, **nicht** als erfolgreiche Prüfung behandeln.
- Status bedeutet technische Prüfung, nicht menschliche Freigabe. Der Text enthält Klärungspunkte, aber derzeit **keine serverseitig validierte strukturierte Befundliste**. Ein Freigabe-Flow muss weiterhin `requirement_id` und Begründung prüfen.
- Genau eine Replik: Tasks leben im RAM und gehen bei Neustart/Deploy verloren. Danach Prüfung explizit erneut starten; bei Status-404 nichts erfinden.

**Zurück zu A2A:** In Studio REST-Tools deaktivieren (nicht löschen), den korrekt authentifizierten A2A-Agenten aktivieren, Dispatcher-Instruktionen auf A2A umstellen und Prüfauftrag, Status-/ID-Übergabe sowie Teams/Freigabe erneut testen. Beide Routen bleiben im Image; keine Rücknahme der Deployment-Revision, kein Key-/Rollenwechsel nötig. Nie beide Prüfrouten gleichzeitig automatisch auswählen lassen. Bei erneutem A2A-Fehler umgekehrt auf REST zurückschalten.

**Übungen:** Tag 2 siehe oben; Tag 3 A2A/Deployment. Der Prüfservice nutzt den Prüfworkflow noch nicht. Trainerstände liegen **privat** in `pondhouse-data/agent-training-solutions`, nicht hier. Der CD-Workflow `deploy.yml` deployt den Prüfservice nach jedem Merge (siehe oben). Branche im Repo anlegen, **kein Fork** (Fork-PRs erhalten kein OIDC). `main` erfordert PR und `referenztests`.
