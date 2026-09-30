"""Prüfworkflow bedienen (D2-11, D2-17, Ü10, Ü12).

    uv run python pruefen.py start PR-101                 # bis zum Prüferschritt, dann endet der Prozess
    uv run python pruefen.py status PR-101                # Checkpoint-Kette und offene Prüferfragen
    uv run python pruefen.py fortsetzen PR-101            # neuer Prozess: laden, entscheiden, Bericht
    uv run python pruefen.py bericht PR-101               # abgeschlossenen Bericht anzeigen

`--extraktion referenz` nutzt die geprüfte Referenz-Extraktion statt des Modells (ohne Azure).
"""

import argparse
import asyncio
import getpass
import json
import shutil
import sys
from pathlib import Path

from pruefworkflow import (
    CHECKPOINTS,
    WORKFLOW_NAME,
    PrueferAnfrage,
    PrueferEntscheidung,
    baue_workflow,
    checkpoint_storage,
)

BERICHTE = Path(__file__).resolve().parent / "berichte"
STATUS_KURZ = {"e": "erfüllt", "a": "abweichend", "u": "unklar"}


def befund_zeile(befund: dict) -> str:
    stellen = ", ".join(f"§{f['abschnitt']}" for f in befund["fundstellen"]) or "keine Fundstelle"
    return f"{befund['requirement_id']}  {befund['status']:<10}  {stellen:<16}  {befund['thema']}"


def zeige_befund(befund: dict) -> None:
    print(f"\n{befund['requirement_id']} {befund['thema']}  –  KI-Befund: {befund['status'].upper()}")
    print(f"  Soll: {befund['soll']}")
    print(f"  Ist:  {befund['ist'] or '—'}")
    for f in befund["fundstellen"]:
        print(f"  Fundstelle §{f['abschnitt']} (v{f['document_version']}): „{f['zitat']}“")
    print(f"  Begründung: {befund['begruendung']}")


async def ereignisse(stream, anfragen: dict[str, PrueferAnfrage]) -> dict | None:
    """Stream auswerten: Fortschritt zeigen, Prüferfragen sammeln, Ergebnis zurückgeben."""
    ausgabe = None
    async for event in stream:
        if event.type == "executor_invoked":
            print(f"  → {event.executor_id}")
        elif event.type == "request_info":
            anfragen[event.request_id] = event.data
        elif event.type == "output":
            ausgabe = event.data
        elif event.type in {"executor_failed", "failed"}:
            print(f"  ✗ {event.type}: {event.details}", file=sys.stderr)
    return ausgabe


def entscheidungen_abfragen(anfragen: dict[str, PrueferAnfrage], vorgaben: dict[str, tuple[str, str]],
                            rest_bestaetigen: bool, pruefer: str) -> dict[str, PrueferEntscheidung]:
    antworten = {}
    for request_id, anfrage in anfragen.items():
        befund = anfrage.befund
        rid = befund["requirement_id"]
        zeige_befund(befund)
        if rid in vorgaben:
            status, kommentar = vorgaben[rid]
        elif rest_bestaetigen or not sys.stdin.isatty():
            status, kommentar = befund["status"], ""
        else:
            wahl = input("  [Enter] bestätigen · e/a/u = korrigieren auf erfüllt/abweichend/unklar: ").strip().lower()
            status = STATUS_KURZ.get(wahl, befund["status"])
            kommentar = ""
            while status != befund["status"] and not kommentar:
                kommentar = input("  Kommentar (Pflicht bei Korrektur): ").strip()
        entscheidung = "bestätigt" if status == befund["status"] else "korrigiert"
        if entscheidung == "korrigiert" and not kommentar:
            raise SystemExit(f"{rid}: Korrektur ohne Kommentar ist nicht zulässig.")
        print(f"  Prüfer: {entscheidung} → {status}" + (f" ({kommentar})" if kommentar else ""))
        antworten[request_id] = PrueferEntscheidung(entscheidung=entscheidung, status=status,
                                                    kommentar=kommentar, pruefer=pruefer)
    return antworten


def bericht_speichern(bericht: dict) -> Path:
    BERICHTE.mkdir(exist_ok=True)
    pfad = BERICHTE / f"{bericht['review_id']}.json"
    pfad.write_text(json.dumps(bericht, ensure_ascii=False, indent=2), encoding="utf-8")
    zeilen = [f"# Prüfbericht {bericht['review_id']}",
              f"{bericht['document_id']} Version {bericht['document_version']} · Anlage {bericht['asset_id']} · "
              f"Katalog {bericht['catalog_id']} {bericht['catalog_version']} · Extraktion: {bericht['extraktion']}",
              "", "| Anforderung | KI-Befund | Prüfer | Endgültig | Fundstellen | Kommentar |", "|---|---|---|---|---|---|"]
    for e in bericht["befunde"]:
        ki, p = e["ki_befund"], e["pruefer_entscheidung"]
        stellen = ", ".join(f"§{f['abschnitt']}" for f in ki["fundstellen"]) or "—"
        zeilen.append(f"| {e['requirement_id']} {ki['thema']} | {ki['status']} | {p['entscheidung']} ({p['pruefer']}) "
                      f"| **{e['endgueltiger_status']}** | {stellen} | {p['kommentar'] or ''} |")
    zeilen += ["", f"Klärungspunkte: {', '.join(bericht['klaerungspunkte']) or 'keine'}"]
    pfad.with_suffix(".md").write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    return pfad


def parse_vorgaben(werte: list[str]) -> dict[str, tuple[str, str]]:
    """--entscheidung R-05=abweichend:Kommentar  (Status auch als e/a/u)"""
    vorgaben = {}
    for wert in werte:
        rid, _, rest = wert.partition("=")
        status, _, kommentar = rest.partition(":")
        status = STATUS_KURZ.get(status.strip().lower(), status.strip())
        if status not in STATUS_KURZ.values():
            raise SystemExit(f"Ungültige Entscheidung {wert!r}; Format R-05=abweichend:Kommentar")
        vorgaben[rid.strip().upper()] = (status, kommentar.strip())
    return vorgaben


async def start(args) -> None:
    review_id = args.review_id.upper()
    if (CHECKPOINTS / review_id).exists():
        if not args.neu:
            raise SystemExit(f"Für {review_id} gibt es schon Checkpoints. Weiter mit `fortsetzen {review_id}` "
                             f"oder neu beginnen mit `start {review_id} --neu`.")
        shutil.rmtree(CHECKPOINTS / review_id)
    storage = checkpoint_storage(review_id)
    workflow = baue_workflow(storage, args.extraktion)
    print(f"Prüfung {review_id} startet (Extraktion: {args.extraktion})")
    anfragen: dict[str, PrueferAnfrage] = {}
    await ereignisse(workflow.run(review_id, stream=True), anfragen)
    if not anfragen:
        raise SystemExit("Workflow endete ohne Prüferschritt – Fehlermeldung oben prüfen.")

    erste = next(iter(anfragen.values()))
    print(f"\nKI-Befunde für {review_id}, SPEC-001 Version {erste.document_version}:")
    for anfrage in anfragen.values():
        print("  " + befund_zeile(anfrage.befund))
    letzter = await storage.get_latest(workflow_name=WORKFLOW_NAME)
    print(f"\nPrüferschritt erreicht: {len(anfragen)} Entscheidungen offen. Checkpoint {letzter.checkpoint_id} gespeichert.")
    if args.direkt:
        await entscheiden(workflow, anfragen, args)
    else:
        print(f"Der Prozess endet hier. Später weiter mit:\n  uv run python pruefen.py fortsetzen {review_id}")


async def fortsetzen(args) -> None:
    review_id = args.review_id.upper()
    storage = checkpoint_storage(review_id)
    letzter = await storage.get_latest(workflow_name=WORKFLOW_NAME) if (CHECKPOINTS / review_id).exists() else None
    if letzter is None:
        raise SystemExit(f"Kein Checkpoint für {review_id}. Zuerst: uv run python pruefen.py start {review_id}")
    if not letzter.pending_request_info_events:
        raise SystemExit(f"{review_id} hat keine offenen Prüferfragen mehr. Bericht: uv run python pruefen.py bericht {review_id}")
    print(f"Lade Checkpoint {letzter.checkpoint_id} vom {letzter.timestamp} für {review_id}")
    workflow = baue_workflow(storage, "referenz")  # Extraktion ist bereits erledigt und im Checkpoint
    anfragen: dict[str, PrueferAnfrage] = {}
    await ereignisse(workflow.run(checkpoint_id=letzter.checkpoint_id, stream=True), anfragen)
    await entscheiden(workflow, anfragen, args)


async def entscheiden(workflow, anfragen: dict[str, PrueferAnfrage], args) -> None:
    antworten = entscheidungen_abfragen(anfragen, parse_vorgaben(args.entscheidung), args.rest_bestaetigen, args.pruefer)
    bericht = await ereignisse(workflow.run(stream=True, responses=antworten), {})
    if bericht is None:
        raise SystemExit("Kein Bericht erzeugt – Fehlermeldung oben prüfen.")
    pfad = bericht_speichern(bericht)
    print(f"\nBericht abgeschlossen: {pfad.relative_to(Path.cwd()) if pfad.is_relative_to(Path.cwd()) else pfad}"
          f" (+ .md). Klärungspunkte: {', '.join(bericht['klaerungspunkte']) or 'keine'}")


async def status(args) -> None:
    review_id = args.review_id.upper()
    if not (CHECKPOINTS / review_id).exists():
        raise SystemExit(f"Kein Checkpoint für {review_id}.")
    storage = checkpoint_storage(review_id)
    kette = sorted(await storage.list_checkpoints(workflow_name=WORKFLOW_NAME), key=lambda c: c.timestamp)
    print(f"Checkpoints für {review_id} (Workflow {WORKFLOW_NAME}), älteste zuerst:")
    for c in kette:
        vorher = (c.previous_checkpoint_id or "—")[:8]
        offen = len(c.pending_request_info_events)
        print(f"  {c.checkpoint_id[:8]}  ← {vorher:<8}  Superstep {c.iteration_count}  {c.timestamp}"
              + (f"  offene Prüferfragen: {offen}" if offen else ""))
    if kette and kette[-1].pending_request_info_events:
        print(f"\nWartet auf den Prüfer. Weiter mit: uv run python pruefen.py fortsetzen {review_id}")


def bericht(args) -> None:
    pfad = BERICHTE / f"{args.review_id.upper()}.md"
    if not pfad.exists():
        raise SystemExit(f"Noch kein Bericht für {args.review_id.upper()}.")
    print(pfad.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Prüfworkflow SPEC-001 (MAF)")
    sub = parser.add_subparsers(dest="befehl", required=True)

    p_start = sub.add_parser("start", help="Prüfung bis zum Prüferschritt ausführen")
    p_start.add_argument("review_id")
    p_start.add_argument("--extraktion", choices=["modell", "referenz"], default="modell")
    p_start.add_argument("--neu", action="store_true", help="vorhandene Checkpoints dieses Auftrags löschen")
    p_start.add_argument("--direkt", action="store_true", help="ohne Neustart gleich entscheiden")

    p_weiter = sub.add_parser("fortsetzen", help="aus dem letzten Checkpoint fortsetzen und entscheiden")
    p_weiter.add_argument("review_id")

    for p in (p_start, p_weiter):
        p.add_argument("--entscheidung", action="append", default=[], metavar="R-05=abweichend:Kommentar")
        p.add_argument("--rest-bestaetigen", action="store_true", help="nicht vorgegebene Befunde bestätigen")
        p.add_argument("--pruefer", default=getpass.getuser())

    sub.add_parser("status", help="Checkpoint-Kette anzeigen").add_argument("review_id")
    sub.add_parser("bericht", help="Bericht anzeigen").add_argument("review_id")

    args = parser.parse_args()
    if args.befehl == "bericht":
        bericht(args)
    else:
        asyncio.run({"start": start, "fortsetzen": fortsetzen, "status": status}[args.befehl](args))


if __name__ == "__main__":
    main()
