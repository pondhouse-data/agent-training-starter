"""Prüfservice ohne Modellaufruf testen: Agent Card, API-Key, Auftragserkennung, A2A/REST mit dem echten
Workflow und der geprüften Referenz-Extraktion statt des Modells."""

import pytest
from starlette.testclient import TestClient

from pruefservice.workflow import review_id_bestimmen, workflow_pruefen
from training_tools import pruefauftrag_laden


async def referenz_pruefen(review_id):
    return await workflow_pruefen(review_id, "referenz")


def befund(text, requirement_id):
    zeile = next(z for z in text.splitlines() if z.startswith(f"| {requirement_id} |"))
    return zeile.split(" | ")[1]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("A2A_API_KEY", "test-key")
    monkeypatch.setenv("PUBLIC_URL", "https://pruefservice.example")
    from pruefservice.app import build_app
    return TestClient(build_app(pruefen=referenz_pruefen))


def send(client, text, key="test-key"):
    body = {"jsonrpc": "2.0", "id": "1", "method": "message/send",
            "params": {"message": {"role": "user", "kind": "message", "messageId": "m1", "contextId": "ctx-test",
                                   "parts": [{"kind": "text", "text": text}]}}}
    return client.post("/a2a", json=body, headers={"X-Api-Key": key} if key else {})


@pytest.mark.parametrize("path", ["/.well-known/agent-card.json", "/.well-known/agent.json",
                                  "/a2a/.well-known/agent-card.json", "/a2a/.well-known/agent.json"])
def test_agent_card_is_public_and_points_to_a2a_endpoint(client, path):
    card = client.get(path).json()
    assert card["name"] == "Kuenz-Pruefspezialist"
    assert card["url"] == "https://pruefservice.example/a2a"
    assert card["protocolVersion"] == "0.3"
    assert "supportedInterfaces" not in card  # Copilot Studio lehnt v1-Cards ab


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
    text = result["artifacts"][0]["parts"][0]["text"]
    assert result["status"]["message"]["parts"][0]["text"] == text
    assert text.startswith("Prüfauftrag PR-001 · SPEC-001 v1 · Katalog AK-FBS 1.0 · Anlage A-100\n")
    assert [befund(text, r) for r in ("R-01", "R-02", "R-04", "R-05")] == ["erfüllt", "erfüllt", "erfüllt", "unklar"]
    # R-03 ist vor Ü10 „unklar“ (Vergleichsregel fehlt), danach „abweichend“ – Klärungspunkt bleibt es in beiden Fällen.
    assert befund(text, "R-03") in {"unklar", "abweichend"}
    assert "\nKlärungspunkte: R-03, R-05\n" in text
    assert "die fachliche Entscheidung trifft der Prüfer" in text


def test_a2a_asks_back_instead_of_guessing(client):
    result = send(client, "Prüfe das bitte").json()["result"]
    assert result["status"]["state"] == "input-required"
    assert "review_id" in result["status"]["message"]["parts"][0]["text"]


@pytest.mark.parametrize("text,review_id", [("Prüfe PR-101", "PR-101"), ("bitte pr-201 prüfen", "PR-201"),
                                            ("Prüfe SPEC-001 v2 für A-100", "PR-201"),
                                            ("Prüfe SPEC-001 Version 1 für A-100", "PR-001")])
def test_review_id_from_request(text, review_id):
    assert review_id_bestimmen(text) == review_id


@pytest.mark.parametrize("text,meldung", [("Prüfe das bitte", "review_id"), ("Prüfe PR-001 und PR-101", "Mehrere"),
                                          ("Prüfe PR-999", "unbekannt"), ("Prüfe SPEC-001 für A-100", "review_id")])
def test_unclear_request_raises_question(text, meldung):
    with pytest.raises(ValueError, match=meldung):
        review_id_bestimmen(text)


def test_review_order_by_id_and_by_document():
    assert pruefauftrag_laden("pr-101")["asset_id"] == "A-100"
    assert pruefauftrag_laden(asset_id="A-100", document_id="SPEC-001", document_version="2")["review_id"] == "PR-201"
    with pytest.raises(ValueError, match="unbekannt"):
        pruefauftrag_laden("PR-999")


def test_rest_review_runs_workflow_and_exposes_task_status(client):
    response = client.post("/pruefung", json={"review_id": "pr-001", "context_id": "rest-test"},
                           headers={"X-Api-Key": "test-key"})
    assert response.status_code == 200
    result = response.json()
    assert result["review_id"] == "PR-001"
    assert result["context_id"] == "rest-test"
    assert result["status"] == "completed"
    assert result["antwort"].startswith("Prüfauftrag PR-001 · SPEC-001 v1")
    assert "Extraktion referenz" in result["antwort"]
    assert result["task_id"]
    assert result["version"]
    status = client.get(f'/pruefung/{result["task_id"]}', headers={"X-Api-Key": "test-key"})
    assert status.status_code == 200
    assert status.json() == result


@pytest.mark.parametrize("key", [None, "falsch"])
@pytest.mark.parametrize("method,path,body", [("POST", "/pruefung", {"review_id": "PR-001"}),
                                             ("GET", "/pruefung/unbekannt", None)])
def test_rest_requires_same_api_key(client, key, method, path, body):
    response = client.request(method, path, json=body, headers={"X-Api-Key": key} if key else {})
    assert response.status_code == 401


@pytest.mark.parametrize("body", [{}, [], {"review_id": None}, {"review_id": 1},
                                  {"review_id": ""}, {"review_id": "PR-001", "unexpected": "x"},
                                  {"review_id": "PR-001", "context_id": ""}])
def test_rest_validates_input_before_running_workflow(client, body):
    assert client.post("/pruefung", json=body, headers={"X-Api-Key": "test-key"}).status_code == 400


def test_rest_rejects_invalid_json(client):
    assert client.post("/pruefung", content="{", headers={"X-Api-Key": "test-key"}).status_code == 400


def test_rest_unknown_review_and_task(client):
    headers = {"X-Api-Key": "test-key"}
    assert client.post("/pruefung", json={"review_id": "PR-999"}, headers=headers).status_code == 404
    assert client.get("/pruefung/unbekannt", headers=headers).status_code == 404


def test_rest_model_failure_is_not_a_success(monkeypatch):
    async def kaputt(_):
        raise RuntimeError("private-model-details")

    monkeypatch.setenv("A2A_API_KEY", "test-key")
    from pruefservice.app import build_app
    with TestClient(build_app(pruefen=kaputt)) as client:
        response = client.post("/pruefung", json={"review_id": "PR-001"}, headers={"X-Api-Key": "test-key"})
        assert response.status_code == 502
        result = response.json()
        assert result["status"] == "failed"
        assert "private-model-details" not in response.text
        status = client.get(f'/pruefung/{result["task_id"]}', headers={"X-Api-Key": "test-key"})
        assert status.json()["status"] == "failed"


def test_openapi_is_public_and_declares_auth_and_operations(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["swagger"] == "2.0"
    assert schema["host"] == "pruefservice.example"
    assert schema["securityDefinitions"]["ApiKey"]["name"] == "X-Api-Key"
    assert schema["security"] == [{"ApiKey": []}]
    assert schema["paths"]["/pruefung"]["post"]["operationId"] == "PruefauftragPruefen"
    assert schema["paths"]["/pruefung/{task_id}"]["get"]["operationId"] == "PruefstatusAbrufen"


def test_rest_status_does_not_run_the_workflow_again(monkeypatch):
    aufrufe = []

    async def zaehlend(review_id):
        aufrufe.append(review_id)
        return await referenz_pruefen(review_id)

    monkeypatch.setenv("A2A_API_KEY", "test-key")
    from pruefservice.app import build_app
    with TestClient(build_app(pruefen=zaehlend)) as client:
        result = client.post("/pruefung", json={"review_id": "PR-001"},
                             headers={"X-Api-Key": "test-key"}).json()
        for _ in range(2):
            assert client.get(f'/pruefung/{result["task_id"]}', headers={"X-Api-Key": "test-key"}).status_code == 200
        assert aufrufe == ["PR-001"]
