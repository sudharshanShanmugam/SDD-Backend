"""Async SQLAlchemy session factory and Redis pool."""
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_engine: Optional[AsyncEngine] = None
_redis_pool: Optional[aioredis.ConnectionPool] = None


def get_engine() -> AsyncEngine:
    """Return (or create) the singleton async SQLAlchemy engine."""
    global _engine
    if _engine is None:
        connect_args: dict = {}
        if "asyncpg" in settings.DATABASE_URL:
            connect_args = {
                "statement_cache_size": 0,   # required for Neon/PgBouncer pooling
                "prepared_statement_cache_size": 0,
                "server_settings": {
                    "application_name": settings.APP_NAME,
                    "jit": "off",
                }
            }

        kwargs: dict = {
            "echo": settings.DATABASE_ECHO,
            "pool_pre_ping": True,
            "connect_args": connect_args,
        }

        # Use NullPool during tests so connections are never reused across tests
        if settings.is_testing:
            kwargs["poolclass"] = NullPool
        else:
            kwargs.update(
                {
                    "pool_size": settings.DATABASE_POOL_SIZE,
                    "max_overflow": settings.DATABASE_MAX_OVERFLOW,
                    "pool_timeout": settings.DATABASE_POOL_TIMEOUT,
                    "pool_recycle": settings.DATABASE_POOL_RECYCLE,
                }
            )

        _engine = create_async_engine(settings.DATABASE_URL, **kwargs)
        logger.info(
            "Database engine created",
            url=settings.DATABASE_URL.split("@")[-1],  # omit credentials
            pool_size=settings.DATABASE_POOL_SIZE,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return a configured async session factory."""
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


# Module-level session factory used by dependency injection
AsyncSessionLocal: async_sessionmaker[AsyncSession] = get_session_factory()


def get_redis_pool() -> aioredis.ConnectionPool:
    """Return (or create) the singleton Redis connection pool."""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.ConnectionPool.from_url(
            settings.REDIS_URL,
            password=settings.REDIS_PASSWORD or None,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
            retry_on_timeout=True,
        )
        logger.info("Redis connection pool created", url=settings.REDIS_URL.split("@")[-1])
    return _redis_pool


async def close_db_connections() -> None:
    """Dispose the database engine (call during shutdown)."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        logger.info("Database connections closed")


async def close_redis_connections() -> None:
    """Disconnect Redis pool (call during shutdown)."""
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None
        logger.info("Redis connections closed")
