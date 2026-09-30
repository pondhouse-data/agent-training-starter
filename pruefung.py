"""Ü10/Ü11: deterministische Prüfung von SPEC-001 gegen den Anforderungskatalog AK-FBS.

Das Modell extrahiert nur Angaben mit Fundstellen (siehe `pruefworkflow.py`). Alles, was danach
kommt, ist normaler Python-Code: Fundstellen gegen den Originaltext prüfen und je Anforderung die
Vergleichsregel aus dem Katalog anwenden. Genau diese Funktionen testen die Referenztests.
"""

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from training_tools import anforderungskatalog_laden, spezifikation_laden

REFERENZ_EXTRAKTION = Path(__file__).resolve().parent / "referenz"

Status = Literal["erfüllt", "abweichend", "unklar"]


# --- Strukturierte Ausgabe der Extraktion (LLM-Schritt) --------------------------------------

class Fundstelle(BaseModel):
    abschnitt: str = Field(description="Abschnittsnummer aus der Spezifikation, z. B. '3.2' oder 'A.1'")
    zitat: str = Field(description="Wörtlicher, zusammenhängender Ausschnitt aus genau diesem Abschnitt (3–12 Wörter)")
    bezug: str = Field(description="Worauf sich die Angabe laut Text bezieht, z. B. 'Kran A-100', 'Aufstellraum', 'Leitstand'")
    werte: list[str] = Field(description="Normalisierte Werte aus dem Zitat, Format je Anforderung siehe Anweisung")


class Angabe(BaseModel):
    requirement_id: str = Field(description="R-01 bis R-06")
    fundstellen: list[Fundstelle] = Field(description="Leer, wenn die Spezifikation dazu nichts sagt")
    bewertung_vorschlag: Status | None = Field(description="Nur für R-06 (fachliche Bewertung), sonst null")
    begruendung: str = Field(description="Ein Satz: was steht wo, oder warum nichts gefunden wurde")


class Extraktion(BaseModel):
    angaben: list[Angabe]


# --- Vergleichsregeln (deterministisch) ------------------------------------------------------

def version_mindestens(ist: str, soll: str) -> bool:
    """R-03: Ist die Protokollversion `ist` mindestens `soll`?

    TODO Ü10: implementieren. Achtung: Versionen sind keine Kommazahlen ("2.10" ist neuer als "2.9").
    Ungültige Angaben wie "2.x" sollen einen ValueError mit "Ungültige" in der Meldung auslösen.
    """
    raise NotImplementedError("TODO Ü10: Versionsvergleich für R-03 fehlt noch")


def _zahl(wert: str) -> float:
    text = wert.strip().replace("−", "-").replace(",", ".").replace("+", "")
    if not re.fullmatch(r"-?\d+(\.\d+)?", text):
        raise ValueError(f"Keine Zahl: {wert!r}")
    return float(text)


def _format(zahl: float) -> str:
    return f"{zahl:g}".replace("-", "−")


def _soll_text(regel: dict, anforderung: dict) -> str:
    einheit = f" {regel['einheit']}" if regel.get("einheit") else ""
    match regel["typ"]:
        case "teilmenge":
            return f"Teilmenge von {{{', '.join(regel['erlaubt'])}}}"
        case "maximum":
            return f"höchstens {_format(regel['grenzwert'])}{einheit}"
        case "version_mindestens":
            return f"Protokollversion mindestens {regel['grenzwert']}"
        case "bereich_innerhalb":
            return f"Bereich angegeben und innerhalb {_format(regel['min'])}{einheit} bis +{_format(regel['max'])}{einheit}"
        case _:
            return anforderung["soll"]


def _bewerte(regel: dict, werte_je_fundstelle: list[list[str]], angabe: Angabe | None) -> tuple[Status, str, object, str]:
    """Liefert (Status, Ist-Text, Ist-Wert, Begründung) für bereits geprüfte Fundstellen."""
    typ = regel["typ"]
    einheit = f" {regel['einheit']}" if regel.get("einheit") else ""

    if typ == "fachliche_bewertung":
        if not werte_je_fundstelle:
            return "unklar", None, None, "Keine Angabe in der Spezifikation gefunden."
        vorschlag = angabe.bewertung_vorschlag if angabe and angabe.bewertung_vorschlag else "unklar"
        return vorschlag, None, None, f"KI-Vorschlag, der Prüfer entscheidet: {angabe.begruendung if angabe else ''}".strip()

    if not werte_je_fundstelle:
        return "unklar", None, None, "Die Spezifikation macht dazu keine Angabe; fehlende Angaben sind nie automatisch erfüllt."

    if typ == "teilmenge":
        sprachen = sorted({w.strip().upper() for werte in werte_je_fundstelle for w in werte})
        if not sprachen:
            return "unklar", None, None, "Fundstelle ohne erkennbare Sprachangabe."
        erlaubt = set(regel["erlaubt"])
        status = "erfüllt" if set(sprachen) <= erlaubt else "abweichend"
        return status, ", ".join(sprachen), sprachen, (
            f"Gefordert: {', '.join(sprachen)}; lieferbar: {', '.join(sorted(erlaubt))}.")

    if typ in {"maximum", "version_mindestens"}:
        verschieden = sorted({w.strip() for werte in werte_je_fundstelle for w in werte})
        if len(verschieden) != 1:
            return "unklar", f"widersprüchlich: {' / '.join(verschieden)}", verschieden, (
                "Die Spezifikation nennt unterschiedliche Werte; der Widerspruch muss mit dem Kunden geklärt werden.")
        wert = verschieden[0]
        if typ == "maximum":
            zahl = _zahl(wert)
            status = "erfüllt" if zahl <= regel["grenzwert"] else "abweichend"
            return status, f"{_format(zahl)}{einheit}", zahl, (
                f"{_format(zahl)}{einheit} gegenüber höchstens {_format(regel['grenzwert'])}{einheit}.")
        ok = version_mindestens(wert, regel["grenzwert"])
        return ("erfüllt" if ok else "abweichend"), f"Protokollversion {wert}", wert, (
            f"Protokollversion {wert} gegenüber mindestens {regel['grenzwert']}.")

    if typ == "bereich_innerhalb":
        bereiche = set()
        for werte in werte_je_fundstelle:
            if len(werte) != 2:
                return "unklar", None, None, f"Bereich nicht eindeutig angegeben: {werte}."
            bereiche.add((_zahl(werte[0]), _zahl(werte[1])))
        if len(bereiche) != 1:
            return "unklar", "widersprüchliche Bereiche", sorted(bereiche), "Die Spezifikation nennt unterschiedliche Bereiche."
        unten, oben = bereiche.pop()
        ok = unten >= regel["min"] and oben <= regel["max"]
        ist = f"{_format(unten)}{einheit} bis +{_format(oben)}{einheit}"
        return ("erfüllt" if ok else "abweichend"), ist, [unten, oben], (
            f"Gefordert {ist}; zulässig {_format(regel['min'])}{einheit} bis +{_format(regel['max'])}{einheit}.")

    raise ValueError(f"Unbekannte Vergleichsregel {typ!r}")


def _normalisiert(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("−", "-")).strip().casefold()


def vergleiche(extraktion: Extraktion, document_version: str) -> list[dict]:
    """Fundstellen gegen den Originaltext prüfen und jede Katalogregel anwenden. Kein Modellaufruf."""
    dokument = spezifikation_laden(document_version)
    katalog = anforderungskatalog_laden(dokument["asset_id"])
    abschnitte = {a["abschnitt"]: a["text"] for a in dokument["abschnitte"]}
    angaben = {a.requirement_id: a for a in extraktion.angaben}

    befunde = []
    for anforderung in katalog["requirements"]:
        rid, regel = anforderung["requirement_id"], anforderung["vergleichsregel"]
        angabe = angaben.get(rid)
        belegt, verworfen = [], []
        for fundstelle in angabe.fundstellen if angabe else []:
            text = abschnitte.get(fundstelle.abschnitt)
            if text is not None and fundstelle.zitat.strip() and _normalisiert(fundstelle.zitat) in _normalisiert(text):
                belegt.append(fundstelle)
            else:
                verworfen.append(fundstelle)

        if verworfen:
            status, ist, ist_wert = "unklar", None, None
            begruendung = ("Fundstelle nicht im Originaltext belegt: "
                           + "; ".join(f"§{f.abschnitt} „{f.zitat}“" for f in verworfen)
                           + ". Nicht übernehmen, im Dokument nachschlagen.")
        else:
            try:
                status, ist, ist_wert, begruendung = _bewerte(regel, [f.werte for f in belegt], angabe)
            except NotImplementedError as fehlt:
                status, ist, ist_wert, begruendung = "unklar", None, None, f"Keine Bewertung: {fehlt}."
            except ValueError as fehler:
                status, ist, ist_wert, begruendung = "unklar", None, None, f"Angabe nicht auswertbar: {fehler}."

        befunde.append({
            "requirement_id": rid,
            "thema": anforderung["thema"],
            "soll": _soll_text(regel, anforderung),
            "ist": ist,
            "ist_wert": ist_wert,
            "fundstellen": [{"document_id": dokument["document_id"], "document_version": document_version,
                             "abschnitt": f.abschnitt, "zitat": f.zitat} for f in belegt],
            "status": status,
            "begruendung": begruendung,
            "regel": regel["typ"],
        })
    return befunde


def referenz_extraktion_laden(document_version: str) -> Extraktion:
    """Festgehaltene, geprüfte Extraktion: damit laufen Regeln und CI ohne Modellaufruf."""
    pfad = REFERENZ_EXTRAKTION / f"SPEC-001_v{document_version}.angaben.json"
    if not pfad.exists():
        raise ValueError(f"Keine Referenz-Extraktion für Dokumentversion {document_version!r}.")
    return Extraktion.model_validate(json.loads(pfad.read_text(encoding="utf-8")))


def pruefe_spezifikation(document_version: str = "1") -> list[dict]:
    """Ü11: Regeln auf die Referenz-Extraktion anwenden (deterministisch, ohne Azure)."""
    return vergleiche(referenz_extraktion_laden(document_version), document_version)


if __name__ == "__main__":
    import sys

    version = sys.argv[1] if len(sys.argv) > 1 else "1"
    for befund in pruefe_spezifikation(version):
        stellen = ", ".join(f"§{f['abschnitt']}" for f in befund["fundstellen"]) or "—"
        print(f"{befund['requirement_id']}  {befund['status']:<10}  {stellen:<12}  {befund['begruendung']}")
