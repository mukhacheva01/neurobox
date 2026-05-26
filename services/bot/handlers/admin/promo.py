"""Админка: 🎟 Промокоды."""
from aiogram import F, Router, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext

from shared.db.database import get_pool
from services.bot.handlers.start import _admin_denied, _is_admin
from services.bot.keyboards.admin import promo_list_kb
from services.bot.states.admin import PromoStates

router = Router()


@router.callback_query(F.data == "admin:promo")
async def cb_admin_promo(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:promo")
        return
    await cb.answer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT code, credits, max_uses, used_count, expires_at FROM promocodes WHERE used_count < max_uses ORDER BY code LIMIT 30")
    lines = ["🎟 <b>Активные промокоды</b>\n"]
    for r in rows:
        exp = r["expires_at"].strftime("%d.%m.%Y") if r["expires_at"] and hasattr(r["expires_at"], "strftime") else "—"
        lines.append(f"<code>{r['code']}</code> — {r['credits']} CR, использовано {r['used_count']}/{r['max_uses']}, до {exp}")
    await cb.message.answer("\n".join(lines) if lines else "Нет активных промокодов.", reply_markup=promo_list_kb())


@router.callback_query(F.data == "admin:promo:create")
async def cb_promo_create(cb: types.CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:promo")
        return
    await cb.answer()
    await state.set_state(PromoStates.enter_code)
    await cb.message.answer("Введи код промокода (латиница, без пробелов):")


@router.message(StateFilter(PromoStates.enter_code), F.text)
async def promo_code(message: types.Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await _admin_denied(message, "promo:code")
        await state.clear()
        return
    code = (message.text or "").strip().upper()[:50]
    if not code:
        await message.answer("Введи код.")
        return
    await state.update_data(promo_code=code)
    await state.set_state(PromoStates.enter_credits)
    await message.answer("Введи количество кредитов:")


@router.message(StateFilter(PromoStates.enter_credits), F.text)
async def promo_credits(message: types.Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await _admin_denied(message, "promo:credits")
        await state.clear()
        return
    try:
        credits = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введи число.")
        return
    if credits <= 0:
        await message.answer("Число > 0.")
        return
    await state.update_data(promo_credits=credits)
    await state.set_state(PromoStates.enter_max_uses)
    await message.answer("Введи лимит активаций (число):")


@router.message(StateFilter(PromoStates.enter_max_uses), F.text)
async def promo_max_uses(message: types.Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await _admin_denied(message, "promo:max_uses")
        await state.clear()
        return
    try:
        max_uses = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введи число.")
        return
    if max_uses <= 0:
        await message.answer("Лимит > 0.")
        return
    await state.update_data(promo_max_uses=max_uses)
    data = await state.get_data()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO promocodes (code, credits, max_uses) VALUES ($1, $2, $3) ON CONFLICT (code) DO NOTHING",
            data["promo_code"], data["promo_credits"], max_uses)
    await message.answer(f"✅ Промокод <code>{data['promo_code']}</code> создан: {data['promo_credits']} CR, лимит {max_uses}.")
    await state.clear()
