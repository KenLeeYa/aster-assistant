from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel


class ConnectorState(StrEnum):
    DISABLED = "disabled"
    MOCK = "mock"
    LIVE = "live"
    ERROR = "error"


class ConnectorStatus(BaseModel):
    name: str
    state: ConnectorState
    capabilities: tuple[str, ...]
    reason: str | None = None


class DisabledConnectorAdapter:
    def __init__(self, *, name: str, capabilities: tuple[str, ...]) -> None:
        self._name = name
        self._capabilities = capabilities

    def status(self) -> ConnectorStatus:
        return ConnectorStatus(
            name=self._name,
            state=ConnectorState.DISABLED,
            capabilities=self._capabilities,
            reason="manual activation and credential gate required",
        )


class CalendarPreview(BaseModel):
    id: UUID
    title: str
    start: datetime
    end: datetime
    timezone: str
    external_id: str | None = None


class FakeCalendarAdapter:
    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self._events: dict[str, CalendarPreview] = {}

    def status(self) -> ConnectorStatus:
        return ConnectorStatus(
            name="google-calendar",
            state=ConnectorState.MOCK if self.enabled else ConnectorState.DISABLED,
            capabilities=("preview", "create"),
            reason=None if self.enabled else "connector disabled",
        )

    def preview(
        self, *, title: str, start: datetime, end: datetime, timezone: str
    ) -> CalendarPreview:
        return CalendarPreview(id=uuid4(), title=title, start=start, end=end, timezone=timezone)

    def create(
        self,
        preview: CalendarPreview,
        *,
        approved: bool,
        idempotency_key: str,
    ) -> CalendarPreview:
        if not self.enabled:
            raise RuntimeError("Google Calendar connector is disabled")
        if not approved:
            raise PermissionError("calendar write requires approval")
        existing = self._events.get(idempotency_key)
        if existing is not None:
            return existing
        created = preview.model_copy(update={"external_id": f"fake-event-{len(self._events) + 1}"})
        self._events[idempotency_key] = created
        return created


class PlaneWorkItemPreview(BaseModel):
    id: UUID
    title: str
    description: str
    source_requirement_ids: tuple[UUID, ...]
    external_id: str | None = None


class FakePlaneAdapter:
    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled
        self._items: dict[str, PlaneWorkItemPreview] = {}

    def status(self) -> ConnectorStatus:
        return ConnectorStatus(
            name="plane",
            state=ConnectorState.MOCK if self.enabled else ConnectorState.DISABLED,
            capabilities=("work-item.preview", "work-item.create"),
            reason=None if self.enabled else "connector disabled",
        )

    def create(
        self,
        preview: PlaneWorkItemPreview,
        *,
        approved: bool,
        idempotency_key: str,
    ) -> PlaneWorkItemPreview:
        if not self.enabled:
            raise RuntimeError("Plane connector is disabled")
        if not approved:
            raise PermissionError("Plane write requires approval")
        existing = self._items.get(idempotency_key)
        if existing is not None:
            return existing
        created = preview.model_copy(update={"external_id": f"fake-plane-{len(self._items) + 1}"})
        self._items[idempotency_key] = created
        return created
