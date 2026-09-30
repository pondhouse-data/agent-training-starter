"""Prüfservice als A2A-Server (Tag 3: D3-02/D3-03, Ü13, Ü14).

Stellt den Prüfworkflow aus Tag 2 über das Agent-to-Agent-Protokoll und als REST-Tool bereit, damit
Copilot Studio ihn anbinden kann. Start lokal: `uv run python -m pruefservice` (siehe README.md).

Hosting-Stand v2: Auftrag laden → Angaben extrahieren (Modell) → vergleichen (Code) → KI-Befunde.
Der Prüferschritt aus Ü12 läuft nicht im Dienst; die Freigabe passiert in Teams (Ü16).
"""

import hmac
import logging
import os
import time
from collections.abc import Awaitable, Callable

from a2a.helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.compat.v0_3.conversions import to_compat_agent_card
from a2a.server.routes import create_jsonrpc_routes, create_rest_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Part
from agent_framework.foundry import FoundryChatClient
from opentelemetry import trace
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from pruefservice.rest import rest_routes
from pruefservice.workflow import antwort_text, review_id_bestimmen, workflow_pruefen
from pruefworkflow import KiBefunde

log = logging.getLogger("pruefservice")
tracer = trace.get_tracer("pruefservice")

VERSION = os.getenv("APP_VERSION", "lokal")
A2A_PATH = "/a2a"
API_KEY_HEADER = "X-Api-Key"
CARD_PATHS = ["/.well-known/agent-card.json", "/.well-known/agent.json"]
# Copilot Studio sucht die Agent Card zuerst relativ zum Endpunkt (…/a2a/.well-known/…), dann am Stamm.
PUBLIC_PATHS = {"/", "/health", "/openapi.json", *CARD_PATHS, *(A2A_PATH + p for p in CARD_PATHS)}

Pruefen = Callable[[str], Awaitable[KiBefunde]]


class PruefserviceExecutor(AgentExecutor):
    """Führt je A2A-Anfrage den Prüfworkflow aus, protokolliert context_id/task_id/review_id und legt einen eigenen Span an.

    Das Ergebnis geht als ein Artefakt „pruefergebnis“ und zusätzlich als Statusnachricht des
    abgeschlossenen Tasks zurück, damit jeder A2A-Client (auch Copilot Studio) den vollständigen Text erhält.
    Ist der Prüfauftrag nicht eindeutig, endet der Task mit input-required und einer Rückfrage.
    """

    def __init__(self, pruefen: Pruefen):
        self._pruefen = pruefen

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
                review_id = review_id_bestimmen(query)
            except ValueError as unklar:
                log.info("Rückfrage context_id=%s task_id=%s: %s", context.context_id, task.id, unklar)
                await updater.requires_input(message=updater.new_agent_message([Part(text=str(unklar))]))
                return
            span.set_attribute("kuenz.review_id", review_id)
            try:
                await updater.start_work()
                text = antwort_text(await self._pruefen(review_id), VERSION)
                await updater.add_artifact([Part(text=text)], name="pruefergebnis")
                await updater.complete(message=updater.new_agent_message([Part(text=text)]))
                log.info("A2A-Antwort gesendet review_id=%s context_id=%s task_id=%s dauer_s=%.1f zeichen=%d",
                         review_id, context.context_id, task.id, time.perf_counter() - started, len(text))
            except Exception as error:
                span.record_exception(error)
                log.exception("A2A-Anfrage fehlgeschlagen review_id=%s context_id=%s task_id=%s",
                              review_id, context.context_id, task.id)
                await updater.failed(message=updater.new_agent_message(
                    [Part(text=f"Prüfservice-Fehler: {type(error).__name__}. Details im Dienst-Log (task_id {task.id}).")]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.context_id is None:
            raise ValueError("A2A-Abbruch ohne context_id")
        await TaskUpdater(event_queue, context.task_id or "", context.context_id).cancel()


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
    configure_otel_providers(service_name=os.getenv("OTEL_SERVICE_NAME", "pruefservice"),  # cloud_RoleName in App Insights
                             exporters=[AzureMonitorTraceExporter(connection_string=connection_string),
                                        AzureMonitorLogExporter(connection_string=connection_string)])
    log.info("Telemetrie an Application Insights aktiv")


def agent_card(public_url: str) -> AgentCard:
    return AgentCard(
        name="Kuenz-Pruefspezialist",  # Copilot Studio: nur [a-zA-Z0-9-.], keine Umlaute/Leerzeichen
        description=("Prüft synthetische Kundenspezifikationen (z. B. SPEC-001 v1/v2 für Anlage A-100) gegen den "
                     "internen Anforderungskatalog AK-FBS und liefert je Anforderung einen Befund "
                     "(erfüllt, abweichend, unklar) mit Fundstelle sowie die Klärungspunkte. "
                     "Eingabe: review_id (z. B. PR-001) oder Anlage, Dokument und Version."),
        version=VERSION,
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),  # wie das Copilot-Studio-Sample; message/stream liefert das Ergebnis als SSE-Events
        supported_interfaces=[
            AgentInterface(url=f"{public_url}{A2A_PATH}", protocol_binding="JSONRPC", protocol_version="0.3"),
            AgentInterface(url=f"{public_url}{A2A_PATH}", protocol_binding="HTTP+JSON", protocol_version="0.3"),
        ],
        skills=[AgentSkill(id="spezifikationspruefung", name="Spezifikationsprüfung",
                           description="Spezifikation gegen den Anforderungskatalog prüfen und Klärungspunkte nennen.",
                           tags=["künz", "spezifikation", "prüfung"],
                           examples=["Prüfe SPEC-001 v1 für A-100", "Prüfe den Prüfauftrag PR-101"])],
    )


def build_pruefen() -> Pruefen:
    """Workflow mit Modell-Extraktion; der Chat-Client meldet sich per Managed Identity bzw. Azure CLI an."""
    client = FoundryChatClient(project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
                               model=os.environ["FOUNDRY_MODEL"], credential=credential())

    async def pruefen(review_id: str) -> KiBefunde:
        return await workflow_pruefen(review_id, "modell", client)

    return pruefen


def build_app(pruefen: Pruefen | None = None) -> Starlette:
    public_url = os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")
    card = agent_card(public_url)
    task_store = InMemoryTaskStore()
    handler = DefaultRequestHandler(agent_executor=PruefserviceExecutor(pruefen or build_pruefen()),
                                    task_store=task_store, agent_card=card)

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
        # Vor den SDK-Routen: deren /{tenant}-Mount würde /pruefung/{task_id} abfangen.
        *rest_routes(handler, task_store, public_url, VERSION),
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
