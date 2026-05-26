"""Админка: 👥 Пользователи — список, карточка, действия."""
from aiogram import F, Router, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext

from shared.db.database import get_pool
from services.bot.handlers.start import _admin_denied, _is_admin
from services.bot.keyboards.admin import admin_back_kb, user_card_kb
from services.bot.states.admin import (
    AdminSendMessageStates,
    CreditUserStates,
    FindUserStates,
    NoteUserStates,
)
from shared.domain.admin_log import log_admin

router = Router()
PAGE = 20


@router.callback_query(F.data == "admin:users")
async def cb_admin_users(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:users")
        return
    await cb.answer()
    await _users_list(cb.message, 0)


async def _users_list(msg, offset: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
        rows = await conn.fetch(
            """SELECT id, username, first_name, credits_bought, credits_free_today, created_at, is_blocked
               FROM users ORDER BY created_at DESC OFFSET $1 LIMIT $2""",
            offset, PAGE)
    lines = []
    for r in rows:
        uname = (r["username"] or "") and f"@{r['username']}" or r["first_name"] or "—"
        bal = (r["credits_bought"] or 0) + (r["credits_free_today"] or 0)
        date = r["created_at"].strftime("%d.%m.%Y") if hasattr(r["created_at"], "strftime") else str(r["created_at"])
        status = "🚫" if r["is_blocked"] else "✅"
        lines.append(f"{r['id']} | {uname} | {bal} CR | {date} | {status}")
    text = "👥 <b>Пользователи</b> (последние)\n\n" + "\n".join(lines[:20])
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    if offset > 0:
        b.row(types.InlineKeyboardButton(text="◀️", callback_data=f"admin:users:page:{max(0, offset - PAGE)}"))
    if offset + PAGE < total:
        b.row(types.InlineKeyboardButton(text="▶️", callback_data=f"admin:users:page:{offset + PAGE}"))
    b.row(types.InlineKeyboardButton(text="◀️ В админку", callback_data="admin:back"))
    await msg.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("admin:users:page:"))
async def cb_users_page(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:users")
        return
    await cb.answer()
    try:
        offset = int(cb.data.replace("admin:users:page:", ""))
    except ValueError:
        return
    await _users_list(cb.message, offset)


@router.callback_query(F.data == "admin:find_user")
async def cb_find_user_start(cb: types.CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:users")
        return
    await cb.answer()
    await state.set_state(FindUserStates.enter_query)
    await cb.message.answer("Введи telegram_id или @username:")


@router.message(StateFilter(FindUserStates.enter_query), F.text)
async def find_user_enter(message: types.Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await _admin_denied(message, "admin:users:find")
        await state.clear()
        return
    q = (message.text or "").strip().lstrip("@")
    if not q:
        await message.answer("Введи ID или username.")
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        if q.isdigit():
            user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", int(q))
        else:
            user = await conn.fetchrow("SELECT * FROM users WHERE username = $1", q)
    if not user:
        await message.answer("Пользователь не найден.")
        await state.clear()
        return
    await state.clear()
    user_id = user["id"]
    pool = await get_pool()
    async with pool.acquire() as c2:
        pay_cnt = await c2.fetchval("SELECT COUNT(*) FROM payments WHERE user_id = $1 AND status = 'confirmed'", user_id)
        pay_sum = await c2.fetchval("SELECT COALESCE(SUM(amount_rub), 0) FROM payments WHERE user_id = $1 AND status = 'confirmed'", user_id)
        gen_cnt = await c2.fetchval("SELECT COUNT(*) FROM ai_requests WHERE user_id = $1", user_id)
    from services.bot.services.mode_service import get_current_mode_display
    mode_name = await get_current_mode_display(user_id)
    created = user["created_at"].strftime("%d.%m.%Y") if hasattr(user["created_at"], "strftime") else str(user["created_at"])
    bal = (user["credits_bought"] or 0) + (user["credits_free_today"] or 0)
    uname = (user["username"] or "") and f"@{user['username']}" or (user["first_name"] or "—")
    blocked = "🚫 Заблокирован" if user["is_blocked"] else "✅ Активен"
    text = (
        f"👤 {user['first_name'] or '—'} ({uname})\n"
        f"🆔 ID: {user_id}\n📅 Рег: {created}\n💰 Баланс: {bal}\n"
        f"💳 Оплат: {pay_cnt} ({float(pay_sum or 0):,.0f} ₽)\n🔄 Генераций: {gen_cnt}\n"
        f"🎭 Режим: {mode_name}\n{blocked}"
    )
    await message.answer(text, reply_markup=user_card_kb(user_id))


# Действия с юзером: бан, разбан, начислить, списать, заметка, написать
@router.callback_query(F.data.startswith("admin:user:ban:"))
async def cb_user_ban(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:users")
        return
    try:
        uid = int(cb.data.replace("admin:user:ban:", ""))
    except ValueError:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_blocked = TRUE WHERE id = $1", uid)
    await log_admin(cb.from_user.id, "ban_user", {"user_id": uid})
    await cb.answer("Пользователь заблокирован", show_alert=True)


@router.callback_query(F.data.startswith("admin:user:unban:"))
async def cb_user_unban(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:users")
        return
    try:
        uid = int(cb.data.replace("admin:user:unban:", ""))
    except ValueError:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_blocked = FALSE WHERE id = $1", uid)
    await log_admin(cb.from_user.id, "unban_user", {"user_id": uid})
    await cb.answer("Разблокирован", show_alert=True)


@router.callback_query(F.data.startswith("admin:user:add:"))
async def cb_user_add(cb: types.CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:users")
        return
    try:
        uid = int(cb.data.replace("admin:user:add:", ""))
    except ValueError:
        return
    await cb.answer()
    await state.update_data(credit_user_id=uid, credit_action="add")
    await state.set_state(CreditUserStates.enter_amount)
    await cb.message.answer("Введи количество CR для начисления:")


@router.callback_query(F.data.startswith("admin:user:sub:"))
async def cb_user_sub(cb: types.CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:users")
        return
    try:
        uid = int(cb.data.replace("admin:user:sub:", ""))
    except ValueError:
        return
    await cb.answer()
    await state.update_data(credit_user_id=uid, credit_action="sub")
    await state.set_state(CreditUserStates.enter_amount)
    await cb.message.answer("Введи количество CR для списания:")


@router.message(StateFilter(CreditUserStates.enter_amount), F.text)
async def credit_amount(message: types.Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await _admin_denied(message, "admin:users:credit")
        await state.clear()
        return
    try:
        amount = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введи число.")
        return
    if amount <= 0:
        await message.answer("Число должно быть > 0.")
        return
    data = await state.get_data()
    uid = data["credit_user_id"]
    action = data["credit_action"]
    from shared.domain.credits import add_credits
    if action == "add":
        await add_credits(uid, amount, "admin_add", f"Начислено админом {message.from_user.id}")
        await message.answer(f"✅ Начислено {amount} CR пользователю {uid}.")
    else:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT credits_bought FROM users WHERE id = $1", uid)
            if row:
                new_bought = max(0, (row["credits_bought"] or 0) - amount)
                await conn.execute("UPDATE users SET credits_bought = $1 WHERE id = $2", new_bought, uid)
        await message.answer(f"✅ Списано {amount} CR у пользователя {uid}.")
    await log_admin(message.from_user.id, "credit", {"user_id": uid, "action": action, "amount": amount})
    await state.clear()


@router.callback_query(F.data.startswith("admin:user:msg:"))
async def cb_user_msg(cb: types.CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:users")
        return
    try:
        uid = int(cb.data.replace("admin:user:msg:", ""))
    except ValueError:
        return
    await cb.answer()
    await state.update_data(admin_msg_target=uid)
    await state.set_state(AdminSendMessageStates.enter_text)
    await cb.message.answer("Отправь текст сообщения для пользователя (одним сообщением). Отмена: /cancel")


@router.message(StateFilter(AdminSendMessageStates.enter_text), F.text)
async def admin_send_msg_to_user(message: types.Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await _admin_denied(message, "admin:users:msg")
        await state.clear()
        return
    if (message.text or "").strip().startswith("/cancel"):
        await state.clear()
        await message.answer("Отменено.")
        return
    data = await state.get_data()
    uid = data.get("admin_msg_target")
    await state.clear()
    if not uid:
        return
    try:
        await message.bot.send_message(uid, "📩 <b>Сообщение от администрации</b>\n\n" + (message.text or ""))
        await message.answer("✅ Сообщение отправлено пользователю.")
    except Exception:
        await message.answer("Не удалось отправить (бот заблокирован или пользователь не найден).")


@router.callback_query(F.data.startswith("admin:user:note:"))
async def cb_user_note(cb: types.CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:users")
        return
    try:
        uid = int(cb.data.replace("admin:user:note:", ""))
    except ValueError:
        return
    await cb.answer()
    await state.update_data(note_user_id=uid)
    await state.set_state(NoteUserStates.enter_note)
    await cb.message.answer("Введи заметку о пользователе:")


@router.message(StateFilter(NoteUserStates.enter_note), F.text)
async def user_note_enter(message: types.Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await _admin_denied(message, "admin:users:note")
        await state.clear()
        return
    data = await state.get_data()
    uid = data.get("note_user_id")
    if not uid:
        await state.clear()
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO user_notes (user_id, admin_id, note) VALUES ($1, $2, $3)",
            uid, message.from_user.id, (message.text or "")[:1000])
    await message.answer("Заметка сохранена.")
    await log_admin(message.from_user.id, "user_note", {"user_id": uid})
    await state.clear()


@router.callback_query(F.data.startswith("admin:user:history:"))
async def cb_user_history(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:users")
        return
    try:
        uid = int(cb.data.replace("admin:user:history:", ""))
    except ValueError:
        return
    await cb.answer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        txs = await conn.fetch(
            "SELECT amount, type, description, created_at FROM credit_transactions WHERE user_id = $1 ORDER BY created_at DESC LIMIT 15",
            uid)
    lines = []
    for t in txs:
        date = t["created_at"].strftime("%d.%m %H:%M") if hasattr(t["created_at"], "strftime") else str(t["created_at"])
        lines.append(f"{date} | {t['amount']:+d} | {t['type']} | {t['description'] or '-'}")
    await cb.message.answer("📊 История операций:\n\n" + ("\n".join(lines) if lines else "Пусто"), reply_markup=admin_back_kb())
