"""Админка: 📋 Модерация доски."""
from aiogram import F, Router, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext

from shared.db.database import get_pool
from services.bot.handlers.start import _admin_denied, _is_admin
from services.bot.keyboards.admin import admin_back_kb, moderation_board_kb
from services.bot.states.admin import BoardStopwordStates

router = Router()


@router.callback_query(F.data == "admin:moderation")
async def cb_admin_moderation(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:moderation")
        return
    await cb.answer()
    await cb.message.answer("📋 <b>Модерация доски</b>", reply_markup=moderation_board_kb())


@router.callback_query(F.data == "admin:mod:complaints")
async def cb_complaints(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:moderation")
        return
    await cb.answer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT c.id, c.post_id, c.user_id, c.reason, c.created_at FROM board_complaints c ORDER BY c.created_at DESC LIMIT 20")
    if not rows:
        await cb.message.answer("Жалоб нет.", reply_markup=admin_back_kb())
        return
    lines = [f"post_id={r['post_id']} user={r['user_id']} {r['reason'] or ''}" for r in rows]
    await cb.message.answer("📋 Жалобы:\n\n" + "\n".join(lines), reply_markup=admin_back_kb())


@router.callback_query(F.data == "admin:mod:banned")
async def cb_banned(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:moderation")
        return
    await cb.answer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, reason, created_at FROM board_bans ORDER BY created_at DESC LIMIT 30")
    if not rows:
        await cb.message.answer("Забаненных на доске нет.", reply_markup=admin_back_kb())
        return
    lines = [f"user_id={r['user_id']} {r['reason'] or ''}" for r in rows]
    await cb.message.answer("🚫 Забаненные на доске:\n\n" + "\n".join(lines), reply_markup=admin_back_kb())


@router.callback_query(F.data == "admin:mod:stopwords")
async def cb_stopwords(cb: types.CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:moderation")
        return
    await cb.answer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT word FROM board_stopwords ORDER BY word")
    words = [r["word"] for r in rows]
    await cb.message.answer(
        "🛑 Стоп-слова (объявление с ними не публикуется):\n\n" + (", ".join(words) if words else "Пусто") + "\n\nДобавить: отправь слово сообщением.",
        reply_markup=admin_back_kb())
    await state.set_state(BoardStopwordStates.enter_word)


@router.message(StateFilter(BoardStopwordStates.enter_word), F.text)
async def stopword_add(message: types.Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await _admin_denied(message, "moderation")
        await state.clear()
        return
    word = (message.text or "").strip().lower()[:100]
    if not word or word.startswith("/"):
        await state.clear()
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO board_stopwords (word) VALUES ($1) ON CONFLICT (word) DO NOTHING", word)
    await message.answer(f"✅ Добавлено стоп-слово: {word}")
    await state.clear()
