"""НейроБокс — Database pool (asyncpg) with safe init, retry and tuning."""
import asyncio

import asyncpg
import structlog

log = structlog.get_logger()

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


async def get_pool() -> asyncpg.Pool:
    """Return the shared connection pool. Thread-safe (asyncio.Lock on first init)."""
    global _pool
    if _pool is not None and not _pool._closed:
        return _pool
    async with _pool_lock:
        if _pool is not None and not _pool._closed:
            return _pool
        from shared.config import settings
        dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        min_size = int(getattr(settings, "neurobox_db_min_size", 2) or 2)
        max_size = int(getattr(settings, "neurobox_db_max_size", 28) or 28)
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                _pool = await asyncpg.create_pool(
                    dsn,
                    min_size=min_size,
                    max_size=max_size,
                    max_inactive_connection_lifetime=300.0,
                    command_timeout=30.0,
                    statement_cache_size=100,
                )
                log.info("database_pool_created", min_size=min_size, max_size=max_size, attempt=attempt)
                return _pool
            except (asyncpg.PostgresError, OSError) as exc:
                log.warning("database_pool_connect_retry",
                            attempt=attempt, max_retries=max_retries, error=str(exc))
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
        raise RuntimeError("Failed to create database pool")


async def close_pool() -> None:
    global _pool
    if _pool and not _pool._closed:
        await _pool.close()
        log.info("database_pool_closed")
    _pool = None
