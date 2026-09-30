"""Ü10: Versionsvergleich für R-03 als normale Funktion – nicht per Prompt."""

import pytest

from pruefung import version_mindestens


@pytest.mark.exercise
@pytest.mark.skip(reason="Ü10: version_mindestens in pruefung.py implementieren, dann Skip entfernen")
@pytest.mark.parametrize("ist,soll,erwartet", [
    ("1.4", "2.0", False),
    ("2.1", "2.0", True),
    ("2.0", "2.0", True),
    ("2.10", "2.9", True),
    ("2", "2.0", True),
    ("2.0.1", "2.0", True),
])
def test_version_mindestens(ist, soll, erwartet):
    assert version_mindestens(ist, soll) is erwartet


@pytest.mark.exercise
@pytest.mark.skip(reason="Ü10: version_mindestens in pruefung.py implementieren, dann Skip entfernen")
@pytest.mark.parametrize("wert", ["", "2.x", "-1.0", "2..1", "2.1beta"])
def test_ungueltige_version(wert):
    with pytest.raises(ValueError, match="Ungültige"):
        version_mindestens(wert, "2.0")
