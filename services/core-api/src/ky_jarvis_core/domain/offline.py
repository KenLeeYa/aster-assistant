from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel

from ky_jarvis_core.domain.policy import RiskLevel

CONSEQUENTIAL_RISKS = {
    RiskLevel.R3_MODIFY,
    RiskLevel.R4_DELETE_OR_EXECUTE,
    RiskLevel.R5_FINANCIAL_OR_PRIVILEGED,
}


class EnvelopeState(StrEnum):
    QUEUED = "queued"
    READY = "ready"
    EXPIRED = "expired"
    REVALIDATION_REQUIRED = "revalidation_required"
    REJECTED = "rejected"


class OfflineEnvelope(BaseModel):
    id: UUID
    device_id: UUID
    nonce: bytes
    ciphertext: bytes
    action_hash: str
    risk_level: RiskLevel
    created_at: datetime
    expires_at: datetime
    revalidate_after: datetime
    state: EnvelopeState


class EnvelopeRelease(BaseModel):
    state: EnvelopeState
    command: dict[str, Any] | None = None


class OfflineCommandQueue:
    def __init__(self, encryption_key: bytes) -> None:
        if len(encryption_key) != 32:
            raise ValueError("offline queue key must be 32 bytes")
        self._cipher = AESGCM(encryption_key)

    def enqueue(
        self,
        *,
        device_id: UUID,
        command: dict[str, Any],
        action_hash: str,
        risk_level: RiskLevel,
        approved: bool,
        now: datetime | None = None,
        ttl: timedelta = timedelta(minutes=15),
        revalidation_window: timedelta = timedelta(minutes=5),
    ) -> OfflineEnvelope:
        if risk_level in CONSEQUENTIAL_RISKS and not approved:
            raise PermissionError("consequential offline command requires scoped approval")
        timestamp = now or datetime.now(UTC)
        envelope_id = uuid4()
        associated_data = f"{envelope_id}:{device_id}:{action_hash}".encode()
        nonce = os.urandom(12)
        plaintext = json.dumps(command, sort_keys=True, separators=(",", ":")).encode()
        ciphertext = self._cipher.encrypt(nonce, plaintext, associated_data)
        return OfflineEnvelope(
            id=envelope_id,
            device_id=device_id,
            nonce=nonce,
            ciphertext=ciphertext,
            action_hash=action_hash,
            risk_level=risk_level,
            created_at=timestamp,
            expires_at=timestamp + ttl,
            revalidate_after=timestamp + revalidation_window,
            state=EnvelopeState.QUEUED,
        )

    def release(
        self,
        envelope: OfflineEnvelope,
        *,
        worker_online: bool,
        current_action_hash: str | None,
        now: datetime | None = None,
    ) -> EnvelopeRelease:
        timestamp = now or datetime.now(UTC)
        if timestamp >= envelope.expires_at:
            return EnvelopeRelease(state=EnvelopeState.EXPIRED)
        if not worker_online:
            return EnvelopeRelease(state=EnvelopeState.QUEUED)
        if envelope.risk_level in CONSEQUENTIAL_RISKS and (
            timestamp >= envelope.revalidate_after or current_action_hash != envelope.action_hash
        ):
            return EnvelopeRelease(state=EnvelopeState.REVALIDATION_REQUIRED)
        if current_action_hash != envelope.action_hash:
            return EnvelopeRelease(state=EnvelopeState.REJECTED)
        associated_data = f"{envelope.id}:{envelope.device_id}:{envelope.action_hash}".encode()
        plaintext = self._cipher.decrypt(
            envelope.nonce,
            envelope.ciphertext,
            associated_data,
        )
        command = json.loads(plaintext)
        if not isinstance(command, dict):
            return EnvelopeRelease(state=EnvelopeState.REJECTED)
        return EnvelopeRelease(state=EnvelopeState.READY, command=command)
