import pytest

from training_tools import anforderungskatalog_laden, spezifikation_laden


def test_catalog_a100_has_six_requirements():
    catalog = anforderungskatalog_laden("A-100")
    assert catalog["catalog_id"] == "AK-FBS"
    assert [r["requirement_id"] for r in catalog["requirements"]] == [f"R-{i:02}" for i in range(1, 7)]


@pytest.mark.parametrize("asset_id, fragment", [("A-200", "bereits vorhanden"), ("A-999", "unbekannt")])
def test_no_catalog_for_other_assets(asset_id, fragment):
    with pytest.raises(ValueError, match=fragment):
        anforderungskatalog_laden(asset_id)


@pytest.mark.parametrize("version", ["1", "2"])
def test_specification_has_stable_sections(version):
    document = spezifikation_laden(version)
    assert document["document_version"] == version
    assert document["asset_id"] == "A-100"
    assert any(section["abschnitt"] == "3.2" for section in document["abschnitte"])


def test_unknown_document_version():
    with pytest.raises(ValueError, match="Unbekannte Dokumentversion"):
        spezifikation_laden("3")
