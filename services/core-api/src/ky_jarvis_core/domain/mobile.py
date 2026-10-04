from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MobileCommandState(StrEnum):
    QUEUED = "queued"
    DELIVERED = "delivered"
    ACKNOWLEDGED = "acknowledged"
    EXPIRED = "expired"


class MobileCommand(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    device_id: UUID
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=4_000)
    idempotency_key: str = Field(min_length=1, max_length=200)
    correlation_id: str = Field(min_length=1, max_length=200)
    state: MobileCommandState = MobileCommandState.QUEUED
    receipt: str | None = Field(default=None, max_length=80)
    created_at: datetime
    expires_at: datetime
    delivered_at: datetime | None = None
    acknowledged_at: datetime | None = None


class MobileChannelService:
    """In-memory, display-only command channel for a paired foreground app."""

    def __init__(self, *, default_ttl: timedelta = timedelta(minutes=15)) -> None:
        if default_ttl <= timedelta(0):
            raise ValueError("default TTL must be positive")
        self._default_ttl = default_ttl
        self._commands: dict[UUID, MobileCommand] = {}
        self._idempotency: dict[tuple[UUID, str], UUID] = {}

    def enqueue(
        self,
        *,
        device_id: UUID,
        title: str,
        body: str,
        idempotency_key: str,
        correlation_id: str,
        now: datetime | None = None,
    ) -> MobileCommand:
        timestamp = now or datetime.now(UTC)
        dedupe_key = (device_id, idempotency_key)
        existing_id = self._idempotency.get(dedupe_key)
        if existing_id is not None:
            existing = self._commands[existing_id]
            if existing.title != title or existing.body != body:
                raise ValueError("idempotency key already used with different content")
            return existing
        command = MobileCommand(
            device_id=device_id,
            title=title,
            body=body,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            created_at=timestamp,
            expires_at=timestamp + self._default_ttl,
        )
        self._commands[command.id] = command
        self._idempotency[dedupe_key] = command.id
        return command

    def pending(
        self,
        *,
        device_id: UUID,
        now: datetime | None = None,
    ) -> tuple[MobileCommand, ...]:
        timestamp = now or datetime.now(UTC)
        pending: list[MobileCommand] = []
        for command in self._commands.values():
            if command.device_id != device_id:
                continue
            if command.state in {MobileCommandState.ACKNOWLEDGED, MobileCommandState.EXPIRED}:
                continue
            if timestamp >= command.expires_at:
                self._commands[command.id] = command.model_copy(
                    update={"state": MobileCommandState.EXPIRED}
                )
                continue
            if command.state is MobileCommandState.QUEUED:
                command = command.model_copy(
                    update={
                        "state": MobileCommandState.DELIVERED,
                        "delivered_at": timestamp,
                    }
                )
                self._commands[command.id] = command
            pending.append(command)
        return tuple(sorted(pending, key=lambda item: item.created_at))

    def acknowledge(
        self,
        command_id: UUID,
        *,
        device_id: UUID,
        receipt: str = "displayed",
        now: datetime | None = None,
    ) -> MobileCommand:
        timestamp = now or datetime.now(UTC)
        command = self._commands[command_id]
        if command.device_id != device_id:
            raise PermissionError("command belongs to a different device")
        if command.state is MobileCommandState.EXPIRED or timestamp >= command.expires_at:
            expired = command.model_copy(update={"state": MobileCommandState.EXPIRED})
            self._commands[command_id] = expired
            raise ValueError("command expired")
        if command.state is MobileCommandState.ACKNOWLEDGED:
            return command
        acknowledged = command.model_copy(
            update={
                "state": MobileCommandState.ACKNOWLEDGED,
                "receipt": receipt,
                "acknowledged_at": timestamp,
                "delivered_at": command.delivered_at or timestamp,
            }
        )
        self._commands[command_id] = acknowledged
        return acknowledged

    def list_commands(self, *, device_id: UUID | None = None) -> tuple[MobileCommand, ...]:
        commands = tuple(self._commands.values())
        if device_id is not None:
            commands = tuple(item for item in commands if item.device_id == device_id)
        return tuple(sorted(commands, key=lambda item: item.created_at))

    def get(self, command_id: UUID) -> MobileCommand:
        return self._commands[command_id]
