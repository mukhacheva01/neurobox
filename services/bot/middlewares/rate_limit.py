"""Rate limit: max N messages/callbacks per minute per user. Redis (atomic) with in-memory fallback."""
import time
from collections import deque

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

WINDOW_SEC = 60
MAX_PER_WINDOW = 45
_CLEANUP_INTERVAL = 300

# In-memory fallback: {user_id: deque[timestamps]}
_rate: dict[int, deque] = {}
_last_full_cleanup = 0.0


def _check_and_record_memory(user_id: int) -> bool:
    """Returns True if OVER limit. Records hit if under."""
    global _last_full_cleanup
    now = time.monotonic()

    # Periodic full cleanup
    if now - _last_full_cleanup > _CLEANUP_INTERVAL:
        _last_full_cleanup = now
        cutoff = now - WINDOW_SEC
        stale = [uid for uid, dq in _rate.items() if not dq or dq[-1] < cutoff]
        for uid in stale:
            del _rate[uid]

    dq = _rate.get(user_id)
    if dq is None:
        dq = deque(maxlen=MAX_PER_WINDOW + 10)
        _rate[user_id] = dq

    cutoff = now - WINDOW_SEC
    while dq and dq[0] < cutoff:
        dq.popleft()

    if len(dq) >= MAX_PER_WINDOW:
        return True
    dq.append(now)
    return False


async def _send_rate_limit_warning(event) -> None:
    """Send rate-limit warning to user."""
    try:
        if isinstance(event, Message):
            await event.answer("⏳ Слишком много запросов. Подожди около минуты.")
        elif isinstance(event, CallbackQuery):
            await event.answer("⏳ Подожди минуту.", show_alert=True)
    except Exception:
        pass


class RateLimitMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user_id = None
        if isinstance(event, (Message, CallbackQuery)) and event.from_user:
            user_id = event.from_user.id
        if not user_id:
            return await handler(event, data)

        from shared.domain.credits import _is_admin_user
        if _is_admin_user(user_id):
            return await handler(event, data)

        # Try Redis atomic check+incr (single round-trip)
        try:
            from shared.redis.store import rate_limit_check_and_incr
            over = await rate_limit_check_and_incr(user_id)
            if over:
                await _send_rate_limit_warning(event)
                return
            return await handler(event, data)
        except Exception:
            pass

        # Fallback: in-memory
        if _check_and_record_memory(user_id):
            await _send_rate_limit_warning(event)
            return
        return await handler(event, data)
