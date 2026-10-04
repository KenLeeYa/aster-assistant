from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from ky_jarvis_core.domain.endpoint_contracts import EndpointRequest
from pydantic import ValidationError


def valid_request() -> dict[str, object]:
    return {
        "request_id": uuid4(),
        "device_id": uuid4(),
        "capability": "display_notification",
        "action_hash": "a" * 64,
        "idempotency_key": "one-shot-1",
        "approval_id": uuid4(),
        "expires_at": datetime.now(UTC) + timedelta(minutes=1),
        "arguments": {"message": "Review complete"},
    }


def test_endpoint_request_is_narrow_and_time_bounded() -> None:
    assert EndpointRequest.model_validate(valid_request()).capability == "display_notification"
    for override in (
        {"capability": "run_shell"},
        {"arguments": {"shell": "echo unsafe"}},
        {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
        {"action_hash": "not-a-hash"},
    ):
        with pytest.raises(ValidationError):
            EndpointRequest.model_validate(valid_request() | override)
