from __future__ import annotations

from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from ky_jarvis_core.domain.devices import DeviceSecurityService, DeviceTrustState


class PushWake(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    device_id: UUID
    category: str = Field(pattern=r"^(worker-presence|display-command)$")
    correlation_id: str = Field(min_length=1, max_length=200)


class PushAdapter(Protocol):
    def send(self, wake: PushWake) -> str: ...


class DisabledPushAdapter:
    def send(self, wake: PushWake) -> str:
        del wake
        raise RuntimeError("push notifications are disabled")


class FakePushAdapter:
    def __init__(self) -> None:
        self.sent: list[PushWake] = []

    def send(self, wake: PushWake) -> str:
        self.sent.append(wake)
        return f"fake-push-{wake.id}"


class PushDispatcher:
    def __init__(
        self,
        *,
        devices: DeviceSecurityService,
        adapter: PushAdapter,
        enabled: bool = False,
    ) -> None:
        self._devices = devices
        self._adapter = adapter
        self._enabled = enabled

    def dispatch(
        self,
        *,
        device_id: UUID,
        category: str,
        correlation_id: str,
    ) -> str:
        if not self._enabled:
            raise PermissionError("push notifications are disabled")
        device = self._devices.get_device(device_id)
        if device.trust_state is not DeviceTrustState.TRUSTED:
            raise PermissionError("trusted device required")
        return self._adapter.send(
            PushWake(
                device_id=device_id,
                category=category,
                correlation_id=correlation_id,
            )
        )
