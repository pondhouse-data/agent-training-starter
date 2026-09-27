"""Ü8: einfacher MAF-Agent mit lokalem Tool; noch kein Prüfworkflow."""

import asyncio
import os

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from azure.identity.aio import AzureCliCredential
from dotenv import load_dotenv

from training_tools import lade_anforderungskatalog, lade_spezifikation


async def main() -> None:
    load_dotenv()
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    model = os.getenv("FOUNDRY_MODEL")
    if not endpoint or not model:
        raise SystemExit(".env anlegen: FOUNDRY_PROJECT_ENDPOINT und FOUNDRY_MODEL setzen (siehe SETUP.md).")

    async with AzureCliCredential() as credential:
        client = FoundryChatClient(project_endpoint=endpoint, model=model, credential=credential)
        agent = Agent(
            client=client,
            name="SpezifikationsStarter",
            instructions=("Du unterstützt die Prüfung einer synthetischen Spezifikation. "
                          "Lade den Katalog für die angefragte Anlage mit dem Tool. "
                          "Erfinde keine Anforderungen oder Fundstellen. Antworte kurz auf Deutsch. "
                          "TODO Ü10: deterministische Vergleichsregeln als Workflow ergänzen."),
            tools=[lade_anforderungskatalog, lade_spezifikation],
        )
        response = await agent.run("Welche sechs Anforderungen gelten für A-100? Lade den Katalog.")
        print(response)


if __name__ == "__main__":
    asyncio.run(main())
