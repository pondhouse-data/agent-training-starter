"""Anwendbarkeit der Fundstellen: Ein wörtlich belegtes Zitat zum falschen Gegenstand ist kein Beleg.

Die Regel steht im Katalog (`anwendbarkeit.ausschlussbegriffe`) und wirkt unabhängig davon, was das
Modell extrahiert. Diese Tests sind keine Übungstests und laufen immer.
"""

import json
from pathlib import Path

import pytest

from pruefung import Fundstelle, fremder_gegenstand, referenz_extraktion_laden, vergleiche
from training_tools import anforderungskatalog_laden, spezifikation_laden

REFERENZ = json.loads((Path(__file__).parents[1] / "training_data/referenzbefunde.json").read_text(encoding="utf-8"))


def befund(befunde, requirement_id):
    return next(b for b in befunde if b["requirement_id"] == requirement_id)


def extraktion_mit(version, requirement_id, *fundstellen):
    extraktion = referenz_extraktion_laden(version)
    angabe = next(a for a in extraktion.angaben if a.requirement_id == requirement_id)
    angabe.fundstellen = list(fundstellen)
    return extraktion


RAUMTEMPERATUR_PULT = Fundstelle(abschnitt="6.3", zitat="bei einer Raumtemperatur von +10 °C bis +35 °C",
                                 bezug="Bedienpult", werte=["10", "35"])
RAUMTEMPERATUR_TECHNIK = Fundstelle(abschnitt="6.3", zitat="mit einer Raumtemperatur von +18 °C bis +27 °C",
                                    bezug="Technikraum", werte=["18", "27"])
KRAN_V2 = Fundstelle(abschnitt="6.2", zitat="von −20 °C bis +45 °C", bezug="Kran A-100", werte=["-20", "45"])


@pytest.mark.parametrize("fundstelle", [RAUMTEMPERATUR_PULT, RAUMTEMPERATUR_TECHNIK])
def test_raumtemperatur_ist_kein_beleg_fuer_r05(fundstelle):
    """Befund aus Ü10: Das Zitat steht wörtlich in §6.3, betrifft aber Pult/Technikraum, nicht den Kran."""
    ergebnis = befund(vergleiche(extraktion_mit("1", "R-05", fundstelle), "1"), "R-05")
    assert ergebnis["status"] == "unklar"
    assert ergebnis["fundstellen"] == []
    assert "§6.3" in ergebnis["begruendung"] and "Raumtemperatur" in ergebnis["begruendung"]
    assert "keine Angabe" in ergebnis["begruendung"]


def test_kran_betriebstemperatur_v2_bleibt_abweichend():
    ergebnis = befund(vergleiche(extraktion_mit("2", "R-05", KRAN_V2), "2"), "R-05")
    assert ergebnis["status"] == "abweichend"
    assert [f["abschnitt"] for f in ergebnis["fundstellen"]] == ["6.2"]


def test_kran_und_raumtemperatur_zusammen_wertet_nur_den_kran():
    ergebnis = befund(vergleiche(extraktion_mit("2", "R-05", KRAN_V2, RAUMTEMPERATUR_PULT), "2"), "R-05")
    assert ergebnis["status"] == "abweichend"
    assert [f["abschnitt"] for f in ergebnis["fundstellen"]] == ["6.2"]
    assert "§6.3" in ergebnis["begruendung"]


@pytest.mark.parametrize("version,requirement_id,fundstelle", [
    ("1", "R-02", Fundstelle(abschnitt="2.5", zitat="Nutzlast von 5 kN/m² ausgelegt", bezug="Boden", werte=["5"])),
    ("1", "R-04", Fundstelle(abschnitt="4.5", zitat="um bis zu 2 s verzögert sein", bezug="Video", werte=["2000"])),
    ("2", "R-03", Fundstelle(abschnitt="4.6", zitat="ist OPC UA 1.04 vorzusehen", bezug="Leitstand", werte=["1.04"])),
])
def test_ablenker_aus_der_spezifikation_sind_kein_beleg(version, requirement_id, fundstelle):
    ergebnis = befund(vergleiche(extraktion_mit(version, requirement_id, fundstelle), version), requirement_id)
    assert ergebnis["status"] == "unklar"
    assert ergebnis["fundstellen"] == []


@pytest.mark.parametrize("pruefung", REFERENZ["pruefungen"], ids=lambda p: f"v{p['document_version']}")
def test_referenzfundstellen_sind_anwendbar(pruefung):
    """Die Ausschlussbegriffe dürfen keine richtige Fundstelle treffen."""
    katalog = {r["requirement_id"]: r for r in anforderungskatalog_laden("A-100")["requirements"]}
    abschnitte = {a["abschnitt"]: a for a in spezifikation_laden(pruefung["document_version"])["abschnitte"]}
    for b in pruefung["befunde"]:
        for f in b["fundstellen"]:
            assert fremder_gegenstand(katalog[b["requirement_id"]], abschnitte[f["abschnitt"]]) is None, (
                b["requirement_id"], f["abschnitt"])
