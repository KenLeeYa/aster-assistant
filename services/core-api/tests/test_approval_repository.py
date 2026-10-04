from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from ky_jarvis_core.domain.approvals import ApprovalService, ApprovalState
from ky_jarvis_core.domain.policy import RiskLevel
from ky_jarvis_core.persistence.approval_repository import (
    ApprovalRepository,
    SqlApprovalMapping,
    approval_requests,
)


def test_approval_transition_is_single_use_across_repository_instances() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    approval_requests.create(engine)
    first = ApprovalRepository(engine)
    second = ApprovalRepository(engine)
    request, _ = ApprovalService().create(
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
    first.add(request)
    assert second.get(request.id) is not None
    assert second.transition(
        request.id,
        expected=ApprovalState.PENDING,
        target=ApprovalState.APPROVED,
        action_hash=request.action_hash,
        now=datetime.now(UTC),
    )
    assert not first.transition(
        request.id,
        expected=ApprovalState.PENDING,
        target=ApprovalState.APPROVED,
        action_hash=request.action_hash,
    )
    assert first.get(request.id).state is ApprovalState.APPROVED


def test_approval_service_uses_durable_mapping() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    approval_requests.create(engine)
    repository = ApprovalRepository(engine)
    service = ApprovalService(
        token_pepper=b"test-pepper",
        requests=SqlApprovalMapping(repository),
    )
    request, _ = service.create(
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
    reloaded = ApprovalService(
        token_pepper=b"test-pepper",
        requests=SqlApprovalMapping(repository),
    )
    approved = reloaded.decide_authenticated(
        request.id,
        action_hash=request.action_hash,
        approved=True,
        decided_by="paired-device",
    )
    assert approved.state is ApprovalState.APPROVED
    assert service.get(request.id).decided_by == "paired-device"
