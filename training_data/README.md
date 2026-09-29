# Spezifikationsprüfung: SPEC-001, Anforderungskatalog AK-FBS, Referenzbefunde

Material für Strang B (Tag 2 und 3). Der fiktive Kunde ARI (K-001) will Kran A-100 mit einem Fernbedienstand nachrüsten, wie ihn A-200 schon hat, und schickt dazu ein Lastenheft (SPEC-001). Künz prüft es gegen einen internen Anforderungskatalog (AK-FBS). Alles ist synthetisch und passt zu den Anlagenunterlagen in `../unterlagen/` und den Tabellen in `../daten/`.

| Datei | Inhalt | Verwendet in |
|---|---|---|
| `SPEC-001_v1_…md` / `dist/*.pdf` | Lastenheft Version 1 | D2-02 (Event-Trigger: PDF landet in SharePoint), D2-11, Ü10, Ü12, Ü13, Ü16 |
| `SPEC-001_v2_…md` / `dist/*.pdf` | Lastenheft Version 2 (geänderter Dokumentstand) | Ü18 Abschlussfall (PR-201), Fehlerbilder in D2-19 |
| `SPEC-001_v1.extracted.json`, `…_v2…` | Text je Abschnitt mit stabiler Fundstelle (`abschnitt`) – **erzeugt**, nicht von Hand ändern | MAF-Starter: Tool „Spezifikation laden“; keine PDF-/OCR-Verarbeitung im Training |
| `AK-FBS_anforderungskatalog.json` | Sechs Anforderungen R-01 bis R-06 mit Vergleichsregel | MAF-Starter: Tool „Anforderungskatalog laden“ (Ü9: A-100 liefert sechs Anforderungen) |
| `AK-FBS_anforderungskatalog.md` / `dist/*.pdf` | Lesbare Fassung des Katalogs – **erzeugt** | Theorie D2-12, Übungsheft |
| `pruefauftraege.json` | Prüfaufträge PR-001, PR-101…105, PR-201 (review_id → Anlage, Dokument, Version) | Prüfservice-Tool „Prüfauftrag laden“ (Ü13/Ü14) |
| `referenzbefunde.json` | Erwartete Befunde je Dokumentversion inklusive Fundstellen und Klärungspunkten | CI-Referenztests (Ü11), Kontrolle in Ü10, Ü12, Ü16, Ü18 |
| `build.py` | Erzeugt die JSON- und MD-Dateien, prüft die Referenzbefunde gegen Katalog und Originaltext; `--dist` erzeugt die PDFs (Lastenheft im ARI-Layout, Katalog im Künz-Layout, siehe `../layout/`) | nach jeder Änderung ausführen |

## Referenzbefunde auf einen Blick

| Anforderung | Vergleichsregel | SPEC-001 v1 | SPEC-001 v2 |
|---|---|---|---|
| R-01 Dokumentationssprache | Teilmenge von {DE, EN} | erfüllt (§2.1) | erfüllt |
| R-02 Tragfähigkeit | höchstens 41 t | erfüllt (§2.3) | erfüllt |
| R-03 TOS-Schnittstelle | Protokollversion mindestens 2.0 | **abweichend** (§3.2: 1.4) | erfüllt (§3.2: 2.1) |
| R-04 Latenz | höchstens 50 ms | erfüllt (§4.1: 30 ms) | **unklar** – Widerspruch §4.1 (30 ms) und A.1 (80 ms) |
| R-05 Betriebstemperatur Kran | angegeben und innerhalb −20…+40 °C | **unklar** – keine Angabe | **abweichend** (§6.2: bis +45 °C) |
| R-06 Zugangsüberwachung | fachliche Bewertung (LLM + Prüfer) | erfüllt (§5.2) | erfüllt |
| **Klärungspunkte** | | R-03, R-05 | R-04, R-05 |

Das entspricht dem Stundenplan: Demo D2-11 zeigt die drei Befundarten an R-01, R-03 und R-05. Übung 10 implementiert den Vergleich „Version ≥ 2“ für R-03, und Übung 16 gibt die Klärungspunkte R-03 und R-05 frei.

## Bewusste Fallen

- **R-03, Versionsvergleich:** „1.4“ gegenüber „2.0“ ist als Text- oder Gleitkommavergleich fehleranfällig. Deshalb wird er in Übung 10 als normale Funktion umgesetzt und nicht per Prompt.
- **R-05 in v1, fehlende Angabe:** §6.1 nennt nur den klimatisierten Aufstellraum. Ein Modell, das daraus „erfüllt“ macht oder den Bereich −20…+40 °C aus der Anlagenübersicht AUE-A100 übernimmt, verwechselt Spezifikation und Bestand. Richtig ist „unklar“.
- **R-04 in v2, widersprüchliche Angabe:** 30 ms in §4.1 gegenüber 80 ms in Anhang A.1. Richtig ist „unklar“ mit beiden Fundstellen. Das ist eines der drei Fehlerbilder für D2-19.
- **§3.4, Vollständigkeit:** „Ein Bediener führt A-100 und A-200 vom selben Stand“ hat keine passende interne Anforderung. Das zeigt, warum die Vollständigkeitsprüfung eine spätere Erweiterung ist und nicht aus sechs erfüllten Einzelprüfungen folgt.
- **Länge und Ablenker (seit 27.09.2026):** Beide Versionen haben rund 3.000 Wörter auf 10 Seiten, mit typischen Lastenheft-Kapiteln (Leistungsumfang, IT-Sicherheit, Abnahme, Schulung, Ersatzteile, kaufmännische Bedingungen). Vier Stellen sehen nach Katalogthema aus, sind es aber nicht: §6.3 Raumtemperatur für Technikraum und Bedienpult (nicht R-05), §4.5 Verzögerung der Videoaufzeichnung bis 2 s (nicht R-04), §4.6 OPC UA 1.04 zum Leitstand (nicht R-03), §2.5 Bodenbelastbarkeit 5 kN/m² (nicht R-02). Die Referenzbefunde bleiben unverändert.
- **R-06, fachliche Bewertung:** Keine deterministische Regel. Das LLM schlägt vor, der Prüfer entscheidet. Diesen Befund können die Teilnehmer in Übung 12 bestätigen oder korrigieren.

## Katalog und Anlagen

AK-FBS gilt nur für A-100. Für A-200 gibt es keinen Katalog, weil dort kein Fernbedienstand nachzurüsten ist. Der Starter sollte das als verständliche Meldung zurückgeben, genauso wie bei der unbekannten Anlage A-999 in Übung 9.
