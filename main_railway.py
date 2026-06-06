"""
Minimal Railway-compatible entry point.
Skips heavy startup (MCP registry, market scrapers, background workers)
to get the API healthy on Railway quickly.
Full startup is in app/main.py — use that for local Docker.
"""
import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from app.core.config import get_settings
from app.core.exceptions import RentalRevenueException
from app.services.observability.slo_metrics import (
    get_slo_thresholds,
    observe_http_request,
    render_metrics,
)

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Minimal startup — just DB pool and essential services."""
    logger.info("Oyvoda API starting (Railway mode)...")

    # Initialize database connection pool
    try:
        from app.core.database import init_database
        await init_database()
        logger.info("Database pool initialized")
    except Exception as e:
        logger.error(f"Database init failed: {e}")

    # Initialize session manager
    try:
        from app.services.concierge.guest_session import init_session_manager
        await init_session_manager()
        logger.info("Session manager initialized")
    except Exception as e:
        logger.warning(f"Session manager init failed (non-fatal): {e}")

    # Load pending escalations
    try:
        from app.services.concierge.escalation_service import get_escalation_service
        esc_svc = get_escalation_service()
        esc_loaded = await esc_svc.load_pending_from_db()
        logger.info(f"Escalation service: loaded {esc_loaded} pending tickets")
    except Exception as e:
        logger.warning(f"Escalation service init failed (non-fatal): {e}")

    logger.info("Oyvoda API startup complete")
    yield

    # Shutdown
    try:
        from app.core.database import close_database
        await close_database()
    except Exception:
        pass


app = FastAPI(
    title="Oyvoda API",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def slo_metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception:
        observe_http_request(
            path=request.url.path,
            method=request.method,
            status_code=500,
            duration_s=time.perf_counter() - start,
        )
        raise
    observe_http_request(
        path=request.url.path,
        method=request.method,
        status_code=status_code,
        duration_s=time.perf_counter() - start,
    )
    return response


@app.exception_handler(RentalRevenueException)
async def rental_revenue_exception_handler(request: Request, exc: RentalRevenueException):
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict())


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": str(exc)}}
    )


# Mount API routers
from app.api.v1 import router as api_v1_router
from app.api.v1.endpoints.operator_dashboard import router as operator_dashboard_router
from app.api.v1.endpoints.landing import router as landing_router
from app.api.v1.endpoints.operator_onboarding import router as onboarding_ui_router

app.include_router(api_v1_router, prefix=settings.api_v1_prefix)
app.include_router(operator_dashboard_router)
app.include_router(landing_router)
app.include_router(onboarding_ui_router)

# Static files
import os as _os
_static_dir = _os.path.join(_os.path.dirname(__file__), "app", "static")
_os.makedirs(_os.path.join(_static_dir, "dashboard"), exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": settings.app_version,
        "environment": settings.environment,
        "focus_concierge_only": settings.focus_concierge_only,
        "strict_startup_checks": settings.strict_startup_checks,
        "slo_thresholds": get_slo_thresholds(),
    }


@app.get("/metrics")
async def metrics():
    payload, content_type = render_metrics()
    return Response(content=payload, media_type=content_type)


@app.get("/api")
async def api_root():
    return {"service": "Oyvoda API", "version": settings.app_version, "docs": "/docs"}
