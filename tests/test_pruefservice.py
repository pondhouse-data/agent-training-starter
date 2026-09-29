"""Prüfservice ohne Modellaufruf testen: Agent Card, API-Key, Prüfauftrag-Tool, A2A-Ablauf mit Attrappe."""

import pytest
from agent_framework import AgentResponse, Message
from starlette.testclient import TestClient

from training_tools import pruefauftrag_laden


class FakeAgent:
    """Ersetzt den Foundry-Agenten; antwortet deterministisch."""

    def create_session(self, session_id=None):
        return None

    async def run(self, query, session=None, **_):
        return AgentResponse(messages=[Message(role="assistant", contents=[f"Echo: {query}"])])


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("A2A_API_KEY", "test-key")
    monkeypatch.setenv("PUBLIC_URL", "https://pruefservice.example")
    from pruefservice.app import build_app
    return TestClient(build_app(agent=FakeAgent()))


def send(client, text, key="test-key"):
    body = {"jsonrpc": "2.0", "id": "1", "method": "message/send",
            "params": {"message": {"role": "user", "kind": "message", "messageId": "m1", "contextId": "ctx-test",
                                   "parts": [{"kind": "text", "text": text}]}}}
    return client.post("/a2a", json=body, headers={"X-Api-Key": key} if key else {})


@pytest.mark.parametrize("path", ["/.well-known/agent-card.json", "/.well-known/agent.json",
                                  "/a2a/.well-known/agent-card.json", "/a2a/.well-known/agent.json"])
def test_agent_card_is_public_and_points_to_a2a_endpoint(client, path):
    card = client.get(path).json()
    assert card["name"] == "Künz Prüfspezialist"
    assert card["url"] == "https://pruefservice.example/a2a"


def test_agent_card_allows_browser_cors(client):
    response = client.get("/a2a/.well-known/agent-card.json", headers={"Origin": "https://copilotstudio.microsoft.com"})
    assert response.headers["access-control-allow-origin"] == "*"


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


@pytest.mark.parametrize("key", [None, "falsch"])
def test_a2a_requires_api_key(client, key):
    assert send(client, "Prüfe PR-001", key=key).status_code == 401


def test_a2a_round_trip_returns_artifact_and_status_message(client):
    result = send(client, "Prüfe PR-001").json()["result"]
    assert result["status"]["state"] == "completed"
    assert result["artifacts"][0]["parts"][0]["text"] == "Echo: Prüfe PR-001"
    assert result["status"]["message"]["parts"][0]["text"] == "Echo: Prüfe PR-001"


def test_review_order_by_id_and_by_document():
    assert pruefauftrag_laden("pr-101")["asset_id"] == "A-100"
    assert pruefauftrag_laden(asset_id="A-100", document_id="SPEC-001", document_version="2")["review_id"] == "PR-201"
    with pytest.raises(ValueError, match="unbekannt"):
        pruefauftrag_laden("PR-999")
