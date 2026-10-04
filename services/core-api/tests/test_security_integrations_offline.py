from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from ky_jarvis_core.domain.audit import AuditChain
from ky_jarvis_core.domain.offline import EnvelopeState, OfflineCommandQueue
from ky_jarvis_core.domain.policy import RiskLevel
from ky_jarvis_core.integrations.adapters import (
    CalendarPreview,
    FakeCalendarAdapter,
    FakePlaneAdapter,
    PlaneWorkItemPreview,
)
from ky_jarvis_core.integrations.files import LocalFileConnector, PathBoundaryError
from ky_jarvis_core.integrations.sidecar import SidecarManager, SidecarPolicy, SidecarSpec


def test_audit_chain_redacts_secrets_and_detects_tampering() -> None:
    chain = AuditChain()
    event = chain.append(
        "connector.called",
        {"Authorization": "Bearer should-not-survive-123456", "result": "ok"},
    )

    assert event.payload["Authorization"] == "[REDACTED]"
    assert chain.verify() is True
    chain._events[0] = event.model_copy(update={"payload": {"result": "tampered"}})  # noqa: SLF001
    assert chain.verify() is False


def test_local_file_connector_denies_traversal_and_symlink_escape(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("outside", encoding="utf-8")
    connector = LocalFileConnector([allowed])

    with pytest.raises(PathBoundaryError):
        connector.read_text(allowed / ".." / "outside" / "secret.txt")

    link = allowed / "escape"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is not available on this Windows profile")
    with pytest.raises(PathBoundaryError):
        connector.read_text(link / "secret.txt")


def test_fake_calendar_and_plane_writes_are_gated_and_idempotent() -> None:
    now = datetime(2026, 9, 1, 9, tzinfo=UTC)
    calendar = FakeCalendarAdapter()
    preview = CalendarPreview(
        id=uuid4(), title="Review", start=now, end=now + timedelta(hours=1), timezone="UTC"
    )
    with pytest.raises(PermissionError):
        calendar.create(preview, approved=False, idempotency_key="calendar-1")
    first = calendar.create(preview, approved=True, idempotency_key="calendar-1")
    second = calendar.create(preview, approved=True, idempotency_key="calendar-1")
    assert first.external_id == second.external_id

    plane = FakePlaneAdapter(enabled=False)
    plane_preview = PlaneWorkItemPreview(
        id=uuid4(), title="Task", description="Draft", source_requirement_ids=(uuid4(),)
    )
    with pytest.raises(RuntimeError, match="disabled"):
        plane.create(plane_preview, approved=True, idempotency_key="plane-1")


def test_offline_queue_never_claims_execution_and_revalidates_stale_write() -> None:
    now = datetime(2026, 9, 1, 9, tzinfo=UTC)
    queue = OfflineCommandQueue(b"q" * 32)
    envelope = queue.enqueue(
        device_id=uuid4(),
        command={"action": "calendar.create", "title": "Review"},
        action_hash="a" * 64,
        risk_level=RiskLevel.R3_MODIFY,
        approved=True,
        now=now,
    )

    assert b"calendar.create" not in envelope.ciphertext
    assert (
        queue.release(envelope, worker_online=False, current_action_hash="a" * 64, now=now).state
        is EnvelopeState.QUEUED
    )
    assert (
        queue.release(
            envelope,
            worker_online=True,
            current_action_hash="a" * 64,
            now=now + timedelta(minutes=6),
        ).state
        is EnvelopeState.REVALIDATION_REQUIRED
    )


@pytest.mark.asyncio
async def test_sidecar_manager_uses_exact_allowlisted_executable() -> None:
    executable = Path(sys.executable).resolve()
    allowed = ("-c", "print('sidecar-ok')")
    manager = SidecarManager([SidecarPolicy(executable=executable, allowed_arguments=(allowed,))])
    result = await manager.run(SidecarSpec(executable=executable, arguments=allowed))
    assert result.exit_code == 0
    assert result.stdout.strip() == "sidecar-ok"

    with pytest.raises(PermissionError, match="arguments"):
        await manager.run(
            SidecarSpec(executable=executable, arguments=("-c", "print('not-allowed')"))
        )
