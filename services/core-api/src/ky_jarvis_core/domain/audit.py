from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel

SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(authorization|api[_-]?key|client[_-]?secret|password|refresh[_-]?token|access[_-]?token)"
)
SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?i)(bearer\s+[a-z0-9._~+/=-]{12,}|sk-[a-z0-9_-]{12,}|gh[opusr]_[a-z0-9]{20,})"
)


def redact(value: Any, *, key: str | None = None) -> Any:
    if key and SENSITIVE_KEY_PATTERN.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): redact(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str):
        return SENSITIVE_VALUE_PATTERN.sub("[REDACTED]", value)
    return value


class AuditEvent(BaseModel):
    sequence: int
    event_type: str
    payload: dict[str, Any]
    occurred_at: datetime
    previous_hash: str | None
    event_hash: str


class AuditRepositoryPort(Protocol):
    def list(self) -> Sequence[AuditEvent]: ...

    def append(self, event: AuditEvent) -> None: ...


class AuditChain:
    def __init__(self, repository: AuditRepositoryPort | None = None) -> None:
        self._repository = repository
        self._events: list[AuditEvent] = list(repository.list()) if repository else []
        if not self.verify():
            raise ValueError("stored audit chain failed verification")

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._events)

    def append(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> AuditEvent:
        safe_payload = redact(payload)
        assert isinstance(safe_payload, dict)
        sequence = len(self._events) + 1
        occurred_at = now or datetime.now(UTC)
        previous_hash = self._events[-1].event_hash if self._events else None
        event_hash = self._hash_fields(
            sequence, event_type, safe_payload, occurred_at, previous_hash
        )
        event = AuditEvent(
            sequence=sequence,
            event_type=event_type,
            payload=safe_payload,
            occurred_at=occurred_at,
            previous_hash=previous_hash,
            event_hash=event_hash,
        )
        if self._repository is not None:
            self._repository.append(event)
        self._events.append(event)
        return event

    def verify(self) -> bool:
        previous_hash: str | None = None
        for expected_sequence, event in enumerate(self._events, start=1):
            if event.sequence != expected_sequence or event.previous_hash != previous_hash:
                return False
            expected = self._hash_fields(
                event.sequence,
                event.event_type,
                event.payload,
                event.occurred_at,
                event.previous_hash,
            )
            if event.event_hash != expected:
                return False
            previous_hash = event.event_hash
        return True

    @staticmethod
    def _hash_fields(
        sequence: int,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime,
        previous_hash: str | None,
    ) -> str:
        encoded = json.dumps(
            {
                "sequence": sequence,
                "event_type": event_type,
                "payload": payload,
                "occurred_at": occurred_at.isoformat(),
                "previous_hash": previous_hash,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()
