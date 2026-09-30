"""D2-11/Ü10/Ü12: Prüfworkflow für SPEC-001 als MAF-Graph-Workflow.

    Auftrag laden → Angaben extrahieren (LLM, strukturierte Ausgabe) → vergleichen (Funktion)
    → Prüfer entscheidet je Befund (request_info, Checkpoint) → Bericht

Bedienung über `pruefen.py`. Executor-IDs sind fest vergeben: Ein Checkpoint lässt sich nur mit
derselben Topologie und denselben IDs wieder laden.
"""

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Never

from agent_framework import (
    Agent,
    BaseChatClient,
    Executor,
    FileCheckpointStorage,
    Workflow,
    WorkflowBuilder,
    WorkflowContext,
    handler,
    response_handler,
)
from opentelemetry import trace

from pruefung import Extraktion, referenz_extraktion_laden, vergleiche
from training_tools import anforderungskatalog_laden, pruefauftrag_laden, spezifikation_laden

WORKFLOW_NAME = "spezifikationspruefung"
CHECKPOINTS = Path(__file__).resolve().parent / ".checkpoints"

ExtraktionsModus = Literal["modell", "referenz"]


# --- Nachrichten zwischen den Executors (landen im Checkpoint) -------------------------------

@dataclass
class Pruefkontext:
    review_id: str
    asset_id: str
    document_id: str
    document_version: str
    catalog_id: str
    catalog_version: str


@dataclass
class ExtraktionErgebnis:
    kontext: Pruefkontext
    extraktion: dict
    quelle: str


@dataclass
class KiBefunde:
    kontext: Pruefkontext
    befunde: list[dict]
    extraktion_quelle: str


@dataclass
class PrueferAnfrage:
    """Was der Prüfer je Befund sieht. Der KI-Befund bleibt unverändert."""
    review_id: str
    document_version: str
    befund: dict


@dataclass
class PrueferEntscheidung:
    entscheidung: Literal["bestätigt", "korrigiert"]
    status: Literal["erfüllt", "abweichend", "unklar"]
    kommentar: str
    pruefer: str
    zeitpunkt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


@dataclass
class PrueferErgebnis:
    kontext: Pruefkontext
    befunde: list[dict]
    entscheidungen: dict[str, PrueferEntscheidung]
    extraktion_quelle: str


CHECKPOINT_TYPEN = [f"pruefworkflow:{t.__name__}" for t in
                    (Pruefkontext, ExtraktionErgebnis, KiBefunde, PrueferAnfrage, PrueferEntscheidung, PrueferErgebnis)]


# --- Executors -------------------------------------------------------------------------------

class AuftragLaden(Executor):
    def __init__(self) -> None:
        super().__init__(id="auftrag_laden")

    @handler
    async def laden(self, review_id: str, ctx: WorkflowContext[Pruefkontext]) -> None:
        auftrag = pruefauftrag_laden(review_id)
        trace.get_current_span().set_attribute("kuenz.review_id", auftrag["review_id"])  # im Trace auffindbar (Ü17)
        await ctx.send_message(Pruefkontext(
            review_id=auftrag["review_id"], asset_id=auftrag["asset_id"], document_id=auftrag["document_id"],
            document_version=auftrag["document_version"], catalog_id=auftrag["catalog_id"],
            catalog_version=auftrag["catalog_version"]))


EXTRAKTION_ANWEISUNG = """Du extrahierst Angaben aus einer Kundenspezifikation für eine Anforderungsprüfung.
Du bewertest NICHT, ob Anforderungen erfüllt sind (Ausnahme: R-06). Der Vergleich passiert danach im Code.

Regeln:
- Nur Text aus der gelieferten Dokumentversion verwenden, kein Vorwissen und keine anderen Unterlagen.
- Für jede Anforderung R-01 bis R-06 genau einen Eintrag liefern.
- Fundstelle = Abschnittsnummer + wörtliches Zitat (zusammenhängend, 3–12 Wörter, exakt wie im Text).
- Nur Angaben, die sich genau auf den Gegenstand der Anforderung beziehen. Erst `bezug` bestimmen, dann
  entscheiden: Passt der Bezug nicht zur Anforderung (anderes Gerät, anderer Raum, anderes System oder
  andere Schnittstelle), ist es keine Fundstelle.
- Nennt das Dokument an mehreren Stellen unterschiedliche Werte, ALLE diese Fundstellen liefern.
- Findest du nichts: fundstellen = [] und in der Begründung sagen, dass die Angabe fehlt. Nichts erfinden.
- Format von `werte` je Fundstelle:
  R-01 Sprachcodes, z. B. ["DE", "EN"] · R-02 Zahl in t, z. B. ["41"] · R-03 Versionsnummer exakt wie im
  Text, z. B. ["1.4"] · R-04 Zahl in ms, z. B. ["30"] · R-05 [Minimum, Maximum] in °C mit ASCII-Minus,
  z. B. ["-20", "40"] · R-06 [] und zusätzlich bewertung_vorschlag (erfüllt/abweichend/unklar).
- bewertung_vorschlag bei R-01 bis R-05 immer null."""


class AngabenExtrahieren(Executor):
    """Einziger LLM-Schritt. Im Modus `referenz` wird die geprüfte Referenz-Extraktion geladen.

    Ohne `client` meldet sich der Schritt lokal per Azure CLI an; der Prüfservice übergibt seinen
    Client mit Managed Identity.
    """

    def __init__(self, modus: ExtraktionsModus = "modell", client: BaseChatClient | None = None) -> None:
        super().__init__(id="angaben_extrahieren")
        self.modus = modus
        self.client = client

    async def _modell_extraktion(self, kontext: Pruefkontext) -> Extraktion:
        from agent_framework.foundry import FoundryChatClient
        from azure.identity.aio import AzureCliCredential
        from dotenv import load_dotenv

        load_dotenv()
        endpoint, model = os.getenv("FOUNDRY_PROJECT_ENDPOINT"), os.getenv("FOUNDRY_MODEL")
        if not endpoint or not model:
            raise RuntimeError(".env fehlt: FOUNDRY_PROJECT_ENDPOINT und FOUNDRY_MODEL setzen oder --extraktion referenz.")

        dokument = spezifikation_laden(kontext.document_version)
        katalog = anforderungskatalog_laden(kontext.asset_id)
        anforderungen = "\n".join(f"- {r['requirement_id']} {r['thema']}: {r['soll']}" for r in katalog["requirements"])
        text = "\n".join(f"§{a['abschnitt']} {a['titel']}: {a['text']}" for a in dokument["abschnitte"])
        prompt = (f"Anforderungen ({katalog['catalog_id']} {katalog['version']}):\n{anforderungen}\n\n"
                  f"Spezifikation {dokument['document_id']} Version {dokument['document_version']}:\n{text}")

        options = {"response_format": Extraktion, "reasoning": {"effort": os.getenv("EXTRAKTION_REASONING", "medium")}}
        if self.client is not None:
            response = await self._agent(self.client).run(prompt, options=options)
        else:
            async with AzureCliCredential() as credential:
                client = FoundryChatClient(project_endpoint=endpoint, model=model, credential=credential)
                response = await self._agent(client).run(prompt, options=options)
        if response.value is None:
            raise RuntimeError(f"Modell lieferte keine gültige strukturierte Ausgabe: {response.text[:300]}")
        return response.value

    @staticmethod
    def _agent(client) -> Agent:
        return Agent(client=client, id="angaben-extraktion", name="AngabenExtraktion", instructions=EXTRAKTION_ANWEISUNG)

    @handler
    async def extrahieren(self, kontext: Pruefkontext, ctx: WorkflowContext[ExtraktionErgebnis]) -> None:
        if self.modus == "referenz":
            extraktion, quelle = referenz_extraktion_laden(kontext.document_version), "referenz"
        else:
            extraktion, quelle = await self._modell_extraktion(kontext), f"modell:{os.getenv('FOUNDRY_MODEL')}"
        await ctx.send_message(ExtraktionErgebnis(kontext=kontext, extraktion=extraktion.model_dump(), quelle=quelle))


class Vergleichen(Executor):
    """Deterministisch: Fundstellen gegen Originaltext, dann Vergleichsregeln aus dem Katalog."""

    def __init__(self) -> None:
        super().__init__(id="vergleichen")

    @handler
    async def vergleichen(self, ergebnis: ExtraktionErgebnis, ctx: WorkflowContext[KiBefunde]) -> None:
        befunde = vergleiche(Extraktion.model_validate(ergebnis.extraktion), ergebnis.kontext.document_version)
        await ctx.send_message(KiBefunde(kontext=ergebnis.kontext, befunde=befunde, extraktion_quelle=ergebnis.quelle))


class Pruefer(Executor):
    """Human-in-the-loop: eine Anfrage je Befund. Wartet beliebig lange; Zustand steckt im Checkpoint."""

    def __init__(self) -> None:
        super().__init__(id="pruefer")
        self._eingang: KiBefunde | None = None
        self._entscheidungen: dict[str, PrueferEntscheidung] = {}

    @handler
    async def befunde_vorlegen(self, eingang: KiBefunde, ctx: WorkflowContext[PrueferErgebnis]) -> None:
        self._eingang, self._entscheidungen = eingang, {}
        for befund in eingang.befunde:
            await ctx.request_info(
                PrueferAnfrage(review_id=eingang.kontext.review_id,
                               document_version=eingang.kontext.document_version, befund=befund),
                PrueferEntscheidung,
                request_id=f"{eingang.kontext.review_id}/{befund['requirement_id']}")

    @response_handler
    async def entscheidung_erhalten(self, anfrage: PrueferAnfrage, entscheidung: PrueferEntscheidung,
                                    ctx: WorkflowContext[PrueferErgebnis]) -> None:
        self._entscheidungen[anfrage.befund["requirement_id"]] = entscheidung
        if self._eingang and len(self._entscheidungen) == len(self._eingang.befunde):
            await ctx.send_message(PrueferErgebnis(
                kontext=self._eingang.kontext, befunde=self._eingang.befunde,
                entscheidungen=dict(self._entscheidungen), extraktion_quelle=self._eingang.extraktion_quelle))

    async def on_checkpoint_save(self) -> dict:
        return {"eingang": self._eingang, "entscheidungen": self._entscheidungen}

    async def on_checkpoint_restore(self, state: dict) -> None:
        self._eingang = state.get("eingang")
        self._entscheidungen = dict(state.get("entscheidungen") or {})


class BerichtErstellen(Executor):
    def __init__(self) -> None:
        super().__init__(id="bericht_erstellen")

    @handler
    async def erstellen(self, ergebnis: PrueferErgebnis, ctx: WorkflowContext[Never, dict]) -> None:
        k = ergebnis.kontext
        eintraege = []
        for befund in ergebnis.befunde:
            e = ergebnis.entscheidungen[befund["requirement_id"]]
            eintraege.append({
                "requirement_id": befund["requirement_id"],
                "ki_befund": befund,
                "pruefer_entscheidung": {"entscheidung": e.entscheidung, "status": e.status, "kommentar": e.kommentar,
                                         "pruefer": e.pruefer, "zeitpunkt": e.zeitpunkt},
                "endgueltiger_status": e.status,
            })
        await ctx.yield_output({
            "review_id": k.review_id, "asset_id": k.asset_id, "document_id": k.document_id,
            "document_version": k.document_version, "catalog_id": k.catalog_id, "catalog_version": k.catalog_version,
            "extraktion": ergebnis.extraktion_quelle,
            "abgeschlossen": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "klaerungspunkte": [e["requirement_id"] for e in eintraege if e["endgueltiger_status"] != "erfüllt"],
            "befunde": eintraege,
        })


# --- Aufbau ----------------------------------------------------------------------------------

def checkpoint_storage(review_id: str) -> FileCheckpointStorage:
    """Ein Verzeichnis je Prüfauftrag; nur die eigenen Nachrichtentypen dürfen entpickelt werden."""
    return FileCheckpointStorage(CHECKPOINTS / review_id.strip().upper(), allowed_checkpoint_types=CHECKPOINT_TYPEN)


def baue_workflow(storage: FileCheckpointStorage | None = None, extraktion: ExtraktionsModus = "modell") -> Workflow:
    auftrag, extrahieren, vergleichen = AuftragLaden(), AngabenExtrahieren(extraktion), Vergleichen()
    pruefer, bericht = Pruefer(), BerichtErstellen()
    return (WorkflowBuilder(name=WORKFLOW_NAME, start_executor=auftrag, checkpoint_storage=storage)
            .add_chain([auftrag, extrahieren, vergleichen, pruefer, bericht])
            .build())
