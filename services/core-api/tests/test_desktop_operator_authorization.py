from __future__ import annotations

import base64
import math
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from ky_jarvis_core.config import Settings
from ky_jarvis_core.domain import operator_authorization as operator_module
from ky_jarvis_core.domain.devices import pairing_challenge
from ky_jarvis_core.domain.operator_authorization import (
    DesktopOperatorAuthorization,
    FileOperatorCredentialStore,
    MemoryOperatorCredentialStore,
    OperatorCredential,
    OperatorGrantStore,
    operator_action_hash,
)
from ky_jarvis_core.main import create_app
from webauthn.helpers.structs import CredentialDeviceType

INTENT_HEADERS = {"X-KY-JARVIS-Intent": "ui-v1"}


def test_core_removes_operator_bootstrap_secret_from_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enrollment_secret = secrets.token_urlsafe(32)
    monkeypatch.setenv("KY_JARVIS_OPERATOR_BOOTSTRAP_SECRET", enrollment_secret)

    app = create_app(Settings(operator_bootstrap_secret=enrollment_secret))

    assert app.state.services.operator.status()["configured"] is True
    assert app.state.settings.operator_bootstrap_secret is None
    assert "KY_JARVIS_OPERATOR_BOOTSTRAP_SECRET" not in os.environ


def test_public_operator_credential_metadata_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "operator" / "credential.json"
    credential = OperatorCredential(
        credential_id=b"persistent-credential-id",
        credential_public_key=b"public-key-only",
        sign_count=7,
        user_id=b"stable-user-id",
        transports=("internal",),
        created_at=datetime(2026, 9, 3, tzinfo=UTC),
        device_type="single_device",
        backed_up=False,
    )

    FileOperatorCredentialStore(path).save(credential)
    loaded = FileOperatorCredentialStore(path).get()

    assert loaded == credential
    assert "private" not in path.read_text(encoding="utf-8").lower()


@pytest.mark.asyncio
async def test_operator_enrollment_endpoint_fails_closed_and_requires_platform_uv() -> None:
    enrollment_secret = secrets.token_urlsafe(32)
    app = create_app(Settings(operator_bootstrap_secret=enrollment_secret))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        status = await client.get("/api/v1/operator/status")
        denied = await client.post(
            "/api/v1/operator/registration/options",
            headers=INTENT_HEADERS,
            json={"bootstrap_secret": secrets.token_urlsafe(32)},
        )
        options = await client.post(
            "/api/v1/operator/registration/options",
            headers=INTENT_HEADERS,
            json={"bootstrap_secret": enrollment_secret},
        )

    assert status.json()["configured"] is True
    assert status.json()["registered"] is False
    assert denied.status_code == 401
    assert options.status_code == 200
    assert options.json()["options"]["authenticatorSelection"]["userVerification"] == "required"


def test_windows_hello_verification_issues_one_shot_action_bound_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DesktopOperatorAuthorization(
        credential_store=MemoryOperatorCredentialStore(),
        rp_id="localhost",
        origin="http://localhost:3000",
        bootstrap_secret="test-enrollment-secret",  # noqa: S106
    )
    registration = service.begin_registration("test-enrollment-secret")
    selection = registration["options"]["authenticatorSelection"]
    assert selection == {
        "authenticatorAttachment": "platform",
        "residentKey": "required",
        "requireResidentKey": True,
        "userVerification": "required",
    }
    credential_id = b"credential-id-for-test"
    public_key = b"credential-public-key-for-test"
    monkeypatch.setattr(
        operator_module,
        "verify_registration_response",
        lambda **_: SimpleNamespace(
            credential_id=credential_id,
            credential_public_key=public_key,
            sign_count=0,
            credential_device_type=CredentialDeviceType.SINGLE_DEVICE,
            credential_backed_up=False,
        ),
    )
    registered = service.finish_registration(
        registration["challenge_id"],
        {"response": {"transports": ["internal"]}},
    )
    assert registered["registered"] is True

    action_body = {"server_fingerprint": "sha256:windows-hello-contract"}
    authentication = service.begin_authentication(
        method="POST",
        path="/api/v1/device-pairings",
        body=action_body,
    )
    assert authentication["options"]["userVerification"] == "required"
    monkeypatch.setattr(
        operator_module,
        "verify_authentication_response",
        lambda **_: SimpleNamespace(
            credential_id=credential_id,
            new_sign_count=1,
            credential_device_type=CredentialDeviceType.SINGLE_DEVICE,
            credential_backed_up=False,
        ),
    )
    verified = service.finish_authentication(
        authentication["challenge_id"],
        {"id": "fake-browser-credential"},
    )

    assert (
        service.authorize(
            verified["grant_token"],
            method="POST",
            path="/api/v1/device-pairings",
            body=action_body,
        )
        == "windows-hello:local-user"
    )
    with pytest.raises(PermissionError, match="desktop operator authorization required"):
        service.authorize(
            verified["grant_token"],
            method="POST",
            path="/api/v1/device-pairings",
            body=action_body,
        )


def test_operator_grant_rejects_wrong_action_and_expiry() -> None:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    grants = OperatorGrantStore(ttl=timedelta(seconds=30))
    expected_hash = operator_action_hash(
        method="DELETE",
        path="/api/v1/devices/00000000-0000-0000-0000-000000000001",
        body={},
    )
    wrong_hash = operator_action_hash(
        method="DELETE",
        path="/api/v1/devices/00000000-0000-0000-0000-000000000002",
        body={},
    )
    wrong_action_token, _ = grants.issue(expected_hash, now=now)
    with pytest.raises(PermissionError, match="desktop operator authorization required"):
        grants.consume(wrong_action_token, action_hash=wrong_hash, now=now)
    with pytest.raises(PermissionError, match="desktop operator authorization required"):
        grants.consume(wrong_action_token, action_hash=expected_hash, now=now)

    expired_token, _ = grants.issue(expected_hash, now=now)
    with pytest.raises(PermissionError, match="desktop operator authorization required"):
        grants.consume(
            expired_token,
            action_hash=expected_hash,
            now=now + timedelta(seconds=31),
        )


def test_operator_action_hash_rejects_non_finite_json_numbers() -> None:
    with pytest.raises(ValueError, match="Out of range float values"):
        operator_action_hash(
            method="POST",
            path="/api/v1/device-pairings",
            body={"invalid": math.nan},
        )


@pytest.mark.asyncio
async def test_intent_header_alone_cannot_authorize_desktop_tool_execution() -> None:
    app = create_app(Settings())
    transport = httpx.ASGITransport(app=app)
    execution = {
        "tool_name": "calendar.create.fake",
        "payload": {
            "title": "Protected action",
            "start": "2026-09-03T09:00:00+08:00",
            "end": "2026-09-03T10:00:00+08:00",
            "timezone": "Asia/Taipei",
        },
        "idempotency_key": "operator-auth-negative-1",
        "reason": "Security regression",
        "originating_request": "Attempt a desktop-only approval",
        "rollback_method": "Delete the fake event",
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        requested = await client.post(
            "/api/v1/tool-executions",
            headers=INTENT_HEADERS,
            json=execution,
        )
        body = requested.json()
        resumed = await client.post(
            f"/api/v1/tool-executions/{body['approval']['id']}/resume",
            headers=INTENT_HEADERS,
            json={"token": body["decision_token"], "approved": True},
        )
        decided = await client.post(
            f"/api/v1/approvals/{body['approval']['id']}/decision",
            headers=INTENT_HEADERS,
            json={
                "token": body["decision_token"],
                "action_payload": {},
                "approved": False,
            },
        )

    assert requested.status_code == 200
    assert resumed.status_code == 401
    assert decided.status_code == 401
    assert resumed.json() == {"detail": "desktop operator authorization required"}
    assert decided.json() == {"detail": "desktop operator authorization required"}


@pytest.mark.asyncio
async def test_memory_authority_and_deletion_require_action_bound_operator_grants() -> None:
    app = create_app(Settings())
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/memories",
            headers=INTENT_HEADERS,
            json={
                "memory_type": "decision",
                "content": "Security-sensitive candidate",
                "source_type": "user_message",
            },
        )
        memory_id = created.json()["id"]
        approve_path = f"/api/v1/memories/{memory_id}/approve"
        denied_approval = await client.post(
            approve_path,
            headers=INTENT_HEADERS,
            json={},
        )
        approval_grant, _ = app.state.services.operator.grants.issue(
            operator_action_hash(method="POST", path=approve_path, body={})
        )
        approved = await client.post(
            approve_path,
            headers={
                **INTENT_HEADERS,
                "X-KY-JARVIS-Operator-Grant": approval_grant,
            },
            json={},
        )
        delete_path = f"/api/v1/memories/{memory_id}"
        denied_delete = await client.delete(delete_path, headers=INTENT_HEADERS)
        delete_grant, _ = app.state.services.operator.grants.issue(
            operator_action_hash(method="DELETE", path=delete_path, body={})
        )
        deleted = await client.delete(
            delete_path,
            headers={
                **INTENT_HEADERS,
                "X-KY-JARVIS-Operator-Grant": delete_grant,
            },
        )

    assert created.status_code == 200
    assert denied_approval.status_code == 401
    assert approved.status_code == 200
    assert approved.json()["approved_by"] == "windows-hello:local-user"
    assert denied_delete.status_code == 401
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_intent_header_alone_cannot_pair_confirm_or_revoke_device() -> None:
    app = create_app(Settings())
    transport = httpx.ASGITransport(app=app)
    services = app.state.services
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    offer = services.devices.begin_pairing(server_fingerprint="sha256:operator-auth-test")
    proof = private_key.sign(
        pairing_challenge(offer.session_id, offer.one_time_secret),
        ec.ECDSA(hashes.SHA256()),
    )
    pending = services.devices.complete_pairing(
        session_id=offer.session_id,
        one_time_secret=offer.one_time_secret,
        public_key_pem=public_pem,
        approval_public_key_pem=public_pem,
        proof_signature_b64=base64.b64encode(proof).decode(),
        user_id="local-user",
        display_name="Security contract phone",
        app_version="0.1.0",
        os_version="Android contract",
        capabilities=("ptt",),
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        began = await client.post(
            "/api/v1/device-pairings",
            headers=INTENT_HEADERS,
            json={"server_fingerprint": "sha256:forbidden-without-operator"},
        )
        confirmed = await client.post(
            f"/api/v1/devices/{pending.id}/confirm",
            headers=INTENT_HEADERS,
            json={"comparison_code": offer.comparison_code},
        )
        revoked = await client.delete(
            f"/api/v1/devices/{pending.id}",
            headers=INTENT_HEADERS,
        )

    assert UUID(str(pending.id)) == pending.id
    assert began.status_code == 401
    assert confirmed.status_code == 401
    assert revoked.status_code == 401
    assert all(
        response.json() == {"detail": "desktop operator authorization required"}
        for response in (began, confirmed, revoked)
    )
