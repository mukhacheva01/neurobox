"""НейроБокс — Redis store: singleton connection, task queue, rate limiting, KV cache."""
import asyncio
import contextlib
import json

import structlog

from shared.config import settings

log = structlog.get_logger()

_redis = None
_redis_lock = asyncio.Lock()
QUEUE_KEY = "neurobox:tasks"


async def _get_redis():
    """Return shared Redis client. Safe for concurrent first-call (asyncio.Lock)."""
    global _redis
    if _redis is not None:
        try:
            await _redis.ping()
            return _redis
        except Exception:
            _redis = None
    async with _redis_lock:
        if _redis is not None:
            return _redis
        try:
            from redis.asyncio import Redis
            _redis = Redis.from_url(
                settings.redis_url,
                decode_responses=False,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
                max_connections=20,
            )
            await _redis.ping()
            log.info("redis_connected")
            return _redis
        except Exception as e:
            log.warning("redis_connect_failed", error=str(e))
            _redis = None
            return None


async def close_redis() -> None:
    """Graceful shutdown of Redis connection."""
    global _redis
    if _redis:
        try:
            await _redis.aclose()
        except Exception:
            pass
        _redis = None


# ── Lock для тяжёлых операций (один запрос на пользователя, защита от двойного списания) ──

@contextlib.asynccontextmanager
async def gen_lock(user_id: int, key_prefix: str = "gen_lock", ttl_sec: int = 120):
    """Захват блокировки по user_id. Если Redis недоступен — yield True (пропускаем)."""
    r = await _get_redis()
    lock_key = f"{key_prefix}:{user_id}"
    acquired = False
    if r:
        try:
            acquired = await r.set(lock_key, b"1", nx=True, ex=ttl_sec)
        except Exception:
            pass
    try:
        yield acquired
    finally:
        if r and acquired:
            try:
                await r.delete(lock_key)
            except Exception:
                pass


# ── KV helpers ──

async def set_upscale_url(chat_id: int, message_id: int, image_url: str, ttl_sec: int = 3600) -> bool:
    r = await _get_redis()
    if not r:
        return False
    try:
        await r.set(f"upscale:{chat_id}:{message_id}", image_url, ex=ttl_sec)
        return True
    except Exception:
        return False


async def get_upscale_url(chat_id: int, message_id: int) -> str | None:
    r = await _get_redis()
    if not r:
        return None
    try:
        val = await r.get(f"upscale:{chat_id}:{message_id}")
        return val.decode() if val else None
    except Exception:
        return None


# ── Task queue ──

async def push_task(task: dict) -> bool:
    r = await _get_redis()
    if not r:
        return False
    try:
        await r.rpush(QUEUE_KEY, json.dumps(task, ensure_ascii=False))
        return True
    except Exception:
        return False


# ── Rate limiter (atomic INCR + EXPIRE in pipeline) ──

RATE_WINDOW_SEC = 60
RATE_MAX_PER_WINDOW = 45


async def rate_limit_check_and_incr(user_id: int) -> bool:
    """Check rate limit AND increment in one call. Returns True if OVER limit."""
    r = await _get_redis()
    if not r:
        return False
    try:
        key = f"neurobox:rate:{user_id}"
        pipe = r.pipeline(transaction=True)
        pipe.incr(key)
        pipe.expire(key, RATE_WINDOW_SEC)
        results = await pipe.execute()
        count = results[0]
        return count > RATE_MAX_PER_WINDOW
    except Exception:
        return False


async def rate_limit_is_over(user_id: int) -> bool:
    """Check if rate limit exceeded (read-only). Fallback-compatible."""
    r = await _get_redis()
    if not r:
        return False
    try:
        n_raw = await r.get(f"neurobox:rate:{user_id}")
        return int(n_raw) >= RATE_MAX_PER_WINDOW if n_raw else False
    except Exception:
        return False


async def rate_limit_incr(user_id: int) -> None:
    """Increment rate counter. Fallback-compatible."""
    r = await _get_redis()
    if not r:
        return
    try:
        key = f"neurobox:rate:{user_id}"
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, RATE_WINDOW_SEC)
    except Exception:
        pass
