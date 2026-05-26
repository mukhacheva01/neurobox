"""Клавиатуры админ-панели."""
from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder

from shared.config import settings


def admin_dashboard_kb():
    b = InlineKeyboardBuilder()
    b.row(
        types.InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats"),
        types.InlineKeyboardButton(text="👍👎 Оценки", callback_data="admin:ratings"),
    )
    b.row(
        types.InlineKeyboardButton(text="👥 Пользователи", callback_data="admin:users"),
        types.InlineKeyboardButton(text="💰 Финансы", callback_data="admin:finance"),
    )
    b.row(
        types.InlineKeyboardButton(text="🎟 Промокоды", callback_data="admin:promo"),
        types.InlineKeyboardButton(text="📋 Подписки", callback_data="admin:subs"),
    )
    b.row(
        types.InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast"),
        types.InlineKeyboardButton(text="🔍 Найти юзера", callback_data="admin:find_user"),
    )
    b.row(
        types.InlineKeyboardButton(text="📋 Модерация", callback_data="admin:moderation"),
        types.InlineKeyboardButton(text="⚙️ Система", callback_data="admin:system"),
    )
    # Кнопка «Веб-панель» — только если задан ADMIN_PANEL_URL (открывает URL в браузере)
    url = (getattr(settings, "admin_panel_url", None) or "").strip().rstrip("/")
    if url and (url.startswith("http://") or url.startswith("https://")):
        b.row(types.InlineKeyboardButton(text="🌐 Веб-панель", url=url))
    return b.as_markup()


def admin_back_kb():
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="◀️ В админку", callback_data="admin:back"))
    return b.as_markup()


def user_card_kb(user_id: int):
    b = InlineKeyboardBuilder()
    b.row(
        types.InlineKeyboardButton(text="💰 Начислить", callback_data=f"admin:user:add:{user_id}"),
        types.InlineKeyboardButton(text="💸 Списать", callback_data=f"admin:user:sub:{user_id}"),
    )
    b.row(
        types.InlineKeyboardButton(text="🚫 Забанить", callback_data=f"admin:user:ban:{user_id}"),
        types.InlineKeyboardButton(text="✅ Разбанить", callback_data=f"admin:user:unban:{user_id}"),
    )
    b.row(
        types.InlineKeyboardButton(text="📝 Заметка", callback_data=f"admin:user:note:{user_id}"),
        types.InlineKeyboardButton(text="📊 История", callback_data=f"admin:user:history:{user_id}"),
    )
    b.row(
        types.InlineKeyboardButton(text="♾️ Безлимит", callback_data=f"admin:user:unlimited:{user_id}"),
        types.InlineKeyboardButton(text="💬 Написать", callback_data=f"admin:user:msg:{user_id}"),
    )
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back"))
    return b.as_markup()


def users_list_pagination_kb(offset: int, page_size: int, total: int):
    b = InlineKeyboardBuilder()
    if offset > 0:
        b.row(types.InlineKeyboardButton(text="◀️", callback_data=f"admin:users:page:{max(0, offset - page_size)}"))
    if offset + page_size < total:
        b.row(types.InlineKeyboardButton(text="▶️", callback_data=f"admin:users:page:{offset + page_size}"))
    b.row(types.InlineKeyboardButton(text="◀️ В админку", callback_data="admin:back"))
    return b.as_markup()


def finance_pagination_kb(offset: int, page_size: int, total: int):
    b = InlineKeyboardBuilder()
    if offset > 0:
        b.row(types.InlineKeyboardButton(text="◀️", callback_data=f"admin:finance:page:{max(0, offset - page_size)}"))
    if offset + page_size < total:
        b.row(types.InlineKeyboardButton(text="▶️", callback_data=f"admin:finance:page:{offset + page_size}"))
    b.row(types.InlineKeyboardButton(text="📊 Выручка по дням", callback_data="admin:finance:revenue"))
    b.row(types.InlineKeyboardButton(text="📈 Экспорт CSV", callback_data="admin:finance:csv"))
    b.row(types.InlineKeyboardButton(text="◀️ В админку", callback_data="admin:back"))
    return b.as_markup()


def promo_list_kb():
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="➕ Создать", callback_data="admin:promo:create"))
    b.row(types.InlineKeyboardButton(text="◀️ В админку", callback_data="admin:back"))
    return b.as_markup()


def moderation_board_kb():
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="📋 Жалобы", callback_data="admin:mod:complaints"))
    b.row(types.InlineKeyboardButton(text="🚫 Забаненные", callback_data="admin:mod:banned"))
    b.row(types.InlineKeyboardButton(text="🛑 Стоп-слова", callback_data="admin:mod:stopwords"))
    b.row(types.InlineKeyboardButton(text="◀️ В админку", callback_data="admin:back"))
    return b.as_markup()


def system_kb():
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="🔄 Очистить кеш", callback_data="admin:sys:clear_cache"))
    b.row(types.InlineKeyboardButton(text="📥 Скачать лог", callback_data="admin:sys:download_log"))
    b.row(types.InlineKeyboardButton(text="◀️ В админку", callback_data="admin:back"))
    return b.as_markup()
