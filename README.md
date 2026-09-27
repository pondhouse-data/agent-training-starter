# MAF-Starter – synthetische Spezifikationsprüfung

Öffentliches Übungsprojekt für das Agententraining (Copilot Studio + Microsoft Agent Framework, Python). Die Daten in `training_data/` sind synthetisch; der reale KIS-Export ist ausdrücklich **nicht** enthalten. Keine Secrets committen.

**Start:** [SETUP.md](SETUP.md) von oben nach unten ausführen; Codespace ist der Standard. Nach `az login --use-device-code` und `.env`-Konfiguration: `uv run python agent.py`. Ohne Azure-Zugang funktionieren `uv run pytest` und die lokalen Ladefunktionen bereits.

- `training_tools.py`: Spezifikation und Katalog laden (A-100; A-200/A-999 ergeben verständliche Fehler).
- `agent.py`: MAF-Agent und Foundry-Modell mit `AzureCliCredential`. In Ü8 die Instruktion ändern, in Ü9 die Toolfunktion reviewen.
- `tests/`: lokale Tests sind grün; Referenzbefunde R-01/R-03/R-05 für Ü10/11 sind **absichtlich übersprungen**, bis der Prüfworkflow existiert. Ein grüner PR-Check beweist derzeit nur die Starter-Basis, noch nicht die fachliche Prüfung!

**TODO Übungen:** Ü10 Graph-Workflow, deterministische Vergleiche (insbesondere R-03), strukturierte Befunde und verifizierte Fundstellen; Ü11 Referenztests aktivieren und roten/grünen Lauf zeigen; Ü12 Checkpoints und Prüferentscheidung; Tag 3 A2A/Deployment. Trainerstände liegen **privat** in `pondhouse-data/agent-training-solutions`, nicht hier. Der CD-Workflow mit Azure-OIDC folgt erst nach Einrichtung der Azure-App/Container Registry. Branche im Repo anlegen, **kein Fork** (Fork-PRs erhalten kein OIDC). `main` erfordert PR und `referenztests`.
