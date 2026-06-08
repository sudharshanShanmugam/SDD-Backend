"""SDD Platform – FastAPI application entry point."""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import sentry_sdk
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.exceptions import SDDBaseException
from app.core.logging import get_logger, setup_logging
from app.db.session import close_db_connections, close_redis_connections, get_engine

logger = get_logger(__name__)


# ── Sentry ────────────────────────────────────────────────────────────────────

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        release=settings.APP_VERSION,
    )


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle handler."""
    setup_logging()
    logger.info(
        "Starting SDD Platform",
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
    )

    # Create all tables directly from models (reliable for fresh deployments)
    engine = get_engine()
    from sqlalchemy import text as sa_text
    from app.db.base import Base
    import app.models  # noqa: F401 — registers all models with Base.metadata

    async with engine.begin() as conn:
        # Enable pgcrypto for gen_random_uuid()
        await conn.execute(sa_text('CREATE EXTENSION IF NOT EXISTS "pgcrypto"'))
        await conn.run_sync(Base.metadata.create_all)
        # Add columns introduced after initial deploy (idempotent)
        await conn.execute(sa_text("""
            ALTER TABLE tasks ADD COLUMN IF NOT EXISTS reporter_id UUID
                REFERENCES users(id) ON DELETE SET NULL;
        """))

    logger.info("Database schema created/verified")

    # Seed initial data in non-testing environments
    if not settings.is_testing:
        from app.db.session import AsyncSessionLocal
        from app.db.init_db import init_db

        async with AsyncSessionLocal() as session:
            await init_db(session)

    logger.info("SDD Platform started successfully")
    yield

    # Shutdown
    logger.info("Shutting down SDD Platform")
    await close_db_connections()
    await close_redis_connections()
    logger.info("Shutdown complete")


# ── Application factory ───────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="AI-powered Spec Driven Development Platform API",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── Custom middleware ─────────────────────────────────────────────────────
    # add_middleware inserts at index 0 each time, so the LAST call becomes
    # the outermost wrapper (runs first on requests, last on responses).
    # CORS must be outermost to intercept OPTIONS preflight before any other
    # middleware can reject it.
    from app.middleware.logging import RequestLoggingMiddleware
    from app.middleware.tenant import TenantMiddleware
    from app.middleware.rate_limit import RateLimitMiddleware
    from app.middleware.audit import AuditMiddleware

    app.add_middleware(AuditMiddleware)
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=settings.RATE_LIMIT_PER_MINUTE,
        requests_per_hour=settings.RATE_LIMIT_PER_HOUR,
        enabled=settings.RATE_LIMIT_ENABLED,
    )
    app.add_middleware(TenantMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # CORS last → outermost → runs first, handles OPTIONS before anything else
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-RateLimit-Limit-Minute", "X-RateLimit-Remaining-Minute"],
    )

    # ── Exception handlers ────────────────────────────────────────────────────
    @app.exception_handler(SDDBaseException)
    async def sdd_exception_handler(request: Request, exc: SDDBaseException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_dict(),
            headers=exc.headers or {},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = []
        for error in exc.errors():
            errors.append(
                {
                    "field": ".".join(str(loc) for loc in error.get("loc", [])),
                    "message": error.get("msg", ""),
                    "type": error.get("type", ""),
                }
            )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error_code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "detail": errors,
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception", exc_info=exc, path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error_code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
            },
        )

    # ── Health endpoints ──────────────────────────────────────────────────────
    @app.get("/health", tags=["System"], include_in_schema=True)
    async def health_check() -> dict:
        from sqlalchemy import text
        from app.db.session import AsyncSessionLocal, get_redis_pool
        import redis.asyncio as aioredis

        db_status = "ok"
        redis_status = "ok"

        try:
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            db_status = "error"

        try:
            pool = get_redis_pool()
            client = aioredis.Redis(connection_pool=pool)
            await client.ping()
            await client.aclose()
        except Exception:
            redis_status = "error"

        overall = "healthy" if db_status == "ok" and redis_status == "ok" else "degraded"
        return {
            "status": overall,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "database": db_status,
            "redis": redis_status,
        }

    @app.get("/health/ready", tags=["System"], include_in_schema=False)
    async def readiness() -> JSONResponse:
        from sqlalchemy import text
        from app.db.session import AsyncSessionLocal, get_redis_pool
        import redis.asyncio as aioredis

        checks: dict = {}
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {exc}"

        try:
            pool = get_redis_pool()
            r = aioredis.Redis(connection_pool=pool)
            await r.ping()
            await r.aclose()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error: {exc}"

        all_ok = all(v == "ok" for v in checks.values())
        return JSONResponse(
            status_code=200 if all_ok else 503,
            content={"status": "ready" if all_ok else "not_ready", "checks": checks},
        )

    # ── Include API router ────────────────────────────────────────────────────
    from app.api.router import api_router
    app.include_router(api_router)

    return app


# ── Application instance ──────────────────────────────────────────────────────

_fastapi_app = create_app()

# Wrap FastAPI with the Socket.IO ASGI app so that:
#   - /socket.io/* → handled by Socket.IO (WebSocket + HTTP polling)
#   - everything else → passed through to FastAPI
# The `app` name must stay at module level because uvicorn uses `app.main:app`.
import socketio as _socketio
from app.ws.socket import sio as _sio

app = _socketio.ASGIApp(_sio, other_asgi_app=_fastapi_app)
