from __future__ import annotations

from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class TranscriptState(StrEnum):
    PARTIAL = "partial"
    FINAL = "final"
    ABANDONED = "abandoned"


class VoiceTranscript(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    voice_session_id: UUID
    device_id: UUID | None = None
    speaker: str = "user"
    provider: str
    locale: str = "zh-TW"
    text: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    state: TranscriptState
    source_kind: str = "speech"
    submitted: bool = False
    promoted_message_id: UUID | None = None


class SttProvider(Protocol):
    def transcribe(self, audio: bytes, *, locale: str) -> VoiceTranscript: ...


class TtsProvider(Protocol):
    def speak(self, text: str, *, locale: str) -> None: ...


class WakeWordProvider(Protocol):
    def detected(self, audio: bytes, *, sample_rate: int) -> bool: ...


class DisabledWakeWordAdapter:
    enabled = False

    def detected(self, audio: bytes, *, sample_rate: int) -> bool:
        del audio, sample_rate
        raise RuntimeError("wake-word adapter is disabled")


def promote_final_transcript(transcript: VoiceTranscript) -> VoiceTranscript:
    if transcript.state is not TranscriptState.FINAL:
        raise ValueError("only final transcripts can become user messages")
    if not transcript.submitted:
        raise ValueError("final transcript requires deliberate submission")
    if transcript.speaker != "user" or transcript.source_kind in {"wake_word", "vad_noise", "echo"}:
        raise ValueError("non-user or ephemeral audio cannot become a user message")
    return transcript.model_copy(update={"promoted_message_id": uuid4()})


def requires_visual_confirmation(transcript: VoiceTranscript) -> bool:
    sensitive_terms = {
        "刪除",
        "發布",
        "付款",
        "匯款",
        "密碼",
        "權限",
        "recipient",
        "delete",
        "publish",
    }
    low_confidence = transcript.confidence is not None and transcript.confidence < 0.85
    return low_confidence and any(term in transcript.text.casefold() for term in sensitive_terms)
