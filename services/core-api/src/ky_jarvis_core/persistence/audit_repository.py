"""Append-only audit persistence using the existing audit_events table."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import Engine

from ky_jarvis_core.domain.audit import AuditEvent
from ky_jarvis_core.persistence.schema import metadata

audit_events = metadata.tables["audit_events"]


class AuditRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list(self) -> tuple[AuditEvent, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(sa.select(audit_events).order_by(audit_events.c.sequence))
            return tuple(
                AuditEvent(
                    sequence=row.sequence,
                    event_type=row.event_type,
                    payload=row.payload,
                    occurred_at=datetime.fromisoformat(row.audit_metadata["occurred_at"]),
                    previous_hash=row.previous_hash,
                    event_hash=row.event_hash,
                )
                for row in rows
            )

    def append(self, event: AuditEvent) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                sa.insert(audit_events).values(
                    id=uuid4(),
                    sequence=event.sequence,
                    event_type=event.event_type,
                    payload=event.payload,
                    previous_hash=event.previous_hash,
                    event_hash=event.event_hash,
                    created_at=event.occurred_at,
                    audit_metadata={"occurred_at": event.occurred_at.isoformat()},
                )
            )
