import pytest
import sqlalchemy as sa
from ky_jarvis_core.domain.memory import GovernedMemoryStore, MemoryStatus, MemoryType
from ky_jarvis_core.persistence.memory_repository import SqlMemoryMapping, memories


def test_memory_source_and_forget_survive_restart() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    memories.create(engine)
    first = GovernedMemoryStore(SqlMemoryMapping(engine))
    item = first.propose(
        user_id="local-user",
        content="Use Traditional Chinese",
        memory_type=MemoryType.PREFERENCE,
        source_type="user_message",
        created_by="user",
    )
    second = GovernedMemoryStore(SqlMemoryMapping(engine))
    assert second.get(item.id).source_type == "user_message"
    second.forget(item.id)
    assert first.get(item.id).status is MemoryStatus.DELETED
    with pytest.raises(ValueError, match="cannot reactivate"):
        SqlMemoryMapping(engine)[item.id] = item
