"""Ü9: `anforderungskatalog_laden` um den Parameter requirement_id erweitern (KI-unterstützt)."""

import pytest

from training_tools import anforderungskatalog_laden


@pytest.mark.exercise
@pytest.mark.skip(reason="Ü9: Parameter requirement_id ergänzen, dann Skip entfernen")
def test_einzelne_anforderung_laden():
    katalog = anforderungskatalog_laden("A-100", requirement_id="R-03")
    assert [r["requirement_id"] for r in katalog["requirements"]] == ["R-03"]
    assert katalog["requirements"][0]["vergleichsregel"] == {"typ": "version_mindestens", "grenzwert": "2.0"}


@pytest.mark.exercise
@pytest.mark.skip(reason="Ü9: Parameter requirement_id ergänzen, dann Skip entfernen")
@pytest.mark.parametrize("requirement_id", ["R-99", "R3"])
def test_unbekannte_anforderung_verstaendlich(requirement_id):
    with pytest.raises(ValueError, match=requirement_id):
        anforderungskatalog_laden("A-100", requirement_id=requirement_id)


@pytest.mark.exercise
@pytest.mark.skip(reason="Ü9: Parameter requirement_id ergänzen, dann Skip entfernen")
def test_ohne_requirement_id_weiter_ganzer_katalog():
    assert len(anforderungskatalog_laden("A-100")["requirements"]) == 6
