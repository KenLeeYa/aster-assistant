from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from ky_jarvis_core.config import Settings
from ky_jarvis_core.domain.devices import DeviceRecord, DeviceTrustState
from ky_jarvis_core.domain.memory import MemoryType
from ky_jarvis_core.domain.policy import RiskLevel
from ky_jarvis_core.main import create_app
from ky_jarvis_core.persistence.approval_repository import approval_requests
from ky_jarvis_core.persistence.audit_repository import audit_events
from ky_jarvis_core.persistence.device_repository import devices
from ky_jarvis_core.persistence.execution_ledger import tool_executions
from ky_jarvis_core.persistence.memory_repository import memories
from pydantic import SecretStr


def test_core_reloads_approval_and_audit_state(tmp_path: Path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'governance.db'}"
    engine = sa.create_engine(url)
    approval_requests.create(engine)
    audit_events.create(engine)
    devices.create(engine)
    memories.create(engine)
    tool_executions.create(engine)
    engine.dispose()

    first = create_app(Settings(database_url=SecretStr(url)))
    request, _ = first.state.services.approvals.create(
        title="Review",
        reason="Test",
        target="local.test",
        risk_level=RiskLevel.R2_CREATE_REVERSIBLE,
        permissions=("test.preview",),
        preview={"value": "safe"},
        side_effects=(),
        rollback_method="none",
        originating_request="test",
        agent_run_id=uuid4(),
        tool_name="test.preview",
        idempotency_key="once",
    )
    first.state.services.audit.append("approval.created", {"approval_id": str(request.id)})
    now = datetime.now(UTC)
    device = DeviceRecord(
        id=uuid4(),
        user_id="local-user",
        display_name="Test endpoint",
        platform="android",
        app_version="test",
        os_version="test",
        public_key_pem="test-public-key",
        trust_state=DeviceTrustState.REVOKED,
        created_at=now,
        updated_at=now,
    )
    first.state.services.devices._devices[device.id] = device
    memory = first.state.services.memory.propose(
        user_id="local-user",
        content="Use Traditional Chinese",
        memory_type=MemoryType.PREFERENCE,
        source_type="user_message",
        created_by="user",
    )
    first.state.services.close()

    second = create_app(Settings(database_url=SecretStr(url)))
    assert second.state.services.approvals.get(request.id).action_hash == request.action_hash
    assert second.state.services.audit.verify()
    assert len(second.state.services.audit.events) == 1
    assert (
        second.state.services.devices.get_device(device.id).trust_state is DeviceTrustState.REVOKED
    )
    assert second.state.services.memory.get(memory.id).content == "Use Traditional Chinese"
    second.state.services.close()
