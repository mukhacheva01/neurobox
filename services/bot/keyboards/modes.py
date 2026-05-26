"""Клавиатуры выбора режима чата."""
from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder

CATEGORIES = [
    ("🔮 Универсальный", "Универсальный"),
    ("💼 Бизнес и маркетинг", "Бизнес и маркетинг"),
    ("💻 Программирование", "Программирование"),
    ("✍️ Тексты и контент", "Тексты и контент"),
    ("🎓 Обучение", "Обучение"),
    ("🎨 Креатив", "Креатив"),
    ("🏥 Здоровье и спорт", "Здоровье и спорт"),
    ("⚖️ Юридический", "Юридический"),
    ("🌐 Языки и перевод", "Языки и перевод"),
    ("🛠 Утилиты", "Утилиты"),
    ("✏️ Мой режим", "custom"),
]


def categories_kb():
    b = InlineKeyboardBuilder()
    for label, cat_id in CATEGORIES:
        b.row(types.InlineKeyboardButton(text=label, callback_data=f"mode_cat:{cat_id}"))
    return b.as_markup()


def modes_in_category_kb(modes: list, back_to_categories: bool = True):
    """modes = [(id, name, emoji), ...]"""
    b = InlineKeyboardBuilder()
    for mode_id, name, emoji in modes:
        b.row(types.InlineKeyboardButton(text=f"{emoji} {name}", callback_data=f"mode_select:{mode_id}"))
    if back_to_categories:
        b.row(types.InlineKeyboardButton(text="◀️ Назад к категориям", callback_data="mode_open"))
    b.row(types.InlineKeyboardButton(text="◀️ В меню", callback_data="main_menu"))
    return b.as_markup()


def custom_mode_kb(has_custom: bool):
    b = InlineKeyboardBuilder()
    if has_custom:
        b.row(types.InlineKeyboardButton(text="✏️ Изменить", callback_data="mode_custom_edit"))
        b.row(types.InlineKeyboardButton(text="🗑 Удалить", callback_data="mode_custom_delete"))
    else:
        b.row(types.InlineKeyboardButton(text="✏️ Задать промпт", callback_data="mode_custom_edit"))
    b.row(types.InlineKeyboardButton(text="◀️ В меню", callback_data="main_menu"))
    return b.as_markup()
