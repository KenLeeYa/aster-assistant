from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from ky_jarvis_core.domain.devices import DeviceRecord, DeviceTrustState
from ky_jarvis_core.persistence.device_repository import SqlDeviceMapping, devices


def test_device_revocation_survives_reload_and_cannot_be_undone() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    devices.create(engine)
    first = SqlDeviceMapping(engine)
    now = datetime.now(UTC)
    record = DeviceRecord(
        id=uuid4(),
        user_id="local-user",
        display_name="Test phone",
        platform="android",
        app_version="test",
        os_version="test",
        public_key_pem="test-public-key",
        trust_state=DeviceTrustState.TRUSTED,
        created_at=now,
        updated_at=now,
    )
    first[record.id] = record
    second = SqlDeviceMapping(engine)
    assert second[record.id].trust_state is DeviceTrustState.TRUSTED
    second[record.id] = record.model_copy(update={"trust_state": DeviceTrustState.REVOKED})
    assert first[record.id].trust_state is DeviceTrustState.REVOKED
    with pytest.raises(ValueError, match="cannot regain trust"):
        first[record.id] = record
