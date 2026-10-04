from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import httpx

from ky_jarvis_core.domain.gateway import validate_external_url
from ky_jarvis_core.integrations.adapters import PlaneWorkItemPreview


class PlaneContractAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        enabled: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        host = urlparse(base_url).hostname
        if host is None:
            raise ValueError("Plane base URL requires a host")
        validated = validate_external_url(base_url.rstrip("/"), allowed_hosts=(host,))
        self._base_url = validated
        self._enabled = enabled
        self._transport = transport
        self._idempotency: dict[str, PlaneWorkItemPreview] = {}

    def create(
        self,
        preview: PlaneWorkItemPreview,
        *,
        approved: bool,
        idempotency_key: str,
    ) -> PlaneWorkItemPreview:
        if not self._enabled:
            raise RuntimeError("Plane contract adapter is disabled")
        if not approved:
            raise PermissionError("Plane write requires approval")
        existing = self._idempotency.get(idempotency_key)
        if existing is not None:
            return existing
        payload = {
            "title": preview.title,
            "description": preview.description,
            "source_requirement_ids": [str(item) for item in preview.source_requirement_ids],
        }
        with httpx.Client(
            base_url=self._base_url,
            transport=self._transport,
            follow_redirects=False,
            timeout=10,
        ) as client:
            response = client.post(
                "/api/v1/work-items",
                headers={"Idempotency-Key": idempotency_key},
                json=payload,
            )
        if 300 <= response.status_code < 400:
            raise ValueError("Plane redirects are denied")
        response.raise_for_status()
        if len(response.content) > 262_144:
            raise ValueError("Plane response exceeds contract limit")
        body: Any = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("id"), str):
            raise ValueError("Plane response does not match the fake-server contract")
        encoded = json.dumps(body, ensure_ascii=False).encode()
        if len(encoded) > 262_144:
            raise ValueError("Plane response exceeds contract limit")
        created = preview.model_copy(update={"external_id": body["id"]})
        self._idempotency[idempotency_key] = created
        return created
