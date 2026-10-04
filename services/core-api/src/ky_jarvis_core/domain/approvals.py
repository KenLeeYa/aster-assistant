from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import MutableMapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from ky_jarvis_core.domain.policy import RiskLevel


class ApprovalState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CONSUMED = "consumed"


def canonical_action_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


class ApprovalRequest(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    title: str
    reason: str
    target: str
    risk_level: RiskLevel
    permissions: tuple[str, ...]
    preview: dict[str, Any]
    side_effects: tuple[str, ...]
    rollback_method: str
    expires_at: datetime
    originating_request: str
    agent_run_id: UUID
    tool_name: str
    idempotency_key: str
    action_hash: str
    token_hash: str
    nonce: str
    state: ApprovalState = ApprovalState.PENDING
    decided_by: str | None = None
    decided_at: datetime | None = None


class ApprovalService:
    def __init__(
        self,
        *,
        token_pepper: bytes | None = None,
        requests: MutableMapping[UUID, ApprovalRequest] | None = None,
    ) -> None:
        self._pepper = token_pepper or secrets.token_bytes(32)
        self._requests: MutableMapping[UUID, ApprovalRequest] = (
            requests if requests is not None else {}
        )

    def create(
        self,
        *,
        title: str,
        reason: str,
        target: str,
        risk_level: RiskLevel,
        permissions: tuple[str, ...],
        preview: dict[str, Any],
        side_effects: tuple[str, ...],
        rollback_method: str,
        originating_request: str,
        agent_run_id: UUID,
        tool_name: str,
        idempotency_key: str,
        ttl: timedelta = timedelta(minutes=10),
        now: datetime | None = None,
    ) -> tuple[ApprovalRequest, str]:
        timestamp = now or datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(18)
        payload = {
            "target": target,
            "tool_name": tool_name,
            "preview": preview,
            "permissions": permissions,
            "idempotency_key": idempotency_key,
        }
        request = ApprovalRequest(
            title=title,
            reason=reason,
            target=target,
            risk_level=risk_level,
            permissions=permissions,
            preview=preview,
            side_effects=side_effects,
            rollback_method=rollback_method,
            expires_at=timestamp + ttl,
            originating_request=originating_request,
            agent_run_id=agent_run_id,
            tool_name=tool_name,
            idempotency_key=idempotency_key,
            action_hash=canonical_action_hash(payload),
            token_hash=self._token_hash(token),
            nonce=nonce,
        )
        self._requests[request.id] = request
        return request, token

    def decide(
        self,
        approval_id: UUID,
        *,
        token: str,
        action_payload: dict[str, Any],
        approved: bool,
        decided_by: str,
        now: datetime | None = None,
    ) -> ApprovalRequest:
        timestamp = now or datetime.now(UTC)
        request = self.get(approval_id)
        if request.state is not ApprovalState.PENDING:
            raise ValueError("approval is not pending")
        if timestamp >= request.expires_at:
            expired = request.model_copy(update={"state": ApprovalState.EXPIRED})
            self._requests[approval_id] = expired
            raise ValueError("approval expired")
        if not hmac.compare_digest(request.token_hash, self._token_hash(token)):
            raise ValueError("invalid approval token")
        if not hmac.compare_digest(request.action_hash, canonical_action_hash(action_payload)):
            raise ValueError("approval action hash changed")
        updated = request.model_copy(
            update={
                "state": ApprovalState.APPROVED if approved else ApprovalState.DENIED,
                "decided_by": decided_by,
                "decided_at": timestamp,
            }
        )
        self._requests[approval_id] = updated
        return updated

    def decide_authenticated(
        self,
        approval_id: UUID,
        *,
        action_hash: str,
        approved: bool,
        decided_by: str,
        now: datetime | None = None,
    ) -> ApprovalRequest:
        """Apply a decision already authenticated by a trusted device signature."""
        timestamp = now or datetime.now(UTC)
        request = self.get(approval_id)
        if request.state is not ApprovalState.PENDING:
            raise ValueError("approval is not pending")
        if timestamp >= request.expires_at:
            expired = request.model_copy(update={"state": ApprovalState.EXPIRED})
            self._requests[approval_id] = expired
            raise ValueError("approval expired")
        if not hmac.compare_digest(request.action_hash, action_hash):
            raise ValueError("approval action hash changed")
        updated = request.model_copy(
            update={
                "state": ApprovalState.APPROVED if approved else ApprovalState.DENIED,
                "decided_by": decided_by,
                "decided_at": timestamp,
            }
        )
        self._requests[approval_id] = updated
        return updated

    def consume(self, approval_id: UUID) -> ApprovalRequest:
        request = self.get(approval_id)
        if request.state is not ApprovalState.APPROVED:
            raise ValueError("only an approved request can be consumed")
        consumed = request.model_copy(update={"state": ApprovalState.CONSUMED})
        self._requests[approval_id] = consumed
        return consumed

    def invalidate_for_target(self, target: str) -> int:
        count = 0
        for approval_id, request in tuple(self._requests.items()):
            if request.target == target and request.state is ApprovalState.PENDING:
                self._requests[approval_id] = request.model_copy(
                    update={"state": ApprovalState.DENIED}
                )
                count += 1
        return count

    def get(self, approval_id: UUID) -> ApprovalRequest:
        try:
            return self._requests[approval_id]
        except KeyError as exc:
            raise KeyError(f"unknown approval: {approval_id}") from exc

    def list_requests(self, *, now: datetime | None = None) -> tuple[ApprovalRequest, ...]:
        timestamp = now or datetime.now(UTC)
        for approval_id, request in tuple(self._requests.items()):
            if request.state is ApprovalState.PENDING and timestamp >= request.expires_at:
                self._requests[approval_id] = request.model_copy(
                    update={"state": ApprovalState.EXPIRED}
                )
        return tuple(self._requests.values())

    def _token_hash(self, token: str) -> str:
        return hmac.new(self._pepper, token.encode(), hashlib.sha256).hexdigest()
