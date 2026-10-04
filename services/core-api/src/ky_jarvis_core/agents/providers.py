from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Protocol

import httpx


class StructuredModelProvider(Protocol):
    async def generate(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, object],
    ) -> Mapping[str, object]: ...


class OllamaUnavailableError(RuntimeError):
    """Raised when the configured local Ollama service or model is unavailable."""


class ColibriGatewayProvider:
    """Optional local gateway adapter; never assumes gateway schema enforcement."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise ValueError("Colibri gateway must use explicit local loopback")
        if not model or timeout_seconds <= 0:
            raise ValueError("model and positive timeout are required")
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def generate(
        self, *, system: str, user: str, schema: Mapping[str, object]
    ) -> Mapping[str, object]:
        payload: dict[str, object] = {
            "model": self._model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": dict(schema)},
            },
        }
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post("/v1/chat/completions", json=payload)
                response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            result = json.loads(content)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise OllamaUnavailableError("local Colibri gateway response failed") from exc
        if not isinstance(result, dict):
            raise OllamaUnavailableError("local Colibri gateway returned no JSON object")
        # The LangGraph specialist validates against its Pydantic result model.
        return result


class OllamaProvider:
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model: str,
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def generate(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, object],
    ) -> Mapping[str, object]:
        compatible_schema = _ollama_compatible_schema(dict(schema))
        if not isinstance(compatible_schema, dict):
            raise ValueError("Ollama schema must be an object")
        payload: dict[str, object] = {
            "model": self._model,
            "stream": False,
            "format": compatible_schema,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": 0},
        }
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post("/api/chat", json=payload)
                response.raise_for_status()
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise OllamaUnavailableError("local Ollama request failed") from exc

        body = response.json()
        if not isinstance(body, dict):
            raise OllamaUnavailableError("Ollama response was not an object")
        message = body.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise OllamaUnavailableError("Ollama response did not contain message content")
        try:
            parsed = httpx.Response(200, content=message["content"]).json()
        except ValueError as exc:
            raise OllamaUnavailableError("Ollama returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise OllamaUnavailableError("Ollama structured output was not an object")
        return parsed


def _ollama_compatible_schema(value: object) -> object:
    """Remove bounds rejected by Ollama's grammar compiler; Pydantic still enforces them."""

    unsupported_bounds = {"minLength", "maxLength", "minItems", "maxItems"}
    if isinstance(value, Mapping):
        return {
            str(key): _ollama_compatible_schema(item)
            for key, item in value.items()
            if str(key) not in unsupported_bounds
        }
    if isinstance(value, list):
        return [_ollama_compatible_schema(item) for item in value]
    return value


class SequenceProvider:
    """Deterministic provider used by contract tests and offline demonstrations."""

    def __init__(self, responses: Sequence[Mapping[str, object]]) -> None:
        if not responses:
            raise ValueError("at least one response is required")
        self._responses = list(responses)
        self.calls = 0

    async def generate(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, object],
    ) -> Mapping[str, object]:
        del system, user, schema
        index = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        return self._responses[index]
