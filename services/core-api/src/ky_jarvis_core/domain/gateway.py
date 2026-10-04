from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

from ky_jarvis_core.domain.policy import RiskLevel, classify_permission


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,63}$")
    description: str = Field(max_length=500)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    connector: str
    risk_level: RiskLevel
    required_permissions: tuple[str, ...] = ()
    requires_approval: bool
    supports_dry_run: bool
    idempotency_strategy: str
    timeout_seconds: int = Field(default=15, ge=1, le=120)
    max_response_bytes: int = Field(default=262_144, ge=1, le=1_048_576)
    allowed_hosts: tuple[str, ...] = ()
    side_effects: tuple[str, ...] = ()


class ToolResult(BaseModel):
    tool_name: str
    result: dict[str, Any]
    idempotent_replay: bool = False
    untrusted_output: bool = True


def validate_external_url(url: str, *, allowed_hosts: tuple[str, ...]) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("external tool URLs require plain https origins")
    host = parsed.hostname.casefold().rstrip(".")
    if host not in {item.casefold().rstrip(".") for item in allowed_hosts}:
        raise ValueError("host is not allowlisted")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return url
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise ValueError("private or special-use destination denied")
    return url


def validate_redirect_chain(
    urls: tuple[str, ...], *, allowed_hosts: tuple[str, ...]
) -> tuple[str, ...]:
    if not urls or len(urls) > 5:
        raise ValueError("redirect chain must contain between one and five URLs")
    validated = tuple(validate_external_url(url, allowed_hosts=allowed_hosts) for url in urls)
    origins = {
        (urlparse(url).scheme, urlparse(url).hostname, urlparse(url).port or 443)
        for url in validated
    }
    if len(origins) != 1:
        raise ValueError("cross-origin redirects are denied")
    return validated


def _sanitize_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        raise ValueError("tool result nesting exceeds declared limit")
    if isinstance(value, str):
        return "".join(
            character if character in {"\n", "\t"} or ord(character) >= 32 else "�"
            for character in value
        )
    if isinstance(value, list):
        return [_sanitize_value(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("tool result keys must be strings")
            clean_key = _sanitize_value(key, depth=depth + 1)[:128]
            if clean_key in sanitized:
                raise ValueError("tool result keys collide after sanitization")
            sanitized[clean_key] = _sanitize_value(item, depth=depth + 1)
        return sanitized
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise ValueError("tool result contains a non-JSON value")


class TypedToolGateway:
    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        self._idempotency: dict[tuple[str, str], tuple[str, ToolResult]] = {}

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._definitions.values())

    def definition(self, name: str) -> ToolDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {**definition.model_dump(mode="json"), "metadata_trust": "untrusted_metadata"}
            for definition in self.definitions
        ]

    def validate_payload(self, name: str, payload: dict[str, Any]) -> None:
        definition = self.definition(name)
        if not Draft202012Validator(definition.input_schema).is_valid(payload):
            raise ValueError("tool input does not match its declared schema")

    def register(
        self,
        definition: ToolDefinition,
        handler: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        policy = classify_permission(
            definition.risk_level,
            external_write=definition.connector != "internal",
        )
        if policy.requires_approval and not definition.requires_approval:
            raise ValueError("tool definition weakens the central approval policy")
        Draft202012Validator.check_schema(definition.input_schema)
        Draft202012Validator.check_schema(definition.output_schema)
        self._definitions[definition.name] = definition
        self._handlers[definition.name] = handler

    def execute(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
        approved: bool = False,
    ) -> ToolResult:
        definition = self.definition(name)
        self.validate_payload(name, payload)
        if definition.requires_approval and not approved:
            raise PermissionError("scoped approval required")
        payload_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        cache_key = (name, idempotency_key)
        if cache_key in self._idempotency:
            stored_hash, stored_result = self._idempotency[cache_key]
            if not hmac.compare_digest(stored_hash, payload_hash):
                raise ValueError("idempotency key was reused with different input")
            return stored_result.model_copy(update={"idempotent_replay": True})
        raw_result = self._handlers[name](payload)
        sanitized_result = _sanitize_value(raw_result)
        if not isinstance(sanitized_result, dict):
            raise ValueError("tool response must be an object")
        Draft202012Validator(definition.output_schema).validate(sanitized_result)
        encoded = json.dumps(sanitized_result, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) > definition.max_response_bytes:
            raise ValueError("tool response exceeds declared limit")
        result = ToolResult(tool_name=name, result=sanitized_result)
        self._idempotency[cache_key] = (payload_hash, result)
        return result


def build_reference_gateway() -> TypedToolGateway:
    gateway = TypedToolGateway()
    gateway.register(
        ToolDefinition(
            name="calendar.create.fake",
            description="Create an event only inside the credential-free fake Calendar server.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1, "maxLength": 120},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "timezone": {"type": "string", "minLength": 1, "maxLength": 80},
                },
                "required": ["title", "start", "end", "timezone"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "timezone": {"type": "string"},
                    "external_id": {"type": "string"},
                    "provider": {"const": "fake-calendar"},
                },
                "required": [
                    "id",
                    "title",
                    "start",
                    "end",
                    "timezone",
                    "external_id",
                    "provider",
                ],
                "additionalProperties": False,
            },
            connector="fake-google-calendar",
            risk_level=RiskLevel.R2_CREATE_REVERSIBLE,
            required_permissions=("calendar.write",),
            requires_approval=True,
            supports_dry_run=True,
            idempotency_strategy="caller-key",
            side_effects=("fake provider event creation",),
        ),
        lambda payload: {
            "id": str(uuid4()),
            "title": payload["title"],
            "start": payload["start"],
            "end": payload["end"],
            "timezone": payload["timezone"],
            "external_id": f"fake-event-{uuid4()}",
            "provider": "fake-calendar",
        },
    )
    gateway.register(
        ToolDefinition(
            name="plane.work-item.create.fake",
            description="Create a work item only inside the credential-free fake Plane server.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1, "maxLength": 120},
                    "description": {"type": "string", "maxLength": 4_000},
                    "source_requirement_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 100,
                    },
                },
                "required": ["title", "description", "source_requirement_ids"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "external_id": {"type": "string"},
                    "provider": {"const": "fake-plane"},
                },
                "required": ["id", "title", "external_id", "provider"],
                "additionalProperties": False,
            },
            connector="fake-plane",
            risk_level=RiskLevel.R2_CREATE_REVERSIBLE,
            required_permissions=("project.write",),
            requires_approval=True,
            supports_dry_run=True,
            idempotency_strategy="caller-key",
            side_effects=("fake provider work-item creation",),
        ),
        lambda payload: {
            "id": str(uuid4()),
            "title": payload["title"],
            "external_id": f"fake-plane-{uuid4()}",
            "provider": "fake-plane",
        },
    )
    return gateway
