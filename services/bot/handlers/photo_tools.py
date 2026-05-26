"""НейроБокс — /rmbg, /style, /ocr (ответ на фото), контекстное меню для фото без подписи."""
import asyncio
import base64

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile

from shared.domain.credits import (
    get_or_create_user,
    refund_spend_credits,
    spend_credits,
)
from shared.domain.telemetry import elapsed_ms, log_ai_error, log_ai_success
from shared.providers.openrouter_image import edit_openrouter_image
from shared.providers.openrouter_image import (
    remove_background_openrouter as remove_background,
)


def _photo_input(url_or_data_uri):
    """Convert base64 data URI to BufferedInputFile for Telegram."""
    if isinstance(url_or_data_uri, str) and url_or_data_uri.startswith("data:image/"):
        try:
            b64_part = url_or_data_uri.split(",", 1)[1] if "," in url_or_data_uri else url_or_data_uri
            raw_bytes = base64.b64decode(b64_part)
            return BufferedInputFile(raw_bytes, filename="image.png")
        except Exception:
            pass
    return url_or_data_uri

router = Router()

RMBG_CR = 5
STYLE_CR = 8

async def _download_photo_bytes(bot, file_id: str) -> bytes:
    file = await bot.get_file(file_id)
    buf = await bot.download_file(file.file_path)
    return buf.read()


async def _do_rmbg_from_file_id(bot, user_id: int, file_id: str, target_message: types.Message) -> None:
    """Удаление фона по file_id (из контекстного меню «Убрать фон»)."""
    await get_or_create_user(user_id, None, None)
    spend = await spend_credits(user_id, "rmbg", "rmbg")
    if not spend["ok"]:
        if spend.get("message"):
            await target_message.answer(spend["message"])
            return
        from services.bot.utils.paywall import smart_paywall_message
        text, kb = await smart_paywall_message("Убрать фон с фото", RMBG_CR, user_id)
        await target_message.answer(text, reply_markup=kb)
        return
    import time as _time
    _started = _time.monotonic()
    status_msg = await target_message.answer("🖼 Удаляю фон...")
    try:
        data = await _download_photo_bytes(bot, file_id)
        result = await asyncio.wait_for(remove_background(image_bytes=data), timeout=200)
    except asyncio.TimeoutError:
        await log_ai_error(user_id, "rmbg", "rmbg", "rmbg_file_id", RMBG_CR, elapsed_ms(_started), "Таймаут rmbg", status="timeout", error_event="rmbg_error")
        if spend.get("cost", 0) and not spend.get("trial"):
            await refund_spend_credits(user_id, spend, "таймаут rmbg")
        await status_msg.edit_text("⏱ Удаление фона заняло слишком долго.\n\n💚 Кредиты возвращены.")
        return
    except Exception as e:
        import structlog
        await log_ai_error(user_id, "rmbg", "rmbg", "rmbg_file_id", RMBG_CR, elapsed_ms(_started), str(e), status="exception", error_event="rmbg_error")
        structlog.get_logger().error("rmbg error", error=str(e), user_id=user_id)
        if spend.get("cost", 0) and not spend.get("trial"):
            await refund_spend_credits(user_id, spend, "ошибка rmbg")
        await status_msg.edit_text("❌ Ошибка обработки фото.\n\n💚 Кредиты возвращены.")
        return
    if not result["ok"]:
        await log_ai_error(user_id, "rmbg", "rmbg", "rmbg_file_id", RMBG_CR, elapsed_ms(_started), result.get("error", "Ошибка"), error_event="rmbg_error")
        await status_msg.edit_text(f"❌ {result['error']}")
        if spend.get("cost", 0) and not spend.get("trial"):
            await refund_spend_credits(user_id, spend, "ошибка rmbg")
        return
    remaining = spend.get("bought", 0) + spend.get("free", 0)
    await log_ai_success(user_id, "rmbg", "rmbg", "rmbg_file_id", RMBG_CR, elapsed_ms(_started))
    await status_msg.edit_text("✅ Готово!")
    await target_message.answer_photo(photo=_photo_input(result["image_url"]), caption=f"🖼 Фон удалён | −{RMBG_CR} CR | Остаток: {remaining} CR")


async def _do_rmbg(message: types.Message, photo: types.PhotoSize) -> None:
    """Общая логика удаления фона по photo (PhotoSize)."""
    user_id = message.from_user.id
    await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)
    spend = await spend_credits(user_id, "rmbg", "rmbg")
    if not spend["ok"]:
        if spend.get("message"):
            await message.answer(spend["message"])
            return
        from services.bot.utils.paywall import smart_paywall_message
        text, kb = await smart_paywall_message("Убрать фон с фото", RMBG_CR, user_id)
        await message.answer(text, reply_markup=kb)
        return
    import time as _time
    _started = _time.monotonic()
    await message.answer("🖼 Удаляю фон...")
    try:
        data = await _download_photo_bytes(message.bot, photo.file_id)
        result = await asyncio.wait_for(remove_background(image_bytes=data), timeout=200)
    except asyncio.TimeoutError:
        await log_ai_error(user_id, "rmbg", "rmbg", "rmbg", RMBG_CR, elapsed_ms(_started), "Таймаут rmbg", status="timeout", error_event="rmbg_error")
        if spend.get("cost", 0) and not spend.get("trial"):
            await refund_spend_credits(user_id, spend, "таймаут rmbg")
        await message.answer("⏱ Удаление фона заняло слишком долго.\n\n💚 Кредиты возвращены.")
        return
    except Exception as e:
        import structlog
        await log_ai_error(user_id, "rmbg", "rmbg", "rmbg", RMBG_CR, elapsed_ms(_started), str(e), status="exception", error_event="rmbg_error")
        structlog.get_logger().error("rmbg error", error=str(e), user_id=user_id)
        if spend.get("cost", 0) and not spend.get("trial"):
            await refund_spend_credits(user_id, spend, "ошибка rmbg")
        await message.answer("❌ Ошибка обработки фото. Попробуй позже.\n\n💚 Кредиты возвращены.")
        return
    if not result["ok"]:
        await log_ai_error(user_id, "rmbg", "rmbg", "rmbg", RMBG_CR, elapsed_ms(_started), result.get("error", "Ошибка"), error_event="rmbg_error")
        await message.answer(f"❌ {result['error']}")
        if spend.get("cost", 0) and not spend.get("trial"):
            await refund_spend_credits(user_id, spend, "ошибка rmbg")
        return
    remaining = spend.get("bought", 0) + spend.get("free", 0)
    await log_ai_success(user_id, "rmbg", "rmbg", "rmbg", RMBG_CR, elapsed_ms(_started))
    await message.answer_photo(photo=_photo_input(result["image_url"]), caption=f"🖼 Фон удалён | −{RMBG_CR} CR | Остаток: {remaining} CR")


@router.message(Command("rmbg"))
async def cmd_rmbg(message: types.Message):
    if message.reply_to_message and message.reply_to_message.photo:
        await _do_rmbg(message, message.reply_to_message.photo[-1])
        return
    await message.answer(
        "✂️ Чтобы убрать фон:\n"
        "1) отправь фото с подписью <code>/rmbg</code>, или\n"
        "2) ответь <code>/rmbg</code> на сообщение с фото."
    )


@router.message(Command("style"))
async def cmd_style(message: types.Message):
    if not (message.reply_to_message and message.reply_to_message.photo):
        await message.answer("🎨 Ответь командой <code>/style описание</code> на сообщение с фото.")
        return

    parts = (message.text or "").split(maxsplit=1)
    style_prompt = parts[1].strip() if len(parts) > 1 else ""
    if not style_prompt:
        await message.answer("Напиши описание стиля: <code>/style в стиле аниме</code>")
        return

    user_id = message.from_user.id
    await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)
    spend = await spend_credits(user_id, "flux-2-turbo", "style", cost_override=STYLE_CR)
    if not spend["ok"]:
        if spend.get("message"):
            await message.answer(spend["message"])
            return
        from services.bot.utils.paywall import smart_paywall_message
        text, kb = await smart_paywall_message("Стилизация фото", STYLE_CR, user_id)
        await message.answer(text, reply_markup=kb)
        return

    photo = message.reply_to_message.photo[-1]
    image_bytes = await _download_photo_bytes(message.bot, photo.file_id)
    import time as _time
    _started = _time.monotonic()
    await message.answer("🎨 Стилизую фото...")
    try:
        result = await asyncio.wait_for(edit_openrouter_image(image_bytes, style_prompt), timeout=120)
    except asyncio.TimeoutError:
        await log_ai_error(user_id, "image_style", "gpt-image", style_prompt[:200], STYLE_CR, elapsed_ms(_started), "Таймаут стилизации", status="timeout", error_event="image_style_error")
        await refund_spend_credits(user_id, spend, "таймаут стилизации")
        await message.answer("⏱ Стилизация заняла слишком долго.\n\n💚 Кредиты возвращены.")
        return

    if not result["ok"]:
        await log_ai_error(user_id, "image_style", "gpt-image", style_prompt[:200], STYLE_CR, elapsed_ms(_started), result.get("error", "Ошибка"), error_event="image_style_error")
        await refund_spend_credits(user_id, spend, "ошибка стилизации")
        await message.answer(f"❌ {result['error']}\n\n💚 Кредиты возвращены.")
        return

    remaining = spend.get("bought", 0) + spend.get("free", 0)
    await log_ai_success(user_id, "image_style", "gpt-image", style_prompt[:200], STYLE_CR, elapsed_ms(_started))
    await message.answer_photo(
        photo=_photo_input(result["image_url"]),
        caption=f"🎨 Стиль: {style_prompt[:100]}\n\n−{STYLE_CR} CR | Остаток: {remaining} CR",
    )


@router.message(Command("ocr"))
async def cmd_ocr(message: types.Message):
    if not (message.reply_to_message and message.reply_to_message.photo):
        await message.answer("📄 Ответь командой <code>/ocr</code> на сообщение с фото.")
        return
    await cmd_ocr_reply(message)


@router.message(F.photo, F.func(lambda m: (m.caption or "").strip().lower() in ("убери фон", "rmbg", "/rmbg", "удалить фон")))
async def msg_rmbg_caption(message: types.Message):
    await _do_rmbg(message, message.photo[-1])


@router.message(F.reply_to_message.photo, F.func(lambda m: (m.text or "").strip().lower() in ("убери фон", "/rmbg", "удалить фон")))
async def msg_rmbg_reply(message: types.Message):
    await _do_rmbg(message, message.reply_to_message.photo[-1])


@router.message(F.reply_to_message.photo, F.func(lambda m: ((m.text or "").strip().startswith("стилизуй ") and len((m.text or "").strip()) > 9)))
async def cmd_style_reply(message: types.Message):
    """Стилизация фото — fal image-to-image по описанию (аниме, масло, пиксель и т.д.)."""
    user_id = message.from_user.id
    await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)
    spend = await spend_credits(user_id, "flux-2-turbo", "style", cost_override=STYLE_CR)
    if not spend["ok"]:
        if spend.get("message"):
            await message.answer(spend["message"])
            return
        from services.bot.utils.paywall import smart_paywall_message
        text, kb = await smart_paywall_message("Стилизация фото", STYLE_CR, user_id)
        await message.answer(text, reply_markup=kb)
        return
    style_prompt = (message.text or "").strip().replace("стилизуй", "", 1).strip()
    if not style_prompt:
        await message.answer("Напиши описание стиля: например «в стиле аниме» или «масляная живопись».")
        await refund_spend_credits(user_id, spend, "отмена: нет описания")
        return
    photo = message.reply_to_message.photo[-1]
    image_bytes = await _download_photo_bytes(message.bot, photo.file_id)
    import time as _time
    _started = _time.monotonic()
    await message.answer("🎨 Стилизую фото...")
    try:
        result = await asyncio.wait_for(edit_openrouter_image(image_bytes, style_prompt), timeout=120)
    except asyncio.TimeoutError:
        await log_ai_error(user_id, "image_style", "gpt-image", style_prompt[:200], STYLE_CR, elapsed_ms(_started), "Таймаут стилизации", status="timeout", error_event="image_style_error")
        await refund_spend_credits(user_id, spend, "таймаут стилизации")
        await message.answer("⏱ Стилизация заняла слишком долго.\n\n💚 Кредиты возвращены.")
        return
    if not result["ok"]:
        await log_ai_error(user_id, "image_style", "gpt-image", style_prompt[:200], STYLE_CR, elapsed_ms(_started), result.get("error", "Ошибка"), error_event="image_style_error")
        await refund_spend_credits(user_id, spend, "ошибка стилизации")
        await message.answer(f"❌ {result['error']}\n\n💚 Кредиты возвращены.")
        return
    remaining = spend.get("bought", 0) + spend.get("free", 0)
    await log_ai_success(user_id, "image_style", "gpt-image", style_prompt[:200], STYLE_CR, elapsed_ms(_started))
    await message.answer_photo(
        photo=_photo_input(result["image_url"]),
        caption=f"🎨 Стиль: {style_prompt[:100]}\n\n−{STYLE_CR} CR | Остаток: {remaining} CR",
    )

@router.message(F.reply_to_message.photo, F.func(lambda m: ((m.text or "").strip().lower() == "текст с фото" or (m.text or "").strip().lower() == "ocr")))
async def cmd_ocr_reply(message: types.Message):
    """Текст из фото — OpenAI Vision."""
    user_id = message.from_user.id
    await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)
    OCR_CR = 3
    spend = await spend_credits(user_id, "ocr", "ocr")
    if not spend["ok"]:
        if spend.get("message"):
            await message.answer(spend["message"])
            return
        from services.bot.utils.paywall import smart_paywall_message
        text, kb = await smart_paywall_message("Текст с фото (OCR)", OCR_CR, user_id)
        await message.answer(text, reply_markup=kb)
        return
    photo = message.reply_to_message.photo[-1]
    image_bytes = await _download_photo_bytes(message.bot, photo.file_id)
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_uri = f"data:image/jpeg;base64,{b64}"
    import time as _time

    from shared.providers.openai_text import _get_openrouter_client
    _started = _time.monotonic()
    await message.answer("📄 Извлекаю текст...")
    try:
        client = _get_openrouter_client()
        r = await asyncio.wait_for(client.chat.completions.create(
            model="openai/gpt-4.1-nano",
            messages=[{"role": "user", "content": [{"type": "text", "text": "Извлеки весь текст с изображения. Сохрани структуру (абзацы, списки). Ответь только текстом, без пояснений."}, {"type": "image_url", "image_url": {"url": data_uri}}]}],
            max_tokens=1024), timeout=60)
        text = r.choices[0].message.content or "Текст не распознан."
    except asyncio.TimeoutError:
        await log_ai_error(user_id, "ocr", "ocr", "ocr", OCR_CR, elapsed_ms(_started), "Таймаут OCR", status="timeout", error_event="ocr_error")
        if spend.get("cost", 0) and not spend.get("trial"):
            await refund_spend_credits(user_id, spend, "таймаут OCR")
        await message.answer("⏱ Извлечение текста заняло слишком долго.\n\n💚 Кредиты возвращены.")
        return
    except Exception as e:
        import structlog
        await log_ai_error(user_id, "ocr", "ocr", "ocr", OCR_CR, elapsed_ms(_started), str(e), status="exception", error_event="ocr_error")
        structlog.get_logger().error("ocr error", error=str(e), user_id=user_id)
        if spend.get("cost", 0) and not spend.get("trial"):
            await refund_spend_credits(user_id, spend, "ошибка OCR")
        await message.answer("❌ Ошибка распознавания текста. Попробуй позже.\n\n💚 Кредиты возвращены.")
        return
    remaining = spend.get("bought", 0) + spend.get("free", 0)
    await log_ai_success(user_id, "ocr", "ocr", "ocr", OCR_CR, elapsed_ms(_started))
    await message.answer(f"📄 <b>Текст с фото:</b>\n\n{text}\n\n<i>−{OCR_CR} CR | Остаток: {remaining} CR</i>")


@router.callback_query(F.data.startswith("photo_action:"))
async def cb_photo_action(cb: types.CallbackQuery):
    """Контекстное меню фото без подписи: Убрать фон, Описать, Сгенерировать похожее, Анимировать."""
    await cb.answer()
    user_id = cb.from_user.id
    action = (cb.data or "").replace("photo_action:", "").strip()
    from shared.redis.store import _get_redis
    r = await _get_redis()
    file_id = None
    if r:
        file_id = await r.get(f"photo_pending:{user_id}")
        if file_id and hasattr(file_id, "decode"):
            file_id = file_id.decode()
        if file_id:
            await r.delete(f"photo_pending:{user_id}")
    if action == "rmbg":
        if file_id:
            await _do_rmbg_from_file_id(cb.bot, user_id, file_id, cb.message)
        else:
            await cb.message.answer("⏱ Фото устарело. Отправь фото заново и выбери «Убрать фон».")
    elif action == "describe":
        if file_id:
            from services.bot.handlers.text import run_photo_describe
            await run_photo_describe(cb.bot, user_id, file_id, cb.message)
        else:
            await cb.message.answer("⏱ Фото устарело. Отправь фото заново и выбери «Описать».")
    elif action == "similar":
        if r and file_id:
            await r.delete(f"photo_pending:{user_id}")
        await cb.message.answer(
            "🎨 <b>Сгенерировать похожее</b>\n\n"
            "Открой раздел 🎨 Картинка и отправь это фото с подписью, например:\n"
            "«Сгенерируй в том же стиле» или «Сделай похожий пейзаж».")
    elif action == "animate":
        if r and file_id:
            await r.delete(f"photo_pending:{user_id}")
        from shared.config import settings
        if settings.enable_video:
            await cb.message.answer(
                "🎬 <b>Анимировать фото</b>\n\n"
                "Открой раздел 🎬 Видео и отправь фото с подписью:\n"
                "<code>/video описание движения</code>\n\n"
                "Например: /video человек машет рукой")
        else:
            await cb.message.answer(
                "🎬 <b>Анимация фото</b> временно недоступна.\n\n"
                "Сейчас можно использовать описание фото, удаление фона и генерацию похожих изображений."
            )
