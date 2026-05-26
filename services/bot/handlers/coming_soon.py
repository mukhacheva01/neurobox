"""НейроБокс — Обработка неподдерживаемых типов: стикеры, GIF, контакты и т.д."""
from aiogram import F, Router, types
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router()


@router.message(F.sticker)
async def handle_sticker(message: types.Message):
    """Стикер → подсказка что бот умеет."""
    b = InlineKeyboardBuilder()
    b.row(
        types.InlineKeyboardButton(text="💬 Задать вопрос", callback_data="screen_text"),
        types.InlineKeyboardButton(text="🎨 Картинка", callback_data="screen_images"),
    )
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    await message.answer(
        "😊 Классный стикер! Но я пока не умею их обрабатывать.\n\n"
        "Что я умею:\n"
        "• Напиши текст — отвечу через AI\n"
        "• Отправь фото — проанализирую\n"
        "• Отправь голосовое/кружок — распознаю и отвечу",
        reply_markup=b.as_markup())


@router.message(F.animation)
async def handle_animation(message: types.Message):
    """GIF/анимация → подсказка."""
    await message.answer(
        "🎞 GIF получил! Но пока не умею их анализировать.\n\n"
        "💡 Попробуй отправить <b>фото</b> с подписью — бот проанализирует или отредактирует.")


@router.message(F.contact)
async def handle_contact(message: types.Message):
    await message.answer("📱 Контакты я не обрабатываю. Напиши текст или отправь фото!")


@router.message(F.location)
async def handle_location(message: types.Message):
    await message.answer("📍 Геолокацию я не обрабатываю. Напиши текст или отправь фото!")
