"""Prüflogik und Prüfworkflow ohne Modellaufruf: Fundstellen, fehlende/widersprüchliche Angaben, Checkpoint."""

import asyncio

import pytest
from agent_framework import FileCheckpointStorage

from pruefung import Angabe, Extraktion, Fundstelle, pruefe_spezifikation, referenz_extraktion_laden, vergleiche
from pruefworkflow import CHECKPOINT_TYPEN, WORKFLOW_NAME, PrueferEntscheidung, baue_workflow


def befund(befunde, requirement_id):
    return next(b for b in befunde if b["requirement_id"] == requirement_id)


def extraktion_mit(version, requirement_id, *fundstellen):
    extraktion = referenz_extraktion_laden(version)
    angabe = next(a for a in extraktion.angaben if a.requirement_id == requirement_id)
    angabe.fundstellen = list(fundstellen)
    return extraktion


@pytest.mark.parametrize("version", ["1", "2"])
def test_referenz_extraktion_ohne_r03_entspricht_referenzbefunden(version):
    """R-03 ist Ü10; alle anderen Regeln müssen schon jetzt die Referenz treffen (Ü11 prüft R-03 zusätzlich)."""
    import json
    from pathlib import Path

    referenz = json.loads((Path(__file__).parents[1] / "training_data/referenzbefunde.json").read_text(encoding="utf-8"))
    erwartet = next(p for p in referenz["pruefungen"] if p["document_version"] == version)["befunde"]
    actual = pruefe_spezifikation(version)
    for e in erwartet:
        if e["requirement_id"] == "R-03":
            continue
        assert befund(actual, e["requirement_id"])["status"] == e["status"], e["requirement_id"]
        assert befund(actual, e["requirement_id"])["fundstellen"] == e["fundstellen"], e["requirement_id"]


def test_erfundene_fundstelle_wird_nicht_uebernommen():
    erfunden = Fundstelle(abschnitt="6.1", zitat="von −20 °C bis +40 °C", bezug="Kran A-100", werte=["-20", "40"])
    ergebnis = befund(vergleiche(extraktion_mit("1", "R-05", erfunden), "1"), "R-05")
    assert ergebnis["status"] == "unklar"
    assert ergebnis["fundstellen"] == []
    assert "nicht im Originaltext" in ergebnis["begruendung"]


def test_fundstelle_aus_falscher_dokumentversion_wird_verworfen():
    aus_v2 = Fundstelle(abschnitt="6.2", zitat="von −20 °C bis +45 °C", bezug="Kran A-100", werte=["-20", "45"])
    assert befund(vergleiche(extraktion_mit("1", "R-05", aus_v2), "1"), "R-05")["status"] == "unklar"


def test_fehlende_angabe_ist_nie_erfuellt():
    ergebnis = befund(vergleiche(extraktion_mit("1", "R-02"), "1"), "R-02")
    assert ergebnis["status"] == "unklar"


def test_widerspruechliche_werte_sind_unklar_mit_allen_fundstellen():
    ergebnis = befund(pruefe_spezifikation("2"), "R-04")
    assert ergebnis["status"] == "unklar"
    assert [f["abschnitt"] for f in ergebnis["fundstellen"]] == ["4.1", "A.1"]


def test_grenzwert_ueberschritten_ist_abweichend():
    zu_hoch = Fundstelle(abschnitt="4.1", zitat="Die Latenz beträgt höchstens 30 ms.", bezug="Kran", werte=["60"])
    assert befund(vergleiche(extraktion_mit("1", "R-04", zu_hoch), "1"), "R-04")["status"] == "abweichend"


def test_extraktion_ohne_eintrag_fuer_anforderung():
    unvollstaendig = Extraktion(angaben=[a for a in referenz_extraktion_laden("1").angaben if a.requirement_id != "R-01"])
    assert befund(vergleiche(unvollstaendig, "1"), "R-01")["status"] == "unklar"


def test_r06_bleibt_ki_vorschlag():
    ergebnis = befund(pruefe_spezifikation("1"), "R-06")
    assert ergebnis["regel"] == "fachliche_bewertung"
    assert ergebnis["begruendung"].startswith("KI-Vorschlag")


def test_workflow_pausiert_und_wird_in_neuer_instanz_fortgesetzt(tmp_path):
    """Ü12/D2-17 ohne Modell: anhalten, alles verwerfen, aus dem Checkpoint neu aufbauen, entscheiden."""

    async def ablauf():
        speicher = FileCheckpointStorage(tmp_path, allowed_checkpoint_types=CHECKPOINT_TYPEN)
        anfragen = {}
        async for event in baue_workflow(speicher, "referenz").run("PR-103", stream=True):
            if event.type == "request_info":
                anfragen[event.request_id] = event.data
        assert sorted(anfragen) == [f"PR-103/R-0{i}" for i in range(1, 7)]

        # "Neuer Prozess": neue Storage- und Workflow-Instanz, nur das Verzeichnis bleibt.
        speicher = FileCheckpointStorage(tmp_path, allowed_checkpoint_types=CHECKPOINT_TYPEN)
        letzter = await speicher.get_latest(workflow_name=WORKFLOW_NAME)
        assert len(letzter.pending_request_info_events) == 6
        workflow = baue_workflow(speicher, "referenz")
        wieder = {}
        async for event in workflow.run(checkpoint_id=letzter.checkpoint_id, stream=True):
            if event.type == "request_info":
                wieder[event.request_id] = event.data
        assert sorted(wieder) == sorted(anfragen)

        antworten = {rid: PrueferEntscheidung("bestätigt", a.befund["status"], "", "test") for rid, a in wieder.items()}
        antworten["PR-103/R-06"] = PrueferEntscheidung("korrigiert", "unklar", "Sperrlogik klären", "test")
        bericht = None
        async for event in workflow.run(stream=True, responses=antworten):
            if event.type == "output":
                bericht = event.data
        return bericht

    bericht = asyncio.run(ablauf())
    assert (bericht["review_id"], bericht["document_version"], bericht["extraktion"]) == ("PR-103", "1", "referenz")
    r06 = next(b for b in bericht["befunde"] if b["requirement_id"] == "R-06")
    assert r06["ki_befund"]["status"] == "erfüllt"
    assert r06["pruefer_entscheidung"]["entscheidung"] == "korrigiert"
    assert r06["endgueltiger_status"] == "unklar"
    assert "R-06" in bericht["klaerungspunkte"]


def test_abschnitt_mit_paragraphzeichen_wird_akzeptiert():
    extraktion = extraktion_mit("1", "R-02", Fundstelle(abschnitt="§ 2.3", zitat="von 41 t bleibt unverändert",
                                                        bezug="Kran A-100", werte=["41"]))
    r02 = befund(vergleiche(extraktion, "1"), "R-02")
    assert r02["status"] == "erfüllt"
    assert r02["fundstellen"][0]["abschnitt"] == "2.3"
