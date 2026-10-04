from datetime import UTC, datetime, time
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from ky_jarvis_core.config import Settings
from ky_jarvis_core.domain.projects import DeterministicProjectPlanner
from ky_jarvis_core.domain.scheduling import DeterministicScheduler, TimeBlock
from ky_jarvis_core.domain.voice import (
    TranscriptState,
    VoiceTranscript,
    promote_final_transcript,
    requires_visual_confirmation,
)
from ky_jarvis_core.integrations.adapters import (
    FakeCalendarAdapter,
    FakePlaneAdapter,
    PlaneWorkItemPreview,
)
from ky_jarvis_core.main import create_app


def test_project_plan_preserves_source_requirement_ids() -> None:
    plan = DeterministicProjectPlanner().create_preview(
        request="建立安全的排程功能",
        source_message_id="message-1",
        created_at=datetime.now(UTC),
    )

    requirement_id = plan.requirements[0].id
    assert all(requirement_id in item.source_requirement_ids for item in plan.work_items)
    assert all(requirement_id in item.source_requirement_ids for item in plan.decisions)
    assert plan.approval_required is True
    assert all(item.synchronization_status == "disabled" for item in plan.work_items)


def test_project_and_schedule_previews_are_kept_in_internal_stores() -> None:
    planner = DeterministicProjectPlanner()
    plan = planner.create_preview(
        request="建立安全的排程功能",
        source_message_id="message-2",
        created_at=datetime.now(UTC),
    )
    scheduler = DeterministicScheduler()
    zone = ZoneInfo("Asia/Taipei")
    proposal = scheduler.propose(
        work_item_id=plan.work_items[0].id,
        duration_minutes=60,
        earliest=datetime(2026, 9, 3, 9, 0, tzinfo=zone),
        deadline=datetime(2026, 9, 3, 18, 0, tzinfo=zone),
        busy=(),
    )

    assert planner.get(plan.project_id) == plan
    assert scheduler.get(proposal.id) == proposal
    assert proposal.requires_approval is True


def test_scheduler_avoids_fixture_conflicts_in_taipei() -> None:
    zone = ZoneInfo("Asia/Taipei")
    scheduler = DeterministicScheduler()
    proposal = scheduler.propose(
        work_item_id=uuid4(),
        duration_minutes=240,
        earliest=datetime(2026, 9, 1, 9, 0, tzinfo=zone),
        deadline=datetime(2026, 9, 2, 18, 0, tzinfo=zone),
        busy=(
            TimeBlock(
                start=datetime(2026, 9, 1, 10, 0, tzinfo=zone),
                end=datetime(2026, 9, 1, 12, 0, tzinfo=zone),
            ),
        ),
        working_start=time(9, 0),
        working_end=time(18, 0),
    )

    scheduled_minutes = sum(
        int((block.end - block.start).total_seconds() / 60) for block in proposal.blocks
    )
    assert scheduled_minutes == 240
    busy = TimeBlock(
        start=datetime(2026, 9, 1, 10, 0, tzinfo=zone),
        end=datetime(2026, 9, 1, 12, 0, tzinfo=zone),
    )
    assert all(block.end <= busy.start or block.start >= busy.end for block in proposal.blocks)
    assert proposal.requires_approval is True


def test_fake_calendar_and_plane_reject_writes_without_approval() -> None:
    zone = ZoneInfo("Asia/Taipei")
    calendar = FakeCalendarAdapter(enabled=True)
    event = calendar.preview(
        title="審查排程",
        start=datetime(2026, 9, 3, 9, 0, tzinfo=zone),
        end=datetime(2026, 9, 3, 10, 0, tzinfo=zone),
        timezone="Asia/Taipei",
    )
    plane = FakePlaneAdapter(enabled=True)
    item = PlaneWorkItemPreview(
        id=uuid4(),
        title="審查需求",
        description="僅 fake provider fixture",
        source_requirement_ids=(uuid4(),),
    )

    with pytest.raises(PermissionError, match="approval"):
        calendar.create(event, approved=False, idempotency_key="calendar-1")
    with pytest.raises(PermissionError, match="approval"):
        plane.create(item, approved=False, idempotency_key="plane-1")
    assert event.external_id is None
    assert item.external_id is None


@pytest.mark.asyncio
async def test_project_and_schedule_preview_api_never_calls_an_external_provider() -> None:
    app = create_app(Settings())
    transport = httpx.ASGITransport(app=app)
    headers = {"X-KY-JARVIS-Intent": "ui-v1"}
    zone = ZoneInfo("Asia/Taipei")
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        project = await client.post(
            "/api/v1/projects/preview",
            headers=headers,
            json={"request": "建立排程", "source_message_id": "api-message-1"},
        )
        work_item_id = project.json()["work_items"][0]["id"]
        schedule = await client.post(
            "/api/v1/schedules/preview",
            headers=headers,
            json={
                "work_item_id": work_item_id,
                "duration_minutes": 60,
                "earliest": datetime(2026, 9, 3, 9, 0, tzinfo=zone).isoformat(),
                "deadline": datetime(2026, 9, 3, 18, 0, tzinfo=zone).isoformat(),
                "busy": [],
                "timezone": "Asia/Taipei",
            },
        )
        projects = await client.get("/api/v1/projects")
        schedules = await client.get("/api/v1/schedules")

    assert project.status_code == 200
    assert project.json()["decisions"][0]["status"] == "draft"
    assert schedule.status_code == 200
    assert schedule.json()["requires_approval"] is True
    assert len(projects.json()) == 1
    assert len(schedules.json()) == 1


def test_partial_or_unsubmitted_voice_never_promotes() -> None:
    partial = VoiceTranscript(
        voice_session_id=uuid4(),
        provider="mock",
        text="刪除檔案",
        confidence=0.4,
        state=TranscriptState.PARTIAL,
    )
    with pytest.raises(ValueError, match="final"):
        promote_final_transcript(partial)

    final = partial.model_copy(update={"state": TranscriptState.FINAL, "submitted": True})
    promoted = promote_final_transcript(final)
    assert promoted.promoted_message_id is not None
    assert requires_visual_confirmation(final) is True
