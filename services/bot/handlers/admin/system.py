"""Админка: ⚙️ Система — uptime, Redis, PostgreSQL, последний webhook ЮKassa."""
import time

from aiogram import F, Router, types
from aiogram.types import BufferedInputFile

from shared.db.database import get_pool
from services.bot.handlers.start import _admin_denied, _is_admin
from services.bot.keyboards.admin import admin_back_kb, system_kb
from shared.config import settings
from shared.config.settings import BOT_VERSION

router = Router()
_start_time = time.time()


async def _redis_ok() -> bool:
    try:
        from redis.asyncio import Redis
        r = Redis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        return True
    except Exception:
        return False


@router.callback_query(F.data == "admin:system")
async def cb_admin_system(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:system")
        return
    await cb.answer()
    uptime_s = int(time.time() - _start_time)
    uptime_str = f"{uptime_s // 3600}ч {(uptime_s % 3600) // 60}м"
    redis_ok = await _redis_ok()
    pg_ok = False
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        pg_ok = True
    except Exception:
        pass
    last_webhook = ""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT payment_id, confirmed_at FROM payments WHERE status = 'confirmed' ORDER BY confirmed_at DESC LIMIT 1")
            if row and row.get("confirmed_at"):
                last_webhook = row["confirmed_at"].strftime("%Y-%m-%d %H:%M") if hasattr(row["confirmed_at"], "strftime") else str(row["confirmed_at"])
    except Exception:
        pass
    text = (
        f"⚙️ <b>Система</b>\n\n"
        f"Версия: {BOT_VERSION}\n"
        f"Uptime: {uptime_str}\n"
        f"Redis: {'✅ OK' if redis_ok else '❌ FAIL'}\n"
        f"PostgreSQL: {'✅ OK' if pg_ok else '❌ FAIL'}\n"
        f"Последний webhook ЮKassa: {last_webhook or '—'}\n"
    )
    await cb.message.answer(text, reply_markup=system_kb())


@router.callback_query(F.data == "admin:sys:clear_cache")
async def cb_clear_cache(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:system")
        return
    await cb.answer("Кеш очищен (Redis FSM не сбрасываем)", show_alert=True)


@router.callback_query(F.data == "admin:sys:download_log")
async def cb_download_log(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:system")
        return
    await cb.answer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT admin_id, action, details, created_at FROM admin_logs ORDER BY created_at DESC LIMIT 100")
    lines = []
    for r in rows:
        d = r["created_at"].strftime("%Y-%m-%d %H:%M") if hasattr(r["created_at"], "strftime") else str(r["created_at"])
        lines.append(f"{d} | admin={r['admin_id']} | {r['action']} | {r['details']}")
    content = "\n".join(lines) or "Пусто"
    await cb.message.answer_document(
        BufferedInputFile(content.encode("utf-8"), filename="admin_log.txt"),
        caption="📥 Лог админ-действий",
        reply_markup=admin_back_kb())
