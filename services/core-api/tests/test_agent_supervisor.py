from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from ky_jarvis_core.agents.providers import OllamaProvider, SequenceProvider
from ky_jarvis_core.agents.supervisor import AgentRunService, build_supervisor
from ky_jarvis_core.config import Settings
from ky_jarvis_core.main import create_app
from langgraph.checkpoint.memory import InMemorySaver


def _valid_plan() -> dict[str, object]:
    return {
        "summary": "建立可審查計畫",
        "steps": ["建立需求", "等待核准"],
        "requires_approval": True,
        "source_requirement_ids": ["REQ-1"],
    }


class BlockingProvider:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, object],
    ) -> dict[str, object]:
        del system, user, schema
        self.started.set()
        await self.release.wait()
        return _valid_plan()


@pytest.mark.asyncio
async def test_supervisor_retries_invalid_output_with_a_hard_bound() -> None:
    provider = SequenceProvider([{}, {}])
    graph = build_supervisor(provider, max_attempts=2)

    state = await graph.ainvoke({"request": "建立專案"})

    assert state["status"] == "failed"
    assert state["attempts"] == 2
    assert provider.calls == 2
    assert str(state["error"]).startswith("invalid_structured_output:")


@pytest.mark.asyncio
async def test_checkpoint_is_reusable_across_service_instances() -> None:
    checkpointer = InMemorySaver()
    provider = SequenceProvider([_valid_plan()])
    first = AgentRunService(build_supervisor(provider, checkpointer=checkpointer))

    state = await first.run("建立專案", thread_id="thread-1")
    assert state["status"] == "completed"

    second_graph = build_supervisor(provider, checkpointer=checkpointer)
    snapshot = second_graph.get_state({"configurable": {"thread_id": "thread-1"}})
    assert snapshot.values["result"]["source_requirement_ids"] == ["REQ-1"]


@pytest.mark.asyncio
async def test_run_service_streams_terminal_state_and_keeps_history() -> None:
    service = AgentRunService(build_supervisor(SequenceProvider([_valid_plan()])))

    started = service.start("建立專案", thread_id="stream-thread")
    events = [event async for event in service.watch(started.run_id)]

    assert [event.status for event in events] == ["running", "completed"]
    assert events[-1].result is not None
    assert events[-1].result["summary"] == "建立可審查計畫"
    assert service.history[-1].run_id == started.run_id


@pytest.mark.asyncio
async def test_run_service_cancels_only_an_active_run() -> None:
    provider = BlockingProvider()
    service = AgentRunService(build_supervisor(provider))
    started = service.start("建立專案", thread_id="cancel-thread")
    await asyncio.wait_for(provider.started.wait(), timeout=1)

    assert service.cancel(started.run_id) is True
    events = [event async for event in service.watch(started.run_id)]

    assert events[-1].status == "cancelled"
    assert service.cancel(started.run_id) is False


@pytest.mark.asyncio
async def test_run_api_exposes_start_sse_status_and_terminal_conflict() -> None:
    app = create_app(Settings(), model_provider=SequenceProvider([_valid_plan()]))
    transport = httpx.ASGITransport(app=app)
    headers = {"X-KY-JARVIS-Intent": "ui-v1"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        started = await client.post(
            "/api/v1/runs",
            headers=headers,
            json={"message": "建立專案", "thread_id": "api-stream"},
        )
        run_id = started.json()["run_id"]
        stream = await client.get(f"/api/v1/runs/{run_id}/events")
        status = await client.get(f"/api/v1/runs/{run_id}")
        cancelled = await client.post(f"/api/v1/runs/{run_id}/cancel", headers=headers)

    assert started.status_code == 200
    assert started.json()["status"] == "running"
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert '"status":"completed"' in stream.text
    assert status.json()["result"]["summary"] == "建立可審查計畫"
    assert cancelled.status_code == 409


@pytest.mark.asyncio
async def test_ollama_provider_uses_local_structured_chat_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        body = json.loads(request.content)
        assert body["stream"] is False
        assert body["format"]["type"] == "object"
        assert "maxLength" not in body["format"]["properties"]["summary"]
        assert "maxItems" not in body["format"]["properties"]["steps"]
        return httpx.Response(200, json={"message": {"content": json.dumps(_valid_plan())}})

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="fixture-model",
        transport=httpx.MockTransport(handler),
    )
    result = await provider.generate(
        system="bounded",
        user="plan",
        schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string", "maxLength": 2_000},
                "steps": {"type": "array", "maxItems": 20},
            },
        },
    )
    assert result["summary"] == "建立可審查計畫"
