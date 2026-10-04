from uuid import uuid4

import pytest
import sqlalchemy as sa
from ky_jarvis_core.domain.gateway import ToolResult
from ky_jarvis_core.persistence.execution_ledger import (
    ExecutionLedger,
    UncertainToolOutcome,
    tool_executions,
)


def test_reserved_action_cannot_replay_after_restart() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    tool_executions.create(engine)
    first = ExecutionLedger(engine)
    approval_id = uuid4()
    arguments = dict(
        tool_name="example.tool",
        idempotency_key="request-one",
        action_hash="a" * 64,
        approval_id=approval_id,
    )
    assert first.reserve(**arguments) is None
    with pytest.raises(UncertainToolOutcome):
        ExecutionLedger(engine).reserve(**arguments)

    first.complete(
        tool_name="example.tool",
        idempotency_key="request-one",
        action_hash="a" * 64,
        result=ToolResult(tool_name="example.tool", result={"ok": True}),
    )
    replay = ExecutionLedger(engine).reserve(**arguments)
    assert replay is not None and replay.idempotent_replay
    assert replay.result == {"ok": True}
    with pytest.raises(ValueError, match="different action"):
        first.reserve(**(arguments | {"action_hash": "b" * 64}))
