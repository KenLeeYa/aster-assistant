from __future__ import annotations

import pytest
from ky_jarvis_core.config import Settings
from ky_jarvis_core.readiness import readiness_report
from pydantic import SecretStr

pytestmark = pytest.mark.asyncio


async def _pass(_: str) -> str:
    return "pass"


async def _no_models(_: str) -> str:
    return "available_no_models"


async def test_readiness_requires_database_but_not_a_downloaded_model() -> None:
    settings = Settings(database_url=SecretStr("sqlite:///:memory:"))

    report = await readiness_report(
        settings,
        database_probe=_pass,
        ollama_probe=_no_models,
    )

    assert report["ready"] is True
    assert report["status"] == "ok"
    assert report["checks"] == {
        "configuration": "pass",
        "database": "pass",
        "ollama": "available_no_models",
        "colibri": "not_selected",
    }
