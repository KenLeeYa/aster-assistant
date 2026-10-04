import base64
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from ky_jarvis_core.config import Settings
from ky_jarvis_core.domain.devices import (
    DeviceSecurityService,
    DeviceTrustState,
    MobileSessionTokens,
    approval_signature_payload,
    pairing_challenge,
    token_claim_challenge,
)
from ky_jarvis_core.domain.operator_authorization import operator_action_hash
from ky_jarvis_core.domain.realtime import (
    MockRealtimeProvider,
    RealtimeBroker,
    RealtimeSessionPolicy,
    UsageBudget,
)
from ky_jarvis_core.main import create_app


def _pair_trusted_device(
    service: DeviceSecurityService, now: datetime
) -> tuple[ec.EllipticCurvePrivateKey, MobileSessionTokens]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    offer = service.begin_pairing(server_fingerprint="sha256:test", now=now)
    signature = private_key.sign(
        pairing_challenge(offer.session_id, offer.one_time_secret),
        ec.ECDSA(hashes.SHA256()),
    )
    device = service.complete_pairing(
        session_id=offer.session_id,
        one_time_secret=offer.one_time_secret,
        public_key_pem=public_pem,
        approval_public_key_pem=public_pem,
        proof_signature_b64=base64.b64encode(signature).decode(),
        user_id="local-user",
        display_name="Test phone",
        app_version="0.1.0",
        os_version="Android 16",
        now=now,
    )
    tokens = service.confirm_device(
        device.id,
        comparison_code=offer.comparison_code,
        now=now,
    )
    return private_key, tokens


def test_pairing_is_one_time_and_refresh_reuse_revokes_device() -> None:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    service = DeviceSecurityService(token_pepper=b"test-pepper")
    private_key, tokens = _pair_trusted_device(service, now)
    del private_key

    rotated = service.rotate_refresh_token(
        tokens.family_id,
        tokens.refresh_token,
        now=now + timedelta(minutes=1),
    )
    assert rotated.refresh_token != tokens.refresh_token
    with pytest.raises(ValueError, match="reuse detected"):
        service.rotate_refresh_token(
            tokens.family_id,
            tokens.refresh_token,
            now=now + timedelta(minutes=2),
        )
    assert service.get_device(tokens.device_id).trust_state is DeviceTrustState.COMPROMISED


def test_expired_and_reused_pairing_attempts_fail() -> None:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    service = DeviceSecurityService(token_pepper=b"test-pepper")
    offer = service.begin_pairing(ttl=timedelta(seconds=1), server_fingerprint="test", now=now)
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    signature = private_key.sign(
        pairing_challenge(offer.session_id, offer.one_time_secret),
        ec.ECDSA(hashes.SHA256()),
    )
    with pytest.raises(ValueError, match="expired"):
        service.complete_pairing(
            session_id=offer.session_id,
            one_time_secret=offer.one_time_secret,
            public_key_pem=public_pem,
            proof_signature_b64=base64.b64encode(signature).decode(),
            user_id="local-user",
            display_name="Expired",
            app_version="0.1.0",
            os_version="Android 16",
            now=now + timedelta(seconds=2),
        )


def test_confirmed_tokens_are_claimed_once_by_the_device_key() -> None:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    service = DeviceSecurityService(token_pepper=b"test-pepper")
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    offer = service.begin_pairing(server_fingerprint="sha256:test", now=now)
    proof = private_key.sign(
        pairing_challenge(offer.session_id, offer.one_time_secret),
        ec.ECDSA(hashes.SHA256()),
    )
    device = service.complete_pairing(
        session_id=offer.session_id,
        one_time_secret=offer.one_time_secret,
        public_key_pem=public_pem,
        approval_public_key_pem=public_pem,
        proof_signature_b64=base64.b64encode(proof).decode(),
        user_id="local-user",
        display_name="Android",
        app_version="0.1.0",
        os_version="Android 17",
        now=now,
    )
    service.confirm_device(device.id, comparison_code=offer.comparison_code, now=now)
    claim_proof = private_key.sign(
        token_claim_challenge(offer.session_id, offer.one_time_secret),
        ec.ECDSA(hashes.SHA256()),
    )
    claimed = service.claim_pairing_tokens(
        offer.session_id,
        one_time_secret=offer.one_time_secret,
        proof_signature_b64=base64.b64encode(claim_proof).decode(),
        now=now,
    )
    assert claimed.device_id == device.id
    with pytest.raises(ValueError, match="already claimed"):
        service.claim_pairing_tokens(
            offer.session_id,
            one_time_secret=offer.one_time_secret,
            proof_signature_b64=base64.b64encode(claim_proof).decode(),
            now=now,
        )


def test_device_signature_binds_exact_mobile_approval_payload() -> None:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    service = DeviceSecurityService(token_pepper=b"test-pepper")
    private_key, tokens = _pair_trusted_device(service, now)
    approval_id = uuid4()
    payload = approval_signature_payload(
        approval_id=approval_id,
        action_hash="a" * 64,
        nonce="nonce",
        decision="approve",
        device_id=tokens.device_id,
        timestamp=now,
    )
    signature = base64.b64encode(private_key.sign(payload, ec.ECDSA(hashes.SHA256()))).decode()

    service.verify_approval_signature(tokens.device_id, payload, signature)
    with pytest.raises(ValueError, match="verification failed"):
        service.verify_approval_signature(tokens.device_id, payload + b"changed", signature)


def test_revoked_device_loses_session_approval_push_and_realtime_authority() -> None:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    service = DeviceSecurityService(token_pepper=b"test-pepper")
    private_key, tokens = _pair_trusted_device(service, now)
    signed_payload = b"approval-bound-to-this-device"
    signature = base64.b64encode(
        private_key.sign(signed_payload, ec.ECDSA(hashes.SHA256()))
    ).decode()
    broker = RealtimeBroker(
        devices=service,
        provider=MockRealtimeProvider(),
        enabled=True,
    )

    service.revoke_device(tokens.device_id, now=now + timedelta(seconds=1))

    with pytest.raises(ValueError, match="family revoked"):
        service.rotate_refresh_token(
            tokens.family_id,
            tokens.refresh_token,
            now=now + timedelta(seconds=2),
        )
    with pytest.raises(ValueError, match="invalid access token"):
        service.authenticate_access_token(
            tokens.access_token,
            now=now + timedelta(seconds=2),
        )
    with pytest.raises(ValueError, match="device is not trusted"):
        service.verify_approval_signature(tokens.device_id, signed_payload, signature)
    with pytest.raises(PermissionError, match="trusted device required"):
        broker.request_client_secret(
            device_id=tokens.device_id,
            requested_mode="conversation",
            now=now + timedelta(seconds=2),
        )


@pytest.mark.asyncio
async def test_pair_confirm_claim_and_revoke_api_contract() -> None:
    app = create_app(Settings())
    transport = ASGITransport(app=app)
    intent = {"X-KY-JARVIS-Intent": "ui-v1"}
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        pairing_body = {"server_fingerprint": "sha256:local-contract"}
        pairing_grant, _ = app.state.services.operator.grants.issue(
            operator_action_hash(
                method="POST",
                path="/api/v1/device-pairings",
                body=pairing_body,
            )
        )
        offer_response = await client.post(
            "/api/v1/device-pairings",
            headers={**intent, "X-KY-JARVIS-Operator-Grant": pairing_grant},
            json=pairing_body,
        )
        offer = offer_response.json()
        session_id = offer["session_id"]
        one_time_secret = offer["one_time_secret"]
        pairing_proof = private_key.sign(
            pairing_challenge(UUID(session_id), one_time_secret),
            ec.ECDSA(hashes.SHA256()),
        )
        completed = await client.post(
            "/api/v1/device-pairings/complete",
            headers=intent,
            json={
                "session_id": session_id,
                "one_time_secret": one_time_secret,
                "public_key_pem": public_pem,
                "approval_public_key_pem": public_pem,
                "proof_signature_b64": base64.b64encode(pairing_proof).decode(),
                "user_id": "local-user",
                "display_name": "Contract phone",
                "app_version": "0.1.0",
                "os_version": "Android contract",
                "capabilities": ["ptt", "biometric-approval"],
            },
        )
        device_id = completed.json()["id"]
        confirm_body = {"comparison_code": offer["comparison_code"]}
        confirm_path = f"/api/v1/devices/{device_id}/confirm"
        confirm_grant, _ = app.state.services.operator.grants.issue(
            operator_action_hash(method="POST", path=confirm_path, body=confirm_body)
        )
        confirmed = await client.post(
            confirm_path,
            headers={**intent, "X-KY-JARVIS-Operator-Grant": confirm_grant},
            json=confirm_body,
        )
        claim_proof = private_key.sign(
            token_claim_challenge(UUID(session_id), one_time_secret),
            ec.ECDSA(hashes.SHA256()),
        )
        claimed = await client.post(
            f"/api/v1/device-pairings/{session_id}/claim",
            headers=intent,
            json={
                "one_time_secret": one_time_secret,
                "proof_signature_b64": base64.b64encode(claim_proof).decode(),
            },
        )
        tokens = claimed.json()
        mobile = {
            **intent,
            "Authorization": f"Bearer {tokens['access_token']}",
        }
        heartbeat = await client.post("/api/v1/mobile/heartbeat", headers=mobile, json={})
        revoke_path = f"/api/v1/devices/{device_id}"
        revoke_grant, _ = app.state.services.operator.grants.issue(
            operator_action_hash(method="DELETE", path=revoke_path, body={})
        )
        revoked = await client.delete(
            revoke_path,
            headers={**intent, "X-KY-JARVIS-Operator-Grant": revoke_grant},
        )
        blocked_heartbeat = await client.post(
            "/api/v1/mobile/heartbeat",
            headers=mobile,
            json={},
        )
        blocked_refresh = await client.post(
            "/api/v1/mobile/sessions/refresh",
            headers=intent,
            json={
                "family_id": tokens["family_id"],
                "refresh_token": tokens["refresh_token"],
            },
        )
        repeated_claim = await client.post(
            f"/api/v1/device-pairings/{session_id}/claim",
            headers=intent,
            json={
                "one_time_secret": one_time_secret,
                "proof_signature_b64": base64.b64encode(claim_proof).decode(),
            },
        )

    assert offer_response.status_code == 200
    assert completed.status_code == 200
    assert confirmed.status_code == 200
    assert confirmed.json()["tokens"] == "claim-on-device"
    assert claimed.status_code == 200
    assert heartbeat.status_code == 200
    assert revoked.status_code == 200
    assert revoked.json()["trust_state"] == "revoked"
    assert blocked_heartbeat.status_code == 401
    assert blocked_refresh.status_code == 401
    assert repeated_claim.status_code == 401


def test_realtime_requires_trusted_device_budget_and_concurrency() -> None:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    devices = DeviceSecurityService(token_pepper=b"test-pepper")
    _, tokens = _pair_trusted_device(devices, now)
    provider = MockRealtimeProvider()
    broker = RealtimeBroker(
        devices=devices,
        provider=provider,
        policy=RealtimeSessionPolicy(max_concurrent_sessions=1),
        enabled=True,
    )
    broker.set_budget(
        "local-user",
        UsageBudget(day=now.date(), soft_limit_units=5, hard_limit_units=10),
    )

    secret = broker.request_client_secret(
        device_id=tokens.device_id,
        requested_mode="conversation",
        now=now,
    )
    assert secret.value.startswith("mock-client-secret-")
    assert secret.value not in broker.issuance(secret.issuance_id).model_dump_json()
    with pytest.raises(PermissionError, match="concurrent"):
        broker.request_client_secret(
            device_id=tokens.device_id,
            requested_mode="conversation",
            now=now + timedelta(seconds=1),
        )
    broker.close(secret.issuance_id)
    broker.record_usage("local-user", units=10, day=now.date())
    with pytest.raises(PermissionError, match="budget"):
        broker.request_client_secret(
            device_id=tokens.device_id,
            requested_mode="conversation",
            now=now + timedelta(seconds=2),
        )
    assert provider.calls == 1
