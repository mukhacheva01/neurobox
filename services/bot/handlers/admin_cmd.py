"""НейроБокс — Admin panel: команды /admin, /админ и callback «open_admin».
Единственный вход — кнопка в меню или команда → статистика + клавиатура дашборда."""
from aiogram import F, Router, types
from aiogram.filters import Command

from shared.db.database import get_pool
from services.bot.handlers.start import _admin_denied
from services.bot.keyboards.admin import admin_dashboard_kb
from shared.config import settings
from shared.config.settings import BOT_VERSION

router = Router()


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_id_list


async def _show_admin_dashboard(target, user_id: int):
    """Показать дашборд админки (общая логика для callback и др.)."""
    try:
        if not is_admin(user_id):
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
        await target.answer(text, reply_markup=admin_dashboard_kb())
    except Exception as e:
        import structlog
        structlog.get_logger().error("admin panel error", error=str(e), user_id=user_id)
        await target.answer("❌ Ошибка загрузки админки. Попробуй позже.")


@router.message(Command("admin"))
@router.message(Command("админ"))
async def cmd_admin(message: types.Message):
    """Команды /admin и /админ — открывают дашборд админки (только для админов)."""
    if not is_admin(message.from_user.id):
        await _admin_denied(message, "cmd_admin")
        return
    await _show_admin_dashboard(message, message.from_user.id)


@router.callback_query(F.data == "open_admin")
async def cb_open_admin(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id):
        await _admin_denied(cb, "open_admin")
        return
    await cb.answer()
    await _show_admin_dashboard(cb.message, cb.from_user.id)
