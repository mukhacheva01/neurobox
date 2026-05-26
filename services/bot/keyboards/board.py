"""Клавиатуры доски объявлений."""
from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder


def board_list_kb(offset: int, has_more: bool, is_admin: bool = False):
    b = InlineKeyboardBuilder()
    row = [
        types.InlineKeyboardButton(text="✏️ Написать", callback_data="board_write"),
        types.InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu"),
    ]
    if has_more:
        row.append(types.InlineKeyboardButton(text="▶️ Ещё", callback_data=f"board_more:{offset}"))
    b.row(*row)
    return b.as_markup()


def post_actions_kb(post_id: int, user_liked: bool, is_author: bool, is_admin: bool, can_pin: bool):
    """Кнопки под объявлением: лайк, ответить, закрепить (админ), удалить (автор/админ)."""
    b = InlineKeyboardBuilder()
    like_text = "💔" if user_liked else "❤️"
    b.row(
        types.InlineKeyboardButton(text=like_text, callback_data=f"board:like:{post_id}"),
        types.InlineKeyboardButton(text="💬 Ответить", callback_data=f"board:comment:{post_id}"),
    )
    if can_pin and is_admin:
        b.row(types.InlineKeyboardButton(text="📌 Закрепить", callback_data=f"board:pin:{post_id}"))
    if is_author or is_admin:
        b.row(types.InlineKeyboardButton(text="🗑 Удалить", callback_data=f"board:delete:{post_id}"))
    if is_admin and not is_author:
        b.row(types.InlineKeyboardButton(text="🚫 Забанить на доске", callback_data=f"board:ban_user:{post_id}"))
    return b.as_markup()


def post_pinned_actions_kb(post_id: int, user_liked: bool, is_author: bool, is_admin: bool):
    b = InlineKeyboardBuilder()
    like_text = "💔" if user_liked else "❤️"
    r = [types.InlineKeyboardButton(text=like_text, callback_data=f"board:like:{post_id}"), types.InlineKeyboardButton(text="💬 Ответить", callback_data=f"board:comment:{post_id}")]
    if is_admin:
        r.append(types.InlineKeyboardButton(text="📌 Открепить", callback_data=f"board:unpin:{post_id}"))
    b.row(*r)
    if is_author or is_admin:
        b.row(types.InlineKeyboardButton(text="🗑 Удалить", callback_data=f"board:delete:{post_id}"))
    return b.as_markup()


def skip_photo_kb():
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="Пропустить", callback_data="board_skip_photo"))
    return b.as_markup()


def confirm_post_kb():
    b = InlineKeyboardBuilder()
    b.row(
        types.InlineKeyboardButton(text="✅ Опубликовать", callback_data="board_confirm_post"),
        types.InlineKeyboardButton(text="✏️ Изменить", callback_data="board_edit_post"),
        types.InlineKeyboardButton(text="❌ Отмена", callback_data="board_cancel_post"),
    )
    return b.as_markup()


def comment_thread_kb(post_id: int):
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="◀️ К доске", callback_data="board_open"))
    return b.as_markup()
