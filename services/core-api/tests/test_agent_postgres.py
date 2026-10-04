from __future__ import annotations

import os
from uuid import uuid4

import pytest
from ky_jarvis_core.agents.providers import SequenceProvider
from ky_jarvis_core.agents.supervisor import async_postgres_checkpointer, build_supervisor

pytestmark = pytest.mark.asyncio


async def test_langgraph_checkpoint_survives_graph_recreation() -> None:
    sqlalchemy_url = os.environ.get("KY_JARVIS_DATABASE_URL", "")
    if not sqlalchemy_url.startswith("postgresql"):
        pytest.skip("live PostgreSQL integration URL is not configured")
    checkpoint_url = sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://", 1)
    thread_id = f"checkpoint-{uuid4()}"
    response = {
        "summary": "persisted",
        "steps": ["one"],
        "requires_approval": False,
        "source_requirement_ids": [],
    }

    async with async_postgres_checkpointer(checkpoint_url) as checkpointer:
        first = build_supervisor(SequenceProvider([response]), checkpointer=checkpointer)
        state = await first.ainvoke(
            {"request": "create project"},
            config={"configurable": {"thread_id": thread_id}},
        )
        assert state["status"] == "completed"

        second = build_supervisor(SequenceProvider([response]), checkpointer=checkpointer)
        snapshot = await second.aget_state({"configurable": {"thread_id": thread_id}})
        assert snapshot.values["result"]["summary"] == "persisted"
