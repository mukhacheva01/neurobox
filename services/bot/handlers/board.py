"""НейроБокс — Доска объявлений: просмотр, создание, лайки, комментарии, закрепление."""
from aiogram import F, Router, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext

from services.bot.handlers.start import _is_admin
from services.bot.keyboards.board import (
    board_list_kb,
    confirm_post_kb,
    post_actions_kb,
    post_pinned_actions_kb,
    skip_photo_kb,
)
from services.bot.keyboards.main import back_to_main_kb
from services.bot.services.board_service import (
    BOARD_PAGE,
    MAX_POSTS_PER_DAY,
    add_comment,
    ban_on_board,
    contains_stopword,
    count_pinned,
    count_user_posts_today,
    create_post,
    delete_post,
    get_post,
    get_post_author_id,
    get_stopwords,
    is_banned_on_board,
    list_posts,
    set_pinned,
    toggle_like,
    user_liked,
    user_liked_post_ids,
)
from services.bot.states.board import BoardCommentStates, BoardPostStates
from shared.domain.credits import get_or_create_user

router = Router()


def _format_post(p: dict, user_id: int, is_admin: bool, liked: bool) -> str:
    uname = (p.get("username") or "") and f"@{p['username']}" or (p.get("first_name") or "Пользователь")
    date = p["created_at"].strftime("%d %b") if hasattr(p["created_at"], "strftime") else str(p["created_at"])
    head = "📌 Закреплено\n" if p.get("is_pinned") else ""
    head += f"👤 {uname} · {date}\n"
    return head + f"{p['text']}\n\n❤️ {p.get('likes_count') or 0}  💬 {p.get('comments_count') or 0}"


async def _render_board(target, offset: int, user_id: int, is_admin: bool):
    """target: Message или CallbackQuery (с .message)."""
    msg = target.message if hasattr(target, "message") else target
    posts, has_more = await list_posts(offset, BOARD_PAGE)
    if not posts:
        await msg.answer(
            "📢 <b>Доска объявлений</b>\n\nЗдесь пользователи делятся полезным. Пока пусто.\n\n✏️ Написать — первое объявление.",
            reply_markup=board_list_kb(offset, has_more, is_admin))
        return
    await msg.answer(
        "📢 <b>Доска объявлений</b>\n\nЗдесь пользователи делятся полезным: промпты, лайфхаки, вопросы, предложения.")
    pinned_cnt = await count_pinned()
    liked_ids = await user_liked_post_ids(user_id, [p["id"] for p in posts])
    for p in posts:
        liked = p["id"] in liked_ids
        is_author = p["user_id"] == user_id
        can_pin = is_admin and pinned_cnt < 3 and not p.get("is_pinned")
        kb = post_pinned_actions_kb(p["id"], liked, is_author, is_admin) if p.get("is_pinned") else post_actions_kb(p["id"], liked, is_author, is_admin, can_pin)
        await msg.answer(_format_post(p, user_id, is_admin, liked), reply_markup=kb)
    await msg.answer("───────────────────", reply_markup=board_list_kb(offset, has_more, is_admin))


@router.callback_query(F.data == "board_open")
async def cmd_board(message_or_cb: types.Message | types.CallbackQuery):
    if isinstance(message_or_cb, types.CallbackQuery):
        await message_or_cb.answer()
        user_id = message_or_cb.from_user.id
        target = message_or_cb
    else:
        user_id = message_or_cb.from_user.id
        target = message_or_cb
    await get_or_create_user(user_id, message_or_cb.from_user.username, message_or_cb.from_user.first_name)
    is_admin = _is_admin(user_id)
    await _render_board(target, 0, user_id, is_admin)


@router.callback_query(F.data.startswith("board_more:"))
async def cb_board_more(cb: types.CallbackQuery):
    await cb.answer()
    try:
        offset = int(cb.data.replace("board_more:", ""))
    except ValueError:
        return
    user_id = cb.from_user.id
    is_admin = _is_admin(user_id)
    posts, has_more = await list_posts(offset, BOARD_PAGE)
    pinned_cnt = await count_pinned()
    liked_ids = await user_liked_post_ids(user_id, [p["id"] for p in posts])
    for p in posts:
        liked = p["id"] in liked_ids
        is_author = p["user_id"] == user_id
        can_pin = is_admin and pinned_cnt < 3 and not p.get("is_pinned")
        kb = post_pinned_actions_kb(p["id"], liked, is_author, is_admin) if p.get("is_pinned") else post_actions_kb(p["id"], liked, is_author, is_admin, can_pin)
        await cb.message.answer(_format_post(p, user_id, is_admin, liked), reply_markup=kb)
    await cb.message.answer("───────────────────", reply_markup=board_list_kb(offset, has_more, is_admin))


# Создание объявления — FSM
@router.callback_query(F.data == "board_write")
async def cb_board_write(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    user_id = cb.from_user.id
    if await is_banned_on_board(user_id):
        await cb.message.answer("⛔ Ты заблокирован на доске.")
        return
    if await count_user_posts_today(user_id) >= MAX_POSTS_PER_DAY:
        await cb.message.answer(f"⛔ Лимит: {MAX_POSTS_PER_DAY} объявления в сутки.")
        return
    await state.set_state(BoardPostStates.enter_text)
    await cb.message.answer("Напиши текст объявления (до 1000 символов):\n\n/cancel — отмена")


@router.message(StateFilter(BoardPostStates.enter_text), F.text, ~F.text.startswith("/"))
async def board_enter_text(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()[:1000]
    if not text:
        await message.answer("Введи текст.")
        return
    stopwords = await get_stopwords()
    if stopwords and contains_stopword(text, stopwords):
        await message.answer("⛔ В тексте есть запрещённые слова. Объявление не опубликовано.")
        await state.clear()
        return
    await state.update_data(text=text)
    await state.set_state(BoardPostStates.enter_photo)
    await message.answer("Прикрепить фото? Отправь картинку или нажми кнопку.", reply_markup=skip_photo_kb())


@router.message(StateFilter(BoardPostStates.enter_photo), F.photo)
async def board_enter_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=photo_id)
    data = await state.get_data()
    await state.set_state(BoardPostStates.confirm)
    await message.answer(
        f"Твоё объявление:\n\n{data['text']}\n\nОпубликовать?",
        reply_markup=confirm_post_kb())


@router.callback_query(StateFilter(BoardPostStates.enter_photo), F.data == "board_skip_photo")
async def board_skip_photo(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    await state.set_state(BoardPostStates.confirm)
    await cb.message.answer(
        f"Твоё объявление:\n\n{data['text']}\n\nОпубликовать?",
        reply_markup=confirm_post_kb())


@router.callback_query(StateFilter(BoardPostStates.confirm), F.data == "board_confirm_post")
async def board_confirm_post(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    user_id = cb.from_user.id
    await create_post(user_id, data["text"], data.get("photo_file_id"))
    await state.clear()
    await cb.message.answer("✅ Объявление опубликовано!")
    if data.get("photo_file_id"):
        await cb.message.answer_photo(photo=data["photo_file_id"], caption=data["text"][:200])
    else:
        await cb.message.answer(data["text"][:500])


@router.callback_query(StateFilter(BoardPostStates.confirm), F.data == "board_edit_post")
async def board_edit_post(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(BoardPostStates.enter_text)
    await cb.message.answer("Напиши новый текст объявления (до 1000 символов):")


@router.callback_query(StateFilter(BoardPostStates.confirm), F.data == "board_cancel_post")
async def board_cancel_post(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    await cb.message.answer("Отменено.", reply_markup=back_to_main_kb())


@router.message(StateFilter(BoardPostStates.enter_text), F.text.startswith("/cancel"))
@router.message(StateFilter(BoardPostStates.enter_photo), F.text.startswith("/cancel"))
async def board_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=back_to_main_kb())


# Лайк
@router.callback_query(F.data.startswith("board:like:"))
async def cb_board_like(cb: types.CallbackQuery):
    try:
        post_id = int(cb.data.replace("board:like:", ""))
    except ValueError:
        return
    await toggle_like(post_id, cb.from_user.id)
    await cb.answer("❤️" if await user_liked(post_id, cb.from_user.id) else "💔")


# Комментарий — FSM
@router.callback_query(F.data.startswith("board:comment:"))
async def cb_board_comment(cb: types.CallbackQuery, state: FSMContext):
    try:
        post_id = int(cb.data.replace("board:comment:", ""))
    except ValueError:
        return
    await cb.answer()
    await state.update_data(comment_post_id=post_id)
    await state.set_state(BoardCommentStates.enter_text)
    await cb.message.answer("Напиши текст ответа (до 500 символов):\n\n/cancel — отмена")


@router.message(StateFilter(BoardCommentStates.enter_text), F.text, ~F.text.startswith("/"))
async def board_comment_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    post_id = data.get("comment_post_id")
    if not post_id:
        await state.clear()
        return
    text = (message.text or "").strip()[:500]
    if not text:
        await message.answer("Введи текст.")
        return
    await add_comment(post_id, message.from_user.id, text)
    await state.clear()
    post = await get_post(post_id)
    if post:
        author_id = post["user_id"]
        await message.answer(f"✅ Ответ добавлен.\n\n💬 {text[:100]}...")
        # Уведомление автору (если не отключено)
        from services.bot.services.board_service import board_notifications_disabled
        if author_id != message.from_user.id and not await board_notifications_disabled(author_id):
            try:
                await message.bot.send_message(
                    author_id,
                    f"💬 Новый ответ на твоё объявление:\n\n{text[:200]}")
            except Exception:
                pass


# Закрепить / открепить (админ)
@router.callback_query(F.data.startswith("board:pin:"))
async def cb_board_pin(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    try:
        post_id = int(cb.data.replace("board:pin:", ""))
    except ValueError:
        return
    ok = await set_pinned(post_id, True)
    await cb.answer("📌 Закреплено" if ok else "Макс. 3 закреплённых", show_alert=not ok)


@router.callback_query(F.data.startswith("board:unpin:"))
async def cb_board_unpin(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    try:
        post_id = int(cb.data.replace("board:unpin:", ""))
    except ValueError:
        return
    await set_pinned(post_id, False)
    await cb.answer("Откреплено")


# Удалить
@router.callback_query(F.data.startswith("board:delete:"))
async def cb_board_delete(cb: types.CallbackQuery):
    try:
        post_id = int(cb.data.replace("board:delete:", ""))
    except ValueError:
        return
    post = await get_post(post_id)
    if not post:
        await cb.answer("Уже удалено", show_alert=True)
        return
    if post["user_id"] != cb.from_user.id and not _is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await delete_post(post_id, cb.from_user.id)
    await cb.answer("Удалено")
    await cb.message.edit_text(cb.message.text + "\n\n[Удалено]")


# Бан на доске
@router.callback_query(F.data.startswith("board:ban_user:"))
async def cb_board_ban_user(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    try:
        post_id = int(cb.data.replace("board:ban_user:", ""))
    except ValueError:
        return
    author_id = await get_post_author_id(post_id)
    if not author_id:
        await cb.answer("Пост не найден", show_alert=True)
        return
    await ban_on_board(author_id, cb.from_user.id, "бан с доски")
    await cb.answer("Пользователь заблокирован на доске", show_alert=True)
