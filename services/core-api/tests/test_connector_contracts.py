from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest
from ky_jarvis_core.integrations.adapters import PlaneWorkItemPreview
from ky_jarvis_core.integrations.oauth import OAuthPkcePreviewAdapter
from ky_jarvis_core.integrations.plane import PlaneContractAdapter


def test_google_oauth_preview_uses_pkce_state_and_one_time_verifier() -> None:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    adapter = OAuthPkcePreviewAdapter(
        provider="google-calendar",
        enabled=True,
        client_id="fixture-public-client",
        authorization_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        redirect_uri="http://127.0.0.1:8765/oauth/google/callback",
        scopes=("openid", "https://www.googleapis.com/auth/calendar.events"),
    )

    preview = adapter.begin(now=now)
    query = parse_qs(urlparse(preview.authorization_url).query)

    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == [preview.state]
    assert "client_secret" not in query
    assert adapter.consume_verifier(preview.state, now=now + timedelta(minutes=1))
    with pytest.raises(ValueError, match="already consumed"):
        adapter.consume_verifier(preview.state, now=now + timedelta(minutes=2))
    with pytest.raises(RuntimeError, match="not configured"):
        adapter.exchange_code("fixture-code")


def test_google_oauth_preview_is_disabled_without_manual_activation() -> None:
    adapter = OAuthPkcePreviewAdapter(
        provider="google-calendar",
        enabled=False,
        client_id="replace-with-client-id",
        authorization_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        redirect_uri="http://127.0.0.1:8765/oauth/google/callback",
        scopes=("openid",),
    )

    with pytest.raises(RuntimeError, match="disabled"):
        adapter.begin()


def test_plane_contract_uses_fake_server_approval_and_idempotency() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/api/v1/work-items"
        assert request.headers["Idempotency-Key"] == "plane-contract-1"
        assert json.loads(request.content)["source_requirement_ids"]
        return httpx.Response(201, json={"id": "fake-plane-item-1"})

    adapter = PlaneContractAdapter(
        base_url="https://plane.test",
        enabled=True,
        transport=httpx.MockTransport(handler),
    )
    preview = PlaneWorkItemPreview(
        id=uuid4(),
        title="Contract fixture",
        description="No LIVE provider",
        source_requirement_ids=(uuid4(),),
    )

    with pytest.raises(PermissionError, match="approval"):
        adapter.create(preview, approved=False, idempotency_key="plane-contract-1")
    first = adapter.create(preview, approved=True, idempotency_key="plane-contract-1")
    second = adapter.create(preview, approved=True, idempotency_key="plane-contract-1")

    assert first.external_id == "fake-plane-item-1"
    assert second == first
    assert calls == 1


def test_plane_contract_rejects_redirect_from_fake_server() -> None:
    adapter = PlaneContractAdapter(
        base_url="https://plane.test",
        enabled=True,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(302, headers={"Location": "https://evil.test"})
        ),
    )
    preview = PlaneWorkItemPreview(
        id=uuid4(),
        title="Redirect fixture",
        description="No redirect",
        source_requirement_ids=(uuid4(),),
    )

    with pytest.raises(ValueError, match="redirects"):
        adapter.create(preview, approved=True, idempotency_key="plane-redirect-1")
