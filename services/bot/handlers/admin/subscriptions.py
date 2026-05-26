"""Админка: 📋 Подписки — просмотр, управление безлимитом и подписками."""
from aiogram import F, Router, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from shared.db.database import get_pool
from services.bot.handlers.start import _admin_denied, _is_admin
from services.bot.states.admin import UnlimitedByUsernameStates

router = Router()


@router.callback_query(F.data == "admin:subs")
async def cb_admin_subs(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:subscriptions")
        return
    await cb.answer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Активные безлимиты
        unlimited = await conn.fetch(
            """SELECT u.id, u.username, u.unlimited_ends_at
               FROM users u
               WHERE u.unlimited_ends_at IS NOT NULL AND u.unlimited_ends_at > NOW()
               ORDER BY u.unlimited_ends_at DESC LIMIT 50""")
        # Активные триалы
        trials = await conn.fetch(
            """SELECT u.id, u.username, u.trial_started_at
               FROM users u
               WHERE u.trial_started_at IS NOT NULL
                 AND u.trial_started_at + INTERVAL '45 minutes' > NOW()
               ORDER BY u.trial_started_at DESC LIMIT 20""")
        # Последние покупки безлимита
        subs = await conn.fetch(
            """SELECT p.user_id, u.username, p.pack_name, p.amount_rub, p.confirmed_at
               FROM payments p JOIN users u ON u.id = p.user_id
               WHERE p.status = 'confirmed' AND p.pack_name = 'unlimited'
               ORDER BY p.confirmed_at DESC LIMIT 20""")
    lines = ["📋 <b>Подписки и безлимиты</b>\n"]

    lines.append("\n<b>♾️ Активные безлимиты:</b>")
    if unlimited:
        for r in unlimited:
            uname = f"@{r['username']}" if r["username"] else str(r["id"])
            end = r["unlimited_ends_at"].strftime("%d.%m.%Y %H:%M") if hasattr(r["unlimited_ends_at"], "strftime") else str(r["unlimited_ends_at"])
            lines.append(f"  {uname} — до {end}")
    else:
        lines.append("  Нет активных безлимитов")

    lines.append("\n<b>⏱ Активные триалы (45 мин):</b>")
    if trials:
        for r in trials:
            uname = f"@{r['username']}" if r["username"] else str(r["id"])
            started = r["trial_started_at"].strftime("%H:%M") if hasattr(r["trial_started_at"], "strftime") else str(r["trial_started_at"])
            lines.append(f"  {uname} — с {started}")
    else:
        lines.append("  Нет активных триалов")

    lines.append("\n<b>💳 Последние покупки безлимита:</b>")
    if subs:
        for r in subs:
            uname = f"@{r['username']}" if r["username"] else str(r["user_id"])
            dt = r["confirmed_at"].strftime("%d.%m %H:%M") if r["confirmed_at"] and hasattr(r["confirmed_at"], "strftime") else "—"
            lines.append(f"  {dt} | {uname} | {r['pack_name']} | {float(r['amount_rub']):,.0f} ₽")
    else:
        lines.append("  Нет покупок безлимита")

    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="♾️ Безлимит по нику", callback_data="admin:unlimited_by_username"))
    b.row(types.InlineKeyboardButton(text="◀️ В админку", callback_data="admin:back"))
    await cb.message.answer("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(F.data == "admin:unlimited_by_username")
async def cb_unlimited_by_username(cb: types.CallbackQuery, state: FSMContext):
    """Админ: ввод ника для выдачи безлимита."""
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:subscriptions")
        return
    await cb.answer()
    await state.set_state(UnlimitedByUsernameStates.enter_username)
    await cb.message.answer("Введи username пользователя (с @ или без):\n\nПример: <code>vasya</code> или <code>@vasya</code>")


@router.message(StateFilter(UnlimitedByUsernameStates.enter_username), F.text)
async def msg_unlimited_username(message: types.Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await _admin_denied(message, "admin:subscriptions")
        await state.clear()
        return
    username = (message.text or "").strip().lstrip("@").strip()
    if not username:
        await message.answer("Введи username (с @ или без).")
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT id, username, unlimited_ends_at FROM users WHERE LOWER(TRIM(username)) = LOWER($1)",
            username,
        )
    await state.clear()
    if not user:
        await message.answer(f"Пользователь @{username} не найден в базе.")
        return
    uid = user["id"]
    from shared.domain.credits import get_unlimited_ends_at
    end = await get_unlimited_ends_at(uid)
    end_str = end.strftime("%d.%m.%Y %H:%M") if end and hasattr(end, "strftime") else "не активен"
    uname = f"@{user['username']}" if user.get("username") else str(uid)
    b = InlineKeyboardBuilder()
    for days, label in [(7, "7 дней"), (30, "30 дней"), (90, "90 дней"), (365, "365 дней")]:
        b.row(types.InlineKeyboardButton(text=f"♾️ +{label}", callback_data=f"admin:user:setunl:{uid}:{days}"))
    b.row(types.InlineKeyboardButton(text="❌ Отключить безлимит", callback_data=f"admin:user:setunl:{uid}:0"))
    b.row(types.InlineKeyboardButton(text="◀️ В админку", callback_data="admin:back"))
    await message.answer(
        f"♾️ <b>Безлимит для {uname}</b> (ID: {uid})\n\nТекущий статус: <b>{end_str}</b>\n\nВыбери срок:",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data.startswith("admin:user:unlimited:"))
async def cb_user_unlimited(cb: types.CallbackQuery):
    """Админ: дать/продлить безлимит пользователю."""
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:subscriptions")
        return
    try:
        uid = int(cb.data.replace("admin:user:unlimited:", ""))
    except ValueError:
        return
    await cb.answer()
    from shared.domain.credits import get_unlimited_ends_at
    end = await get_unlimited_ends_at(uid)
    end_str = end.strftime("%d.%m.%Y %H:%M") if end and hasattr(end, "strftime") else "не активен"

    b = InlineKeyboardBuilder()
    for days, label in [(7, "7 дней"), (30, "30 дней"), (90, "90 дней"), (365, "365 дней")]:
        b.row(types.InlineKeyboardButton(text=f"♾️ +{label}", callback_data=f"admin:user:setunl:{uid}:{days}"))
    b.row(types.InlineKeyboardButton(text="❌ Отключить безлимит", callback_data=f"admin:user:setunl:{uid}:0"))
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back"))
    await cb.message.answer(
        f"♾️ <b>Безлимит для {uid}</b>\n\nТекущий статус: <b>{end_str}</b>\n\nВыбери срок:",
        reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("admin:user:setunl:"))
async def cb_set_unlimited(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, cb.data or "admin:subscriptions")
        return
    parts = cb.data.split(":")
    try:
        uid = int(parts[3])
        days = int(parts[4])
    except (ValueError, IndexError):
        return
    await cb.answer()

    if days == 0:
        # Отключить безлимит
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE users SET unlimited_ends_at = NULL WHERE id = $1", uid)
        from shared.domain.credits import _balance_cache_invalidate
        await _balance_cache_invalidate(uid)
        from shared.domain.admin_log import log_admin
        await log_admin(cb.from_user.id, "remove_unlimited", {"user_id": uid})
        await cb.message.answer(f"❌ Безлимит отключён для {uid}.")
    else:
        from shared.domain.credits import get_unlimited_ends_at, set_unlimited_until
        await set_unlimited_until(uid, days=days)
        end = await get_unlimited_ends_at(uid)
        end_str = end.strftime("%d.%m.%Y") if end and hasattr(end, "strftime") else "?"
        from shared.domain.admin_log import log_admin
        await log_admin(cb.from_user.id, "set_unlimited", {"user_id": uid, "days": days})
        await cb.message.answer(f"✅ Безлимит для {uid} активен до <b>{end_str}</b> (+{days} дн.)")
