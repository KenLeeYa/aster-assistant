from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

_PROTECTED_ACTIONS = (
    re.compile(r"^POST /api/v1/memories/[0-9a-fA-F-]{36}/approve$"),
    re.compile(r"^DELETE /api/v1/memories/[0-9a-fA-F-]{36}$"),
    re.compile(r"^POST /api/v1/tool-executions/[0-9a-fA-F-]{36}/resume$"),
    re.compile(r"^POST /api/v1/approvals/[0-9a-fA-F-]{36}/decision$"),
    re.compile(r"^POST /api/v1/device-pairings$"),
    re.compile(r"^POST /api/v1/devices/[0-9a-fA-F-]{36}/confirm$"),
    re.compile(r"^DELETE /api/v1/devices/[0-9a-fA-F-]{36}$"),
)
_MAX_CANONICAL_ACTION_BYTES = 64 * 1024
_MAX_PENDING_CHALLENGES = 32


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def operator_action_hash(*, method: str, path: str, body: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"body": body, "method": method.upper(), "path": path},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(canonical) > _MAX_CANONICAL_ACTION_BYTES:
        raise ValueError("desktop operator action exceeds size limit")
    return hashlib.sha256(canonical).hexdigest()


def require_protected_operator_action(*, method: str, path: str) -> None:
    action = f"{method.upper()} {path}"
    if not any(pattern.fullmatch(action) for pattern in _PROTECTED_ACTIONS):
        raise ValueError("unsupported desktop operator action")


@dataclass(frozen=True)
class OperatorCredential:
    credential_id: bytes
    credential_public_key: bytes
    sign_count: int
    user_id: bytes
    transports: tuple[str, ...]
    created_at: datetime
    device_type: str
    backed_up: bool


class OperatorCredentialStore(Protocol):
    def get(self) -> OperatorCredential | None: ...

    def save(self, credential: OperatorCredential) -> None: ...


class MemoryOperatorCredentialStore:
    def __init__(self) -> None:
        self._credential: OperatorCredential | None = None

    def get(self) -> OperatorCredential | None:
        return self._credential

    def save(self, credential: OperatorCredential) -> None:
        self._credential = credential


class FileOperatorCredentialStore:
    """Atomic store for public WebAuthn credential metadata outside the repository."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def get(self) -> OperatorCredential | None:
        if not self._path.is_file():
            return None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if data.get("schema_version") != 1:
                raise ValueError("unsupported schema")
            return OperatorCredential(
                credential_id=_b64url_decode(str(data["credential_id"])),
                credential_public_key=_b64url_decode(str(data["credential_public_key"])),
                sign_count=int(data["sign_count"]),
                user_id=_b64url_decode(str(data["user_id"])),
                transports=tuple(str(item) for item in data.get("transports", [])),
                created_at=datetime.fromisoformat(str(data["created_at"])),
                device_type=str(data["device_type"]),
                backed_up=bool(data["backed_up"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("desktop operator credential store is invalid") from exc

    def save(self, credential: OperatorCredential) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "credential_id": _b64url_encode(credential.credential_id),
            "credential_public_key": _b64url_encode(credential.credential_public_key),
            "sign_count": credential.sign_count,
            "user_id": _b64url_encode(credential.user_id),
            "transports": credential.transports,
            "created_at": credential.created_at.isoformat(),
            "device_type": credential.device_type,
            "backed_up": credential.backed_up,
        }
        temporary = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        temporary.replace(self._path)


@dataclass(frozen=True)
class OperatorGrant:
    action_hash: str
    actor: str
    expires_at: datetime


class OperatorGrantStore:
    """One-shot bearer grants bound to a canonical HTTP action hash."""

    def __init__(self, *, ttl: timedelta = timedelta(seconds=90)) -> None:
        self._ttl = ttl
        self._grants: dict[str, OperatorGrant] = {}
        self._lock = threading.RLock()

    def issue(
        self,
        action_hash: str,
        *,
        actor: str = "windows-hello:local-user",
        now: datetime | None = None,
    ) -> tuple[str, datetime]:
        current = now or datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expires_at = current + self._ttl
        with self._lock:
            self._grants = {
                key: grant for key, grant in self._grants.items() if grant.expires_at > current
            }
            self._grants[digest] = OperatorGrant(
                action_hash=action_hash,
                actor=actor,
                expires_at=expires_at,
            )
        return token, expires_at

    def consume(
        self,
        token: str | None,
        *,
        action_hash: str,
        now: datetime | None = None,
    ) -> str:
        if not token:
            raise PermissionError("desktop operator authorization required")
        current = now or datetime.now(UTC)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._lock:
            grant = self._grants.pop(digest, None)
        if grant is None:
            raise PermissionError("desktop operator authorization required")
        if grant.expires_at <= current or not secrets.compare_digest(
            grant.action_hash,
            action_hash,
        ):
            raise PermissionError("desktop operator authorization required")
        return grant.actor


@dataclass(frozen=True)
class _RegistrationChallenge:
    challenge: bytes
    user_id: bytes
    expires_at: datetime


@dataclass(frozen=True)
class _AuthenticationChallenge:
    challenge: bytes
    credential_id: bytes
    action_hash: str
    expires_at: datetime


class DesktopOperatorAuthorization:
    def __init__(
        self,
        *,
        credential_store: OperatorCredentialStore,
        rp_id: str,
        origin: str,
        bootstrap_secret: str | None,
        challenge_ttl: timedelta = timedelta(minutes=2),
        grant_ttl: timedelta = timedelta(seconds=90),
    ) -> None:
        self._credentials = credential_store
        self._rp_id = rp_id
        self._origin = origin.rstrip("/")
        self._bootstrap_secret = bootstrap_secret
        self._challenge_ttl = challenge_ttl
        self._registrations: dict[str, _RegistrationChallenge] = {}
        self._authentications: dict[str, _AuthenticationChallenge] = {}
        self._lock = threading.RLock()
        self.grants = OperatorGrantStore(ttl=grant_ttl)

    def status(self) -> dict[str, Any]:
        credential = self._credentials.get()
        return {
            "configured": self._bootstrap_secret is not None,
            "registered": credential is not None,
            "authenticator": "platform",
            "user_verification": "required",
            "grant_mode": "single-action",
        }

    def begin_registration(
        self,
        bootstrap_secret: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now(UTC)
        expected = self._bootstrap_secret
        if expected is None or not secrets.compare_digest(bootstrap_secret, expected):
            raise PermissionError("invalid operator enrollment secret")
        if self._credentials.get() is not None:
            raise ValueError("desktop operator is already registered")
        challenge = secrets.token_bytes(32)
        user_id = secrets.token_bytes(32)
        challenge_id = secrets.token_urlsafe(24)
        options = generate_registration_options(
            rp_id=self._rp_id,
            rp_name="KY-JARVIS Desktop",
            user_name="local-user",
            user_id=user_id,
            user_display_name="KY-JARVIS local operator",
            challenge=challenge,
            timeout=int(self._challenge_ttl.total_seconds() * 1000),
            authenticator_selection=AuthenticatorSelectionCriteria(
                authenticator_attachment=AuthenticatorAttachment.PLATFORM,
                resident_key=ResidentKeyRequirement.REQUIRED,
                require_resident_key=True,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
        )
        with self._lock:
            self._registrations = {
                key: value
                for key, value in self._registrations.items()
                if value.expires_at > current
            }
            while len(self._registrations) >= _MAX_PENDING_CHALLENGES:
                self._registrations.pop(next(iter(self._registrations)))
            self._registrations[challenge_id] = _RegistrationChallenge(
                challenge=challenge,
                user_id=user_id,
                expires_at=current + self._challenge_ttl,
            )
        return {"challenge_id": challenge_id, "options": json.loads(options_to_json(options))}

    def finish_registration(
        self,
        challenge_id: str,
        credential: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now(UTC)
        with self._lock:
            registration = self._registrations.pop(challenge_id, None)
        if registration is None or registration.expires_at <= current:
            raise PermissionError("registration challenge is invalid or expired")
        if self._credentials.get() is not None:
            raise ValueError("desktop operator is already registered")
        try:
            verified = verify_registration_response(
                credential=credential,
                expected_challenge=registration.challenge,
                expected_rp_id=self._rp_id,
                expected_origin=self._origin,
                require_user_verification=True,
            )
        except Exception as exc:
            raise PermissionError("Windows Hello registration failed") from exc
        response = credential.get("response")
        raw_transports = response.get("transports", []) if isinstance(response, dict) else []
        transports = tuple(
            item
            for item in raw_transports
            if isinstance(item, str)
            and item in {transport.value for transport in AuthenticatorTransport}
        )
        stored = OperatorCredential(
            credential_id=verified.credential_id,
            credential_public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            user_id=registration.user_id,
            transports=transports,
            created_at=current,
            device_type=verified.credential_device_type.value,
            backed_up=verified.credential_backed_up,
        )
        with self._lock:
            if self._credentials.get() is not None:
                raise ValueError("desktop operator is already registered")
            self._credentials.save(stored)
            self._bootstrap_secret = None
        return self.status()

    def begin_authentication(
        self,
        *,
        method: str,
        path: str,
        body: dict[str, Any],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        require_protected_operator_action(method=method, path=path)
        current = now or datetime.now(UTC)
        credential = self._credentials.get()
        if credential is None:
            raise PermissionError("desktop operator is not registered")
        challenge = secrets.token_bytes(32)
        challenge_id = secrets.token_urlsafe(24)
        transports = [AuthenticatorTransport(item) for item in credential.transports]
        options = generate_authentication_options(
            rp_id=self._rp_id,
            challenge=challenge,
            timeout=int(self._challenge_ttl.total_seconds() * 1000),
            allow_credentials=[
                PublicKeyCredentialDescriptor(
                    id=credential.credential_id,
                    transports=transports or None,
                )
            ],
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        with self._lock:
            self._authentications = {
                key: value
                for key, value in self._authentications.items()
                if value.expires_at > current
            }
            while len(self._authentications) >= _MAX_PENDING_CHALLENGES:
                self._authentications.pop(next(iter(self._authentications)))
            self._authentications[challenge_id] = _AuthenticationChallenge(
                challenge=challenge,
                credential_id=credential.credential_id,
                action_hash=operator_action_hash(method=method, path=path, body=body),
                expires_at=current + self._challenge_ttl,
            )
        return {"challenge_id": challenge_id, "options": json.loads(options_to_json(options))}

    def finish_authentication(
        self,
        challenge_id: str,
        credential_response: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now(UTC)
        with self._lock:
            authentication = self._authentications.pop(challenge_id, None)
        if authentication is None or authentication.expires_at <= current:
            raise PermissionError("authentication challenge is invalid or expired")
        credential = self._credentials.get()
        if credential is None or not secrets.compare_digest(
            credential.credential_id,
            authentication.credential_id,
        ):
            raise PermissionError("desktop operator credential changed")
        try:
            verified = verify_authentication_response(
                credential=credential_response,
                expected_challenge=authentication.challenge,
                expected_rp_id=self._rp_id,
                expected_origin=self._origin,
                credential_public_key=credential.credential_public_key,
                credential_current_sign_count=credential.sign_count,
                require_user_verification=True,
            )
        except Exception as exc:
            raise PermissionError("Windows Hello verification failed") from exc
        if not secrets.compare_digest(verified.credential_id, credential.credential_id):
            raise PermissionError("desktop operator credential mismatch")
        self._credentials.save(
            OperatorCredential(
                credential_id=credential.credential_id,
                credential_public_key=credential.credential_public_key,
                sign_count=verified.new_sign_count,
                user_id=credential.user_id,
                transports=credential.transports,
                created_at=credential.created_at,
                device_type=verified.credential_device_type.value,
                backed_up=verified.credential_backed_up,
            )
        )
        token, expires_at = self.grants.issue(authentication.action_hash, now=current)
        return {
            "grant_token": token,
            "expires_at": expires_at.isoformat(),
            "action_hash": authentication.action_hash,
        }

    def authorize(
        self,
        grant_token: str | None,
        *,
        method: str,
        path: str,
        body: dict[str, Any],
        now: datetime | None = None,
    ) -> str:
        require_protected_operator_action(method=method, path=path)
        return self.grants.consume(
            grant_token,
            action_hash=operator_action_hash(method=method, path=path, body=body),
            now=now,
        )
