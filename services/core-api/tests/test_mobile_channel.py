from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from ky_jarvis_core.agents.providers import SequenceProvider
from ky_jarvis_core.config import Settings
from ky_jarvis_core.domain.devices import (
    DeviceSecurityService,
    MobileSessionTokens,
    approval_signature_payload,
    pairing_challenge,
)
from ky_jarvis_core.domain.mobile import MobileChannelService, MobileCommandState
from ky_jarvis_core.domain.voice import TranscriptState, VoiceTranscript
from ky_jarvis_core.main import create_app


def _pair_trusted_device(
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
    offer = service.begin_pairing(server_fingerprint="sha256:test", now=now)
    signature = private_key.sign(
        pairing_challenge(offer.session_id, offer.one_time_secret),
        ec.ECDSA(hashes.SHA256()),
    )
    device = service.complete_pairing(
        session_id=offer.session_id,
        one_time_secret=offer.one_time_secret,
        public_key_pem=public_pem,
        proof_signature_b64=base64.b64encode(signature).decode(),
        user_id="local-user",
        display_name="Test phone",
        app_version="0.1.0",
        os_version="Android 16",
        now=now,
    )
    return service.confirm_device(
        device.id,
        comparison_code=offer.comparison_code,
        now=now,
    )


def _pair_mobile_approval_device(
    service: DeviceSecurityService,
    now: datetime,
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
        display_name="Biometric contract phone",
        app_version="0.1.0",
        os_version="Android contract",
        capabilities=("biometric-approval",),
        now=now,
    )
    tokens = service.confirm_device(
        device.id,
        comparison_code=offer.comparison_code,
        now=now,
    )
    return private_key, tokens


def test_mobile_command_delivery_is_idempotent_and_acknowledged() -> None:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    device_id = UUID("00000000-0000-0000-0000-000000000001")
    channel = MobileChannelService()

    first = channel.enqueue(
        device_id=device_id,
        title="桌面訊息",
        body="請確認手機已收到。",
        idempotency_key="qa-command-1",
        correlation_id="qa-1",
        now=now,
    )
    duplicate = channel.enqueue(
        device_id=device_id,
        title="桌面訊息",
        body="請確認手機已收到。",
        idempotency_key="qa-command-1",
        correlation_id="qa-1",
        now=now + timedelta(seconds=1),
    )

    assert duplicate.id == first.id
    delivered = channel.pending(device_id=device_id, now=now + timedelta(seconds=2))
    assert delivered[0].state is MobileCommandState.DELIVERED
    acknowledged = channel.acknowledge(
        first.id,
        device_id=device_id,
        now=now + timedelta(seconds=3),
    )
    assert acknowledged.state is MobileCommandState.ACKNOWLEDGED
    assert channel.pending(device_id=device_id, now=now + timedelta(seconds=4)) == ()


def test_expired_mobile_command_is_not_delivered() -> None:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    device_id = UUID("00000000-0000-0000-0000-000000000001")
    channel = MobileChannelService(default_ttl=timedelta(seconds=1))
    command = channel.enqueue(
        device_id=device_id,
        title="過期訊息",
        body="不應顯示",
        idempotency_key="qa-expired",
        correlation_id="qa-expired",
        now=now,
    )

    assert channel.pending(device_id=device_id, now=now + timedelta(seconds=2)) == ()
    assert channel.get(command.id).state is MobileCommandState.EXPIRED


@pytest.mark.asyncio
async def test_authenticated_mobile_command_and_chat_round_trip() -> None:
    provider = SequenceProvider(
        [
            {
                "summary": "手機訊息已由本機模型處理。",
                "steps": ["保留在本機", "回傳結構化結果"],
                "requires_approval": False,
                "source_requirement_ids": [],
            }
        ]
    )
    app = create_app(Settings(), model_provider=provider)
    tokens = _pair_trusted_device(
        app.state.services.devices,
        datetime.now(UTC),
    )
    intent = {"X-KY-JARVIS-Intent": "ui-v1"}
    mobile = {
        **intent,
        "Authorization": f"Bearer {tokens.access_token}",
    }
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        queued = await client.post(
            "/api/v1/mobile/commands",
            headers=intent,
            json={
                "device_id": str(tokens.device_id),
                "title": "桌面測試",
                "body": "這是桌面傳給手機的訊息。",
                "idempotency_key": "api-qa-1",
            },
        )
        pending = await client.get(
            "/api/v1/mobile/commands/pending",
            headers=mobile,
        )
        command_id = queued.json()["id"]
        acknowledged = await client.post(
            f"/api/v1/mobile/commands/{command_id}/ack",
            headers=mobile,
            json={"receipt": "displayed"},
        )
        reply = await client.post(
            "/api/v1/mobile/messages",
            headers=mobile,
            json={"message": "請建立本機安全測試計畫", "thread_id": "phone-qa"},
        )

    assert queued.status_code == 200
    assert pending.status_code == 200
    assert pending.json()[0]["id"] == command_id
    assert acknowledged.json()["state"] == "acknowledged"
    assert reply.status_code == 200
    assert reply.json()["summary"] == "手機訊息已由本機模型處理。"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_mobile_endpoints_reject_missing_and_stale_device_tokens() -> None:
    stale_app = create_app(Settings())
    stale_tokens = _pair_trusted_device(
        stale_app.state.services.devices,
        datetime.now(UTC),
    )
    app = create_app(Settings())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        pending = await client.get("/api/v1/mobile/commands/pending")
        message = await client.post(
            "/api/v1/mobile/messages",
            headers={"X-KY-JARVIS-Intent": "ui-v1"},
            json={"message": "unauthenticated"},
        )
        stale_access = await client.get(
            "/api/v1/mobile/commands/pending",
            headers={"Authorization": f"Bearer {stale_tokens.access_token}"},
        )
        stale_refresh = await client.post(
            "/api/v1/mobile/sessions/refresh",
            headers={"X-KY-JARVIS-Intent": "ui-v1"},
            json={
                "family_id": str(stale_tokens.family_id),
                "refresh_token": stale_tokens.refresh_token,
            },
        )

    assert pending.status_code == 401
    assert message.status_code == 401
    assert stale_access.status_code == 401
    assert stale_refresh.status_code == 401
    assert stale_access.json() == {"detail": "invalid or expired device session"}
    assert stale_refresh.json() == {"detail": "invalid or expired device session"}


@pytest.mark.asyncio
async def test_mobile_workspace_and_signed_approval_contract() -> None:
    now = datetime.now(UTC)
    app = create_app(Settings())
    approval_key, tokens = _pair_mobile_approval_device(app.state.services.devices, now)
    transport = ASGITransport(app=app)
    intent = {"X-KY-JARVIS-Intent": "ui-v1"}
    mobile = {
        **intent,
        "Authorization": f"Bearer {tokens.access_token}",
    }
    execution = {
        "tool_name": "calendar.create.fake",
        "payload": {
            "title": "Mobile approval contract",
            "start": "2026-09-03T09:00:00+08:00",
            "end": "2026-09-03T10:00:00+08:00",
            "timezone": "Asia/Taipei",
        },
        "idempotency_key": "mobile-biometric-approval-1",
        "reason": "Verify the signed mobile approval path",
        "originating_request": "Create one fake event",
        "rollback_method": "Delete the fake event",
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        project = await client.post(
            "/api/v1/projects/preview",
            headers=intent,
            json={"request": "手機專案畫面", "source_message_id": "mobile-workspace-1"},
        )
        work_item_id = project.json()["work_items"][0]["id"]
        schedule = await client.post(
            "/api/v1/schedules/preview",
            headers=intent,
            json={
                "work_item_id": work_item_id,
                "duration_minutes": 60,
                "earliest": "2026-09-03T09:00:00+08:00",
                "deadline": "2026-09-03T18:00:00+08:00",
                "busy": [],
                "timezone": "Asia/Taipei",
            },
        )
        requested = await client.post(
            "/api/v1/tool-executions",
            headers=intent,
            json=execution,
        )
        projects = await client.get("/api/v1/mobile/projects", headers=mobile)
        agenda = await client.get("/api/v1/mobile/agenda", headers=mobile)
        listed = await client.get("/api/v1/mobile/approvals", headers=mobile)
        approval = listed.json()[0]
        signed_at = datetime.now(UTC)
        signature = approval_key.sign(
            approval_signature_payload(
                approval_id=UUID(approval["id"]),
                action_hash=approval["action_hash"],
                nonce=approval["nonce"],
                decision="approve",
                device_id=tokens.device_id,
                timestamp=signed_at,
            ),
            ec.ECDSA(hashes.SHA256()),
        )
        missing_biometric_signature = await client.post(
            f"/api/v1/mobile/approvals/{approval['id']}/decision",
            headers=mobile,
            json={"decision": "approve", "timestamp": signed_at.isoformat()},
        )
        decided = await client.post(
            f"/api/v1/mobile/approvals/{approval['id']}/decision",
            headers=mobile,
            json={
                "decision": "approve",
                "timestamp": signed_at.isoformat(),
                "signature_b64": base64.b64encode(signature).decode(),
            },
        )
        replayed_desktop_token = await client.post(
            f"/api/v1/tool-executions/{approval['id']}/resume",
            headers=intent,
            json={
                "token": requested.json()["decision_token"],
                "approved": True,
            },
        )

    assert project.status_code == 200
    assert schedule.status_code == 200
    assert projects.status_code == 200 and len(projects.json()) == 1
    assert agenda.status_code == 200 and len(agenda.json()) == 1
    assert listed.status_code == 200
    assert approval["action_hash"] and approval["nonce"]
    assert "token_hash" not in approval
    assert missing_biometric_signature.status_code == 422
    assert decided.status_code == 200
    assert decided.json()["approval"]["state"] == "consumed"
    assert decided.json()["result"]["untrusted_output"] is True
    assert replayed_desktop_token.status_code == 401


@pytest.mark.asyncio
async def test_mobile_voice_turn_promotes_final_transcript_to_same_agent_path() -> None:
    class FakeSttProvider:
        def transcribe(self, audio: bytes, *, locale: str) -> VoiceTranscript:
            assert len(audio) > 44
            return VoiceTranscript(
                voice_session_id=UUID("22222222-2222-2222-2222-222222222222"),
                provider="fake-stt",
                locale=locale,
                text="請回覆語音雙向測試",
                confidence=0.99,
                state=TranscriptState.FINAL,
                submitted=True,
            )

    provider = SequenceProvider(
        [
            {
                "summary": "語音已在本機完成轉錄與規劃。",
                "steps": ["手機錄音", "本機轉錄", "手機回覆"],
                "requires_approval": False,
                "source_requirement_ids": [],
            }
        ]
    )
    app = create_app(
        Settings(enable_voice=True),
        model_provider=provider,
        stt_provider=FakeSttProvider(),
    )
    tokens = _pair_trusted_device(app.state.services.devices, datetime.now(UTC))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/mobile/voice-turns",
            headers={
                "X-KY-JARVIS-Intent": "ui-v1",
                "Authorization": f"Bearer {tokens.access_token}",
                "Content-Type": "application/octet-stream",
                "X-Audio-Sample-Rate": "16000",
                "X-Audio-Locale": "zh-TW",
            },
            content=b"\x00\x00" * 1_600,
        )

    assert response.status_code == 200
    assert response.json()["transcript"]["text"] == "請回覆語音雙向測試"
    assert response.json()["reply"]["summary"] == "語音已在本機完成轉錄與規劃。"
