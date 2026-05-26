"""Админка: 📢 Рассылка — текст, опционально фото, кнопка URL, выбор аудитории, 30 msg/сек, is_blocked при 403."""
import asyncio

from aiogram import F, Router, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from shared.db.database import get_pool
from services.bot.handlers.start import _admin_denied, _is_admin
from services.bot.keyboards.admin import admin_back_kb
from services.bot.states.admin import BroadcastStates

router = Router()
BROADCAST_BATCH_DELAY = 1 / 30  # 30 сообщений в секунду


@router.callback_query(F.data == "admin:broadcast")
async def cb_broadcast_start(cb: types.CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:broadcast")
        return
    await cb.answer()
    await state.set_state(BroadcastStates.enter_text)
    await cb.message.answer(
        "📢 <b>Рассылка</b>\n\nОтправь текст сообщения (HTML).\nОтмена: /cancel")


@router.message(StateFilter(BroadcastStates.enter_text), F.text, ~F.text.startswith("/"))
async def broadcast_text(message: types.Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await _admin_denied(message, "broadcast:start")
        await state.clear()
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Введи текст.")
        return
    await state.update_data(broadcast_text=text)
    await state.set_state(BroadcastStates.enter_media)
    await message.answer("📷 Добавь фото (или отправь /skip чтобы только текст):")


@router.message(StateFilter(BroadcastStates.enter_media), F.photo)
async def broadcast_photo(message: types.Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await _admin_denied(message, "broadcast:photo")
        await state.clear()
        return
    photo = message.photo[-1]
    await state.update_data(broadcast_photo_file_id=photo.file_id)
    await state.set_state(BroadcastStates.enter_button)
    await message.answer("🔗 Кнопка под сообщением: отправь «URL|Текст кнопки» или /skip:")


@router.message(StateFilter(BroadcastStates.enter_media), F.text, ~F.text.startswith("/"))
async def broadcast_skip_photo(message: types.Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await _admin_denied(message, "broadcast:button")
        await state.clear()
        return
    if (message.text or "").strip().lower() != "/skip":
        await message.answer("Отправь фото или /skip")
        return
    await state.set_state(BroadcastStates.enter_button)
    await message.answer("🔗 Кнопка под сообщением: отправь «URL|Текст кнопки» или /skip:")


@router.message(StateFilter(BroadcastStates.enter_button), F.text, ~F.text.startswith("/"))
async def broadcast_button(message: types.Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await _admin_denied(message, "broadcast:audience")
        await state.clear()
        return
    raw = (message.text or "").strip()
    if raw.lower() == "/skip":
        await state.set_state(BroadcastStates.select_audience)
        await message.answer("Выбери аудиторию:", reply_markup=_audience_kb())
        return
    if "|" in raw:
        url, label = raw.split("|", 1)
        url, label = url.strip(), label.strip() or "Перейти"
    else:
        url, label = raw.strip(), "Перейти"
    if url and url.startswith(("http://", "https://")):
        await state.update_data(broadcast_button_url=url, broadcast_button_label=label[:64])
    await state.set_state(BroadcastStates.select_audience)
    await message.answer("Выбери аудиторию:", reply_markup=_audience_kb())


def _audience_kb() -> InlineKeyboardMarkup:
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="👥 Все", callback_data="admin:broadcast:aud:all"))
    b.row(InlineKeyboardButton(text="🟢 Активные 7 дн.", callback_data="admin:broadcast:aud:active7"))
    b.row(InlineKeyboardButton(text="💰 Платящие", callback_data="admin:broadcast:aud:paying"))
    b.row(InlineKeyboardButton(text="📭 Нулевой баланс", callback_data="admin:broadcast:aud:zero"))
    b.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin:back"))
    return b.as_markup()


@router.callback_query(StateFilter(BroadcastStates.select_audience), F.data.startswith("admin:broadcast:aud:"))
async def broadcast_audience(cb: types.CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:broadcast")
        return
    aud = cb.data.replace("admin:broadcast:aud:", "")
    if aud not in ("all", "active7", "paying", "zero"):
        await cb.answer()
        return
    await state.update_data(broadcast_audience=aud)
    await state.set_state(BroadcastStates.confirm)
    data = await state.get_data()
    text = data.get("broadcast_text", "")
    has_photo = bool(data.get("broadcast_photo_file_id"))
    has_btn = bool(data.get("broadcast_button_url"))
    aud_label = {"all": "Все", "active7": "Активные 7 дн.", "paying": "Платящие", "zero": "Нулевой баланс"}.get(aud, aud)
    count = await _get_audience_count(aud)
    preview = f"📢 <b>Предпросмотр</b>\n\nТекст: {text[:200]}...\nФото: {'да' if has_photo else 'нет'}\nКнопка: {'да' if has_btn else 'нет'}\nАудитория: {aud_label} — <b>{count}</b> чел."
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✅ Отправить", callback_data="admin:broadcast:confirm"))
    b.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin:back"))
    await cb.answer()
    await cb.message.answer(preview, reply_markup=b.as_markup())


async def _get_audience_count(audience: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if audience == "all":
            return await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_blocked = FALSE")
        if audience == "active7":
            return await conn.fetchval(
                """SELECT COUNT(DISTINCT u.id) FROM users u
                   INNER JOIN ai_requests r ON r.user_id = u.id
                   WHERE u.is_blocked = FALSE AND r.started_at >= CURRENT_DATE - INTERVAL '7 days'""")
        if audience == "paying":
            return await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE is_blocked = FALSE AND total_payments_rub > 0")
        if audience == "zero":
            return await conn.fetchval(
                """SELECT COUNT(*) FROM users WHERE is_blocked = FALSE
                   AND credits_bought = 0 AND (credits_free_reset < CURRENT_DATE OR credits_free_today = 0)""")
    return 0


async def _get_audience_user_ids(audience: str) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if audience == "all":
            rows = await conn.fetch("SELECT id FROM users WHERE is_blocked = FALSE")
        elif audience == "active7":
            rows = await conn.fetch(
                """SELECT DISTINCT u.id FROM users u
                   INNER JOIN ai_requests r ON r.user_id = u.id
                   WHERE u.is_blocked = FALSE AND r.started_at >= CURRENT_DATE - INTERVAL '7 days'""")
        elif audience == "paying":
            rows = await conn.fetch(
                "SELECT id FROM users WHERE is_blocked = FALSE AND total_payments_rub > 0")
        elif audience == "zero":
            rows = await conn.fetch(
                """SELECT id FROM users WHERE is_blocked = FALSE
                   AND credits_bought = 0 AND (credits_free_reset < CURRENT_DATE OR credits_free_today = 0)""")
        else:
            rows = await conn.fetch("SELECT id FROM users WHERE is_blocked = FALSE")
    return [r["id"] for r in rows]


def _confirm_kb():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="✅ Отправить", callback_data="admin:broadcast:confirm"))
    b.row(types.InlineKeyboardButton(text="❌ Отмена", callback_data="admin:back"))
    return b.as_markup()


@router.callback_query(StateFilter(BroadcastStates.confirm), F.data == "admin:broadcast:confirm")
async def cb_broadcast_confirm(cb: types.CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:broadcast")
        return
    await cb.answer()
    data = await state.get_data()
    text = data.get("broadcast_text", "")
    photo_file_id = data.get("broadcast_photo_file_id")
    audience = data.get("broadcast_audience", "all")
    await state.clear()
    user_ids = await _get_audience_user_ids(audience)
    button_url = data.get("broadcast_button_url")
    button_label = data.get("broadcast_button_label") or "Перейти"
    reply_markup = None
    if button_url:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text=button_label[:64], url=button_url))
        reply_markup = b.as_markup()
    sent = 0
    err = 0
    blocked = 0
    await cb.message.answer("📢 Рассылка начата...")
    for uid in user_ids:
        try:
            if photo_file_id:
                await cb.bot.send_photo(uid, photo_file_id, caption=text or None, parse_mode="HTML", reply_markup=reply_markup)
            else:
                await cb.bot.send_message(uid, text, parse_mode="HTML", reply_markup=reply_markup)
            sent += 1
        except Exception as e:
            err_str = str(e).lower()
            if "blocked" in err_str or "forbidden" in err_str or "bot was blocked" in err_str or "user is deactivated" in err_str:
                blocked += 1
                try:
                    pool = await get_pool()
                    async with pool.acquire() as conn:
                        await conn.execute("UPDATE users SET is_blocked = TRUE WHERE id = $1", uid)
                except Exception:
                    pass
            err += 1
        await asyncio.sleep(BROADCAST_BATCH_DELAY)
        if (sent + err) % 100 == 0:
            try:
                await cb.message.edit_text(
                    f"📢 {sent + err}/{len(user_ids)}, доставлено: {sent}, ошибок: {err}, заблокировали: {blocked}")
            except Exception:
                pass
    await cb.message.answer(
        f"✅ Рассылка завершена.\nОтправлено: {sent}, ошибок: {err}, заблокировали бота: {blocked}",
        reply_markup=admin_back_kb())
