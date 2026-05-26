"""НейроБокс — поддержка и feedback."""
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from shared.db.database import get_pool
from shared.config import settings
from shared.domain.admin_runtime import get_admin_text
from shared.domain.credits import get_or_create_user

router = Router()
MAX_FEEDBACK_LEN = 2000


def _support_kb():
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="🤖 Написать в поддержку", url="https://t.me/ai_xup_help_bot"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    return b.as_markup()


async def _support_text() -> str:
    return await get_admin_text(
        "support_text",
        (
            "💬 <b>Поддержка</b>\n\n"
            "Если у тебя есть вопросы, предложения или проблемы — напиши нам!\n\n"
            "🤖 Бот поддержки: @ai_xup_help_bot\n\n"
            "Обычно отвечаем в течение нескольких часов."
        ),
    )


@router.callback_query(F.data.in_({"screen_feedback", "screen_support"}))
async def cb_screen_feedback(cb: types.CallbackQuery):
    await cb.answer()
    await cb.message.answer(await _support_text(), reply_markup=_support_kb())


@router.message(Command("paysupport"))
async def cmd_paysupport(message: types.Message):
    await message.answer(await _support_text(), reply_markup=_support_kb())


def _is_feedback_msg(msg: types.Message) -> bool:
    return (msg.text or "").strip().lower().startswith("обратная связь:")


@router.message(F.text, _is_feedback_msg)
async def msg_feedback_inline(message: types.Message):
    text = (message.text or "").strip()
    idx = text.lower().find("обратная связь:")
    body = text[idx + len("обратная связь:"):].strip()
    if not body:
        await message.answer("Добавь текст после «обратная связь:»")
        return
    if len(body) > MAX_FEEDBACK_LEN:
        await message.answer(f"⚠️ Сообщение слишком длинное (макс. {MAX_FEEDBACK_LEN} символов).")
        return
    user_id = message.from_user.id
    await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO feedback (user_id, text) VALUES ($1, $2)",
            user_id, body[:MAX_FEEDBACK_LEN],
        )
    await message.answer("✅ Спасибо! Мы учли твой отзыв.")
    admin_ids = getattr(settings, "admin_id_list", None) or []
    if admin_ids:
        try:
            for aid in admin_ids:
                try:
                    await message.bot.send_message(
                        aid,
                        f"📩 <b>Feedback</b> от {message.from_user.id} (@{message.from_user.username or '—'}):\n\n{body[:1500]}",
                    )
                except Exception:
                    pass
        except Exception:
            pass
