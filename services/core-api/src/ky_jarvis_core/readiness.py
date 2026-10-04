from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from ky_jarvis_core.config import Settings

Probe = Callable[[str], Awaitable[str]]


async def probe_database(database_url: str) -> str:
    def _probe() -> None:
        engine = create_engine(database_url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        finally:
            engine.dispose()

    try:
        await asyncio.wait_for(asyncio.to_thread(_probe), timeout=2.0)
    except (OSError, TimeoutError, RuntimeError, SQLAlchemyError):
        return "unavailable"
    return "pass"


async def probe_ollama(base_url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            response = await client.get(f"{base_url.rstrip('/')}/api/tags")
            response.raise_for_status()
    except httpx.HTTPError:
        return "unavailable"
    payload = response.json()
    models = payload.get("models", []) if isinstance(payload, dict) else []
    return "pass" if models else "available_no_models"


async def probe_colibri(base_url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            response = await client.get(f"{base_url.rstrip('/')}/v1/models")
            response.raise_for_status()
    except httpx.HTTPError:
        return "unavailable"
    try:
        body = response.json()
    except ValueError:
        return "invalid_response"
    return "pass" if isinstance(body, dict) else "invalid_response"


async def readiness_report(
    settings: Settings,
    *,
    database_probe: Probe = probe_database,
    ollama_probe: Probe = probe_ollama,
    colibri_probe: Probe = probe_colibri,
) -> dict[str, object]:
    if settings.database_url is None:
        database_status = "not_configured"
    else:
        database_status = await database_probe(settings.database_url.get_secret_value())
    if settings.local_model_provider == "colibri":
        model_status = await colibri_probe(str(settings.colibri_base_url))
    else:
        model_status = await ollama_probe(str(settings.ollama_base_url))
    ready = database_status == "pass"
    return {
        "status": "ok" if ready else "degraded",
        "ready": ready,
        "phase": "governed-core",
        "checks": {
            "configuration": "pass",
            "database": database_status,
            "ollama": model_status if settings.local_model_provider == "ollama" else "not_selected",
            "colibri": model_status
            if settings.local_model_provider == "colibri"
            else "not_selected",
        },
    }
