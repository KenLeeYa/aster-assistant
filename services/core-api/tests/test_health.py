import pytest
from httpx import ASGITransport, AsyncClient
from ky_jarvis_core.config import Settings
from ky_jarvis_core.main import create_app

pytestmark = pytest.mark.asyncio


async def test_health_reports_version_and_correlation_id() -> None:
    transport = ASGITransport(app=create_app(Settings()))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health", headers={"X-Correlation-ID": "test-correlation"})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["version"] == "0.1.0"
    assert response.headers["X-Correlation-ID"] == "test-correlation"


async def test_readiness_is_honest_before_database_and_ollama_are_available() -> None:
    transport = ASGITransport(app=create_app(Settings()))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["ready"] is False
    assert response.json()["checks"]["database"] == "not_configured"
