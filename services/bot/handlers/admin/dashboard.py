"""Админка: назад в меню."""
from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from services.bot.handlers.start import _admin_denied, _is_admin
from services.bot.keyboards.admin import admin_dashboard_kb

router = Router()


@router.callback_query(F.data == "admin:web_panel")
async def cb_admin_web_panel(cb: types.CallbackQuery):
    """Подсказка, если ADMIN_PANEL_URL не задан."""
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, "admin:web_panel")
        return
    await cb.answer()
    await cb.message.answer(
        "🌐 <b>Веб-админка</b>\n\n"
        "Домена нет — не страшно. Добавь в <code>.env</code>:\n"
        "<code>ADMIN_PANEL_URL=http://IP_СЕРВЕРА:8091</code>\n\n"
        "Подставь вместо IP_СЕРВЕРА твой IP (например <code>http://123.45.67.89:8091</code>). "
        "Открывай эту ссылку в браузере на телефоне или компьютере — логин <code>admin</code>, пароль из ADMIN_PANEL_PASSWORD в .env.\n\n"
        "После правки .env перезапусти бота — кнопка станет ссылкой.",
    )


@router.callback_query(F.data == "admin:back")
async def cb_admin_back(cb: types.CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        await _admin_denied(cb, "admin:back")
        return
    await cb.answer()
    await state.clear()
    await cb.message.answer("🔧 <b>АДМИН-ПАНЕЛЬ</b>\n\nВыбери раздел:", reply_markup=admin_dashboard_kb())
