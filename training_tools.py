"""Synthetische Trainingsdaten laden; keine Modell- oder Netzwerkaufrufe."""

import json
from pathlib import Path

from agent_framework import tool
from pydantic import Field
from typing import Annotated

DATA = Path(__file__).resolve().parent / "training_data"


def spezifikation_laden(document_version: str = "1") -> dict:
    """SPEC-001 mit stabilen Abschnitts-Fundstellen laden."""
    if document_version not in {"1", "2"}:
        raise ValueError(f"Unbekannte Dokumentversion {document_version!r}; verfügbar: 1, 2.")
    with (DATA / f"SPEC-001_v{document_version}.extracted.json").open(encoding="utf-8") as source:
        return json.load(source)


def anforderungskatalog_laden(asset_id: str = "A-100", requirement_id: str | None = None) -> dict:
    """Katalog für A-100 laden, optional nur eine Anforderung; Unbekanntes ausdrücklich zurückweisen."""
    if asset_id != "A-100":
        if asset_id == "A-200":
            raise ValueError("Für A-200 gibt es keinen Nachrüst-Katalog: Der Fernbedienstand ist bereits vorhanden.")
        raise ValueError(f"Anlage {asset_id} unbekannt oder ohne Katalog. Bitte Anlagen-ID prüfen (A-100).")
    with (DATA / "AK-FBS_anforderungskatalog.json").open(encoding="utf-8") as source:
        katalog = json.load(source)
    if requirement_id is None:
        return katalog
    treffer = [r for r in katalog["requirements"] if r["requirement_id"] == requirement_id]
    if not treffer:
        bekannt = ", ".join(r["requirement_id"] for r in katalog["requirements"])
        raise ValueError(f"Anforderung {requirement_id} gibt es im Katalog {katalog['catalog_id']} nicht. Bekannt: {bekannt}.")
    return {**katalog, "requirements": treffer}


def pruefauftrag_laden(review_id: str | None = None, asset_id: str | None = None,
                       document_id: str | None = None, document_version: str | None = None) -> dict:
    """Prüfauftrag per review_id laden oder über Anlage/Dokument/Version finden (erster passender Auftrag)."""
    with (DATA / "pruefauftraege.json").open(encoding="utf-8") as source:
        auftraege = json.load(source)["pruefauftraege"]
    if review_id:
        for auftrag in auftraege:
            if auftrag["review_id"] == review_id.strip().upper():
                return auftrag
        raise ValueError(f"Prüfauftrag {review_id} unbekannt. Bekannt: {', '.join(a['review_id'] for a in auftraege)}.")
    treffer = [a for a in auftraege
               if (asset_id is None or a["asset_id"] == asset_id)
               and (document_id is None or a["document_id"] == document_id)
               and (document_version is None or a["document_version"] == str(document_version))]
    if not treffer:
        raise ValueError("Kein Prüfauftrag für diese Anlage/Dokument/Version. Bitte review_id angeben (z. B. PR-001).")
    return treffer[0]


@tool(approval_mode="never_require")
def lade_spezifikation(document_version: Annotated[str, Field(description="SPEC-001 Version 1 oder 2")] = "1") -> dict:
    """Lade die synthetische Spezifikation SPEC-001 mit Fundstellen."""
    return spezifikation_laden(document_version)


@tool(approval_mode="never_require")
def lade_anforderungskatalog(
    asset_id: Annotated[str, Field(description="Anlagen-ID, zum Beispiel A-100")],
    requirement_id: Annotated[str | None, Field(description="Optional eine Anforderung, z. B. R-03")] = None,
) -> dict:
    """Lade den internen Anforderungskatalog für eine Anlage, optional nur eine Anforderung."""
    return anforderungskatalog_laden(asset_id, requirement_id)
