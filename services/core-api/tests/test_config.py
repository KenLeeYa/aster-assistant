from pathlib import Path

import pytest
from ky_jarvis_core.config import DeploymentMode, Settings, load_settings
from pydantic import ValidationError


def test_secure_feature_defaults_are_disabled() -> None:
    settings = Settings()

    assert settings.host == "127.0.0.1"
    assert settings.deployment_mode is DeploymentMode.LOCAL_ONLY
    assert settings.operator_rp_id == "localhost"
    assert settings.operator_origin == "http://localhost:3000"
    assert all(enabled is False for enabled in settings.feature_flags().values())


def test_non_loopback_binding_fails_closed_without_explicit_lan_flag() -> None:
    with pytest.raises(ValidationError, match="non-loopback binding"):
        Settings(host="0.0.0.0")  # noqa: S104 - verifies the fail-closed boundary


@pytest.mark.parametrize(
    ("rp_id", "origin", "expected_error"),
    [
        (
            "127.0.0.1",
            "http://127.0.0.1:3000",
            "operator WebAuthn origin requires HTTPS or HTTP localhost",
        ),
        (
            "tauri.localhost",
            "http://tauri.localhost",
            "operator WebAuthn origin requires HTTPS or HTTP localhost",
        ),
    ],
)
def test_operator_webauthn_rejects_insecure_non_localhost_origins(
    rp_id: str,
    origin: str,
    expected_error: str,
) -> None:
    with pytest.raises(ValidationError, match=expected_error):
        Settings(
            operator_rp_id=rp_id,
            operator_origin=origin,
            allowed_web_origins=[origin],
        )


def test_operator_webauthn_rejects_ip_rp_id_even_with_https() -> None:
    origin = "https://127.0.0.1"

    with pytest.raises(ValidationError, match="RP ID cannot be an IP address"):
        Settings(
            operator_rp_id="127.0.0.1",
            operator_origin=origin,
            allowed_web_origins=[origin],
        )


def test_operator_webauthn_accepts_https_rp_suffix() -> None:
    origin = "https://operator.example.test"

    settings = Settings(
        operator_rp_id="example.test",
        operator_origin=origin,
        allowed_web_origins=[origin],
    )

    assert settings.operator_origin == origin


def test_environment_overrides_yaml_without_loading_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file = tmp_path / "app.yaml"
    config_file.write_text("port: 9000\nenable_voice: true\n", encoding="utf-8")
    monkeypatch.setenv("KY_JARVIS_PORT", "8766")

    settings = load_settings(config_file)

    assert settings.port == 8766
    assert settings.enable_voice is True


@pytest.mark.parametrize(
    "relative_path",
    ["config/realtime.example.yaml", "config/remote_access.example.yaml"],
)
def test_documented_disabled_config_fragments_load(relative_path: str) -> None:
    repository_root = Path(__file__).resolve().parents[3]

    settings = load_settings(repository_root / relative_path)

    assert settings.deployment_mode is DeploymentMode.LOCAL_ONLY
    assert settings.realtime_daily_hard_limit_units == 0
    assert settings.enable_remote_gateway is False
