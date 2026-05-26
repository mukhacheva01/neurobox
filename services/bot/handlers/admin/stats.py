"""Админка: 📊 Статистика."""
import csv
from io import StringIO

from aiogram import F, Router, types
from aiogram.types import BufferedInputFile

from shared.db.database import get_pool
from services.bot.handlers.start import _admin_denied, _is_admin
from services.bot.keyboards.admin import admin_back_kb

router = Router()


@router.callback_query(F.data == "admin:stats")
async def cb_admin_stats(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:stats")
        return
    await cb.answer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        users_total = await conn.fetchval("SELECT COUNT(*) FROM users")
        users_today = await conn.fetchval("SELECT COUNT(*) FROM users WHERE created_at >= CURRENT_DATE")
        users_7d = await conn.fetchval("SELECT COUNT(*) FROM users WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'")
        users_30d = await conn.fetchval("SELECT COUNT(*) FROM users WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'")
        active_today = await conn.fetchval(
            "SELECT COUNT(DISTINCT user_id) FROM ai_requests WHERE started_at >= CURRENT_DATE")
        gen_total = await conn.fetchval("SELECT COUNT(*) FROM ai_requests")
        gen_today = await conn.fetchval("SELECT COUNT(*) FROM ai_requests WHERE started_at >= CURRENT_DATE")
        gen_7d = await conn.fetchval("SELECT COUNT(*) FROM ai_requests WHERE started_at >= CURRENT_DATE - INTERVAL '7 days'")
        gen_30d = await conn.fetchval("SELECT COUNT(*) FROM ai_requests WHERE started_at >= CURRENT_DATE - INTERVAL '30 days'")
        by_type = await conn.fetch(
            "SELECT task_type, COUNT(*) AS cnt FROM ai_requests GROUP BY task_type")
        rev_today = await conn.fetchval(
            "SELECT COALESCE(SUM(amount_rub), 0) FROM payments WHERE status = 'confirmed' AND confirmed_at >= CURRENT_DATE")
        rev_7d = await conn.fetchval(
            "SELECT COALESCE(SUM(amount_rub), 0) FROM payments WHERE status = 'confirmed' AND confirmed_at >= CURRENT_DATE - INTERVAL '7 days'")
        rev_30d = await conn.fetchval(
            "SELECT COALESCE(SUM(amount_rub), 0) FROM payments WHERE status = 'confirmed' AND confirmed_at >= CURRENT_DATE - INTERVAL '30 days'")
        rev_all = await conn.fetchval(
            "SELECT COALESCE(SUM(amount_rub), 0) FROM payments WHERE status = 'confirmed'")
        pay_cnt = await conn.fetchval("SELECT COUNT(*) FROM payments WHERE status = 'confirmed'")
        pay_users = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM payments WHERE status = 'confirmed'")
        avg_check = float(rev_all) / pay_cnt if pay_cnt else 0
        arpu = float(rev_all) / pay_users if pay_users else 0
        top_models = await conn.fetch(
            """SELECT model, COUNT(*) AS cnt FROM ai_requests WHERE model IS NOT NULL AND model != ''
               GROUP BY model ORDER BY cnt DESC LIMIT 5""")
        spent_30d = await conn.fetchval(
            "SELECT COALESCE(SUM(ABS(amount)), 0) FROM credit_transactions WHERE type = 'spend' AND created_at >= CURRENT_DATE - INTERVAL '30 days'")
        avg_spent_per_day = float(spent_30d or 0) / 30

    by_type_str = "\n".join(f"  • {r['task_type']}: {r['cnt']}" for r in by_type)
    top_models_str = "\n".join(f"  • {r['model']}: {r['cnt']}" for r in top_models) if top_models else "  —"
    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"👥 <b>Пользователи</b>\n"
        f"  Всего: {users_total:,}\n  Сегодня: {users_today or 0}\n  7 д: {users_7d or 0}\n  30 д: {users_30d or 0}\n"
        f"  Активных сегодня (≥1 генерация): {active_today or 0}\n"
        f"  Платящих: {pay_users or 0} ({100.0 * (pay_users or 0) / (users_total or 1):.1f}%)\n\n"
        f"🔄 <b>Генерации</b>\n  Всего: {gen_total or 0}\n  Сегодня: {gen_today or 0}\n  7 д: {gen_7d or 0}\n  30 д: {gen_30d or 0}\n"
        f"  По типам:\n{by_type_str or '  —'}\n\n"
        f"📈 <b>Топ-5 моделей</b>\n{top_models_str}\n\n"
        f"💰 <b>Выручка</b>\n  Сегодня: {float(rev_today or 0):,.0f} ₽\n  7 д: {float(rev_7d or 0):,.0f} ₽\n  30 д: {float(rev_30d or 0):,.0f} ₽\n  Всего: {float(rev_all or 0):,.0f} ₽\n"
        f"  Средний чек: {avg_check:,.0f} ₽  ARPU: {arpu:,.0f} ₽\n"
        f"  Средний расход CR/день (30 д): {avg_spent_per_day:,.0f}"
    )
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="📈 Экспорт CSV", callback_data="admin:stats:csv"))
    b.row(types.InlineKeyboardButton(text="◀️ В админку", callback_data="admin:back"))
    await cb.message.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data == "admin:ratings")
async def cb_admin_ratings(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:stats")
        return
    await cb.answer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        up_today = await conn.fetchval(
            "SELECT COUNT(*) FROM response_ratings WHERE rating = 'up' AND created_at >= CURRENT_DATE")
        down_today = await conn.fetchval(
            "SELECT COUNT(*) FROM response_ratings WHERE rating = 'down' AND created_at >= CURRENT_DATE")
        up_7 = await conn.fetchval(
            "SELECT COUNT(*) FROM response_ratings WHERE rating = 'up' AND created_at >= CURRENT_DATE - INTERVAL '7 days'")
        down_7 = await conn.fetchval(
            "SELECT COUNT(*) FROM response_ratings WHERE rating = 'down' AND created_at >= CURRENT_DATE - INTERVAL '7 days'")
        up_30 = await conn.fetchval(
            "SELECT COUNT(*) FROM response_ratings WHERE rating = 'up' AND created_at >= CURRENT_DATE - INTERVAL '30 days'")
        down_30 = await conn.fetchval(
            "SELECT COUNT(*) FROM response_ratings WHERE rating = 'down' AND created_at >= CURRENT_DATE - INTERVAL '30 days'")
        up_all = await conn.fetchval("SELECT COUNT(*) FROM response_ratings WHERE rating = 'up'")
        down_all = await conn.fetchval("SELECT COUNT(*) FROM response_ratings WHERE rating = 'down'")
        total_today = (up_today or 0) + (down_today or 0)
        total_7 = (up_7 or 0) + (down_7 or 0)
        total_30 = (up_30 or 0) + (down_30 or 0)
        total_all = (up_all or 0) + (down_all or 0)
        pct_today = (100.0 * (up_today or 0) / total_today) if total_today else 0
        pct_7 = (100.0 * (up_7 or 0) / total_7) if total_7 else 0
        pct_30 = (100.0 * (up_30 or 0) / total_30) if total_30 else 0
        pct_all = (100.0 * (up_all or 0) / total_all) if total_all else 0
    text = (
        f"👍👎 <b>Оценки ответов</b>\n\n"
        f"<b>Сегодня</b>\n  👍 {up_today or 0}  👎 {down_today or 0}  (всего {total_today})\n  Доля 👍: {pct_today:.0f}%\n\n"
        f"<b>7 дней</b>\n  👍 {up_7 or 0}  👎 {down_7 or 0}  (всего {total_7})\n  Доля 👍: {pct_7:.0f}%\n\n"
        f"<b>30 дней</b>\n  👍 {up_30 or 0}  👎 {down_30 or 0}  (всего {total_30})\n  Доля 👍: {pct_30:.0f}%\n\n"
        f"<b>Всё время</b>\n  👍 {up_all or 0}  👎 {down_all or 0}  (всего {total_all})\n  Доля 👍: {pct_all:.0f}%"
    )
    await cb.message.answer(text, reply_markup=admin_back_kb())


@router.callback_query(F.data == "admin:stats:csv")
async def cb_admin_stats_csv(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:stats")
        return
    await cb.answer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT date_trunc('day', created_at) AS day, COUNT(*) AS users
               FROM users GROUP BY date_trunc('day', created_at) ORDER BY day DESC LIMIT 90""")
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "new_users"])
    for r in rows:
        w.writerow([r["day"].strftime("%Y-%m-%d") if hasattr(r["day"], "strftime") else r["day"], r["users"]])
    buf.seek(0)
    await cb.message.answer_document(
        BufferedInputFile(buf.getvalue().encode("utf-8"), filename="stats_users.csv"),
        caption="📈 Экспорт (пользователи по дням)",
        reply_markup=admin_back_kb())
