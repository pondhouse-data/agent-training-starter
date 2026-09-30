"""REST-Tool als reversibler Ersatz für Studios ausgehende A2A-Ausführung.

Verwendet denselben Handler/Executor/Task-Speicher wie A2A, nicht einen zweiten Agenten.
Die REST-Antwort ist synchron; Status bleibt nur bis zum Neustart dieser Replik verfügbar.
"""

import json
import logging
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from a2a.server.context import ServerCallContext
from a2a.types import Message, Part, Role, SendMessageRequest, Task, TaskState
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.responses import JSONResponse
from starlette.routing import Route

from training_tools import pruefauftrag_laden

log = logging.getLogger("pruefservice")


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    review_id: str = Field(min_length=1, max_length=32)
    context_id: str | None = Field(default=None, min_length=1, max_length=128)


def result_body(task: Task, version: str) -> dict:
    text = "\n".join(part.text for artifact in task.artifacts for part in artifact.parts if part.text)
    if not text:
        text = "\n".join(part.text for part in task.status.message.parts if part.text)
    return {"review_id": task.metadata["kuenz.review_id"], "task_id": task.id,
            "context_id": task.context_id,
            "status": TaskState.Name(task.status.state).removeprefix("TASK_STATE_").lower(),
            "antwort": text, "version": version}


def rest_routes(handler, task_store, public_url: str, version: str) -> list[Route]:
    async def review(request):
        try:
            body = ReviewInput.model_validate(await request.json())
        except (ValidationError, json.JSONDecodeError):
            return JSONResponse({"error": "JSON mit review_id (Text) und optional context_id (Text) erwartet."}, status_code=400)
        try:
            review_id = pruefauftrag_laden(body.review_id.strip().upper())["review_id"]
        except ValueError:
            return JSONResponse({"error": "Prüfauftrag unbekannt."}, status_code=404)
        context_id = body.context_id or f"rest-{uuid4()}"
        call_context = ServerCallContext()
        log.info("REST-Prüfung review_id=%s context_id=%s", review_id, context_id)
        result = await handler.on_message_send(SendMessageRequest(message=Message(
            message_id=str(uuid4()), context_id=context_id, role=Role.ROLE_USER,
            parts=[Part(text=f"Prüfe den Prüfauftrag {review_id}.")])), call_context)
        if not isinstance(result, Task):
            return JSONResponse({"error": "Prüfservice lieferte keinen Task."}, status_code=502)
        result.metadata.update({"kuenz.review_id": review_id})
        await task_store.save(result, call_context)
        log.info("REST-Ergebnis review_id=%s context_id=%s task_id=%s status=%s",
                 review_id, context_id, result.id, TaskState.Name(result.status.state))
        return JSONResponse(result_body(result, version),
                            status_code=200 if result.status.state == TaskState.TASK_STATE_COMPLETED else 502)

    async def status(request):
        task = await task_store.get(request.path_params["task_id"], ServerCallContext())
        if task is None or "kuenz.review_id" not in task.metadata:
            return JSONResponse({"error": "Task unbekannt oder nach Neustart nicht mehr verfügbar."}, status_code=404)
        return JSONResponse(result_body(task, version))

    schema = json.loads(Path(__file__).with_name("openapi.json").read_text())
    url = urlsplit(public_url)
    schema.update(host=url.netloc, schemes=[url.scheme])

    async def openapi(_):
        return JSONResponse(schema)

    return [Route("/pruefung", review, methods=["POST"]),
            Route("/pruefung/{task_id}", status, methods=["GET"]),
            Route("/openapi.json", openapi)]
