from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest
from ky_jarvis_core.agents.providers import SequenceProvider
from ky_jarvis_core.agents.supervisor import AgentRunService, build_supervisor
from ky_jarvis_core.config import Settings
from ky_jarvis_core.domain.voice import (
    DisabledWakeWordAdapter,
    TranscriptState,
    VoiceTranscript,
)
from ky_jarvis_core.main import create_app


def _valid_plan() -> dict[str, object]:
    return {
        "summary": "桌面語音測試完成",
        "steps": ["轉錄", "產生結構化回覆"],
        "requires_approval": False,
        "source_requirement_ids": [],
    }


class FixtureSttProvider:
    def transcribe(self, audio: bytes, *, locale: str) -> VoiceTranscript:
        assert audio.startswith(b"RIFF")
        return VoiceTranscript(
            voice_session_id=uuid4(),
            provider="fixture-stt",
            locale=locale,
            text="請建立安全測試計畫",
            confidence=0.95,
            state=TranscriptState.FINAL,
            submitted=True,
        )


class ConcurrencyProvider:
    def __init__(self) -> None:
        self.active = 0
        self.maximum_active = 0
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, object],
    ) -> dict[str, object]:
        del system, user, schema
        self.calls += 1
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        self.entered.set()
        await self.release.wait()
        self.active -= 1
        return _valid_plan()


@pytest.mark.asyncio
async def test_desktop_voice_turn_uses_explicit_pcm_and_final_transcript() -> None:
    app = create_app(
        Settings(),
        model_provider=SequenceProvider([_valid_plan()]),
        stt_provider=FixtureSttProvider(),
    )
    transport = httpx.ASGITransport(app=app)
    headers = {
        "X-KY-JARVIS-Intent": "ui-v1",
        "Content-Type": "application/octet-stream",
        "X-Audio-Sample-Rate": "16000",
        "X-Audio-Locale": "zh-TW",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/voice-turns",
            headers=headers,
            content=b"\x00\x00" * 800,
        )

    assert response.status_code == 200
    assert response.json()["transcript"]["text"] == "請建立安全測試計畫"
    assert response.json()["reply"]["summary"] == "桌面語音測試完成"


@pytest.mark.asyncio
async def test_desktop_voice_turn_stops_reading_after_stream_limit() -> None:
    app = create_app(
        Settings(voice_max_seconds=1),
        model_provider=SequenceProvider([_valid_plan()]),
        stt_provider=FixtureSttProvider(),
    )
    transport = httpx.ASGITransport(app=app)
    consumed_late_chunk = False

    async def oversized_pcm() -> AsyncIterator[bytes]:
        nonlocal consumed_late_chunk
        yield b"\x00\x00" * 8_000
        yield b"\x00\x00"
        consumed_late_chunk = True
        yield b"must-not-be-consumed"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/voice-turns",
            headers={
                "Content-Type": "application/octet-stream",
                "X-Audio-Sample-Rate": "8000",
                "X-KY-JARVIS-Intent": "ui-v1",
            },
            content=oversized_pcm(),
        )

    assert response.status_code == 413
    assert consumed_late_chunk is False


@pytest.mark.asyncio
async def test_text_remains_usable_when_desktop_voice_is_disabled() -> None:
    app = create_app(Settings(), model_provider=SequenceProvider([_valid_plan()]))
    transport = httpx.ASGITransport(app=app)
    headers = {"X-KY-JARVIS-Intent": "ui-v1"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        voice = await client.post(
            "/api/v1/voice-turns",
            headers={**headers, "Content-Type": "application/octet-stream"},
            content=b"\x00\x00" * 100,
        )
        text = await client.post(
            "/api/v1/chat",
            headers=headers,
            json={"message": "文字仍可用", "thread_id": "text-fallback"},
        )

    assert voice.status_code == 503
    assert text.status_code == 200


@pytest.mark.asyncio
async def test_agent_run_semaphore_limits_model_concurrency() -> None:
    provider = ConcurrencyProvider()
    service = AgentRunService(build_supervisor(provider), max_concurrent_runs=1)
    first = asyncio.create_task(service.run("first", thread_id="voice-1"))
    second = asyncio.create_task(service.run("second", thread_id="voice-2"))
    await asyncio.wait_for(provider.entered.wait(), timeout=1)
    await asyncio.sleep(0.05)

    assert provider.calls == 1
    provider.release.set()
    states = await asyncio.gather(first, second)

    assert all(state["status"] == "completed" for state in states)
    assert provider.maximum_active == 1


def test_wake_word_adapter_is_explicitly_disabled() -> None:
    adapter = DisabledWakeWordAdapter()

    assert adapter.enabled is False
    with pytest.raises(RuntimeError, match="disabled"):
        adapter.detected(b"\x00\x00", sample_rate=16_000)
