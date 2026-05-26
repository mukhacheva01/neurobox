"""Проверка бана: если user is_blocked — не обрабатывать апдейты. Кеш в Redis 60 сек."""
import structlog
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from shared.db.database import get_pool

log = structlog.get_logger()
_BAN_CACHE_TTL = 60


async def _get_ban_cached(user_id: int) -> bool | None:
    """Проверить кеш бана в Redis. None = нет в кеше."""
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if r:
            val = await r.get(f"ban:{user_id}")
            if val is not None:
                return val == b"1"
    except Exception:
        pass
    return None


async def _set_ban_cached(user_id: int, is_blocked: bool) -> None:
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if r:
            await r.set(f"ban:{user_id}", "1" if is_blocked else "0", ex=_BAN_CACHE_TTL)
    except Exception:
        pass


class BanCheckMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id
        if not user_id:
            return await handler(event, data)
        try:
            cached = await _get_ban_cached(user_id)
            if cached is True:
                try:
                    if isinstance(event, Message):
                        await event.answer("⛔ Аккаунт заблокирован.")
                    elif isinstance(event, CallbackQuery):
                        await event.answer("⛔ Аккаунт заблокирован.", show_alert=True)
                except Exception:
                    pass
                return
            if cached is False:
                return await handler(event, data)
            # Нет в кеше — проверяем БД
            pool = await get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT is_blocked FROM users WHERE id = $1", user_id)
            if row is None:
                # Новый пользователь — ещё не в БД, пропускаем
                await _set_ban_cached(user_id, False)
                return await handler(event, data)
            is_blocked = bool(row["is_blocked"])
            await _set_ban_cached(user_id, is_blocked)
            if is_blocked:
                try:
                    if isinstance(event, Message):
                        await event.answer("⛔ Аккаунт заблокирован.")
                    elif isinstance(event, CallbackQuery):
                        await event.answer("⛔ Аккаунт заблокирован.", show_alert=True)
                except Exception:
                    pass
                return
        except Exception as e:
            log.warning("ban_check error, allowing through", error=str(e), user_id=user_id)
        return await handler(event, data)
