from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlparse

from pydantic import BaseModel

from ky_jarvis_core.domain.gateway import validate_external_url


class OAuthAuthorizationPreview(BaseModel):
    provider: str
    authorization_url: str
    state: str
    expires_at: datetime
    uses_pkce_s256: bool = True


class OAuthPkcePreviewAdapter:
    def __init__(
        self,
        *,
        provider: str,
        enabled: bool,
        client_id: str,
        authorization_endpoint: str,
        redirect_uri: str,
        scopes: tuple[str, ...],
    ) -> None:
        host = urlparse(authorization_endpoint).hostname
        if host is None:
            raise ValueError("OAuth authorization endpoint requires a host")
        self._authorization_endpoint = validate_external_url(
            authorization_endpoint,
            allowed_hosts=(host,),
        )
        parsed_redirect = urlparse(redirect_uri)
        if parsed_redirect.scheme != "http" or parsed_redirect.hostname not in {
            "127.0.0.1",
            "localhost",
        }:
            raise ValueError("OAuth desktop redirect must use loopback HTTP")
        self._provider = provider
        self._enabled = enabled
        self._client_id = client_id
        self._redirect_uri = redirect_uri
        self._scopes = scopes
        self._pending_verifiers: dict[str, tuple[str, datetime]] = {}

    def begin(self, *, now: datetime | None = None) -> OAuthAuthorizationPreview:
        if not self._enabled:
            raise RuntimeError("OAuth connector is disabled")
        if not self._client_id or self._client_id.startswith("replace-"):
            raise RuntimeError("OAuth public client ID is not configured")
        timestamp = now or datetime.now(UTC)
        state = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode()
        challenge = challenge.rstrip("=")
        expires_at = timestamp + timedelta(minutes=5)
        self._pending_verifiers[state] = (verifier, expires_at)
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                "response_type": "code",
                "scope": " ".join(self._scopes),
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "access_type": "offline",
                "prompt": "consent",
            }
        )
        return OAuthAuthorizationPreview(
            provider=self._provider,
            authorization_url=f"{self._authorization_endpoint}?{query}",
            state=state,
            expires_at=expires_at,
        )

    def consume_verifier(self, state: str, *, now: datetime | None = None) -> str:
        try:
            verifier, expires_at = self._pending_verifiers.pop(state)
        except KeyError as exc:
            raise ValueError("unknown or already consumed OAuth state") from exc
        if (now or datetime.now(UTC)) >= expires_at:
            raise ValueError("OAuth state expired")
        return verifier

    def exchange_code(self, code: str) -> None:
        del code
        raise RuntimeError("LIVE OAuth token exchange is not configured")
