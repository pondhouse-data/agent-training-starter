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


def anforderungskatalog_laden(asset_id: str = "A-100") -> dict:
    """Katalog für A-100 laden; andere Anlagen ausdrücklich zurückweisen."""
    if asset_id != "A-100":
        if asset_id == "A-200":
            raise ValueError("Für A-200 gibt es keinen Nachrüst-Katalog: Der Fernbedienstand ist bereits vorhanden.")
        raise ValueError(f"Anlage {asset_id} unbekannt oder ohne Katalog. Bitte Anlagen-ID prüfen (A-100).")
    with (DATA / "AK-FBS_anforderungskatalog.json").open(encoding="utf-8") as source:
        return json.load(source)


@tool(approval_mode="never_require")
def lade_spezifikation(document_version: Annotated[str, Field(description="SPEC-001 Version 1 oder 2")] = "1") -> dict:
    """Lade die synthetische Spezifikation SPEC-001 mit Fundstellen."""
    return spezifikation_laden(document_version)


@tool(approval_mode="never_require")
def lade_anforderungskatalog(asset_id: Annotated[str, Field(description="Anlagen-ID, zum Beispiel A-100")]) -> dict:
    """Lade den internen Anforderungskatalog für eine Anlage."""
    return anforderungskatalog_laden(asset_id)
