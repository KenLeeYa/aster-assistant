from __future__ import annotations

import io
import math
import wave
from importlib import import_module
from typing import Any
from uuid import uuid4

from ky_jarvis_core.domain.voice import TranscriptState, VoiceTranscript


def pcm16_mono_to_wav(audio: bytes, *, sample_rate: int) -> bytes:
    if sample_rate < 8_000 or sample_rate > 48_000:
        raise ValueError("unsupported audio sample rate")
    if not audio or len(audio) % 2:
        raise ValueError("PCM16 audio must contain complete samples")
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(audio)
    return output.getvalue()


class FasterWhisperSttProvider:
    """Lazy CPU INT8 transcription; raw audio remains memory-only."""

    def __init__(self, *, model_name: str = "small") -> None:
        self._model_name = model_name
        self._model: Any | None = None

    def transcribe(self, audio: bytes, *, locale: str) -> VoiceTranscript:
        if self._model is None:
            module = import_module("faster_whisper")
            model_type = module.WhisperModel
            self._model = model_type(
                self._model_name,
                device="cpu",
                compute_type="int8",
            )
        language = locale.split("-", maxsplit=1)[0].lower()
        segments, _ = self._model.transcribe(
            io.BytesIO(audio),
            language=language,
            beam_size=3,
            vad_filter=True,
        )
        text_parts: list[str] = []
        confidence_values: list[float] = []
        for segment in segments:
            text = str(segment.text).strip()
            if text:
                text_parts.append(text)
            confidence_values.append(max(0.0, min(1.0, math.exp(float(segment.avg_logprob)))))
        text = " ".join(text_parts).strip()
        confidence = sum(confidence_values) / len(confidence_values) if confidence_values else None
        return VoiceTranscript(
            voice_session_id=uuid4(),
            provider=f"faster-whisper:{self._model_name}",
            locale=locale,
            text=text,
            confidence=confidence,
            state=TranscriptState.FINAL if text else TranscriptState.ABANDONED,
            submitted=bool(text),
        )
