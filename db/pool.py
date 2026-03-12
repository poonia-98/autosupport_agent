from typing import Optional

import asyncpg

from core.config import get_settings
from core.logging import get_logger

logger = get_logger("db.pool")

_pool: Optional[asyncpg.Pool] = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    settings = get_settings()
    _pool = await asyncpg.create_pool(
        dsn=settings.asyncpg_dsn,
        min_size=2,
        max_size=20,
        command_timeout=30,
        server_settings={"application_name": "autosupport-api"},
    )
    logger.info("db.pool_ready", min_size=2, max_size=20)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("db.pool_closed")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised. Call init_pool() first.")
    return _pool


async def init_worker_pool() -> asyncpg.Pool:
    """Separate pool for ARQ worker processes."""
    global _pool
    settings = get_settings()
    _pool = await asyncpg.create_pool(
        dsn=settings.asyncpg_dsn,
        min_size=1,
        max_size=5,
        command_timeout=60,
        server_settings={"application_name": "autosupport-worker"},
    )
    return _pool
