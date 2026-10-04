from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, MutableMapping
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MemoryType(StrEnum):
    PROFILE = "profile"
    PREFERENCE = "preference"
    REQUIREMENT = "requirement"
    DECISION = "decision"
    CONSTRAINT = "constraint"
    PROCEDURE = "procedure"
    EVENT = "event"
    REFERENCE = "reference"
    TEMPORARY = "temporary"


class MemoryStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    EXPIRED = "expired"
    DELETED = "deleted"


class MemoryAuthority(IntEnum):
    EXTERNAL = 10
    IMPORTED = 20
    USER_MESSAGE = 60
    STRUCTURED_PROJECT = 80
    APPROVED = 100


UNTRUSTED_SOURCE_TYPES = {
    "document",
    "email",
    "tool_output",
    "web",
    "repository_issue",
}
HIGH_IMPACT_TYPES = {
    MemoryType.REQUIREMENT,
    MemoryType.DECISION,
    MemoryType.CONSTRAINT,
    MemoryType.PROCEDURE,
}
INSTRUCTION_PATTERN = re.compile(
    r"(?i)(ignore (all|previous) instructions|system prompt|reveal secrets?|"
    r"call (a )?tool|執行工具|忽略.*指示)"
)


def normalize_memory_content(content: str) -> str:
    return " ".join(content.casefold().split())


class MemoryRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str
    project_id: UUID | None = None
    scope: str = "global"
    memory_type: MemoryType
    content: str
    normalized_content: str
    source_type: str
    source_id: str | None = None
    source_timestamp: datetime
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    sensitivity: str = "normal"
    status: MemoryStatus
    authority: MemoryAuthority
    valid_from: datetime
    valid_to: datetime | None = None
    supersedes_memory_id: UUID | None = None
    created_by: str
    approved_by: str | None = None
    created_at: datetime
    updated_at: datetime
    content_hash: str
    injection_signals: tuple[str, ...] = ()


class MemoryHit(BaseModel):
    memory: MemoryRecord
    score: float
    provenance: dict[str, str | None]


class GovernedMemoryStore:
    def __init__(self, records: MutableMapping[UUID, MemoryRecord] | None = None) -> None:
        self._records: MutableMapping[UUID, MemoryRecord] = records if records is not None else {}

    def propose(
        self,
        *,
        user_id: str,
        content: str,
        memory_type: MemoryType,
        source_type: str,
        created_by: str,
        project_id: UUID | None = None,
        scope: str = "global",
        importance: float = 0.5,
        confidence: float = 1.0,
        approved_by: str | None = None,
        source_id: str | None = None,
        now: datetime | None = None,
    ) -> MemoryRecord:
        timestamp = now or datetime.now(UTC)
        normalized = normalize_memory_content(content)
        content_hash = hashlib.sha256(normalized.encode()).hexdigest()
        for record in self._records.values():
            if (
                record.user_id == user_id
                and record.project_id == project_id
                and record.content_hash == content_hash
                and record.status in {MemoryStatus.CANDIDATE, MemoryStatus.ACTIVE}
            ):
                return record

        untrusted = source_type in UNTRUSTED_SOURCE_TYPES
        injection_signals = tuple(match.group(0) for match in INSTRUCTION_PATTERN.finditer(content))
        requires_approval = untrusted or memory_type in HIGH_IMPACT_TYPES
        active = approved_by is not None and requires_approval
        if not requires_approval and source_type == "user_message":
            active = True

        authority = (
            MemoryAuthority.APPROVED
            if active
            else MemoryAuthority.EXTERNAL
            if untrusted
            else MemoryAuthority.USER_MESSAGE
        )
        record = MemoryRecord(
            user_id=user_id,
            project_id=project_id,
            scope=scope,
            memory_type=memory_type,
            content=content,
            normalized_content=normalized,
            source_type=source_type,
            source_id=source_id,
            source_timestamp=timestamp,
            confidence=confidence,
            importance=importance,
            status=MemoryStatus.ACTIVE if active else MemoryStatus.CANDIDATE,
            authority=authority,
            valid_from=timestamp,
            created_by=created_by,
            approved_by=approved_by,
            created_at=timestamp,
            updated_at=timestamp,
            content_hash=content_hash,
            injection_signals=injection_signals,
        )
        self._records[record.id] = record
        return record

    def approve(
        self,
        memory_id: UUID,
        *,
        approved_by: str,
        now: datetime | None = None,
    ) -> MemoryRecord:
        record = self.get(memory_id)
        if record.status is not MemoryStatus.CANDIDATE:
            raise ValueError("only candidate memory can be approved")
        updated = record.model_copy(
            update={
                "status": MemoryStatus.ACTIVE,
                "authority": MemoryAuthority.APPROVED,
                "approved_by": approved_by,
                "updated_at": now or datetime.now(UTC),
            }
        )
        self._records[memory_id] = updated
        return updated

    def supersede(
        self,
        memory_id: UUID,
        *,
        replacement_content: str,
        created_by: str,
        approved_by: str,
        now: datetime | None = None,
    ) -> MemoryRecord:
        old = self.get(memory_id)
        if old.status is not MemoryStatus.ACTIVE:
            raise ValueError("only active memory can be superseded")
        timestamp = now or datetime.now(UTC)
        replacement = self.propose(
            user_id=old.user_id,
            project_id=old.project_id,
            scope=old.scope,
            content=replacement_content,
            memory_type=old.memory_type,
            source_type="user_message",
            source_id=str(old.id),
            created_by=created_by,
            approved_by=approved_by,
            importance=old.importance,
            confidence=old.confidence,
            now=timestamp,
        )
        replacement = replacement.model_copy(update={"supersedes_memory_id": old.id})
        self._records[replacement.id] = replacement
        self._records[old.id] = old.model_copy(
            update={
                "status": MemoryStatus.SUPERSEDED,
                "valid_to": timestamp,
                "updated_at": timestamp,
            }
        )
        return replacement

    def forget(self, memory_id: UUID, *, now: datetime | None = None) -> MemoryRecord:
        record = self.get(memory_id)
        timestamp = now or datetime.now(UTC)
        updated = record.model_copy(
            update={
                "status": MemoryStatus.DELETED,
                "valid_to": timestamp,
                "updated_at": timestamp,
            }
        )
        self._records[memory_id] = updated
        return updated

    def get(self, memory_id: UUID) -> MemoryRecord:
        try:
            return self._records[memory_id]
        except KeyError as exc:
            raise KeyError(f"unknown memory: {memory_id}") from exc

    def list_records(self, *, user_id: str) -> tuple[MemoryRecord, ...]:
        return tuple(
            sorted(
                (record for record in self._records.values() if record.user_id == user_id),
                key=lambda item: item.created_at,
                reverse=True,
            )
        )

    def history(self, memory_id: UUID) -> list[MemoryRecord]:
        chain: list[MemoryRecord] = []
        current = self.get(memory_id)
        chain.append(current)
        while current.supersedes_memory_id is not None:
            current = self.get(current.supersedes_memory_id)
            chain.append(current)
        return chain

    def retrieve(
        self,
        query: str,
        *,
        user_id: str,
        project_id: UUID | None = None,
        scopes: set[str] | None = None,
        semantic_scores: Mapping[UUID, float] | None = None,
        limit: int = 10,
        now: datetime | None = None,
    ) -> list[MemoryHit]:
        timestamp = now or datetime.now(UTC)
        query_tokens = set(normalize_memory_content(query).split())
        hits: list[MemoryHit] = []
        for record in self._records.values():
            if record.user_id != user_id or record.status is not MemoryStatus.ACTIVE:
                continue
            if record.valid_from > timestamp or (record.valid_to and record.valid_to <= timestamp):
                continue
            if record.project_id not in {None, project_id}:
                continue
            if scopes is not None and record.scope not in scopes:
                continue
            memory_tokens = set(record.normalized_content.split())
            overlap = len(query_tokens & memory_tokens) / max(len(query_tokens), 1)
            semantic_score = max(0.0, min(1.0, (semantic_scores or {}).get(record.id, 0.0)))
            if query_tokens and overlap == 0 and semantic_score == 0:
                continue
            score = (
                overlap * 0.4
                + semantic_score * 0.25
                + (record.authority / 100) * 0.2
                + record.importance * 0.15
            )
            hits.append(
                MemoryHit(
                    memory=record,
                    score=round(score, 6),
                    provenance={
                        "memory_id": str(record.id),
                        "source_type": record.source_type,
                        "source_id": record.source_id,
                        "source_timestamp": record.source_timestamp.isoformat(),
                        "status": record.status,
                        "scope": record.scope,
                        "authority": record.authority.name,
                    },
                )
            )
        hits.sort(key=lambda hit: (hit.score, hit.memory.created_at), reverse=True)
        return hits[:limit]

    def export_json(self, *, user_id: str) -> str:
        records = [
            record.model_dump(mode="json")
            for record in sorted(self._records.values(), key=lambda item: item.created_at)
            if record.user_id == user_id
        ]
        return json.dumps(
            {"format": "ky-jarvis-memory-v1", "records": records},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def import_json(
        self,
        payload: str,
        *,
        user_id: str,
        created_by: str,
        source_id: str,
        max_bytes: int = 2_000_000,
        now: datetime | None = None,
    ) -> tuple[MemoryRecord, ...]:
        if len(payload.encode()) > max_bytes:
            raise ValueError("memory import exceeds size limit")
        parsed = json.loads(payload)
        if not isinstance(parsed, dict) or parsed.get("format") != "ky-jarvis-memory-v1":
            raise ValueError("unsupported memory import format")
        records = parsed.get("records")
        if not isinstance(records, list):
            raise ValueError("memory import records must be a list")
        imported: list[MemoryRecord] = []
        for index, raw in enumerate(records):
            if not isinstance(raw, dict):
                raise ValueError("memory import record must be an object")
            content = raw.get("content")
            memory_type = raw.get("memory_type")
            if not isinstance(content, str) or not isinstance(memory_type, str):
                raise ValueError("memory import requires content and memory_type")
            imported.append(
                self.propose(
                    user_id=user_id,
                    content=content,
                    memory_type=MemoryType(memory_type),
                    source_type="document",
                    source_id=f"{source_id}#{index}",
                    created_by=created_by,
                    scope=str(raw.get("scope", "global")),
                    now=now,
                )
            )
        return tuple(imported)
