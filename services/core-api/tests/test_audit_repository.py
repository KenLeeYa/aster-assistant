import sqlalchemy as sa
from ky_jarvis_core.domain.audit import AuditChain
from ky_jarvis_core.persistence.audit_repository import AuditRepository, audit_events


def test_audit_chain_survives_restart_and_detects_tampering() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    audit_events.create(engine)
    repository = AuditRepository(engine)
    first = AuditChain(repository)
    first.append("approval.created", {"access_token": "hidden", "request_id": "one"})
    second = AuditChain(repository)
    assert second.verify()
    assert second.events[0].payload["access_token"] == "[REDACTED]"  # noqa: S105
    second.append("approval.denied", {"request_id": "one"})
    assert len(AuditChain(repository).events) == 2

    with engine.begin() as connection:
        connection.execute(
            sa.update(audit_events).where(audit_events.c.sequence == 1).values(event_hash="0" * 64)
        )
    try:
        AuditChain(repository)
    except ValueError as exc:
        assert "verification" in str(exc)
    else:
        raise AssertionError("tampered audit chain should fail startup")
