# Entwicklungsumgebung – Ü8/Ü9

## A · Codespace (Standard)

1. GitHub-Einladung als **Outside Collaborator** zum [Starter](https://github.com/pondhouse-data/agent-training-starter) annehmen; keine Mitgliedschaft in der Organisation. Prüfen: Unter der eigenen Anmeldung lassen sich Repository-Dateien öffnen und **Code** → **Codespaces** ist verfügbar. Sichtbare **Settings** sind keine Voraussetzung. Bei 404 Einladung/Konto prüfen.
2. **Code → Codespaces → Create codespace on main**, unter „Configure and create codespace“ **2 cores** wählen. Warten, bis `postCreateCommand: uv sync` beendet ist. Prüfen im Terminal: `python --version` → `Python 3.12.x`; `uv --version` → `uv 0.12.x`; `uv run python -c "import agent_framework; print('MAF OK')"` → `MAF OK`; `az version --output json` → JSON mit `"azure-cli"`; `uv run pytest -q` → Tests bestanden, Ü10/11-Referenztests **skipped**.
3. `az login --use-device-code` ausführen, mit dem **Pondhouse-Trainingskonto** anmelden (noch nicht mit dem GitHub-Konto verwechseln). Prüfen: `az account show --query name -o tsv` → `Kuenz Training 2026` (ggf. `az account set --subscription 'Kuenz Training 2026'`). Kein API-Key.
4. `cp .env.example .env`, den zugeteilten **Foundry-Projekt-Endpunkt** und Deploymentnamen `training-chat` in `.env` eintragen. `.env` nicht committen. Prüfen: `uv run python -c "from dotenv import load_dotenv; import os; load_dotenv(); print(bool(os.getenv('FOUNDRY_PROJECT_ENDPOINT') and os.getenv('FOUNDRY_MODEL')))"` → `True`. Danach `uv run python agent.py` → Agentenantwort mit sechs Anforderungen für A-100. Der Modellaufruf braucht das eingerichtete Trainingskonto mit Foundry-Rolle (am 28.09.2026 mit einem Trainingskonto im Codespace geprüft).
5. GitHub Copilot in VS Code anmelden (eigene Lizenz oder zugewiesener Business-Seat). Prüfen: Copilot-Chat öffnen und einfache Frage zur geöffneten `training_tools.py` stellen → Antwort mit Dateikontext; die Erweiterung allein beweist keine Lizenz. **Codespace danach stoppen** (GitHub → Your codespaces); an Tag 2 fortsetzen.

## B · Lokal

Bevorzugt VS Code + Docker/Dev Containers: Repository klonen, **Dev Containers: Reopen in Container**. Anschließend dieselben Prüfbefehle aus A. Docker-Installation kann Adminrechte erfordern. Ohne Docker: Python 3.12, Git, uv und Azure CLI installieren (`python --version`, `git --version`, `uv --version`, `az version` prüfen), `git clone https://github.com/pondhouse-data/agent-training-starter.git`, `cd agent-training-starter`, `uv sync --locked`; dann A3–A5. Firmenproxy/Zertifikate vorab prüfen.

## C · Plan B (nur bei gesperrten Codespaces)

Trainer stellt nach H01-Bedarf einen Container mit VS-Code-Remote-Tunnel bereit. Erreichbarkeit von `vscode.dev` und `*.devtunnels.ms` vorab testen, dann dieselben Befehle aus A2–A5. Noch nicht bereitgestellt.

## D · Nach dem Training

Änderungen pushen, Codespace stoppen/löschen. Dev-Container in Künz' Azure DevOps lokal weiterverwenden; Actions-Pipeline dort als Azure Pipeline/Branch Policy übertragen. Fragen: kein Codespace-Kontingent/Org-Policy → Trainer; `az` falscher Tenant/Rolle → Trainingskonto und Foundry User prüfen; Copilot gesperrt → Seat/Tandem/Fallback laut P20.
