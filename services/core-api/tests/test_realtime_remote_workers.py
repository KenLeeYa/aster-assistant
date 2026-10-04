from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from ky_jarvis_core.config import DeploymentMode, Settings
from ky_jarvis_core.domain.devices import (
    DeviceSecurityService,
    MobileSessionTokens,
    pairing_challenge,
)
from ky_jarvis_core.domain.realtime import (
    LocalFallbackResponse,
    RealtimeBroker,
    RealtimeSessionPolicy,
)
from ky_jarvis_core.domain.workers import WorkerPresenceService, WorkerState
from ky_jarvis_core.integrations.push import FakePushAdapter, PushDispatcher
from ky_jarvis_core.main import create_app
from pydantic import ValidationError


def _trusted_device(
    service: DeviceSecurityService,
    now: datetime,
) -> MobileSessionTokens:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    offer = service.begin_pairing(server_fingerprint="sha256:worker-test", now=now)
    proof = private_key.sign(
        pairing_challenge(offer.session_id, offer.one_time_secret),
        ec.ECDSA(hashes.SHA256()),
    )
    device = service.complete_pairing(
        session_id=offer.session_id,
        one_time_secret=offer.one_time_secret,
        public_key_pem=public_pem,
        proof_signature_b64=base64.b64encode(proof).decode(),
        user_id="local-user",
        display_name="Worker test phone",
        app_version="0.1.0",
        os_version="Android contract",
        now=now,
    )
    return service.confirm_device(
        device.id,
        comparison_code=offer.comparison_code,
        now=now,
    )


class UnavailableRealtimeProvider:
    def mint_client_secret(self, **_: object) -> str:
        raise ConnectionError("provider unavailable")


def test_provider_outage_returns_secret_free_local_fallback() -> None:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    devices = DeviceSecurityService(token_pepper=b"test-pepper")
    tokens = _trusted_device(devices, now)
    broker = RealtimeBroker(
        devices=devices,
        provider=UnavailableRealtimeProvider(),
        policy=RealtimeSessionPolicy(
            daily_soft_limit_units=5,
            daily_hard_limit_units=10,
        ),
        enabled=True,
    )

    response = broker.request_client_secret(
        device_id=tokens.device_id,
        requested_mode="conversation",
        now=now,
    )

    assert isinstance(response, LocalFallbackResponse)
    assert response.mode == "local_chained"
    assert "secret" not in response.model_dump_json()


def test_worker_presence_expires_and_push_is_wake_only_for_trusted_devices() -> None:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    workers = WorkerPresenceService(timeout=timedelta(seconds=5))
    registered = workers.register(
        "worker-1",
        display_name="Local worker",
        capabilities=("chat",),
        now=now,
    )
    assert registered.state is WorkerState.ONLINE
    assert workers.get("worker-1", now=now + timedelta(seconds=6)).state is WorkerState.OFFLINE
    assert workers.heartbeat("worker-1", now=now + timedelta(seconds=7)).state is WorkerState.ONLINE

    devices = DeviceSecurityService(token_pepper=b"test-pepper")
    tokens = _trusted_device(devices, now)
    fake = FakePushAdapter()
    dispatcher = PushDispatcher(devices=devices, adapter=fake, enabled=True)
    receipt = dispatcher.dispatch(
        device_id=tokens.device_id,
        category="worker-presence",
        correlation_id="presence-1",
    )
    assert receipt.startswith("fake-push-")
    assert fake.sent[0].model_dump().keys() == {
        "id",
        "device_id",
        "category",
        "correlation_id",
    }
    devices.revoke_device(tokens.device_id, now=now + timedelta(seconds=1))
    with pytest.raises(PermissionError, match="trusted device"):
        dispatcher.dispatch(
            device_id=tokens.device_id,
            category="worker-presence",
            correlation_id="presence-2",
        )


def test_private_remote_and_hybrid_modes_require_explicit_gateway_and_tls_identity() -> None:
    with pytest.raises(ValidationError, match="remote gateway flag"):
        Settings(
            deployment_mode=DeploymentMode.PRIVATE_REMOTE,
            enable_lan_access=True,
        )
    with pytest.raises(ValidationError, match="TLS server identity"):
        Settings(
            deployment_mode=DeploymentMode.HYBRID_GATEWAY,
            enable_lan_access=True,
            enable_remote_gateway=True,
        )
    valid = Settings(
        deployment_mode=DeploymentMode.PRIVATE_REMOTE,
        enable_lan_access=True,
        enable_remote_gateway=True,
        remote_tls_identity="sha256:private-gateway-contract",
    )
    assert valid.deployment_mode is DeploymentMode.PRIVATE_REMOTE


@pytest.mark.asyncio
async def test_authenticated_realtime_budget_and_worker_presence_api() -> None:
    app = create_app(
        Settings(
            enable_openai_realtime=True,
            realtime_daily_soft_limit_units=5,
            realtime_daily_hard_limit_units=10,
        )
    )
    tokens = _trusted_device(app.state.services.devices, datetime.now(UTC))
    transport = ASGITransport(app=app)
    intent = {"X-KY-JARVIS-Intent": "ui-v1"}
    mobile = {
        **intent,
        "Authorization": f"Bearer {tokens.access_token}",
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        offline = await client.get("/api/v1/mobile/worker-presence", headers=mobile)
        registered = await client.post(
            "/api/v1/workers",
            headers=intent,
            json={
                "worker_id": "contract-worker",
                "display_name": "Contract worker",
                "capabilities": ["chat"],
            },
        )
        online = await client.get("/api/v1/mobile/worker-presence", headers=mobile)
        first = await client.post(
            "/api/v1/realtime/client-secrets",
            headers=mobile,
            json={"requested_mode": "conversation"},
        )
        second = await client.post(
            "/api/v1/realtime/client-secrets",
            headers=mobile,
            json={"requested_mode": "conversation"},
        )

    assert offline.status_code == 200 and offline.json()["state"] == "offline"
    assert registered.status_code == 200
    assert online.status_code == 200 and online.json()["state"] == "online"
    assert first.status_code == 200
    assert first.json()["mode"] == "webrtc"
    assert first.json()["value"].startswith("mock-client-secret-")
    issuance = app.state.services.realtime.issuance(UUID(first.json()["issuance_id"]))
    assert first.json()["value"] not in issuance.model_dump_json()
    assert second.status_code == 403
