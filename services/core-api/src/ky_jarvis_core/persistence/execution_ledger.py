"""Fail-closed durable tool reservation using the existing tool_executions table."""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError

from ky_jarvis_core.domain.gateway import ToolResult
from ky_jarvis_core.persistence.schema import metadata

tool_executions = metadata.tables["tool_executions"]


class UncertainToolOutcome(ValueError):
    """A reserved action needs human reconciliation before another attempt."""


class ExecutionLedger:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def receipt_id(tool_name: str, idempotency_key: str) -> UUID:
        return uuid5(NAMESPACE_URL, f"ky-jarvis-tool:{tool_name}:{idempotency_key}")

    def reserve(
        self, *, tool_name: str, idempotency_key: str, action_hash: str, approval_id: UUID | None
    ) -> ToolResult | None:
        key = self.receipt_id(tool_name, idempotency_key)
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    sa.insert(tool_executions).values(
                        id=key,
                        audit_metadata={
                            "state": "reserved",
                            "tool_name": tool_name,
                            "idempotency_key": idempotency_key,
                            "action_hash": action_hash,
                            "approval_id": str(approval_id) if approval_id else None,
                        },
                    )
                )
            return None
        except IntegrityError:
            pass
        with self._engine.connect() as connection:
            row = connection.execute(
                sa.select(tool_executions.c.audit_metadata).where(tool_executions.c.id == key)
            ).one()
        stored = row.audit_metadata
        if stored["action_hash"] != action_hash or stored["approval_id"] != (
            str(approval_id) if approval_id else None
        ):
            raise ValueError("idempotency key reused for a different action or approval")
        if stored["state"] == "completed":
            return ToolResult.model_validate(stored["result"]).model_copy(
                update={"idempotent_replay": True}
            )
        raise UncertainToolOutcome("tool outcome is uncertain; reconcile before retry")

    def complete(
        self, *, tool_name: str, idempotency_key: str, action_hash: str, result: ToolResult
    ) -> None:
        key = self.receipt_id(tool_name, idempotency_key)
        with self._engine.begin() as connection:
            row = connection.execute(
                sa.select(tool_executions.c.audit_metadata).where(tool_executions.c.id == key)
            ).one()
            stored = dict(row.audit_metadata)
            if stored["state"] != "reserved" or stored["action_hash"] != action_hash:
                raise ValueError("tool reservation changed")
            stored["state"] = "completed"
            stored["result"] = result.model_dump(mode="json")
            updated = connection.execute(
                sa.update(tool_executions)
                .where(tool_executions.c.id == key, tool_executions.c.version == 1)
                .values(audit_metadata=stored, version=tool_executions.c.version + 1)
            )
            if updated.rowcount != 1:
                raise UncertainToolOutcome("tool receipt changed; reconcile before retry")
