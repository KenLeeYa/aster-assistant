"""Contracts for a future paired Windows endpoint; no command transport is enabled."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EndpointCapability(StrEnum):
    DISPLAY_NOTIFICATION = "display_notification"
    OPEN_REVIEWED_FILE = "open_reviewed_file"


class EndpointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    device_id: UUID
    capability: EndpointCapability
    action_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=200)
    approval_id: UUID
    expires_at: datetime
    arguments: dict[str, str]

    @model_validator(mode="after")
    def require_bounded_request(self) -> EndpointRequest:
        if self.expires_at.tzinfo is None or self.expires_at <= datetime.now(UTC):
            raise ValueError("endpoint request must have a future timezone-aware expiry")
        if any(key in self.arguments for key in ("command", "shell", "script")):
            raise ValueError("arbitrary command arguments are not permitted")
        return self


class EndpointReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    device_id: UUID
    action_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str
    completed_at: datetime
    status: str = Field(pattern=r"^(completed|denied|failed)$")


class VerifiedEndpointTransport(Protocol):
    """Only accepts requests after paired-device and approval verification."""

    async def dispatch(self, request: EndpointRequest) -> EndpointReceipt: ...


# Transport, paired-device verification, approval consumption, and durable
# idempotency checks must all be implemented before dispatch is enabled.
