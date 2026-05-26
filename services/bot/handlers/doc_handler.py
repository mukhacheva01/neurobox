"""НейроБокс — /doc (сгенерировать документ), загрузка PDF/DOCX (суммаризация)."""
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile

from services.bot.services.doc_extract import extract_text_from_file
from shared.domain.credits import (
    get_or_create_user,
    get_user_model,
    refund_credits,
    spend_credits,
)
from shared.providers.openai_text import generate_text

router = Router()
DOC_FILE_MAX_BYTES = 10 * 1024 * 1024
DOC_FILE_CR = 8
DOC_GEN_CR = 6

@router.message(Command("doc"))
async def cmd_doc_create(message: types.Message):
    """Сгенерировать текстовый документ по описанию: /doc тема."""
    args = (message.text or "").split(maxsplit=1)
    task = args[1].strip() if len(args) > 1 else ""
    if not task:
        await message.answer("📄 Пример: <code>/doc коммерческое предложение для IT-аутсорса</code>")
        return

    user_id = message.from_user.id
    await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)
    spend = await spend_credits(user_id, "gpt-5-nano", "doc_create", cost_override=DOC_GEN_CR)
    if not spend["ok"]:
        if spend.get("message"):
            await message.answer(spend["message"])
            return
        from services.bot.utils.paywall import smart_paywall_message
        text, kb = await smart_paywall_message("Создание документа", DOC_GEN_CR, user_id)
        await message.answer(text, reply_markup=kb)
        return

    model = await get_user_model(user_id, "text")
    prompt = (
        "Составь готовый текст документа на русском языке по задаче пользователя. "
        "Структура: заголовок, краткое введение, основные разделы с подзаголовками, вывод/next steps. "
        "Стиль деловой и конкретный. Без дисклеймеров.\n\n"
        f"Задача: {task[:800]}"
    )
    result = await generate_text(prompt, model, history=None)
    if not result["ok"]:
        await refund_credits(user_id, DOC_GEN_CR, "ошибка генерации документа")
        await message.answer(f"❌ {result['error']}\n\n💚 Кредиты возвращены.")
        return

    body = (result.get("text") or "").strip()
    if not body:
        await refund_credits(user_id, DOC_GEN_CR, "пустой документ")
        await message.answer("❌ Не удалось сгенерировать документ.\n\n💚 Кредиты возвращены.")
        return

    remaining = spend.get("bought", 0) + spend.get("free", 0)
    filename = "document.txt"
    await message.answer_document(
        BufferedInputFile(body.encode("utf-8"), filename=filename),
        caption=f"📄 Документ готов\n\n<i>−{DOC_GEN_CR} CR | Остаток: {remaining} CR</i>",
    )


@router.message(F.document)
async def cmd_doc_upload(message: types.Message):
    """Принять PDF или DOCX — извлечь текст и прислать краткое содержание."""
    doc = message.document
    if not doc or not doc.file_name:
        return
    fn = doc.file_name or ""
    if not (fn.lower().endswith(".pdf") or fn.lower().endswith(".docx")):
        await message.answer("📄 Поддерживаются только PDF и DOCX. Отправь такой файл — пришлю краткое содержание.")
        return
    if (doc.file_size or 0) > DOC_FILE_MAX_BYTES:
        await message.answer(f"⚠️ Файл слишком большой (макс. {DOC_FILE_MAX_BYTES // (1024*1024)} МБ).")
        return
    user_id = message.from_user.id
    await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)
    spend = await spend_credits(user_id, "gpt-5-nano", "doc_upload", cost_override=DOC_FILE_CR)
    if not spend["ok"]:
        if spend.get("message"):
            await message.answer(spend["message"])
            return
        await message.answer(f"😔 Нужно {DOC_FILE_CR} CR для разбора документа. Баланс: /balance")
        return
    await message.chat.do("typing")
    try:
        file = await message.bot.get_file(doc.file_id)
        buf = await message.bot.download_file(file.file_path)
        data = buf.read()
    except Exception as e:
        await refund_credits(user_id, DOC_FILE_CR, "ошибка загрузки файла")
        await message.answer(f"❌ Не удалось скачать файл: {e}\n\n💚 Кредиты возвращены.")
        return
    text, err = extract_text_from_file(fn, data)
    if err:
        await refund_credits(user_id, DOC_FILE_CR, "ошибка извлечения текста")
        await message.answer(f"❌ {err}\n\n💚 Кредиты возвращены.")
        return
    model = await get_user_model(user_id, "text")
    prompt = (
        "Ниже текст из загруженного документа. Дай структурированное краткое содержание: "
        "основные тезисы, ключевые выводы, важные факты. Язык — русский. Без вступления, только суть.\n\n"
        "---\n\n" + text[:50000]
    )
    result = await generate_text(prompt, model, history=None)
    if not result["ok"]:
        await refund_credits(user_id, DOC_FILE_CR, "ошибка генерации")
        await message.answer(f"❌ {result['error']}\n\n💚 Кредиты возвращены.")
        return
    remaining = spend.get("bought", 0) + spend.get("free", 0)
    summary = result["text"]
    await message.answer(
        f"📄 <b>Краткое содержание</b> ({fn})\n\n{summary}\n\n"
        f"<i>−{DOC_FILE_CR} CR | Остаток: {remaining} CR</i>",
    )
