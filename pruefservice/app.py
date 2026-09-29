"""Prüfservice als A2A-Server (Tag 3: D3-02/D3-03, Ü13, Ü14).

Stellt den MAF-Prüfagenten über das Agent-to-Agent-Protokoll bereit, damit Copilot Studio
ihn als A2A-Agent anbinden kann. Start lokal: `uv run python -m pruefservice` (siehe README.md).

Hosting-Stand v1: Der Agent prüft per Modell und Tools. Den Prüfworkflow aus Ü10–Ü12
(deterministische Vergleiche, Checkpoints) setzt später eine neue Revision an dieselbe Stelle.
"""

import hmac
import logging
import os
import time
from typing import Annotated

from a2a.helpers import new_task_from_user_message
from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.compat.v0_3.conversions import to_compat_agent_card
from a2a.server.routes import create_jsonrpc_routes, create_rest_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Part
from agent_framework import Agent, tool
from agent_framework.a2a import A2AExecutor
from agent_framework.foundry import FoundryChatClient
from opentelemetry import trace
from pydantic import Field
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from training_tools import lade_anforderungskatalog, lade_spezifikation, pruefauftrag_laden

log = logging.getLogger("pruefservice")
tracer = trace.get_tracer("pruefservice")

VERSION = os.getenv("APP_VERSION", "lokal")
A2A_PATH = "/a2a"
API_KEY_HEADER = "X-Api-Key"
CARD_PATHS = ["/.well-known/agent-card.json", "/.well-known/agent.json"]
# Copilot Studio sucht die Agent Card zuerst relativ zum Endpunkt (…/a2a/.well-known/…), dann am Stamm.
PUBLIC_PATHS = {"/", "/health", *CARD_PATHS, *(A2A_PATH + p for p in CARD_PATHS)}

INSTRUCTIONS = """Du bist der Prüfspezialist von Künz für synthetische Kundenspezifikationen (Training, keine echten Künz-Vorgaben).
Ablauf für jede Prüfanfrage:
1. Bestimme den Prüfauftrag mit dem Tool lade_pruefauftrag: per review_id (z. B. PR-001), sonst über Anlage, Dokument und Version (z. B. A-100, SPEC-001, 1). Ohne ausreichende Angaben frage nach der review_id.
2. Lade den Anforderungskatalog für die Anlage und die Spezifikation in der Version des Auftrags.
3. Bewerte jede Anforderung genau einmal: erfüllt, abweichend oder unklar.
   - Fehlt die Angabe in der Spezifikation oder widersprechen sich Stellen: unklar, alle Fundstellen nennen.
   - Wende die Vergleichsregel der Anforderung wörtlich an: maximum → erfüllt, wenn Ist ≤ Grenzwert (Gleichheit ist erfüllt);
     version_mindestens → Versionen numerisch vergleichen (1.4 < 2.0), nicht als Text; bereich_innerhalb → der angegebene Bereich
     muss vollständig im erlaubten Bereich liegen; teilmenge → alle geforderten Werte sind erlaubt; fachliche_bewertung → begründen.
   - Werte aus anderen Dokumenten (z. B. Anlagenübersicht) oder zu anderen Themen (Raumtemperatur, Videoverzögerung) zählen nicht.
   - Jede Fundstelle muss als Abschnitt und wörtliches Kurzzitat aus der geladenen Spezifikation stammen. Nichts erfinden.
4. Antworte auf Deutsch in genau diesem Format:
Prüfauftrag <review_id> · <document_id> v<document_version> · Katalog <catalog_id> <catalog_version> · Anlage <asset_id>
| Anforderung | Befund | Ist | Fundstelle | Begründung |
(eine Zeile je Anforderung R-01 … R-06)
Klärungspunkte: <kommagetrennte requirement_ids mit Befund abweichend oder unklar>
Hinweis: KI-Vorschlag des Prüfservice (Version {version}); die fachliche Entscheidung trifft der Prüfer."""


@tool(approval_mode="never_require")
def lade_pruefauftrag(
    review_id: Annotated[str | None, Field(description="Prüfauftrag, z. B. PR-001")] = None,
    asset_id: Annotated[str | None, Field(description="Anlagen-ID, z. B. A-100")] = None,
    document_id: Annotated[str | None, Field(description="Dokument-ID, z. B. SPEC-001")] = None,
    document_version: Annotated[str | None, Field(description="Dokumentversion, z. B. 1")] = None,
) -> dict:
    """Lade den Prüfauftrag (review_id, Anlage, Dokument, Version, Katalog)."""
    auftrag = pruefauftrag_laden(review_id, asset_id, document_id, document_version)
    span = trace.get_current_span()
    span.set_attribute("kuenz.review_id", auftrag["review_id"])
    span.set_attribute("kuenz.document", f"{auftrag['document_id']} v{auftrag['document_version']}")
    log.info("Prüfauftrag geladen review_id=%s asset_id=%s document=%s v%s",
             auftrag["review_id"], auftrag["asset_id"], auftrag["document_id"], auftrag["document_version"])
    return auftrag


class PruefserviceExecutor(A2AExecutor):
    """Führt den Agenten je A2A-Anfrage aus, protokolliert context_id/task_id und legt einen eigenen Span an.

    Das Ergebnis geht als ein Artefakt „pruefergebnis“ und zusätzlich als Statusnachricht des
    abgeschlossenen Tasks zurück, damit jeder A2A-Client (auch Copilot Studio) den vollständigen Text erhält.
    """

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.context_id is None or context.message is None:
            raise ValueError("A2A-Anfrage ohne context_id oder message")
        query = context.get_user_input()
        task = context.current_task
        if not task:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, context.context_id)
        await updater.submit()
        started = time.perf_counter()
        with tracer.start_as_current_span("pruefservice.a2a_anfrage") as span:
            span.set_attribute("a2a.context_id", context.context_id)
            span.set_attribute("a2a.task_id", task.id)
            log.info("A2A-Anfrage context_id=%s task_id=%s text=%r", context.context_id, task.id, query[:300])
            try:
                await updater.start_work()
                session = self._agent.create_session(session_id=context.context_id)
                response = await self._agent.run(query, session=session)
                text = response.text or "Der Prüfservice hat keine Antwort erzeugt."
                await updater.add_artifact([Part(text=text)], name="pruefergebnis")
                await updater.complete(message=updater.new_agent_message([Part(text=text)]))
                log.info("A2A-Antwort gesendet context_id=%s task_id=%s dauer_s=%.1f zeichen=%d",
                         context.context_id, task.id, time.perf_counter() - started, len(text))
            except Exception as error:
                span.record_exception(error)
                log.exception("A2A-Anfrage fehlgeschlagen context_id=%s task_id=%s", context.context_id, task.id)
                await updater.failed(message=updater.new_agent_message(
                    [Part(text=f"Prüfservice-Fehler: {type(error).__name__}. Details im Dienst-Log (task_id {task.id}).")]))


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Alle A2A-Aufrufe verlangen den Header X-Api-Key; Agent Card und Health bleiben öffentlich."""

    def __init__(self, app, api_key: str | None):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS or not self.api_key:
            return await call_next(request)
        supplied = request.headers.get(API_KEY_HEADER, "")
        if not hmac.compare_digest(supplied.encode(), self.api_key.encode()):
            log.warning("Abgewiesen: fehlender/falscher %s path=%s client=%s", API_KEY_HEADER, path,
                        request.headers.get("x-forwarded-for", request.client.host if request.client else "?"))
            return JSONResponse({"error": f"{API_KEY_HEADER} fehlt oder ist falsch."}, status_code=401)
        log.info("HTTP %s %s (API-Key ok)", request.method, path)
        return await call_next(request)


def credential():
    """In Azure Container Apps die Managed Identity, lokal die Azure-CLI-Anmeldung. Nie ein API-Key."""
    if os.getenv("IDENTITY_ENDPOINT"):
        from azure.identity.aio import ManagedIdentityCredential
        log.info("Anmeldung am Modell: Managed Identity des Containers")
        return ManagedIdentityCredential(client_id=os.getenv("AZURE_CLIENT_ID"))
    from azure.identity.aio import AzureCliCredential
    log.info("Anmeldung am Modell: Azure CLI (lokal)")
    return AzureCliCredential()


def configure_telemetry() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", force=True)
    for noisy in ("azure", "httpx", "httpx2", "azure.monitor.opentelemetry.exporter"):
        logging.getLogger(noisy).setLevel(logging.WARNING)  # HTTP-Details des SDK verdecken sonst die Anfragen
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        return
    from agent_framework.observability import configure_otel_providers
    from azure.monitor.opentelemetry.exporter import AzureMonitorLogExporter, AzureMonitorTraceExporter
    configure_otel_providers(exporters=[AzureMonitorTraceExporter(connection_string=connection_string),
                                        AzureMonitorLogExporter(connection_string=connection_string)])
    log.info("Telemetrie an Application Insights aktiv")


def agent_card(public_url: str) -> AgentCard:
    return AgentCard(
        name="Künz Prüfspezialist",
        description=("Prüft synthetische Kundenspezifikationen (z. B. SPEC-001 v1/v2 für Anlage A-100) gegen den "
                     "internen Anforderungskatalog AK-FBS und liefert je Anforderung einen Befund "
                     "(erfüllt, abweichend, unklar) mit Fundstelle sowie die Klärungspunkte. "
                     "Eingabe: review_id (z. B. PR-001) oder Anlage, Dokument und Version."),
        version=VERSION,
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[
            AgentInterface(url=f"{public_url}{A2A_PATH}", protocol_binding="JSONRPC", protocol_version="0.3"),
            AgentInterface(url=f"{public_url}{A2A_PATH}", protocol_binding="HTTP+JSON", protocol_version="0.3"),
        ],
        skills=[AgentSkill(id="spezifikationspruefung", name="Spezifikationsprüfung",
                           description="Spezifikation gegen den Anforderungskatalog prüfen und Klärungspunkte nennen.",
                           tags=["künz", "spezifikation", "prüfung"],
                           examples=["Prüfe SPEC-001 v1 für A-100", "Prüfe den Prüfauftrag PR-101"])],
    )


def build_agent() -> Agent:
    endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
    model = os.environ["FOUNDRY_MODEL"]
    client = FoundryChatClient(project_endpoint=endpoint, model=model, credential=credential())
    return Agent(client=client, name="Pruefspezialist", instructions=INSTRUCTIONS.format(version=VERSION),
                 tools=[lade_pruefauftrag, lade_anforderungskatalog, lade_spezifikation])


def build_app(agent=None) -> Starlette:
    public_url = os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")
    card = agent_card(public_url)
    handler = DefaultRequestHandler(agent_executor=PruefserviceExecutor(agent or build_agent()),
                                    task_store=InMemoryTaskStore(), agent_card=card)

    # Copilot Studio akzeptiert (Stand 29.09.2026) nur v0.3-Agent-Cards; Felder aus v1.0 wie supportedInterfaces
    # führen zu „uses A2A protocol v1, which is not supported yet“. Deshalb die reine v0.3-Fassung ausliefern.
    card_v03 = to_compat_agent_card(card).model_dump(by_alias=True, exclude_none=True)

    async def agent_card_v03(_: Request) -> JSONResponse:
        return JSONResponse(card_v03)

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "version": VERSION})

    routes = [
        Route("/", health),
        Route("/health", health),
        *(Route(prefix + path, agent_card_v03) for path in CARD_PATHS for prefix in ("", A2A_PATH)),
        *create_jsonrpc_routes(handler, A2A_PATH, enable_v0_3_compat=True),
        *create_rest_routes(handler, enable_v0_3_compat=True, path_prefix=A2A_PATH),
    ]
    api_key = os.getenv("A2A_API_KEY")
    if not api_key:
        log.warning("A2A_API_KEY nicht gesetzt: Endpunkt ist OHNE Authentifizierung erreichbar (nur lokal verwenden).")
    app = Starlette(routes=routes)
    app.add_middleware(ApiKeyMiddleware, api_key=api_key)
    # Copilot Studio liest die Agent Card direkt aus dem Browser (copilotstudio.microsoft.com) → CORS nur für GET.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=[])
    log.info("Prüfservice %s bereit: Agent Card %s/.well-known/agent-card.json, A2A-Endpunkt %s%s",
             VERSION, public_url, public_url, A2A_PATH)
    return app
