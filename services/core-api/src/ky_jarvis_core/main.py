from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ky_jarvis_core import __version__
from ky_jarvis_core.api.router import ApplicationServices, create_router
from ky_jarvis_core.config import Settings, load_settings
from ky_jarvis_core.logging import configure_logging
from ky_jarvis_core.readiness import readiness_report

if TYPE_CHECKING:
    from ky_jarvis_core.agents.providers import StructuredModelProvider
    from ky_jarvis_core.domain.voice import SttProvider

configure_logging()
logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    model_provider: StructuredModelProvider | None = None,
    stt_provider: SttProvider | None = None,
) -> FastAPI:
    app_settings = settings or load_settings()
    os.environ.pop("KY_JARVIS_OPERATOR_BOOTSTRAP_SECRET", None)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            application.state.services.close()

    app = FastAPI(
        title="KY-JARVIS Core API",
        version=__version__,
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.services = ApplicationServices(
        app_settings,
        model_provider=model_provider,
        stt_provider=stt_provider,
    )
    app_settings.operator_bootstrap_secret = None
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.allowed_web_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Correlation-ID",
            "X-KY-JARVIS-Intent",
            "X-KY-JARVIS-Operator-Grant",
        ],
    )

    @app.middleware("http")
    async def mutation_guard(request: Request, call_next: Any) -> Response:
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("Origin")
            if origin is not None and origin not in app_settings.allowed_web_origins:
                return JSONResponse(status_code=403, content={"detail": "origin denied"})
            if request.headers.get("X-KY-JARVIS-Intent") != "ui-v1":
                return JSONResponse(
                    status_code=403,
                    content={"detail": "explicit UI intent header required"},
                )
        response: Response = await call_next(request)
        return response

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next: Any) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid4())
        response: Response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        logger.info(
            "request_completed method=%s path=%s status=%s",
            request.method,
            request.url.path,
            response.status_code,
            extra={"correlation_id": correlation_id},
        )
        return response

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": "core-api",
            "version": __version__,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    @app.get("/ready", tags=["system"])
    async def ready() -> dict[str, object]:
        return await readiness_report(app_settings)

    @app.get("/version", tags=["system"])
    async def version() -> dict[str, object]:
        return {
            "application": "KY-JARVIS",
            "version": __version__,
            "api_version": "v1alpha1",
            "build_commit": os.environ.get("KY_JARVIS_BUILD_COMMIT", "development"),
        }

    app.include_router(create_router(app.state.services))

    return app


app = create_app()
