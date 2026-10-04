from __future__ import annotations

import os
from enum import StrEnum
from ipaddress import ip_address
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


class DeploymentMode(StrEnum):
    LOCAL_ONLY = "local-only"
    PRIVATE_REMOTE = "private-remote"
    HYBRID_GATEWAY = "hybrid-gateway"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KY_JARVIS_",
        case_sensitive=False,
        extra="forbid",
    )

    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1024, le=65535)
    timezone: str = "Asia/Taipei"
    locale: str = "zh-TW"
    deployment_mode: DeploymentMode = DeploymentMode.LOCAL_ONLY
    resource_profile: Literal["economy", "balanced", "performance"] = "balanced"
    ollama_base_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:11434")
    ollama_model: str | None = None
    local_model_provider: Literal["ollama", "colibri"] = "ollama"
    colibri_base_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8321")
    colibri_model: str | None = None
    stt_model: str = "small"
    voice_max_seconds: int = Field(default=30, ge=1, le=60)
    realtime_max_session_seconds: int = Field(default=600, ge=30, le=1800)
    realtime_max_concurrent_sessions: int = Field(default=1, ge=1, le=4)
    realtime_daily_soft_limit_units: int = Field(default=0, ge=0)
    realtime_daily_hard_limit_units: int = Field(default=0, ge=0)
    remote_tls_identity: str | None = None
    database_url: SecretStr | None = None
    operator_bootstrap_secret: SecretStr | None = None
    operator_credential_path: Path | None = None
    operator_rp_id: str = "localhost"
    operator_origin: str = "http://localhost:3000"
    operator_challenge_ttl_seconds: int = Field(default=120, ge=30, le=300)
    operator_grant_ttl_seconds: int = Field(default=90, ge=30, le=180)
    allowed_web_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:3000", "http://localhost:3000"]
    )

    enable_voice: bool = False
    enable_wake_word: bool = False
    enable_google_calendar: bool = False
    enable_gmail: bool = False
    enable_google_drive: bool = False
    enable_microsoft_graph: bool = False
    enable_plane: bool = False
    enable_n8n: bool = False
    enable_local_files: bool = False
    enable_windows_executor: bool = False
    enable_mem0_adapter: bool = False
    enable_cloud_ai: bool = False
    enable_lan_access: bool = False
    enable_android_app: bool = False
    enable_android_assistant_role: bool = False
    enable_openai_realtime: bool = False
    enable_remote_gateway: bool = False
    enable_push_notifications: bool = False
    enable_offline_command_queue: bool = False
    enable_device_key_attestation: bool = False

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        del settings_cls, dotenv_settings
        return env_settings, init_settings, file_secret_settings

    @model_validator(mode="after")
    def enforce_network_boundary(self) -> Settings:
        loopback_hosts = {"127.0.0.1", "localhost", "::1"}
        if self.host not in loopback_hosts and not self.enable_lan_access:
            raise ValueError("non-loopback binding requires KY_JARVIS_ENABLE_LAN_ACCESS=true")
        if self.deployment_mode is not DeploymentMode.LOCAL_ONLY and not self.enable_lan_access:
            raise ValueError("remote deployment modes require LAN access to be explicitly enabled")
        if self.deployment_mode is not DeploymentMode.LOCAL_ONLY:
            if not self.enable_remote_gateway:
                raise ValueError("remote deployment modes require the remote gateway flag")
            if not self.remote_tls_identity:
                raise ValueError("remote deployment modes require a TLS server identity")
        if self.enable_remote_gateway and self.deployment_mode is DeploymentMode.LOCAL_ONLY:
            raise ValueError("remote gateway cannot be enabled in local-only mode")
        if self.operator_origin.rstrip("/") not in {
            origin.rstrip("/") for origin in self.allowed_web_origins
        }:
            raise ValueError("operator origin must be an allowed web origin")
        operator_origin = urlsplit(self.operator_origin)
        operator_host = operator_origin.hostname
        if (
            operator_host is None
            or operator_origin.username is not None
            or operator_origin.password is not None
            or operator_origin.path not in {"", "/"}
            or operator_origin.query
            or operator_origin.fragment
        ):
            raise ValueError("operator origin must be an origin without credentials or path")
        if operator_origin.scheme != "https" and not (
            operator_origin.scheme == "http" and operator_host == "localhost"
        ):
            raise ValueError("operator WebAuthn origin requires HTTPS or HTTP localhost")
        try:
            ip_address(self.operator_rp_id)
        except ValueError:
            pass
        else:
            raise ValueError("operator WebAuthn RP ID cannot be an IP address")
        if operator_host != self.operator_rp_id and not operator_host.endswith(
            f".{self.operator_rp_id}"
        ):
            raise ValueError("operator RP ID must equal or suffix-match the operator origin")
        if (
            self.realtime_daily_hard_limit_units > 0
            and self.realtime_daily_soft_limit_units > self.realtime_daily_hard_limit_units
        ):
            raise ValueError("Realtime soft budget cannot exceed hard budget")
        return self

    def feature_flags(self) -> dict[str, bool]:
        return {
            name: value
            for name, value in self.model_dump().items()
            if name.startswith("enable_") and isinstance(value, bool)
        }


def default_user_config_path() -> Path | None:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    return Path(local_app_data) / "KY-JARVIS" / "config" / "app.yaml"


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"configuration must be a YAML mapping: {path}")
    return data


def load_settings(path: Path | None = None) -> Settings:
    selected_path = path or default_user_config_path()
    values = _read_yaml(selected_path) if selected_path and selected_path.is_file() else {}
    return Settings(**values)
