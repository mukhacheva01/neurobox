"""НейроБокс — /save, /favorites (избранное), /export (экспорт истории)."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.bot.services.chat_service import (
    append_chat_message,
    get_chat_history,
    get_chat_history_for_export,
    get_saved_prompt,
    get_system_prompt,
    list_saved_prompts,
    save_prompt,
)
from shared.domain.credits import (
    CREDIT_PRICES,
    get_or_create_user,
    get_user_model,
    spend_credits,
)
from shared.providers.openai_text import generate_text

router = Router()


async def _send_favorites(target: types.Message, user_id: int) -> None:
    prompts = await list_saved_prompts(user_id)
    if not prompts:
        await target.answer("📋 Избранного пока нет. Сохраняй промпты командой /save или кнопкой в чате.")
        return

    b = InlineKeyboardBuilder()
    for p in prompts:
        b.row(types.InlineKeyboardButton(text=f"📌 {p['title'][:40]}", callback_data=f"run_saved_{p['id']}"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    await target.answer("⭐️ <b>Избранное</b> — нажми, чтобы отправить промпт в чат:", reply_markup=b.as_markup())


async def _send_export(target: types.Message, user_id: int) -> None:
    rows = await get_chat_history_for_export(user_id)
    if not rows:
        await target.answer("История диалога пуста.")
        return

    lines = []
    for r in rows:
        role = "Вы" if r["role"] == "user" else "Бот"
        ts = r["created_at"].strftime("%Y-%m-%d %H:%M") if hasattr(r["created_at"], "strftime") else str(r["created_at"])
        lines.append(f"[{ts}] {role}:\n{r['content']}\n")

    content = "\n".join(lines)
    if len(content) > 50 * 1024:
        content = content[: 50 * 1024] + "\n\n... (файл обрезан)"

    buf = BytesIO(content.encode("utf-8"))
    fname = f"neurobox_chat_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    await target.answer_document(BufferedInputFile(buf.getvalue(), filename=fname), caption="📤 История диалога")


@router.message(Command("favorites"))
async def cmd_favorites(message: types.Message):
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await _send_favorites(message, message.from_user.id)


@router.message(Command("export"))
async def cmd_export(message: types.Message):
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await _send_export(message, message.from_user.id)


@router.message(Command("save"))
async def cmd_save(message: types.Message):
    """Сохранить промпт в избранное: /save текст или /save в ответ на сообщение."""
    user_id = message.from_user.id
    await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)

    content = ""
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1:
        content = parts[1].strip()

    if not content and message.reply_to_message:
        content = ((message.reply_to_message.text or "") or (message.reply_to_message.caption or "")).strip()

    if not content:
        history = await get_chat_history_for_export(user_id, limit=20)
        for row in reversed(history):
            if row["role"] == "user":
                candidate = (row["content"] or "").strip()
                if candidate and not candidate.startswith("/save"):
                    content = candidate
                    break

    if not content:
        await message.answer("💾 Пример: <code>/save Напиши продающий оффер для Telegram-бота</code>")
        return

    title = content.splitlines()[0][:60]
    pid = await save_prompt(user_id, title=title, content=content[:5000])
    await message.answer(f"✅ Сохранил в избранное (ID: {pid}). Открыть: /favorites")


@router.callback_query(F.data.in_({"screen_favorites", "favorites"}))
async def cb_screen_favorites(cb: types.CallbackQuery):
    await cb.answer()
    await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.first_name)
    await _send_favorites(cb.message, cb.from_user.id)


@router.callback_query(F.data.startswith("run_saved_"))
async def cb_run_saved(cb: types.CallbackQuery):
    pid = int(cb.data.replace("run_saved_", ""))
    prompt_row = await get_saved_prompt(cb.from_user.id, pid)
    await cb.answer()
    if not prompt_row:
        await cb.message.answer("Промпт не найден.")
        return

    user_id = cb.from_user.id
    prompt = prompt_row["content"]

    model = await get_user_model(user_id, "text")
    cost = CREDIT_PRICES.get(model, 1)
    spend = await spend_credits(user_id, model, f"Избранное: {prompt[:50]}")
    if not spend["ok"]:
        if spend.get("message"):
            await cb.message.answer(spend["message"])
            return
        await cb.message.answer("😔 Недостаточно кредитов для запуска избранного.")
        return

    await cb.message.chat.do("typing")
    history = await get_chat_history(user_id)
    system_prompt = await get_system_prompt(user_id)
    result = await generate_text(prompt, model, history=history, system_prompt=system_prompt)
    if not result["ok"]:
        await cb.message.answer(f"❌ {result['error']}")
        return

    await append_chat_message(user_id, "user", prompt)
    await append_chat_message(user_id, "assistant", result["text"])

    remaining = spend.get("bought", 0) + spend.get("free", 0)
    text = result["text"]
    if len(text) > 4000:
        text = text[:4000] + "\n\n... (обрезано)"
    await cb.message.answer(text + f"\n\n<i>💰 −{cost} CR | Остаток: {remaining} CR | {model}</i>")


@router.callback_query(F.data == "export_chat")
async def cb_export(cb: types.CallbackQuery):
    await cb.answer()
    await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.first_name)
    await _send_export(cb.message, cb.from_user.id)
