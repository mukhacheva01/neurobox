"""Админка: 💰 Финансы."""
import csv
from io import StringIO

from aiogram import F, Router, types
from aiogram.types import BufferedInputFile

from shared.db.database import get_pool
from services.bot.handlers.start import _admin_denied, _is_admin
from services.bot.keyboards.admin import admin_back_kb, finance_pagination_kb

router = Router()
PAGE = 50


@router.callback_query(F.data == "admin:finance")
async def cb_admin_finance(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:finance")
        return
    await cb.answer()
    await _finance_list(cb.message, 0)


async def _finance_list(msg, offset: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM payments") or 0
        rows = await conn.fetch(
            """SELECT p.id, p.user_id, p.amount_rub, p.credits_amount, p.pack_name, p.status, p.created_at, p.confirmed_at,
                      u.username
               FROM payments p LEFT JOIN users u ON u.id = p.user_id
               ORDER BY p.created_at DESC OFFSET $1 LIMIT $2""",
            offset, PAGE + 1)
    rows = rows[:PAGE]
    lines = []
    for r in rows:
        date = r["created_at"].strftime("%d.%m %H:%M") if hasattr(r["created_at"], "strftime") else str(r["created_at"])
        uname = (r["username"] or "") and f"@{r['username']}" or str(r["user_id"])
        lines.append(f"{date} | {uname} | {float(r['amount_rub']):,.0f} ₽ | {r['pack_name'] or '-'} | {r['status']}")
    text = "💰 <b>Финансы</b> (последние платежи)\n\n" + "\n".join(lines)
    await msg.answer(text, reply_markup=finance_pagination_kb(offset, PAGE, total))


@router.callback_query(F.data.startswith("admin:finance:page:"))
async def cb_finance_page(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:finance")
        return
    await cb.answer()
    try:
        offset = int(cb.data.replace("admin:finance:page:", ""))
    except ValueError:
        return
    await _finance_list(cb.message, offset)


@router.callback_query(F.data == "admin:finance:revenue")
async def cb_finance_revenue(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:finance")
        return
    await cb.answer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT date_trunc('day', confirmed_at)::date AS d, COUNT(*) AS cnt, SUM(amount_rub) AS total
               FROM payments WHERE status = 'confirmed' AND confirmed_at IS NOT NULL
               AND confirmed_at >= NOW() - INTERVAL '30 days'
               GROUP BY date_trunc('day', confirmed_at) ORDER BY d DESC LIMIT 30""")
    lines = ["Дата | Кол-во | Сумма"]
    for r in rows:
        d = r["d"].strftime("%Y-%m-%d") if hasattr(r["d"], "strftime") else str(r["d"])
        lines.append(f"{d} | {r['cnt']} | {float(r['total'] or 0):,.0f} ₽")
    await cb.message.answer("📊 Выручка по дням (30 д):\n\n" + "\n".join(lines), reply_markup=admin_back_kb())


@router.callback_query(F.data == "admin:finance:csv")
async def cb_finance_csv(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:finance")
        return
    await cb.answer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT p.created_at, p.user_id, p.amount_rub, p.credits_amount, p.pack_name, p.status, u.username
               FROM payments p LEFT JOIN users u ON u.id = p.user_id ORDER BY p.created_at DESC LIMIT 1000""")
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["created_at", "user_id", "username", "amount_rub", "credits", "pack", "status"])
    for r in rows:
        w.writerow([
            r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else r["created_at"],
            r["user_id"], r["username"] or "", float(r["amount_rub"]), r["credits_amount"], r["pack_name"] or "", r["status"]
        ])
    await cb.message.answer_document(
        BufferedInputFile(buf.getvalue().encode("utf-8"), filename="payments.csv"),
        caption="📈 Экспорт платежей",
        reply_markup=admin_back_kb())
