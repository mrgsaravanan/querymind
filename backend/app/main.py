"""FastAPI application factory."""
from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import query as query_api
from app.config import Settings
from app.deps import Container, build_container, require_admin
from app.pipeline.orchestrator import LLMFactory

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, llm_factory: LLMFactory | None = None) -> FastAPI:
    container = build_container(settings, llm_factory)
    app = FastAPI(title="QueryMind AI", version="1.0.0")
    app.state.container = container
    app.add_middleware(CORSMiddleware, allow_origins=list(container.settings.cors_origins),
                       allow_origin_regex=container.settings.cors_origin_regex or None, allow_methods=["*"],
                       allow_headers=["*"])

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail), "detail": None})

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        # drop `ctx` (may hold exception objects) and `input` (echoes user data) so the body is always serialisable
        detail = [{k: v for k, v in e.items() if k not in ("ctx", "input")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": "Invalid request", "detail": detail})

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse(status_code=500, content={"error": "Internal server error", "detail": None})

    app.include_router(query_api.router)
    _mount_admin(app)

    @app.get("/health", tags=["health"])
    def health():
        c: Container = app.state.container
        checks: dict[str, str] = {}
        try:
            with c.business_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["business_db"] = "ok"
        except Exception:  # noqa: BLE001
            checks["business_db"] = "error"
        try:
            with c.admin_sessions() as s:
                s.execute(text("SELECT 1"))
            checks["admin_db"] = "ok"
        except Exception:  # noqa: BLE001
            checks["admin_db"] = "error"
        try:
            checks["vector_store"] = f"ok ({c.vector_store.count()} examples)"
        except Exception:  # noqa: BLE001
            checks["vector_store"] = "error"
        ok = all(v.startswith("ok") for v in checks.values())
        return JSONResponse(status_code=200 if ok else 503, content={"status": "ok" if ok else "degraded", "checks": checks})

    return app


def _mount_admin(app: FastAPI) -> None:
    """Admin routers are added in step 7."""
    try:
        from app.api.admin import router as admin_router
    except ImportError:
        return
    app.include_router(admin_router, prefix="/admin", dependencies=[Depends(require_admin)])


def app_factory() -> FastAPI:  # for `uvicorn app.main:app_factory --factory`
    return create_app()


def __getattr__(name: str):
    global app
    if name == "app":
        app = create_app()
        return app
    raise AttributeError(name)
