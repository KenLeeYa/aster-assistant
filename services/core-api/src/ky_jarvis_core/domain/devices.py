from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from collections.abc import MutableMapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import BaseModel, Field


class DeviceTrustState(StrEnum):
    PENDING = "pending"
    TRUSTED = "trusted"
    LIMITED = "limited"
    REVOKED = "revoked"
    COMPROMISED = "compromised"


class PairingSession(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    secret_hash: str
    comparison_code: str
    server_fingerprint: str
    expires_at: datetime
    consumed_at: datetime | None = None
    tokens_claimed_at: datetime | None = None
    device_id: UUID | None = None


class PairingOffer(BaseModel):
    session_id: UUID
    one_time_secret: str
    comparison_code: str
    server_fingerprint: str
    expires_at: datetime


class DeviceRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str
    display_name: str
    platform: str = "android"
    app_version: str
    os_version: str
    public_key_algorithm: str = "P-256"
    public_key_pem: str
    approval_public_key_pem: str | None = None
    trust_state: DeviceTrustState = DeviceTrustState.PENDING
    capabilities: tuple[str, ...] = ()
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RefreshTokenFamily(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    device_id: UUID
    current_token_hash: str
    used_token_hashes: tuple[str, ...] = ()
    generation: int = 0
    expires_at: datetime
    revoked_at: datetime | None = None


class MobileSessionTokens(BaseModel):
    device_id: UUID
    family_id: UUID
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime


def pairing_challenge(session_id: UUID, secret: str) -> bytes:
    return f"ky-jarvis-pairing-v1:{session_id}:{secret}".encode()


def token_claim_challenge(session_id: UUID, secret: str) -> bytes:
    return f"ky-jarvis-token-claim-v1:{session_id}:{secret}".encode()


def approval_signature_payload(
    *,
    approval_id: UUID,
    action_hash: str,
    nonce: str,
    decision: str,
    device_id: UUID,
    timestamp: datetime,
) -> bytes:
    return (
        f"ky-jarvis-approval-v1:{approval_id}:{action_hash}:{nonce}:"
        f"{decision}:{device_id}:{timestamp.isoformat()}"
    ).encode()


class DeviceSecurityService:
    def __init__(
        self,
        *,
        token_pepper: bytes | None = None,
        devices: MutableMapping[UUID, DeviceRecord] | None = None,
    ) -> None:
        self._pepper = token_pepper or secrets.token_bytes(32)
        self._pairings: dict[UUID, PairingSession] = {}
        self._devices: MutableMapping[UUID, DeviceRecord] = devices if devices is not None else {}
        self._families: dict[UUID, RefreshTokenFamily] = {}
        self._access_token_hashes: dict[str, tuple[UUID, datetime]] = {}
        self._pending_pairing_tokens: dict[UUID, MobileSessionTokens] = {}

    def begin_pairing(
        self,
        *,
        server_fingerprint: str,
        ttl: timedelta = timedelta(minutes=5),
        now: datetime | None = None,
    ) -> PairingOffer:
        timestamp = now or datetime.now(UTC)
        secret = secrets.token_urlsafe(32)
        session_id = uuid4()
        comparison_code = str(
            int.from_bytes(hashlib.sha256(pairing_challenge(session_id, secret)).digest()[:4])
            % 1_000_000
        ).zfill(6)
        session = PairingSession(
            id=session_id,
            secret_hash=self._token_hash(secret),
            comparison_code=comparison_code,
            server_fingerprint=server_fingerprint,
            expires_at=timestamp + ttl,
        )
        self._pairings[session.id] = session
        return PairingOffer(
            session_id=session.id,
            one_time_secret=secret,
            comparison_code=comparison_code,
            server_fingerprint=server_fingerprint,
            expires_at=session.expires_at,
        )

    def complete_pairing(
        self,
        *,
        session_id: UUID,
        one_time_secret: str,
        public_key_pem: str,
        approval_public_key_pem: str | None = None,
        proof_signature_b64: str,
        user_id: str,
        display_name: str,
        app_version: str,
        os_version: str,
        capabilities: tuple[str, ...] = (),
        now: datetime | None = None,
    ) -> DeviceRecord:
        timestamp = now or datetime.now(UTC)
        session = self._pairings[session_id]
        if session.consumed_at is not None:
            raise ValueError("pairing session already consumed")
        if timestamp >= session.expires_at:
            raise ValueError("pairing session expired")
        if not hmac.compare_digest(session.secret_hash, self._token_hash(one_time_secret)):
            raise ValueError("invalid pairing secret")
        public_key = self._load_p256_public_key(public_key_pem)
        if approval_public_key_pem is not None:
            self._load_p256_public_key(approval_public_key_pem)
        try:
            public_key.verify(
                base64.b64decode(proof_signature_b64, validate=True),
                pairing_challenge(session_id, one_time_secret),
                ec.ECDSA(hashes.SHA256()),
            )
        except (InvalidSignature, ValueError) as exc:
            raise ValueError("device proof verification failed") from exc

        device = DeviceRecord(
            user_id=user_id,
            display_name=display_name,
            app_version=app_version,
            os_version=os_version,
            public_key_pem=public_key_pem,
            approval_public_key_pem=approval_public_key_pem,
            capabilities=capabilities,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._devices[device.id] = device
        self._pairings[session_id] = session.model_copy(
            update={"consumed_at": timestamp, "device_id": device.id}
        )
        return device

    def confirm_device(
        self,
        device_id: UUID,
        *,
        comparison_code: str,
        now: datetime | None = None,
    ) -> MobileSessionTokens:
        timestamp = now or datetime.now(UTC)
        device = self.get_device(device_id)
        if device.trust_state is not DeviceTrustState.PENDING:
            raise ValueError("only a pending device can be confirmed")
        pairing = next(
            (item for item in self._pairings.values() if item.device_id == device_id),
            None,
        )
        if pairing is None or not hmac.compare_digest(pairing.comparison_code, comparison_code):
            raise ValueError("pairing comparison code mismatch")
        self._devices[device_id] = device.model_copy(
            update={
                "trust_state": DeviceTrustState.TRUSTED,
                "updated_at": timestamp,
                "last_seen_at": timestamp,
            }
        )
        tokens = self._new_token_family(device_id, now=timestamp)
        self._pending_pairing_tokens[pairing.id] = tokens
        return tokens

    def claim_pairing_tokens(
        self,
        session_id: UUID,
        *,
        one_time_secret: str,
        proof_signature_b64: str,
        now: datetime | None = None,
    ) -> MobileSessionTokens:
        timestamp = now or datetime.now(UTC)
        pairing = self._pairings[session_id]
        if pairing.device_id is None or pairing.consumed_at is None:
            raise ValueError("pairing has not been completed")
        if pairing.tokens_claimed_at is not None:
            raise ValueError("pairing tokens already claimed")
        if not hmac.compare_digest(pairing.secret_hash, self._token_hash(one_time_secret)):
            raise ValueError("invalid pairing secret")
        tokens = self._pending_pairing_tokens.get(session_id)
        if tokens is None:
            raise ValueError("device confirmation pending")
        if timestamp >= tokens.access_expires_at:
            self._pending_pairing_tokens.pop(session_id, None)
            raise ValueError("pairing token claim expired")
        self.verify_device_signature(
            pairing.device_id,
            token_claim_challenge(session_id, one_time_secret),
            proof_signature_b64,
        )
        self._pending_pairing_tokens.pop(session_id)
        self._pairings[session_id] = pairing.model_copy(update={"tokens_claimed_at": timestamp})
        return tokens

    def rotate_refresh_token(
        self,
        family_id: UUID,
        refresh_token: str,
        *,
        now: datetime | None = None,
    ) -> MobileSessionTokens:
        timestamp = now or datetime.now(UTC)
        family = self._families[family_id]
        device = self.get_device(family.device_id)
        if family.revoked_at is not None or device.trust_state is not DeviceTrustState.TRUSTED:
            raise ValueError("refresh-token family revoked")
        supplied_hash = self._token_hash(refresh_token)
        if supplied_hash in family.used_token_hashes:
            self._revoke_family_and_device(family_id, timestamp, compromised=True)
            raise ValueError("refresh-token reuse detected")
        if not hmac.compare_digest(supplied_hash, family.current_token_hash):
            raise ValueError("invalid refresh token")
        if timestamp >= family.expires_at:
            self._revoke_family_and_device(family_id, timestamp)
            raise ValueError("refresh token expired")

        new_refresh = secrets.token_urlsafe(48)
        updated = family.model_copy(
            update={
                "current_token_hash": self._token_hash(new_refresh),
                "used_token_hashes": (*family.used_token_hashes, family.current_token_hash),
                "generation": family.generation + 1,
            }
        )
        self._families[family_id] = updated
        access, access_expiry = self._new_access_token(device.id, timestamp)
        return MobileSessionTokens(
            device_id=device.id,
            family_id=family_id,
            access_token=access,
            access_expires_at=access_expiry,
            refresh_token=new_refresh,
            refresh_expires_at=updated.expires_at,
        )

    def revoke_device(self, device_id: UUID, *, now: datetime | None = None) -> DeviceRecord:
        timestamp = now or datetime.now(UTC)
        device = self.get_device(device_id)
        revoked = device.model_copy(
            update={
                "trust_state": DeviceTrustState.REVOKED,
                "revoked_at": timestamp,
                "updated_at": timestamp,
            }
        )
        self._devices[device_id] = revoked
        for family_id, family in tuple(self._families.items()):
            if family.device_id == device_id and family.revoked_at is None:
                self._families[family_id] = family.model_copy(update={"revoked_at": timestamp})
        for token_hash, (token_device_id, _) in tuple(self._access_token_hashes.items()):
            if token_device_id == device_id:
                del self._access_token_hashes[token_hash]
        for session_id, pairing in tuple(self._pairings.items()):
            if pairing.device_id == device_id:
                self._pending_pairing_tokens.pop(session_id, None)
        return revoked

    def verify_device_signature(self, device_id: UUID, payload: bytes, signature_b64: str) -> None:
        device = self.get_device(device_id)
        if device.trust_state is not DeviceTrustState.TRUSTED:
            raise ValueError("device is not trusted")
        self._verify_signature(device.public_key_pem, payload, signature_b64)

    def verify_approval_signature(
        self,
        device_id: UUID,
        payload: bytes,
        signature_b64: str,
    ) -> None:
        device = self.get_device(device_id)
        if device.trust_state is not DeviceTrustState.TRUSTED:
            raise ValueError("device is not trusted")
        if device.approval_public_key_pem is None:
            raise ValueError("device has no biometric approval key")
        self._verify_signature(device.approval_public_key_pem, payload, signature_b64)

    def _verify_signature(
        self,
        public_key_pem: str,
        payload: bytes,
        signature_b64: str,
    ) -> None:
        public_key = self._load_p256_public_key(public_key_pem)
        try:
            public_key.verify(
                base64.b64decode(signature_b64, validate=True),
                payload,
                ec.ECDSA(hashes.SHA256()),
            )
        except (InvalidSignature, ValueError) as exc:
            raise ValueError("device signature verification failed") from exc

    def authenticate_access_token(
        self,
        access_token: str,
        *,
        now: datetime | None = None,
    ) -> DeviceRecord:
        timestamp = now or datetime.now(UTC)
        token_hash = self._token_hash(access_token)
        token_record = self._access_token_hashes.get(token_hash)
        if token_record is None:
            raise ValueError("invalid access token")
        device_id, expires_at = token_record
        device = self.get_device(device_id)
        if timestamp >= expires_at or device.trust_state is not DeviceTrustState.TRUSTED:
            self._access_token_hashes.pop(token_hash, None)
            raise ValueError("access token expired or device revoked")
        return device

    def list_devices(self) -> tuple[DeviceRecord, ...]:
        return tuple(sorted(self._devices.values(), key=lambda item: item.created_at))

    def mark_seen(
        self,
        device_id: UUID,
        *,
        now: datetime | None = None,
    ) -> DeviceRecord:
        timestamp = now or datetime.now(UTC)
        device = self.get_device(device_id)
        if device.trust_state is not DeviceTrustState.TRUSTED:
            raise ValueError("device is not trusted")
        updated = device.model_copy(update={"last_seen_at": timestamp, "updated_at": timestamp})
        self._devices[device_id] = updated
        return updated

    def get_device(self, device_id: UUID) -> DeviceRecord:
        return self._devices[device_id]

    def get_family(self, family_id: UUID) -> RefreshTokenFamily:
        return self._families[family_id]

    def pairing_session(self, session_id: UUID) -> PairingSession:
        return self._pairings[session_id]

    def _new_token_family(self, device_id: UUID, *, now: datetime) -> MobileSessionTokens:
        refresh_token = secrets.token_urlsafe(48)
        refresh_expiry = now + timedelta(days=30)
        family = RefreshTokenFamily(
            device_id=device_id,
            current_token_hash=self._token_hash(refresh_token),
            expires_at=refresh_expiry,
        )
        self._families[family.id] = family
        access_token, access_expiry = self._new_access_token(device_id, now)
        return MobileSessionTokens(
            device_id=device_id,
            family_id=family.id,
            access_token=access_token,
            access_expires_at=access_expiry,
            refresh_token=refresh_token,
            refresh_expires_at=refresh_expiry,
        )

    def _new_access_token(self, device_id: UUID, now: datetime) -> tuple[str, datetime]:
        access_token = secrets.token_urlsafe(32)
        expiry = now + timedelta(minutes=10)
        self._access_token_hashes[self._token_hash(access_token)] = (device_id, expiry)
        return access_token, expiry

    def _revoke_family_and_device(
        self,
        family_id: UUID,
        timestamp: datetime,
        *,
        compromised: bool = False,
    ) -> None:
        family = self._families[family_id]
        self._families[family_id] = family.model_copy(update={"revoked_at": timestamp})
        device = self.get_device(family.device_id)
        state = DeviceTrustState.COMPROMISED if compromised else DeviceTrustState.REVOKED
        self._devices[device.id] = device.model_copy(
            update={"trust_state": state, "revoked_at": timestamp, "updated_at": timestamp}
        )

    def _token_hash(self, token: str) -> str:
        return hmac.new(self._pepper, token.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _load_p256_public_key(public_key_pem: str) -> ec.EllipticCurvePublicKey:
        key = serialization.load_pem_public_key(public_key_pem.encode())
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
            key.curve,
            ec.SECP256R1,  # gitleaks:allow -- curve class, not a credential
        ):
            raise ValueError("device key must be P-256")
        return key
