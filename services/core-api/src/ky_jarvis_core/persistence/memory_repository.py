"""Governed memory persistence using the existing memories table."""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from sqlalchemy import Engine

from ky_jarvis_core.domain.memory import MemoryRecord
from ky_jarvis_core.persistence.schema import metadata

memories = metadata.tables["memories"]


def _read(row: sa.Row[tuple[Any, ...]]) -> MemoryRecord:
    extra = row.audit_metadata
    return MemoryRecord(
        id=row.id,
        user_id=row.owner_scope,
        project_id=row.project_id,
        scope=row.scope,
        memory_type=row.memory_type,
        content=row.content,
        normalized_content=row.normalized_content,
        source_type=row.source_type,
        source_id=row.source_id,
        source_timestamp=datetime.fromisoformat(extra["source_timestamp"]),
        confidence=row.confidence,
        importance=row.importance,
        sensitivity=row.sensitivity,
        status=row.status,
        authority=extra["authority"],
        valid_from=datetime.fromisoformat(extra["valid_from"]),
        valid_to=datetime.fromisoformat(extra["valid_to"]) if extra["valid_to"] else None,
        supersedes_memory_id=row.supersedes_memory_id,
        created_by=row.created_by,
        approved_by=row.approved_by,
        created_at=datetime.fromisoformat(extra["created_at"]),
        updated_at=datetime.fromisoformat(extra["updated_at"]),
        content_hash=row.content_hash,
        injection_signals=tuple(extra["injection_signals"]),
    )


class SqlMemoryMapping(MutableMapping[UUID, MemoryRecord]):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def __getitem__(self, key: UUID) -> MemoryRecord:
        with self._engine.connect() as connection:
            row = connection.execute(sa.select(memories).where(memories.c.id == key)).one_or_none()
        if row is None:
            raise KeyError(key)
        return _read(row)

    def __setitem__(self, key: UUID, value: MemoryRecord) -> None:
        if key != value.id:
            raise ValueError("memory id mismatch")
        extra = {
            "authority": int(value.authority),
            "injection_signals": list(value.injection_signals),
            "source_timestamp": value.source_timestamp.isoformat(),
            "valid_from": value.valid_from.isoformat(),
            "valid_to": value.valid_to.isoformat() if value.valid_to else None,
            "created_at": value.created_at.isoformat(),
            "updated_at": value.updated_at.isoformat(),
        }
        values = dict(
            owner_scope=value.user_id,
            user_id=uuid5(NAMESPACE_URL, f"ky-jarvis-user:{value.user_id}"),
            project_id=value.project_id,
            scope=value.scope,
            memory_type=value.memory_type.value,
            content=value.content,
            normalized_content=value.normalized_content,
            source_type=value.source_type,
            source_id=value.source_id,
            source_timestamp=value.source_timestamp,
            confidence=value.confidence,
            importance=value.importance,
            sensitivity=value.sensitivity,
            status=value.status.value,
            valid_from=value.valid_from,
            valid_to=value.valid_to,
            supersedes_memory_id=value.supersedes_memory_id,
            created_by=value.created_by,
            approved_by=value.approved_by,
            content_hash=value.content_hash,
            created_at=value.created_at,
            updated_at=value.updated_at,
            audit_metadata=extra,
        )
        with self._engine.begin() as connection:
            current = connection.execute(
                sa.select(memories.c.version, memories.c.status).where(memories.c.id == key)
            ).one_or_none()
            if current is None:
                connection.execute(sa.insert(memories).values(id=key, **values))
            else:
                if (
                    current.status in {"deleted", "rejected"}
                    and value.status.value != current.status
                ):
                    raise ValueError("deleted or rejected memory cannot reactivate")
                result = connection.execute(
                    sa.update(memories)
                    .where(memories.c.id == key, memories.c.version == current.version)
                    .values(**values, version=memories.c.version + 1)
                )
                if result.rowcount != 1:
                    raise ValueError("memory changed concurrently")

    def __delitem__(self, key: UUID) -> None:
        raise TypeError("memory must be governed by forget/supersede")

    def __iter__(self) -> Iterator[UUID]:
        with self._engine.connect() as connection:
            return iter(connection.scalars(sa.select(memories.c.id)).all())

    def __len__(self) -> int:
        with self._engine.connect() as connection:
            return connection.scalar(sa.select(sa.func.count()).select_from(memories)) or 0
