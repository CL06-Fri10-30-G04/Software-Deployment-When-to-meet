import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import PurePath

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response
from starlette.types import Scope

from .api import ROUTERS
from .api.errors import register_exception_handlers
from .api.monitoring import MONITORING_PAGE
from .monitoring import RequestStats, RequestTimingMiddleware, SystemSampler
from .monitoring.azure import AzureMonitorConfig, AzureMonitorReader
from .paths import FRONTEND_DIR
from .telemetry import configure_telemetry, fastapi_telemetry_config


@dataclass
class Monitoring:
    requests: RequestStats
    sampler: SystemSampler
    azure: AzureMonitorReader


class FrontendFiles(StaticFiles):
    """The static frontend, minus pages that a route serves after a permission check."""

    def __init__(self, *, protected: set[str], **kwargs):
        super().__init__(**kwargs)
        self.protected = {name.lower() for name in protected}

    async def get_response(self, path: str, scope: Scope) -> Response:
        if PurePath(path).name.lower() in self.protected:
            raise HTTPException(status_code=404)
        return await super().get_response(path, scope)


def create_app(session_secret: str | None = None) -> FastAPI:
    secret = session_secret or os.getenv("SESSION_SECRET")
    if not secret:
        raise RuntimeError("SESSION_SECRET must be configured")

    monitoring = Monitoring(
        requests=RequestStats(),
        sampler=SystemSampler(),
        azure=AzureMonitorReader(AzureMonitorConfig.from_env()),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        monitoring.sampler.start()
        yield
        monitoring.sampler.stop()

    configure_telemetry()
    app = FastAPI(title="When to Meet", telemetry=fastapi_telemetry_config(), lifespan=lifespan)
    app.state.db = None
    app.state.monitoring = monitoring
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        session_cookie="session",
        same_site="lax",
        https_only=os.getenv("SESSION_COOKIE_SECURE", "false").lower() in {"true", "1"},
    )
    app.add_middleware(RequestTimingMiddleware, stats=monitoring.requests)
    register_exception_handlers(app)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    for router in ROUTERS:
        app.include_router(router)

    if FRONTEND_DIR.is_dir():
        app.mount(
            "/",
            FrontendFiles(directory=FRONTEND_DIR, html=True, protected={MONITORING_PAGE}),
            name="frontend",
        )
    return app
