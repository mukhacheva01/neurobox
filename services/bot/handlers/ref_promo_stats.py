"""НейроБокс — /ref, /promo, /mystats (рефералы, промокоды, статистика)."""

from __future__ import annotations

import urllib.parse

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from shared.db.database import get_pool
from shared.config import settings
from shared.domain.credits import (
    REFEREE_CR,
    REFERRAL_LEVELS,
    REFERRER_CR,
    apply_promocode,
    get_or_create_user,
    get_referral_code,
    get_referral_level,
)

router = Router()


async def _send_ref_screen(target: types.Message, user_id: int) -> None:
    code = await get_referral_code(user_id)
    bot_name = (settings.bot_username or "").strip().lstrip("@") or "neurobox_bot"
    link = f"https://t.me/{bot_name}?start=ref_{code}"

    pool = await get_pool()
    async with pool.acquire() as conn:
        ref_count = await conn.fetchval("SELECT referral_count FROM users WHERE id = $1", user_id) or 0

    level_name, mult = get_referral_level(ref_count)
    bonus_cr = int(REFERRER_CR * mult)

    next_line = ""
    for min_ref, _, name in REFERRAL_LEVELS:
        if ref_count < min_ref:
            next_line = f"\n🎯 До уровня «{name}»: ещё {min_ref - ref_count} друг(ей)"
            break
    if not next_line:
        next_line = "\n🏆 Максимальный уровень!"

    share_text = (
        "Попробуй НейроБокс — AI-бот для текста, картинок, документов и транскрибации. "
        "Бесплатные кредиты каждый день и быстрый старт без сложной настройки."
    )
    share_url = (
        f"https://t.me/share/url?url={urllib.parse.quote(link)}"
        f"&text={urllib.parse.quote(share_text)}"
    )

    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="📤 Поделиться ссылкой", url=share_url))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))

    await target.answer(
        f"🤝 <b>Реферальная программа</b>\n\n"
        f"Твоя ссылка:\n<code>{link}</code>\n\n"
        f"• Уровень: <b>{level_name}</b> (×{mult})\n"
        f"• За друга: <b>+{bonus_cr} CR</b> тебе, <b>+{REFEREE_CR} CR</b> другу\n"
        f"• Приведено: <b>{ref_count}</b>{next_line}",
        reply_markup=b.as_markup(),
    )


async def _send_mystats(target: types.Message, user_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT credits_total_spent, referral_count, total_payments_rub, created_at FROM users WHERE id = $1",
            user_id,
        )
        tx_count = await conn.fetchval("SELECT COUNT(*) FROM credit_transactions WHERE user_id = $1", user_id)
        req_count = await conn.fetchval("SELECT COUNT(*) FROM ai_requests WHERE user_id = $1", user_id)

    if not user:
        await target.answer("Статистика пока недоступна.")
        return

    created = user["created_at"].strftime("%d.%m.%Y") if hasattr(user["created_at"], "strftime") else str(user["created_at"])
    await target.answer(
        f"📊 <b>Твоя статистика</b>\n\n"
        f"📅 В боте с: {created}\n"
        f"📈 Потрачено CR: <b>{user['credits_total_spent']}</b>\n"
        f"💳 Операций с кредитами: {tx_count or 0}\n"
        f"🤖 Запросов к AI: {req_count or 0}\n"
        f"🤝 Приведено друзей: {user['referral_count']}\n"
        f"💰 Всего оплат: {float(user['total_payments_rub'] or 0):,.0f} ₽"
    )


@router.message(Command("ref"))
async def cmd_ref(message: types.Message):
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await _send_ref_screen(message, message.from_user.id)


@router.message(Command("promo"))
async def cmd_promo(message: types.Message):
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    code = (message.text or "").split(maxsplit=1)
    promo = code[1].strip() if len(code) > 1 else ""
    result = await apply_promocode(message.from_user.id, promo)
    if not result.get("ok"):
        await message.answer(f"❌ {result.get('error', 'Не удалось применить промокод')}")
        return
    await message.answer(f"✅ Промокод применён: <b>+{int(result.get('credits') or 0)} CR</b>")


@router.message(Command("mystats"))
async def cmd_mystats(message: types.Message):
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await _send_mystats(message, message.from_user.id)


@router.callback_query(F.data == "mystats")
async def cb_mystats(cb: types.CallbackQuery):
    await cb.answer()
    await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.first_name)
    await _send_mystats(cb.message, cb.from_user.id)
