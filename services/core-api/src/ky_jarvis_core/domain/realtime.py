from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from ky_jarvis_core.domain.devices import DeviceSecurityService, DeviceTrustState


class RealtimeSessionPolicy(BaseModel):
    model: str = "gpt-realtime-2.1"
    voice: str = "marin"
    locale: str = "zh-TW"
    max_duration_seconds: int = Field(default=600, ge=30, le=1800)
    max_concurrent_sessions: int = Field(default=1, ge=1, le=4)
    allowed_mode: str = "conversation"
    daily_soft_limit_units: int = Field(default=0, ge=0)
    daily_hard_limit_units: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_budget(self) -> RealtimeSessionPolicy:
        if self.daily_hard_limit_units > 0 and (
            self.daily_soft_limit_units > self.daily_hard_limit_units
        ):
            raise ValueError("Realtime soft budget cannot exceed hard budget")
        return self


class UsageBudget(BaseModel):
    day: date
    soft_limit_units: int = Field(default=80, ge=0)
    hard_limit_units: int = Field(default=100, ge=1)
    used_units: int = Field(default=0, ge=0)


class RealtimeIssuance(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    device_id: UUID
    secret_hash: str
    expires_at: datetime
    issued_at: datetime
    mode: str
    safety_identifier: str
    active: bool = True


class ClientSecretResponse(BaseModel):
    mode: str = "webrtc"
    issuance_id: UUID
    value: str
    expires_at: datetime
    model: str
    voice: str
    max_duration_seconds: int


class LocalFallbackResponse(BaseModel):
    mode: str = "local_chained"
    reason: str = "provider unavailable; use governed local voice path"


class RealtimeProvider(Protocol):
    def mint_client_secret(
        self,
        *,
        policy: RealtimeSessionPolicy,
        safety_identifier: str,
        expires_at: datetime,
    ) -> str: ...


class MockRealtimeProvider:
    def __init__(self) -> None:
        self.calls = 0

    def mint_client_secret(
        self,
        *,
        policy: RealtimeSessionPolicy,
        safety_identifier: str,
        expires_at: datetime,
    ) -> str:
        del policy, safety_identifier, expires_at
        self.calls += 1
        return f"mock-client-secret-{uuid4()}"


class RealtimeBroker:
    def __init__(
        self,
        *,
        devices: DeviceSecurityService,
        provider: RealtimeProvider,
        policy: RealtimeSessionPolicy | None = None,
        enabled: bool = False,
    ) -> None:
        self._devices = devices
        self._provider = provider
        self._policy = policy or RealtimeSessionPolicy()
        self._enabled = enabled
        self._issuances: dict[UUID, RealtimeIssuance] = {}
        self._budgets: dict[tuple[str, date], UsageBudget] = {}

    def set_budget(self, user_id: str, budget: UsageBudget) -> None:
        self._budgets[(user_id, budget.day)] = budget

    def request_client_secret(
        self,
        *,
        device_id: UUID,
        requested_mode: str,
        now: datetime | None = None,
    ) -> ClientSecretResponse | LocalFallbackResponse:
        timestamp = now or datetime.now(UTC)
        if not self._enabled:
            raise PermissionError("OpenAI Realtime is disabled")
        device = self._devices.get_device(device_id)
        if device.trust_state is not DeviceTrustState.TRUSTED:
            raise PermissionError("trusted device required")
        if requested_mode != self._policy.allowed_mode:
            raise ValueError("requested Realtime capability is not allowed")
        active_count = sum(
            1
            for item in self._issuances.values()
            if item.device_id == device_id and item.active and item.expires_at > timestamp
        )
        if active_count >= self._policy.max_concurrent_sessions:
            raise PermissionError("Realtime concurrent-session limit reached")
        budget = self._budgets.get((device.user_id, timestamp.date()))
        if budget is None and self._policy.daily_hard_limit_units > 0:
            budget = UsageBudget(
                day=timestamp.date(),
                soft_limit_units=self._policy.daily_soft_limit_units,
                hard_limit_units=self._policy.daily_hard_limit_units,
            )
            self.set_budget(device.user_id, budget)
        if budget is None:
            raise PermissionError("Realtime usage budget is not configured")
        if budget.used_units >= budget.hard_limit_units:
            raise PermissionError("Realtime hard usage budget reached")

        expires_at = timestamp + timedelta(seconds=self._policy.max_duration_seconds)
        safety_identifier = hashlib.sha256(f"{device.user_id}:{device.id}".encode()).hexdigest()[
            :32
        ]
        try:
            value = self._provider.mint_client_secret(
                policy=self._policy,
                safety_identifier=safety_identifier,
                expires_at=expires_at,
            )
        except (ConnectionError, TimeoutError):
            return LocalFallbackResponse()
        if value.startswith("sk-"):
            raise RuntimeError("provider returned a reusable API key")
        issuance = RealtimeIssuance(
            device_id=device.id,
            secret_hash=hashlib.sha256(value.encode()).hexdigest(),
            expires_at=expires_at,
            issued_at=timestamp,
            mode=requested_mode,
            safety_identifier=safety_identifier,
        )
        self._issuances[issuance.id] = issuance
        return ClientSecretResponse(
            issuance_id=issuance.id,
            value=value,
            expires_at=expires_at,
            model=self._policy.model,
            voice=self._policy.voice,
            max_duration_seconds=self._policy.max_duration_seconds,
        )

    def close(self, issuance_id: UUID) -> RealtimeIssuance:
        issuance = self._issuances[issuance_id]
        closed = issuance.model_copy(update={"active": False})
        self._issuances[issuance_id] = closed
        return closed

    def record_usage(self, user_id: str, *, units: int, day: date) -> UsageBudget:
        budget = self._budgets[(user_id, day)]
        updated = budget.model_copy(update={"used_units": budget.used_units + units})
        self._budgets[(user_id, day)] = updated
        return updated

    def issuance(self, issuance_id: UUID) -> RealtimeIssuance:
        return self._issuances[issuance_id]
