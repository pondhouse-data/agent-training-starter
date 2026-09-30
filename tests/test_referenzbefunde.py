"""Ü11: Referenztests als PR-Gate. Nach Ü10 die beiden Skip-Zeilen löschen; ohne Ü10 wird R-03 rot."""

import json
from pathlib import Path

import pytest

REFERENZ = json.loads((Path(__file__).parents[1] / "training_data/referenzbefunde.json").read_text(encoding="utf-8"))


@pytest.mark.exercise
@pytest.mark.parametrize("version,requirement", [("1", "R-01"), ("1", "R-03"), ("1", "R-05"), ("2", "R-03"), ("2", "R-04"), ("2", "R-05")])
def test_referenzbefund(version, requirement):
    from pruefung import pruefe_spezifikation

    expected = next(b for p in REFERENZ["pruefungen"] if p["document_version"] == version
                    for b in p["befunde"] if b["requirement_id"] == requirement)
    actual = next(b for b in pruefe_spezifikation(version) if b["requirement_id"] == requirement)
    assert actual["status"] == expected["status"]
    assert actual["fundstellen"] == expected["fundstellen"]


@pytest.mark.exercise
def test_klaerungspunkte_v1():
    from pruefung import pruefe_spezifikation

    actual = pruefe_spezifikation("1")
    assert [b["requirement_id"] for b in actual if b["status"] != "erfüllt"] == ["R-03", "R-05"]
    assert next(b for b in actual if b["requirement_id"] == "R-03")["status"] == "abweichend"
