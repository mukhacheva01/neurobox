"""НейроБокс — Персоны AI (бывший /mode), свой промпт (бывший /setprompt).
Доступ через Reply-кнопку «🎭 Режим чата» и callback «mode_open»."""
from aiogram import F, Router, types

from services.bot.services.chat_service import set_system_prompt

router = Router()

PERSONAS = [
    ("Программист", "Ты — опытный программист. Помогаешь с кодом, отладкой, архитектурой. Отвечай кратко, с примерами кода."),
    ("Копирайтер", "Ты — копирайтер. Пишешь продающие и информационные тексты. Стиль ясный и убедительный."),
    ("Переводчик", "Ты — профессиональный переводчик. Переводишь точно и естественно между русским и другими языками."),
    ("Репетитор", "Ты — терпеливый репетитор. Объясняешь темы по шагам, проверяешь понимание."),
    ("Юрист", "Ты — юрист. Даёшь общие пояснения по праву, не заменяя консультацию специалиста."),
    ("Маркетолог", "Ты — маркетолог. Помогаешь с стратегией, контентом, аналитикой."),
    ("Психолог", "Ты — поддерживающий психолог. Слушаешь, задаёшь вопросы, не ставишь диагнозы."),
    ("Шеф-повар", "Ты — шеф-повар. Делишься рецептами и советами по готовке."),
    ("Дизайнер", "Ты — дизайнер. Помогаешь с композицией, цветом, типографикой, UI/UX."),
    ("English Teacher", "You are an English teacher. Explain grammar, vocabulary, and practice with the user. Use English and Russian when helpful."),
    ("Стартап-ментор", "Ты — ментор стартапов. Помогаешь с идеей, MVP, метриками, питчем."),
]

## /mode убран — доступен через Reply-кнопку «🎭 Режим чата» и callback «mode_open»

@router.callback_query(F.data.startswith("persona_"))
async def cb_persona(cb: types.CallbackQuery):
    name = cb.data.replace("persona_", "")
    await cb.answer()
    if name == "reset":
        await set_system_prompt(cb.from_user.id, None)
        await cb.message.answer("✅ Режим сброшен. Бот снова в обычном режиме.")
        return
    for pname, prompt in PERSONAS:
        if pname == name:
            await set_system_prompt(cb.from_user.id, prompt)
            await cb.message.answer(f"✅ Режим: <b>{name}</b>\n\nТеперь пиши сообщения — бот будет отвечать в этой роли.")
            return
    await cb.message.answer("Режим не найден.")

## /setprompt убран — доступен через callback «mode_custom_edit» в меню режимов
