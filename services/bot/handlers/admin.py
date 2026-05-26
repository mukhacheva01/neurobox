"""НейроБокс — Admin panel (/admin, /админ): единственный вход — статистика + клавиатура дашборда."""
import structlog
from aiogram import Router, types
from aiogram.filters import Command

from shared.db.database import get_pool
from services.bot.keyboards.admin import admin_dashboard_kb
from shared.config import settings
from shared.config.settings import BOT_VERSION

router = Router()
log = structlog.get_logger()

def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_id_list

@router.message(Command("admin"))
@router.message(Command("админ"))
async def cmd_admin(message: types.Message):
    try:
        if not is_admin(message.from_user.id):
            log.warning("Admin access denied", user_id=message.from_user.id, username=message.from_user.username)
            return
        pool = await get_pool()
        async with pool.acquire() as conn:
            users_count = await conn.fetchval("SELECT COUNT(*) FROM users")
            payments_sum = await conn.fetchval(
                "SELECT COALESCE(SUM(amount_rub), 0) FROM payments WHERE status = 'confirmed'")
            payments_count = await conn.fetchval(
                "SELECT COUNT(*) FROM payments WHERE status = 'confirmed'")
            today_requests = await conn.fetchval(
                "SELECT COUNT(*) FROM ai_requests WHERE started_at >= CURRENT_DATE")
        text = (
            f"🔧 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
            f"📌 Версия: {BOT_VERSION}\n"
            f"👥 Пользователей: {users_count:,}\n"
            f"💰 Оплат: {payments_count} на {float(payments_sum or 0):,.0f} ₽\n"
            f"📊 Запросов сегодня: {today_requests or 0}\n\n"
            "Выбери раздел:"
        )
        await message.answer(text, reply_markup=admin_dashboard_kb())
    except Exception as e:
        await message.answer(f"❌ Ошибка админки: {e!r}")
