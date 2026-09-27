---
title: "Interner Anforderungskatalog – Nachrüstung Fernbedienstand an RMG-Intermodalkranen"
document_id: "AK-FBS"
document_version: "1.0"
bereich: "Interne Vorgabe"
---

| | |
|---|---|
| **Katalog-ID** | AK-FBS |
| **Version** | 1.0 |
| **Gilt für** | A-100 |

> **SYNTHETISCHES TRAININGSDOKUMENT.** Für das Künz-Agententraining erfunden; keine gültige Künz-Vorgabe.

## Grundregeln

- Fehlt die Angabe in der Spezifikation, ist der Befund 'unklar' – nie automatisch 'erfüllt' oder 'abweichend'.
- Widersprechen sich Angaben innerhalb der Spezifikation, ist der Befund 'unklar'; alle widersprüchlichen Fundstellen werden genannt.
- Jede Fundstelle muss im Originaltext der geprüften Dokumentversion vorkommen.
- Geprüft wird nur in eine Richtung: Spezifikation gegen diesen Katalog. Kundenforderungen ohne passende interne Anforderung (z. B. SPEC-001 §3.4) sind nicht Teil der Prüfung.

## Anforderungen

| ID | Thema | Soll | Vergleichsregel |
|---|---|---|---|
| R-01 | Dokumentationssprache | Geforderte Dokumentationssprachen sind Deutsch und/oder Englisch; Künz liefert Dokumentation in DE und EN. | teilmenge: erlaubt = ['DE', 'EN'] |
| R-02 | Tragfähigkeit | Geforderte Tragfähigkeit unter Spreader höchstens 41 t (Bestand A-100, AUE-A100 §2). | maximum: grenzwert = 41, einheit = t |
| R-03 | TOS-Schnittstelle | Fernbetrieb setzt das Künz TOS-Interface ab Protokollversion 2.0 voraus. | version_mindestens: grenzwert = 2.0 |
| R-04 | Latenz Fernbedienstand–Kran | Zugesicherte Latenz zwischen Fernbedienstand und Kran höchstens 50 ms. | maximum: grenzwert = 50, einheit = ms |
| R-05 | Betriebstemperatur des Krans | Die Spezifikation muss den Betriebstemperaturbereich des Krans angeben; er muss innerhalb −20 °C bis +40 °C liegen (AUE-A100 §2). | bereich_innerhalb: min = -20, max = 40, einheit = °C |
| R-06 | Zugangsüberwachung | Für den Fernbetrieb ist eine Zugangsüberwachung der Kranbahn mit Personenerkennung (Laserscanner oder gleichwertig) vorzusehen, die den Fernbetrieb bei Personen im Arbeitsbereich sperrt. | fachliche_bewertung |
