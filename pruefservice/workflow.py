"""Prüfservice v2: derselbe Prüfworkflow wie an Tag 2, aber ohne Prüferschritt.

    Auftrag laden → Angaben extrahieren (Modell) → vergleichen (Code) → KI-Befunde ausgeben

Die Entscheidung des Prüfers fällt nicht im Dienst, sondern danach in Teams (Ü16). Die Executors
kommen unverändert aus `pruefworkflow.py`; eine Änderung an `pruefung.py` (z. B. Ü10) wirkt nach dem
Deployment deshalb direkt auf die Antworten des Dienstes.
"""

import re
from typing import Never

from agent_framework import BaseChatClient, Executor, WorkflowBuilder, WorkflowContext, handler
from opentelemetry import trace

from pruefworkflow import AngabenExtrahieren, AuftragLaden, ExtraktionsModus, KiBefunde, Vergleichen
from training_tools import pruefauftrag_laden

DIENST_WORKFLOW = "spezifikationspruefung-dienst"
RUECKFRAGE = "Bitte nenne genau einen Prüfauftrag als review_id (z. B. PR-001) oder Anlage, Dokument und Version (z. B. A-100, SPEC-001, Version 1)."


class BefundeAusgeben(Executor):
    def __init__(self) -> None:
        super().__init__(id="befunde_ausgeben")

    @handler
    async def ausgeben(self, eingang: KiBefunde, ctx: WorkflowContext[Never, KiBefunde]) -> None:
        klaerung = [b["requirement_id"] for b in eingang.befunde if b["status"] != "erfüllt"]
        trace.get_current_span().set_attribute("kuenz.klaerungspunkte", ",".join(klaerung))
        await ctx.yield_output(eingang)


def baue_dienst_workflow(extraktion: ExtraktionsModus = "modell", client: BaseChatClient | None = None):
    """Je Anfrage neu bauen: eine Workflow-Instanz verarbeitet nur einen Lauf gleichzeitig."""
    kette = [AuftragLaden(), AngabenExtrahieren(extraktion, client), Vergleichen(), BefundeAusgeben()]
    return WorkflowBuilder(name=DIENST_WORKFLOW, start_executor=kette[0]).add_chain(kette).build()


async def workflow_pruefen(review_id: str, extraktion: ExtraktionsModus = "modell",
                           client: BaseChatClient | None = None) -> KiBefunde:
    ergebnis = await baue_dienst_workflow(extraktion, client).run(review_id)
    ausgaben = ergebnis.get_outputs()
    if not ausgaben:
        raise RuntimeError(f"Prüfworkflow endete ohne Befunde (Status {ergebnis.get_final_state()}).")
    return ausgaben[0]


def review_id_bestimmen(text: str) -> str:
    """Prüfauftrag aus der Anfrage lesen, ohne Modell: review_id oder Anlage + Dokument + Version.

    Wirft ValueError mit einer Rückfrage, wenn der Auftrag nicht eindeutig ist.
    """
    ids = sorted({m.upper() for m in re.findall(r"\bPR-\d{3}\b", text, flags=re.IGNORECASE)})
    if len(ids) > 1:
        raise ValueError(f"Mehrere Prüfaufträge genannt ({', '.join(ids)}). {RUECKFRAGE}")
    if ids:
        return pruefauftrag_laden(ids[0])["review_id"]
    anlage = re.search(r"\bA-\d{3}\b", text, flags=re.IGNORECASE)
    dokument = re.search(r"\bSPEC-\d{3}\b", text, flags=re.IGNORECASE)
    version = re.search(r"\b(?:v|version\s*)(\d+)\b", text, flags=re.IGNORECASE)
    if anlage and dokument and version:
        return pruefauftrag_laden(asset_id=anlage.group().upper(), document_id=dokument.group().upper(),
                                  document_version=version.group(1))["review_id"]
    raise ValueError(RUECKFRAGE)


def _zelle(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ") if text not in (None, "") else "—"


def antwort_text(ergebnis: KiBefunde, version: str) -> str:
    """Gleiches Antwortformat wie Hosting v1: Kopfzeile, Tabelle R-01 … R-06, Klärungspunkte, Hinweis."""
    k = ergebnis.kontext
    zeilen = [f"Prüfauftrag {k.review_id} · {k.document_id} v{k.document_version} · "
              f"Katalog {k.catalog_id} {k.catalog_version} · Anlage {k.asset_id}",
              "| Anforderung | Befund | Ist | Fundstelle | Begründung |",
              "|---|---|---|---|---|"]
    for b in ergebnis.befunde:
        fundstellen = "; ".join(f"Abschnitt {f['abschnitt']}: „{f['zitat']}“" for f in b["fundstellen"])
        zeilen.append(f"| {b['requirement_id']} | {b['status']} | {_zelle(b['ist'])} | {_zelle(fundstellen)} "
                      f"| {_zelle(b['begruendung'])} |")
    klaerung = [b["requirement_id"] for b in ergebnis.befunde if b["status"] != "erfüllt"]
    zeilen.append(f"Klärungspunkte: {', '.join(klaerung) or 'keine'}")
    zeilen.append(f"Hinweis: KI-Vorschlag des Prüfservice (Version {version}; Extraktion {ergebnis.extraktion_quelle}, "
                  "Vergleich per Code); die fachliche Entscheidung trifft der Prüfer.")
    return "\n".join(zeilen)
