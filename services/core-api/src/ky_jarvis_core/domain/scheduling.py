from __future__ import annotations

from datetime import date, datetime, time, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator


class TimeBlock(BaseModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_range(self) -> TimeBlock:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("time blocks require timezone-aware values")
        if self.end <= self.start:
            raise ValueError("time block end must follow start")
        return self


class ScheduleProposal(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    work_item_id: UUID
    timezone: str
    blocks: tuple[TimeBlock, ...]
    conflicts: tuple[str, ...] = ()
    requires_approval: bool = True


class DeterministicScheduler:
    def __init__(self) -> None:
        self._proposals: dict[UUID, ScheduleProposal] = {}

    @property
    def proposals(self) -> tuple[ScheduleProposal, ...]:
        return tuple(self._proposals.values())

    def get(self, proposal_id: UUID) -> ScheduleProposal:
        try:
            return self._proposals[proposal_id]
        except KeyError as exc:
            raise KeyError(f"unknown schedule proposal: {proposal_id}") from exc

    def propose(
        self,
        *,
        work_item_id: UUID,
        duration_minutes: int,
        earliest: datetime,
        deadline: datetime,
        busy: tuple[TimeBlock, ...],
        timezone: str = "Asia/Taipei",
        working_start: time = time(9, 0),
        working_end: time = time(18, 0),
        max_block_minutes: int = 120,
        buffer_minutes: int = 15,
    ) -> ScheduleProposal:
        zone = ZoneInfo(timezone)
        cursor = earliest.astimezone(zone).replace(second=0, microsecond=0)
        local_deadline = deadline.astimezone(zone)
        remaining = duration_minutes
        blocks: list[TimeBlock] = []
        busy_local = sorted(
            (
                TimeBlock(start=item.start.astimezone(zone), end=item.end.astimezone(zone))
                for item in busy
            ),
            key=lambda item: item.start,
        )

        while remaining > 0 and cursor < local_deadline:
            cursor = self._next_working_time(cursor, working_start, working_end)
            day_end = datetime.combine(cursor.date(), working_end, zone)
            available_end = min(day_end, local_deadline)
            for event in busy_local:
                padded_start = event.start - timedelta(minutes=buffer_minutes)
                padded_end = event.end + timedelta(minutes=buffer_minutes)
                if padded_end <= cursor or padded_start >= available_end:
                    continue
                if padded_start <= cursor:
                    cursor = padded_end
                    break
                available_end = min(available_end, padded_start)
            else:
                capacity = int((available_end - cursor).total_seconds() // 60)
                if capacity >= 30:
                    length = min(remaining, max_block_minutes, capacity)
                    block = TimeBlock(start=cursor, end=cursor + timedelta(minutes=length))
                    blocks.append(block)
                    remaining -= length
                    cursor = block.end + timedelta(minutes=buffer_minutes)
                    continue
                cursor = datetime.combine(cursor.date() + timedelta(days=1), working_start, zone)
                continue
            if cursor.time() >= working_end:
                cursor = datetime.combine(cursor.date() + timedelta(days=1), working_start, zone)

        if remaining > 0:
            raise ValueError("no conflict-free schedule fits before the deadline")
        proposal = ScheduleProposal(
            work_item_id=work_item_id,
            timezone=timezone,
            blocks=tuple(blocks),
        )
        self._proposals[proposal.id] = proposal
        return proposal

    @staticmethod
    def _next_working_time(current: datetime, start: time, end: time) -> datetime:
        zone = current.tzinfo
        assert zone is not None
        day: date = current.date()
        if current.weekday() >= 5:
            day += timedelta(days=7 - current.weekday())
            return datetime.combine(day, start, zone)
        if current.time() < start:
            return datetime.combine(day, start, zone)
        if current.time() >= end:
            day += timedelta(days=1)
            while day.weekday() >= 5:
                day += timedelta(days=1)
            return datetime.combine(day, start, zone)
        return current
