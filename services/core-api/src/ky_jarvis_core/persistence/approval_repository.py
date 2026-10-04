"""Transactional approval storage using the existing governed schema.

Approval and audit writes are still separate transactions. Consequential tool
dispatch remains gated pending durable idempotency and receipt reconciliation.
"""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Engine

from ky_jarvis_core.domain.approvals import ApprovalRequest, ApprovalState
from ky_jarvis_core.persistence.schema import metadata

approval_requests = metadata.tables["approval_requests"]


class ApprovalRepositoryPort(Protocol):
    def add(self, request: ApprovalRequest, *, owner_scope: str = "local-user") -> None: ...

    def get(self, approval_id: UUID) -> ApprovalRequest | None: ...

    def transition(
        self,
        approval_id: UUID,
        *,
        expected: ApprovalState,
        target: ApprovalState,
        action_hash: str,
        now: datetime | None = None,
    ) -> bool: ...


class ApprovalRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, request: ApprovalRequest, *, owner_scope: str = "local-user") -> None:
        with self._engine.begin() as connection:
            connection.execute(
                sa.insert(approval_requests).values(
                    id=request.id,
                    owner_scope=owner_scope,
                    action_hash=request.action_hash,
                    token_hash=request.token_hash,
                    nonce=request.nonce,
                    risk_level=request.risk_level.value,
                    state=request.state.value,
                    expires_at=request.expires_at,
                    payload=request.model_dump(mode="json"),
                )
            )

    def get(self, approval_id: UUID) -> ApprovalRequest | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                sa.select(approval_requests.c.payload, approval_requests.c.state).where(
                    approval_requests.c.id == approval_id
                )
            ).one_or_none()
        if row is None:
            return None
        request = ApprovalRequest.model_validate(row.payload)
        return request.model_copy(update={"state": ApprovalState(row.state)})

    def list(self) -> tuple[ApprovalRequest, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                sa.select(approval_requests.c.payload, approval_requests.c.state)
            )
            return tuple(
                ApprovalRequest.model_validate(row.payload).model_copy(
                    update={"state": ApprovalState(row.state)}
                )
                for row in rows
            )

    def replace(self, previous: ApprovalRequest, updated: ApprovalRequest) -> bool:
        if previous.id != updated.id or previous.action_hash != updated.action_hash:
            raise ValueError("approval identity or action changed")
        if (previous.state, updated.state) not in {
            (ApprovalState.PENDING, ApprovalState.APPROVED),
            (ApprovalState.PENDING, ApprovalState.DENIED),
            (ApprovalState.PENDING, ApprovalState.EXPIRED),
            (ApprovalState.APPROVED, ApprovalState.CONSUMED),
        }:
            raise ValueError("invalid or replayed approval transition")
        with self._engine.begin() as connection:
            result = connection.execute(
                sa.update(approval_requests)
                .where(
                    approval_requests.c.id == previous.id,
                    approval_requests.c.state == previous.state.value,
                    approval_requests.c.action_hash == previous.action_hash,
                )
                .values(
                    state=updated.state.value,
                    payload=updated.model_dump(mode="json"),
                    version=approval_requests.c.version + 1,
                )
            )
            return result.rowcount == 1

    def transition(
        self,
        approval_id: UUID,
        *,
        expected: ApprovalState,
        target: ApprovalState,
        action_hash: str,
        now: datetime | None = None,
    ) -> bool:
        if (expected, target) not in {
            (ApprovalState.PENDING, ApprovalState.APPROVED),
            (ApprovalState.PENDING, ApprovalState.DENIED),
            (ApprovalState.PENDING, ApprovalState.EXPIRED),
            (ApprovalState.APPROVED, ApprovalState.CONSUMED),
        }:
            raise ValueError("invalid approval transition")
        timestamp = now or datetime.now(UTC)
        with self._engine.begin() as connection:
            statement = (
                sa.update(approval_requests)
                .where(
                    approval_requests.c.id == approval_id,
                    approval_requests.c.state == expected.value,
                    approval_requests.c.action_hash == action_hash,
                )
                .values(state=target.value, version=approval_requests.c.version + 1)
            )
            if target is not ApprovalState.EXPIRED:
                statement = statement.where(approval_requests.c.expires_at > timestamp)
            else:
                statement = statement.where(approval_requests.c.expires_at <= timestamp)
            result = connection.execute(statement)
            return result.rowcount == 1


class SqlApprovalMapping(MutableMapping[UUID, ApprovalRequest]):
    """Mapping adapter preserving ApprovalService's existing business rules."""

    def __init__(self, repository: ApprovalRepository) -> None:
        self._repository = repository

    def __getitem__(self, key: UUID) -> ApprovalRequest:
        result = self._repository.get(key)
        if result is None:
            raise KeyError(key)
        return result

    def __setitem__(self, key: UUID, value: ApprovalRequest) -> None:
        if key != value.id:
            raise ValueError("approval id mismatch")
        previous = self._repository.get(key)
        if previous is None:
            self._repository.add(value)
        elif not self._repository.replace(previous, value):
            raise ValueError("approval changed concurrently")

    def __delitem__(self, key: UUID) -> None:
        raise TypeError("approval deletion is forbidden")

    def __iter__(self) -> Iterator[UUID]:
        return iter(item.id for item in self._repository.list())

    def __len__(self) -> int:
        return len(self._repository.list())
