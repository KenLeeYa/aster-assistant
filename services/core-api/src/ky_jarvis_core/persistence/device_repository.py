"""Device identity/trust persistence; session tokens remain process-local and fail closed."""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from sqlalchemy import Engine

from ky_jarvis_core.domain.devices import DeviceRecord
from ky_jarvis_core.persistence.schema import metadata

devices = metadata.tables["devices"]


class SqlDeviceMapping(MutableMapping[UUID, DeviceRecord]):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def __getitem__(self, key: UUID) -> DeviceRecord:
        with self._engine.connect() as connection:
            row = connection.execute(
                sa.select(devices.c.audit_metadata).where(devices.c.id == key)
            ).one_or_none()
        if row is None:
            raise KeyError(key)
        return DeviceRecord.model_validate(row.audit_metadata["record"])

    def __setitem__(self, key: UUID, value: DeviceRecord) -> None:
        if key != value.id:
            raise ValueError("device id mismatch")
        owner_id = uuid5(NAMESPACE_URL, f"ky-jarvis-user:{value.user_id}")
        payload = {"record": value.model_dump(mode="json")}
        with self._engine.begin() as connection:
            current = connection.execute(
                sa.select(devices.c.version, devices.c.audit_metadata).where(devices.c.id == key)
            ).one_or_none()
            if current is None:
                connection.execute(
                    sa.insert(devices).values(
                        id=value.id,
                        owner_scope=value.user_id,
                        user_id=owner_id,
                        display_name=value.display_name,
                        platform=value.platform,
                        app_version=value.app_version,
                        os_version=value.os_version,
                        trust_state=value.trust_state.value,
                        public_key_algorithm=value.public_key_algorithm,
                        public_key=value.public_key_pem,
                        last_seen_at=value.last_seen_at,
                        revoked_at=value.revoked_at,
                        audit_metadata=payload,
                    )
                )
            else:
                previous = DeviceRecord.model_validate(current.audit_metadata["record"])
                if (
                    previous.trust_state.value in {"revoked", "compromised"}
                    and value.trust_state != previous.trust_state
                ):
                    raise ValueError("revoked device cannot regain trust")
                result = connection.execute(
                    sa.update(devices)
                    .where(devices.c.id == key, devices.c.version == current.version)
                    .values(
                        display_name=value.display_name,
                        trust_state=value.trust_state.value,
                        last_seen_at=value.last_seen_at,
                        revoked_at=value.revoked_at,
                        audit_metadata=payload,
                        version=devices.c.version + 1,
                    )
                )
                if result.rowcount != 1:
                    raise ValueError("device changed concurrently")

    def __delitem__(self, key: UUID) -> None:
        raise TypeError("device deletion is forbidden; revoke instead")

    def __iter__(self) -> Iterator[UUID]:
        with self._engine.connect() as connection:
            return iter(connection.scalars(sa.select(devices.c.id)).all())

    def __len__(self) -> int:
        with self._engine.connect() as connection:
            return connection.scalar(sa.select(sa.func.count()).select_from(devices)) or 0
