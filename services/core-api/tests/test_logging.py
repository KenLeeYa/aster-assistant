from ky_jarvis_core.logging import redact_text


def test_redacts_common_secret_shapes() -> None:
    source = "Authorization: Bearer token.value and api_key=super-secret sk-abcdefghijklmnop"

    result = redact_text(source)

    assert "token.value" not in result
    assert "super-secret" not in result
    assert "sk-abcdefghijklmnop" not in result
    assert result.count("[REDACTED]") == 3
