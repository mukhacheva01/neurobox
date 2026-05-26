"""НейроБокс — Режимы чата: категории, выбор режима, кастомный (FSM)."""
from aiogram import F, Router, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext

from services.bot.keyboards.main import back_to_main_kb
from services.bot.keyboards.modes import (
    categories_kb,
    custom_mode_kb,
    modes_in_category_kb,
)
from services.bot.services.mode_service import (
    get_current_mode_display,
    get_custom_mode_prompt,
    get_mode_by_id,
    get_modes_by_category,
    set_custom_mode,
    set_mode,
)
from services.bot.states.modes import CustomModeStates
from shared.domain.credits import get_or_create_user

router = Router()


@router.message(F.text == "🎭 Режим чата")
async def msg_mode_open(message: types.Message):
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    current = await get_current_mode_display(message.from_user.id)
    await message.answer(
        "🎭 <b>Выбери режим чата</b>\n\n"
        f"Текущий: <b>{current}</b>\n\n"
        "Режим определяет, как бот будет отвечать.",
        reply_markup=categories_kb())


@router.callback_query(F.data == "mode_open")
async def cb_mode_open(cb: types.CallbackQuery):
    await cb.answer()
    await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.first_name)
    current = await get_current_mode_display(cb.from_user.id)
    await cb.message.answer(
        "🎭 <b>Выбери режим чата</b>\n\n"
        f"Текущий: <b>{current}</b>\n\n"
        "Режим определяет, как бот будет отвечать.",
        reply_markup=categories_kb())


@router.callback_query(F.data.startswith("mode_cat:"))
async def cb_mode_category(cb: types.CallbackQuery):
    await cb.answer()
    cat = cb.data.replace("mode_cat:", "")
    if cat == "custom":
        # ✏️ Мой режим
        custom = await get_custom_mode_prompt(cb.from_user.id)
        if custom:
            text = f"✏️ <b>Мой режим</b>\n\n{custom[:50]}..."
        else:
            text = "✏️ <b>Мой режим</b>\n\nНапиши системный промпт — бот будет следовать этим инструкциям. До 2000 символов."
        await cb.message.answer(text, reply_markup=custom_mode_kb(bool(custom)))
        return
    modes = await get_modes_by_category(cat)
    if not modes:
        await cb.message.answer("В этой категории пока нет режимов.", reply_markup=back_to_main_kb())
        return
    labels = {"Универсальный": "🔮 Универсальный", "Бизнес и маркетинг": "💼 Бизнес и маркетинг",
              "Программирование": "💻 Программирование", "Тексты и контент": "✍️ Тексты и контент",
              "Обучение": "🎓 Обучение", "Креатив": "🎨 Креатив", "Здоровье и спорт": "🏥 Здоровье и спорт",
              "Юридический": "⚖️ Юридический", "Языки и перевод": "🌐 Языки и перевод", "Утилиты": "🛠 Утилиты"}
    title = labels.get(cat, cat)
    await cb.message.answer(f"<b>{title}</b>\n\nВыбери режим:", reply_markup=modes_in_category_kb(modes))


@router.callback_query(F.data.startswith("mode_select:"))
async def cb_mode_select(cb: types.CallbackQuery):
    await cb.answer()
    try:
        mode_id = int(cb.data.replace("mode_select:", ""))
    except ValueError:
        return
    mode = await get_mode_by_id(mode_id)
    if not mode:
        await cb.message.answer("Режим не найден.", reply_markup=back_to_main_kb())
        return
    await set_mode(cb.from_user.id, mode_id)
    await cb.message.answer(
        f"✅ Режим: <b>{mode['emoji']} {mode['name']}</b>\n\nТеперь пиши сообщения — бот будет отвечать в этой роли.",
        reply_markup=back_to_main_kb())


@router.callback_query(F.data == "mode_custom_edit")
async def cb_custom_edit(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(CustomModeStates.enter_prompt)
    await cb.message.answer(
        "✏️ Напиши системный промпт для своего режима (до 2000 символов). Бот будет следовать этим инструкциям.\n\nОтправь /cancel чтобы отменить.")


@router.callback_query(F.data == "mode_custom_delete")
async def cb_custom_delete(cb: types.CallbackQuery):
    await cb.answer()
    await set_custom_mode(cb.from_user.id, None)
    await cb.message.answer("✅ Кастомный режим удалён. Используется обычный ассистент.", reply_markup=back_to_main_kb())


@router.message(StateFilter(CustomModeStates.enter_prompt), F.text, ~F.text.startswith("/"))
async def mode_enter_prompt(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()[:2000]
    if not text:
        await message.answer("Введи непустой текст.")
        return
    await set_custom_mode(message.from_user.id, text)
    await state.clear()
    await message.answer(
        f"✅ Установлено. Бот будет следовать инструкции:\n<i>{text[:200]}{'…' if len(text) > 200 else ''}</i>",
        reply_markup=back_to_main_kb())


@router.message(StateFilter(CustomModeStates.enter_prompt), ~F.text)
async def mode_non_text(message: types.Message, state: FSMContext):
    await message.answer("✏️ Отправь текст для системного промпта. Или /cancel для отмены.")


@router.message(StateFilter(CustomModeStates.enter_prompt), F.text.startswith("/cancel"))
async def mode_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=back_to_main_kb())


