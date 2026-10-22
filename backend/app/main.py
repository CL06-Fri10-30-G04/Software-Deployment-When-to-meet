import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .api import ROUTERS
from .api.errors import register_exception_handlers

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"


def create_app(session_secret: str | None = None) -> FastAPI:
    secret = session_secret or os.getenv("SESSION_SECRET")
    if not secret:
        raise RuntimeError("SESSION_SECRET must be configured")

    app = FastAPI(title="When to Meet")
    app.state.db = None
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        session_cookie="session",
        same_site="lax",
        https_only=os.getenv("SESSION_COOKIE_SECURE", "false").lower() in {"true", "1"},
    )
    register_exception_handlers(app)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    for router in ROUTERS:
        app.include_router(router)

    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app
