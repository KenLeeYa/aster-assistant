from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, Field


class WorkerState(StrEnum):
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class WorkerPresence(BaseModel):
    worker_id: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=200)
    capabilities: tuple[str, ...] = ()
    state: WorkerState
    registered_at: datetime
    last_seen_at: datetime


class WorkerPresenceService:
    def __init__(self, *, timeout: timedelta = timedelta(seconds=30)) -> None:
        self._timeout = timeout
        self._workers: dict[str, WorkerPresence] = {}

    def register(
        self,
        worker_id: str,
        *,
        display_name: str,
        capabilities: tuple[str, ...],
        now: datetime | None = None,
    ) -> WorkerPresence:
        timestamp = now or datetime.now(UTC)
        existing = self._workers.get(worker_id)
        presence = WorkerPresence(
            worker_id=worker_id,
            display_name=display_name,
            capabilities=capabilities,
            state=WorkerState.ONLINE,
            registered_at=existing.registered_at if existing else timestamp,
            last_seen_at=timestamp,
        )
        self._workers[worker_id] = presence
        return presence

    def heartbeat(
        self,
        worker_id: str,
        *,
        degraded: bool = False,
        now: datetime | None = None,
    ) -> WorkerPresence:
        timestamp = now or datetime.now(UTC)
        current = self._workers[worker_id]
        updated = current.model_copy(
            update={
                "state": WorkerState.DEGRADED if degraded else WorkerState.ONLINE,
                "last_seen_at": timestamp,
            }
        )
        self._workers[worker_id] = updated
        return updated

    def get(self, worker_id: str, *, now: datetime | None = None) -> WorkerPresence:
        timestamp = now or datetime.now(UTC)
        current = self._workers[worker_id]
        if timestamp - current.last_seen_at <= self._timeout:
            return current
        offline = current.model_copy(update={"state": WorkerState.OFFLINE})
        self._workers[worker_id] = offline
        return offline

    def list(self, *, now: datetime | None = None) -> tuple[WorkerPresence, ...]:
        return tuple(self.get(worker_id, now=now) for worker_id in self._workers)
