"""Ü8: einfacher MAF-Agent mit lokalem Tool; noch kein Prüfworkflow.

    uv run python agent.py                                   # Standardfrage zu A-100
    uv run python agent.py "Welche Regel gilt für R-03?"     # eigene Frage
    ENABLE_CONSOLE_EXPORTERS=true uv run python agent.py     # zusätzlich OpenTelemetry-Spans in der Konsole
"""

import asyncio
import os
import sys
import time

from agent_framework import Agent, FunctionInvocationContext, function_middleware
from agent_framework.foundry import FoundryChatClient
from azure.identity.aio import AzureCliCredential
from dotenv import load_dotenv

from training_tools import lade_anforderungskatalog, lade_spezifikation


@function_middleware
async def toolaufrufe_zeigen(context: FunctionInvocationContext, call_next) -> None:
    """Macht jeden Toolaufruf sichtbar: Eingabe → Ergebnis oder Fehler, mit Dauer."""
    print(f"  [Tool] {context.function.name}({dict(context.arguments or {})})", flush=True)
    start = time.perf_counter()
    try:
        await call_next()
    except Exception as fehler:
        print(f"  [Tool] ✗ {type(fehler).__name__}: {fehler}", flush=True)
        raise
    text = " ".join(getattr(c, "text", None) or str(c) for c in context.result or [])
    print(f"  [Tool] → {len(text)} Zeichen: {text[:90]}… ({(time.perf_counter() - start) * 1000:.0f} ms)", flush=True)


async def main() -> None:
    load_dotenv()
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    model = os.getenv("FOUNDRY_MODEL")
    if not endpoint or not model:
        raise SystemExit(".env anlegen: FOUNDRY_PROJECT_ENDPOINT und FOUNDRY_MODEL setzen (siehe SETUP.md).")
    if os.getenv("ENABLE_CONSOLE_EXPORTERS", "").lower() == "true":
        from agent_framework.observability import configure_otel_providers
        configure_otel_providers()

    frage = " ".join(sys.argv[1:]) or "Welche sechs Anforderungen gelten für A-100? Lade den Katalog."
    async with AzureCliCredential() as credential:
        client = FoundryChatClient(project_endpoint=endpoint, model=model, credential=credential)
        agent = Agent(
            client=client,
            name="SpezifikationsStarter",
            instructions=("Du unterstützt die Prüfung einer synthetischen Spezifikation. "
                          "Lade den Katalog für die angefragte Anlage mit dem Tool. "
                          "Erfinde keine Anforderungen oder Fundstellen. Antworte kurz auf Deutsch."),
            tools=[lade_anforderungskatalog, lade_spezifikation],
            middleware=[toolaufrufe_zeigen],
        )
        print(f"Frage: {frage}")
        response = await agent.run(frage)
        print(f"\n{response}")


if __name__ == "__main__":
    asyncio.run(main())
