"""НейроБокс — Text message handler: чат с историей, /clear, лимит длины, стриминг, фото/видео."""
import asyncio
import base64
import contextlib
import time

import structlog
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.bot.keyboards.main import buy_credits_kb
from services.bot.services.chat_service import (
    append_chat_pair,
    clear_chat_history,
    get_chat_history,
    get_system_prompt,
)
from services.bot.utils.paywall import soft_paywall_hint
from shared.config import settings
from shared.domain.credits import (
    CREDIT_PRICES,
    get_or_create_user,
    get_user_model,
    refund_credits,
    refund_spend_credits,
    spend_credits,
)
from shared.domain.telemetry import elapsed_ms, log_ai_error, log_ai_success
from shared.providers.openai_text import (
    generate_text,
    generate_text_stream,
    is_streaming_model,
)

_log = structlog.get_logger()
# Модели, поддерживающие редактирование фото
_OPENAI_EDIT_MODELS = {"gpt-image", "dall-e-3"}
router = Router()
PROMPT_MAX_CHARS = getattr(settings, "prompt_max_chars", 10000)
RESPONSE_MAX_CHARS = getattr(settings, "response_max_chars", 4000)
STREAM_EDIT_INTERVAL = 1.2


def _gen_lock(user_id: int):
    """Per-user generation lock (Redis). Защита от двойного списания при быстрых кликах."""
    from shared.redis.store import gen_lock
    return gen_lock(user_id, key_prefix="gen_lock", ttl_sec=120)


async def _refund_if_needed(user_id: int, spend: dict, reason: str) -> bool:
    """Возврат кредитов если были списаны и не триал/безлимит. Возвращает True если refund произошёл."""
    refunded = await refund_spend_credits(user_id, spend, reason)
    return bool(refunded)


async def _save_response_rating(user_id: int, chat_id: int, message_id: int, rating: str) -> bool:
    """Сохранить оценку ответа (up/down). Возвращает True если сохранено."""
    from shared.db.database import get_pool
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO response_ratings (user_id, chat_id, message_id, rating) VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (user_id, chat_id, message_id) DO UPDATE SET rating = $4",
                user_id, chat_id, message_id, rating)
    except Exception:
        return False
    return True


@router.callback_query(F.data.startswith("rate_"))
async def cb_rate(cb: types.CallbackQuery):
    parts = cb.data.split(":")
    # Формат: rate_up:USER_ID или rate_down:USER_ID (новый) или rate_up/rate_down (старый)
    if len(parts) == 2:
        action, owner_id_str = parts
        try:
            owner_id = int(owner_id_str)
            if cb.from_user.id != owner_id:
                await cb.answer("Оценить может только автор запроса.", show_alert=True)
                return
        except ValueError:
            pass
        rating = "up" if "up" in action else "down"
    else:
        rating = "up" if cb.data == "rate_up" else "down"
    await _save_response_rating(cb.from_user.id, cb.message.chat.id, cb.message.message_id, rating)
    await cb.answer("Спасибо за оценку!" if rating == "up" else "Ок, учтём")


## /clear поддерживается + доступен через Reply-кнопку «🗑 Очистить контекст» и callback «clear_confirm»


@router.message(Command("clear"))
async def cmd_clear(message: types.Message):
    await clear_chat_history(message.from_user.id)
    await message.answer("🗑 Контекст очищен. Начнём с чистого листа!")


@router.callback_query(F.data.startswith("clear_yes:"))
async def cb_clear_yes(cb: types.CallbackQuery):
    owner_id = int(cb.data.split(":")[1])
    if cb.from_user.id != owner_id:
        await cb.answer("Это не твоя кнопка.", show_alert=True)
        return
    await clear_chat_history(cb.from_user.id)
    await cb.answer()
    await cb.message.edit_text("🗑 Контекст очищен. Начнём с чистого листа!")


@router.callback_query(F.data.startswith("clear_no:"))
async def cb_clear_no(cb: types.CallbackQuery):
    owner_id = int(cb.data.split(":")[1])
    if cb.from_user.id != owner_id:
        await cb.answer("Это не твоя кнопка.", show_alert=True)
        return
    await cb.answer()
    await cb.message.edit_text("Отменено.")



@router.callback_query(F.data.startswith("retry:"))
async def cb_retry_last(cb: types.CallbackQuery):
    """Повторить последний запрос после ошибки."""
    owner_id = int(cb.data.split(":")[1])
    if cb.from_user.id != owner_id:
        await cb.answer("Это не твоя кнопка.", show_alert=True)
        return
    await cb.answer("🔄 Повторяю...")
    history = await get_chat_history(owner_id)
    last_prompt = ""
    for msg in reversed(history or []):
        if msg.get("role") == "user":
            last_prompt = msg.get("content", "")
            break
    if not last_prompt:
        await cb.message.answer("Нет предыдущего запроса для повтора. Напиши новый.")
        return
    # Имитируем отправку текстового сообщения
    model = await get_user_model(owner_id, "text")
    cost = CREDIT_PRICES.get(model, 1)
    spend = await spend_credits(owner_id, model, f"Повтор: {last_prompt[:50]}")
    if not spend["ok"]:
        if spend.get("message"):
            await cb.message.answer(spend["message"])
            return
        from services.bot.utils.paywall import smart_paywall_message
        text, kb = await smart_paywall_message("Чат с AI", cost, owner_id)
        await cb.message.answer(text, reply_markup=kb)
        return
    await cb.message.chat.do("typing")
    import time as _time
    gen_start = _time.monotonic()
    system_prompt = await get_system_prompt(owner_id)
    remaining = spend.get("bought", 0) + spend.get("free", 0)
    result = await generate_text(last_prompt, model, history=history, system_prompt=system_prompt)
    if not result["ok"]:
        refunded = await _refund_if_needed(owner_id, spend, "ошибка повтора")
        err_msg = f"❌ {result['error']}"
        if refunded:
            err_msg += "\n\n💚 Кредиты возвращены."
        b = InlineKeyboardBuilder()
        b.row(types.InlineKeyboardButton(text="🔄 Попробовать снова", callback_data=f"retry:{owner_id}"))
        b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
        await cb.message.answer(err_msg, reply_markup=b.as_markup())
        return
    response_text = result["text"]
    elapsed = _time.monotonic() - gen_start
    await append_chat_pair(owner_id, last_prompt, response_text)
    footer = f"\n\n<i>🤖 {model} · −{cost} CR · {elapsed:.1f}с · Остаток: {remaining} CR</i>"
    truncated = len(response_text) > RESPONSE_MAX_CHARS
    if truncated:
        response_text = response_text[:RESPONSE_MAX_CHARS] + "\n\n… <i>(ответ обрезан)</i>"
    rate_b = InlineKeyboardBuilder()
    if truncated:
        rate_b.row(types.InlineKeyboardButton(text="▶️ Продолжить", callback_data=f"continue:{owner_id}"))
    rate_b.row(
        types.InlineKeyboardButton(text="👍", callback_data=f"rate_up:{owner_id}"),
        types.InlineKeyboardButton(text="👎", callback_data=f"rate_down:{owner_id}"),
    )
    await cb.message.answer(response_text + footer, reply_markup=rate_b.as_markup())


@router.callback_query(F.data.startswith("tts_last:"))
async def cb_tts_last(cb: types.CallbackQuery):
    """Озвучить последний ответ бота (TTS Edge бесплатно)."""
    owner_id = int(cb.data.split(":")[1])
    if cb.from_user.id != owner_id:
        await cb.answer("Это не твоя кнопка.", show_alert=True)
        return
    await cb.answer("🔊 Озвучиваю...")
    # Берём последнее сообщение ассистента из истории
    history = await get_chat_history(owner_id)
    last_text = ""
    for msg in reversed(history or []):
        if msg.get("role") == "assistant":
            last_text = msg.get("content", "")[:1000]
            break
    if not last_text:
        await cb.message.answer("Нет текста для озвучки.")
        return
    try:
        from shared.domain.credits import TTS_VOICES, get_user_model
        from shared.providers.edge_tts_provider import generate_speech
        tts_voice = await get_user_model(owner_id, "tts_voice")
        voices = TTS_VOICES.get("edge-tts", {})
        voice_info = voices.get(tts_voice, list(voices.values())[0])
        result = await generate_speech(last_text, voice_info["id"])
        if result.get("ok"):
            from aiogram.types import BufferedInputFile
            audio = BufferedInputFile(result["audio_bytes"], filename="voice.mp3")
            await cb.message.answer_voice(voice=audio, caption="<i>🔊 Озвучка (Edge TTS, бесплатно)</i>")
        else:
            await cb.message.answer(f"❌ {result.get('error', 'Ошибка TTS')}")
    except Exception as e:
        _log.error("tts_last_error", error=str(e)[:200])
        await cb.message.answer("❌ Не удалось озвучить. Попробуй /voice текст.")


@router.callback_query(F.data.startswith("continue:"))
async def cb_continue(cb: types.CallbackQuery):
    """Продолжить обрезанный ответ."""
    owner_id = int(cb.data.split(":")[1])
    if cb.from_user.id != owner_id:
        await cb.answer("Это не твоя кнопка.", show_alert=True)
        return
    await cb.answer("▶️ Продолжаю...")
    history = await get_chat_history(owner_id)
    system_prompt = await get_system_prompt(owner_id)
    model = await get_user_model(owner_id, "text")
    cost = CREDIT_PRICES.get(model, 1)
    spend = await spend_credits(owner_id, model, "Продолжение ответа")
    if not spend["ok"]:
        if spend.get("message"):
            await cb.message.answer(spend["message"])
            return
        await cb.message.answer("😔 Не хватает кредитов для продолжения.", reply_markup=buy_credits_kb())
        return
    await cb.message.chat.do("typing")
    result = await generate_text("продолжи", model, history=history, system_prompt=system_prompt)
    if not result["ok"]:
        await _refund_if_needed(owner_id, spend, "ошибка продолжения")
        await cb.message.answer(f"❌ {result['error']}")
        return
    text = result["text"]
    await append_chat_pair(owner_id, "продолжи", text)
    if len(text) > RESPONSE_MAX_CHARS:
        text = text[:RESPONSE_MAX_CHARS] + "\n\n… <i>(ответ обрезан)</i>"
    remaining = spend.get("bought", 0) + spend.get("free", 0)
    footer = f"\n\n<i>🤖 {model} · −{cost} CR · Остаток: {remaining} CR</i>"
    await cb.message.answer(text + footer)


# ── Определение типа запроса к фото: редактирование или анализ ──

_EDIT_WORDS = {
    "измени", "поменяй", "замени", "сделай", "убери", "удали", "добавь",
    "перекрась", "перекраси", "стилизуй", "преврати", "переделай",
    "фон", "цвет", "стиль", "ярче", "темнее", "светлее",
    "аниме", "мультфильм", "картина", "масло", "акварель", "пиксель",
    "чб", "ч/б", "черно-белое", "сепия", "ретро", "винтаж", "неон",
    "размой", "обрежь", "увеличь", "уменьши",
}

async def _route_image_edit(image_bytes: bytes, prompt: str, model: str) -> dict:
    """Редактирование фото → OpenRouter (единый API)."""
    from shared.providers.openrouter_image import edit_openrouter_image
    return await edit_openrouter_image(image_bytes, prompt, model)


def _is_edit_request(caption: str) -> bool:
    """Определяет, просит ли пользователь отредактировать изображение."""
    words = caption.lower().split()
    for w in words:
        for kw in _EDIT_WORDS:
            if kw in w:
                return True
    return False

async def _get_photo_urls(message: types.Message, photo) -> tuple[str, str]:
    """Вернуть (base64_data_url для Vision, telegram_url для fal.ai)."""
    file = await message.bot.get_file(photo.file_id)
    telegram_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"
    buf = await message.bot.download_file(file.file_path)
    raw = buf.read()
    b64 = base64.b64encode(raw).decode("utf-8")
    b64_url = f"data:image/jpeg;base64,{b64}"
    return b64_url, telegram_url


async def _get_photo_b64_url_from_file_id(bot, file_id: str) -> str:
    """Получить data URL изображения по file_id (для контекстного меню «Описать»)."""
    file = await bot.get_file(file_id)
    buf = await bot.download_file(file.file_path)
    raw = buf.read()
    b64 = base64.b64encode(raw).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


async def run_photo_describe(bot, user_id: int, file_id: str, target_message: types.Message) -> None:
    """Описать фото по file_id и отправить ответ в target_message (контекстное меню «Описать»)."""
    await get_or_create_user(user_id, None, None)
    model = await get_user_model(user_id, "text")
    cost = CREDIT_PRICES.get(model, 1)
    spend = await spend_credits(user_id, model, "Фото: описание")
    if not spend["ok"]:
        if spend.get("message"):
            await target_message.answer(spend["message"])
            return
        from services.bot.utils.paywall import smart_paywall_message
        text, kb = await smart_paywall_message("Описание фото", cost, user_id)
        await target_message.answer(text, reply_markup=kb)
        return
    status_msg = await target_message.answer("⏳ Описываю фото...")
    try:
        b64_url = await _get_photo_b64_url_from_file_id(bot, file_id)
    except Exception as e:
        _log.error("photo_describe_download_error", error=str(e)[:200], user_id=user_id)
        await _refund_if_needed(user_id, spend, "ошибка загрузки фото")
        await status_msg.edit_text("❌ Не удалось загрузить фото.")
        return
    history = await get_chat_history(user_id)
    system_prompt = await get_system_prompt(user_id)
    remaining = spend.get("bought", 0) + spend.get("free", 0)
    from shared.providers.openai_text import generate_text_with_image
    result = await generate_text_with_image(
        prompt="Опиши это изображение кратко и по делу.", image_url=b64_url, model=model,
        history=history, system_prompt=system_prompt,
    )
    if not result.get("ok"):
        refunded = await _refund_if_needed(user_id, spend, "ошибка генерации (фото)")
        err_msg = f"❌ {result.get('error', 'Ошибка')}"
        if refunded:
            err_msg += "\n\n💚 Кредиты возвращены."
        await status_msg.edit_text(err_msg)
        return
    response_text = result["text"]
    footer = f"\n\n<i>🤖 {model} · −{cost} CR · Остаток: {remaining} CR</i>"
    await status_msg.edit_text((response_text[:RESPONSE_MAX_CHARS] + "…" if len(response_text) > RESPONSE_MAX_CHARS else response_text) + footer)


# ── Фото: автоматическое редактирование или анализ ──

@router.message(F.photo, F.func(lambda m: not (m.caption or "").strip().startswith("/")))
async def handle_photo(message: types.Message):
    """Фото + подпись → редактирование (fal.ai) или анализ (Vision API). Фото без подписи → контекстное меню."""
    user_id = message.from_user.id
    caption = (message.caption or "").strip()
    await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)
    photo = message.photo[-1]

    # Фото без подписи — контекстная подсказка: что сделать?
    if not caption:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if r:
            await r.set(f"photo_pending:{user_id}", photo.file_id, ex=300)
        b = InlineKeyboardBuilder()
        b.row(
            types.InlineKeyboardButton(text="Убрать фон", callback_data="photo_action:rmbg"),
            types.InlineKeyboardButton(text="Описать", callback_data="photo_action:describe"),
        )
        b.row(
            types.InlineKeyboardButton(text="Сгенерировать похожее", callback_data="photo_action:similar"),
            types.InlineKeyboardButton(text="Анимировать", callback_data="photo_action:animate"),
        )
        await message.answer("Что сделать с фото?", reply_markup=b.as_markup())
        return

    # Если подпись похожа на запрос редактирования — только DALL-E 3 / GPT Image умеют править фото
    if caption and _is_edit_request(caption):
        img_model = await get_user_model(user_id, "image")
        if img_model not in _OPENAI_EDIT_MODELS:
            await message.answer(
                "✏️ <b>Редактирование фото</b> (изменить цвет, деталь и т.д.) поддерживается только моделью "
                "<b>GPT Image</b>.\n\n"
                "Выбери её: ⚙️ Модели → Картинки → GPT Image, затем снова отправь фото с подписью.")
            return
        img_cost = CREDIT_PRICES.get(img_model, 5)
        spend = await spend_credits(user_id, img_model, f"Фото-ред: {caption[:40]}")
        if not spend["ok"]:
            if spend.get("message"):
                await message.answer(spend["message"])
                return
            from services.bot.utils.paywall import smart_paywall_message
            text, kb = await smart_paywall_message("Редактирование фото", img_cost, user_id)
            await message.answer(text, reply_markup=kb)
            return
        from services.bot.keyboards.main import _short
        status = await message.answer(f"🎨 Редактирую ({_short(img_model)})...")
        await message.chat.do("upload_photo")
        try:
            file = await message.bot.get_file(photo.file_id)
            buf = await message.bot.download_file(file.file_path)
            raw = buf.read()
        except Exception as e:
            import structlog
            structlog.get_logger().error("photo download error", error=str(e), user_id=user_id)
            c = spend.get("cost", 0)
            if c and not spend.get("trial") and not spend.get("unlimited"):
                await refund_credits(user_id, c, "ошибка загрузки фото")
            await status.edit_text("❌ Не удалось загрузить фото.\n\n💚 Кредиты возвращены.")
            return
        try:
            result = await asyncio.wait_for(_route_image_edit(raw, caption, img_model), timeout=120)
        except asyncio.TimeoutError:
            c = spend.get("cost", 0)
            if c and not spend.get("trial") and not spend.get("unlimited"):
                await refund_credits(user_id, c, "таймаут обработки фото")
            await status.edit_text("⏱ Обработка заняла слишком долго.\n\n💚 Кредиты возвращены.")
            return
        if not result.get("ok"):
            c = spend.get("cost", 0)
            if c and not spend.get("trial") and not spend.get("unlimited"):
                await refund_credits(user_id, c, "ошибка обработки фото")
            await status.edit_text(f"❌ {result.get('error', 'Ошибка')}\n\n💚 Кредиты возвращены.")
            return
        remaining = spend.get("bought", 0) + spend.get("free", 0)
        actual_cost = spend.get("cost", img_cost)
        photo_value = result["image_url"]
        # GPT Image (OpenAI Edit) часто возвращает b64 — Telegram не принимает data URI, нужны bytes
        if isinstance(photo_value, str) and photo_value.startswith("data:image/"):
            try:
                b64 = photo_value.split(",", 1)[1] if "," in photo_value else photo_value
                raw = base64.b64decode(b64)
                photo_value = BufferedInputFile(raw, filename="edited.png")
            except Exception as e:
                import structlog
                structlog.get_logger().warning("photo edit b64 decode failed", error=str(e))
        try:
            await message.answer_photo(
                photo=photo_value,
                caption=f"🎨 <b>{caption[:150]}</b>\n\n<i>🖼 {_short(img_model)} · −{actual_cost} CR · Остаток: {remaining} CR</i>")
            await status.delete()
        except Exception as e:
            import structlog
            structlog.get_logger().error("answer_photo failed", error=str(e))
            await status.edit_text(
                f"❌ Не удалось отправить результат ({str(e)[:80]}).\n\n<i>🖼 {_short(img_model)} · −{actual_cost} CR · Остаток: {remaining} CR</i>")
        return

    # Иначе — анализ через Vision API
    model = await get_user_model(user_id, "text")
    cost = CREDIT_PRICES.get(model, 1)
    spend = await spend_credits(user_id, model, f"Фото: {caption[:50] if caption else 'анализ'}")
    if not spend["ok"]:
        if spend.get("message"):
            await message.answer(spend["message"])
            return
        from services.bot.utils.paywall import smart_paywall_message
        need_cr = spend.get("cost") or cost
        text, kb = await smart_paywall_message("Анализ фото (чат)", need_cr, user_id)
        await message.answer(text, reply_markup=kb)
        return
    await message.chat.do("typing")
    gen_start = time.monotonic()
    try:
        b64_url, _ = await _get_photo_urls(message, photo)
    except Exception as e:
        import structlog
        structlog.get_logger().error("photo download error", error=str(e), user_id=user_id)
        await _refund_if_needed(user_id, spend, "ошибка загрузки фото")
        await message.answer("❌ Не удалось загрузить фото.")
        return
    history = await get_chat_history(user_id)
    system_prompt = await get_system_prompt(user_id)
    remaining = spend.get("bought", 0) + spend.get("free", 0)
    from shared.providers.openai_text import generate_text_with_image
    result = await generate_text_with_image(
        prompt=caption, image_url=b64_url, model=model,
        history=history, system_prompt=system_prompt
    )
    if not result.get("ok"):
        refunded = await _refund_if_needed(user_id, spend, "ошибка генерации (фото)")
        err_msg = f"❌ {result.get('error', 'Ошибка')}"
        if refunded:
            err_msg += "\n\n💚 Кредиты возвращены."
        await message.answer(err_msg)
        return
    response_text = result["text"]
    elapsed = time.monotonic() - gen_start
    footer = f"\n\n<i>🤖 {model} · −{cost} CR · {elapsed:.1f}с · Остаток: {remaining} CR</i>"
    await append_chat_pair(user_id, f"[фото] {caption}" if caption else "[фото]", response_text)
    truncated = len(response_text) > RESPONSE_MAX_CHARS
    if truncated:
        response_text = response_text[:RESPONSE_MAX_CHARS] + "\n\n… <i>(ответ обрезан)</i>"
    rate_b = InlineKeyboardBuilder()
    if truncated:
        rate_b.row(types.InlineKeyboardButton(text="▶️ Продолжить", callback_data=f"continue:{user_id}"))
    rate_b.row(
        types.InlineKeyboardButton(text="👍", callback_data=f"rate_up:{user_id}"),
        types.InlineKeyboardButton(text="👎", callback_data=f"rate_down:{user_id}"),
    )
    await message.answer(response_text + footer, reply_markup=rate_b.as_markup())


# ── Видео: анализ превью-кадра ──

@router.message(F.video, F.func(lambda m: not (m.caption or "").strip().startswith("/")))
async def handle_video(message: types.Message):
    """Видео + подпись → редактирование кадра или анализ через Vision API."""
    user_id = message.from_user.id
    caption = (message.caption or "").strip()
    await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)
    thumb = message.video.thumbnail if message.video else None
    if not thumb:
        await message.answer(
            "📹 У этого видео нет превью.\n\n"
            "💡 Отправь <b>скриншот</b> как фото с подписью — так я смогу помочь.")
        return

    # Запрос на редактирование → видео-модель пользователя (image-to-video из кадра)
    if caption and _is_edit_request(caption):
        from shared.domain.credits import VIDEO_MODELS
        vid_model = await get_user_model(user_id, "video")
        vid_info = VIDEO_MODELS.get(vid_model)
        if not vid_info:
            vid_model = "kling-2.6"
            vid_info = VIDEO_MODELS[vid_model]
        vid_cost = vid_info["cr"]
        spend = await spend_credits(user_id, vid_model, f"Видео-ред: {caption[:40]}")
        if not spend["ok"]:
            if spend.get("message"):
                await message.answer(spend["message"])
                return
            from services.bot.keyboards.main import promo_credits_kb
            await message.answer(
                f"😔 {vid_info['label']} стоит {vid_cost} CR. Баланс: /balance",
                reply_markup=promo_credits_kb())
            return
        status = await message.answer(f"🎬 Генерирую видео ({vid_info['label']})... до 5 мин")
        await message.chat.do("upload_video")
        try:
            _, tg_url = await _get_photo_urls(message, thumb)
        except Exception as e:
            import structlog
            structlog.get_logger().error("video thumb error", error=str(e), user_id=user_id)
            c = spend.get("cost", 0)
            if c and not spend.get("trial") and not spend.get("unlimited"):
                await refund_credits(user_id, c, "ошибка загрузки кадра")
            await status.edit_text("❌ Не удалось загрузить кадр.\n\n💚 Кредиты возвращены.")
            return
        try:
            from shared.providers.falai_video import generate_video
            result = await asyncio.wait_for(
                generate_video(caption, vid_info["endpoint"], image_url=tg_url), timeout=400)
        except asyncio.TimeoutError:
            c = spend.get("cost", 0)
            if c and not spend.get("trial") and not spend.get("unlimited"):
                await refund_credits(user_id, c, "таймаут генерации видео")
            await status.edit_text("⏱ Генерация видео заняла слишком долго.\n\n💚 Кредиты возвращены.")
            return
        if not result.get("ok"):
            c = spend.get("cost", 0)
            if c and not spend.get("trial") and not spend.get("unlimited"):
                await refund_credits(user_id, c, "ошибка генерации видео")
            await status.edit_text(f"❌ {result.get('error', 'Ошибка')}\n\n💚 Кредиты возвращены.")
            return
        remaining = spend.get("bought", 0) + spend.get("free", 0)
        actual_cost = spend.get("cost", vid_cost)
        vid_caption = (
            f"🎬 <b>{caption[:200]}</b>\n\n"
            f"<i>🎥 {vid_info['label']} · −{actual_cost} CR · Остаток: {remaining} CR</i>"
        )
        video_input = BufferedInputFile(result["video_bytes"], "video.mp4") if result.get("video_bytes") else result.get("video_url", "")
        try:
            await message.answer_video(video=video_input, caption=vid_caption)
            await status.delete()
        except Exception:
            link = result.get("video_url") or "(отправлено файлом)"
            await status.edit_text(f"🎬 Готово!\n\n{link}\n\n{vid_caption}")
        return

    # Анализ через Vision API
    model = await get_user_model(user_id, "text")
    cost = CREDIT_PRICES.get(model, 1)
    spend = await spend_credits(user_id, model, f"Видео: {caption[:50] if caption else 'анализ'}")
    if not spend["ok"]:
        if spend.get("message"):
            await message.answer(spend["message"])
            return
        from services.bot.utils.paywall import smart_paywall_message
        need_cr = spend.get("cost") or cost
        text, kb = await smart_paywall_message("Анализ видео (чат)", need_cr, user_id)
        await message.answer(text, reply_markup=kb)
        return
    await message.chat.do("typing")
    gen_start = time.monotonic()
    try:
        b64_url, _ = await _get_photo_urls(message, thumb)
    except Exception as e:
        import structlog
        structlog.get_logger().error("video thumb error", error=str(e), user_id=user_id)
        await _refund_if_needed(user_id, spend, "ошибка загрузки превью")
        await message.answer("❌ Не удалось загрузить превью видео.")
        return
    history = await get_chat_history(user_id)
    system_prompt = await get_system_prompt(user_id)
    remaining = spend.get("bought", 0) + spend.get("free", 0)
    from shared.providers.openai_text import generate_text_with_image
    result = await generate_text_with_image(
        prompt=caption, image_url=b64_url, model=model,
        history=history, system_prompt=system_prompt, is_video_frame=True
    )
    if not result.get("ok"):
        refunded = await _refund_if_needed(user_id, spend, "ошибка генерации (видео)")
        err_msg = f"❌ {result.get('error', 'Ошибка')}"
        if refunded:
            err_msg += "\n\n💚 Кредиты возвращены."
        await message.answer(err_msg)
        return
    response_text = result["text"]
    elapsed = time.monotonic() - gen_start
    footer = f"\n\n<i>🤖 {model} · −{cost} CR · {elapsed:.1f}с · Остаток: {remaining} CR</i>"
    await append_chat_pair(user_id, f"[видео] {caption}" if caption else "[видео]", response_text)
    truncated = len(response_text) > RESPONSE_MAX_CHARS
    if truncated:
        response_text = response_text[:RESPONSE_MAX_CHARS] + "\n\n… <i>(ответ обрезан)</i>"
    rate_b = InlineKeyboardBuilder()
    if truncated:
        rate_b.row(types.InlineKeyboardButton(text="▶️ Продолжить", callback_data=f"continue:{user_id}"))
    rate_b.row(
        types.InlineKeyboardButton(text="👍", callback_data=f"rate_up:{user_id}"),
        types.InlineKeyboardButton(text="👎", callback_data=f"rate_down:{user_id}"),
    )
    await message.answer(response_text + footer, reply_markup=rate_b.as_markup())


_PROMPT_INJECTION_PHRASES = (
    "ignore previous", "ignore all", "system:", "you are now", "you are a",
    "forget everything", "new instructions", "disregard", "override",
)


def _is_prompt_injection(text: str) -> bool:
    """Проверка на типичные фразы prompt injection."""
    lower = text.lower().strip()
    for phrase in _PROMPT_INJECTION_PHRASES:
        if phrase in lower:
            return True
    return False


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: types.Message):
    user_id = message.from_user.id
    prompt = (message.text or "").strip()
    if not prompt:
        await message.answer("Напиши текст сообщения или нажми /start для меню.")
        return

    async with _gen_lock(user_id) as acquired:
        if not acquired:
            await message.answer("⏳ Предыдущий запрос ещё обрабатывается.")
            return

        if _is_prompt_injection(prompt):
            _log.warning("prompt_injection_rejected", user_id=user_id, prompt_preview=prompt[:80])
            await message.answer("⚠️ Сообщение отклонено. Сформулируй запрос по-другому.")
            return

        if len(prompt) > PROMPT_MAX_CHARS:
            await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)
            await message.answer(f"⚠️ Слишком длинное сообщение (макс. {PROMPT_MAX_CHARS:,} символов). Сократи.")
            return

        # Video request routing
        from services.bot.handlers.video import (
            _extract_video_prompt,
            _is_video_request,
            _process_video_text_request,
        )
        if _is_video_request(prompt):
            video_prompt = _extract_video_prompt(prompt)
            if video_prompt:
                await _process_video_text_request(
                    message, user_id, video_prompt,
                    message.from_user.username, message.from_user.first_name,
                )
                return

        await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)
        model = await get_user_model(user_id, "text")
        cost = CREDIT_PRICES.get(model, 1)
        spend = await spend_credits(user_id, model, f"Текст: {prompt[:50]}")
        if not spend["ok"]:
            if spend.get("message"):
                await message.answer(spend["message"])
                return
            from services.bot.utils.paywall import smart_paywall_message
            need_cr = spend.get("cost") or cost
            text, kb = await smart_paywall_message(f"Чат с AI ({model})", need_cr, user_id)
            await message.answer(text, reply_markup=kb)
            return

        await message.chat.do("typing")
        gen_start = time.monotonic()
        history = await get_chat_history(user_id)
        system_prompt = await get_system_prompt(user_id)
        remaining = spend.get("bought", 0) + spend.get("free", 0)

        use_stream = is_streaming_model(model)
        status_msg = None
        if use_stream:
            status_msg = await message.answer("⏳ Печатаю...")
            accumulated = ""
            last_edit = 0.0
            final_text = None
            try:
                async for chunk in generate_text_stream(prompt, model, history=history, system_prompt=system_prompt):
                    if chunk.get("ok") is False:
                        await log_ai_error(user_id, "text", model, prompt[:200], cost, elapsed_ms(gen_start), chunk.get("error", "Ошибка"), error_event="message_error")
                        refunded = await _refund_if_needed(user_id, spend, "ошибка генерации текста")
                        err_msg = f"❌ {chunk.get('error', 'Ошибка')}"
                        if refunded:
                            err_msg += "\n\n💚 Кредиты возвращены."
                        await status_msg.edit_text(err_msg)
                        return
                    if "delta" in chunk:
                        accumulated += chunk["delta"]
                        now = time.monotonic()
                        if now - last_edit >= STREAM_EDIT_INTERVAL and accumulated:
                            display = (accumulated[:RESPONSE_MAX_CHARS] + "…") if len(accumulated) > RESPONSE_MAX_CHARS else accumulated
                            with contextlib.suppress(Exception):
                                await status_msg.edit_text(display + f"\n\n<i>💰 −{cost} CR | {model}</i>")
                            last_edit = now
                    if chunk.get("done"):
                        final_text = chunk.get("text", accumulated)
                        break
            except Exception as e:
                await log_ai_error(user_id, "text", model, prompt[:200], cost, elapsed_ms(gen_start), str(e), status="exception", error_event="message_error")
                refunded = await _refund_if_needed(user_id, spend, "ошибка генерации текста")
                _log.error("text_generation_error", error=str(e)[:200], user_id=user_id, model=model)
                err_msg = "❌ Ошибка генерации. Попробуй ещё раз."
                if refunded:
                    err_msg += "\n\n💚 Кредиты возвращены."
                retry_kb = InlineKeyboardBuilder()
                retry_kb.row(types.InlineKeyboardButton(text="🔄 Попробовать снова", callback_data=f"retry:{user_id}"))
                retry_kb.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
                await status_msg.edit_text(err_msg, reply_markup=retry_kb.as_markup())
                return
            response_text = final_text or accumulated
        else:
            result = await generate_text(prompt, model, history=history, system_prompt=system_prompt)
            if not result["ok"]:
                await log_ai_error(user_id, "text", model, prompt[:200], cost, elapsed_ms(gen_start), result.get("error", "Ошибка"), error_event="message_error")
                refunded = await _refund_if_needed(user_id, spend, "ошибка генерации текста")
                err_msg = f"❌ {result['error']}"
                if refunded:
                    err_msg += "\n\n💚 Кредиты возвращены."
                retry_kb = InlineKeyboardBuilder()
                retry_kb.row(types.InlineKeyboardButton(text="🔄 Попробовать снова", callback_data=f"retry:{user_id}"))
                retry_kb.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
                await message.answer(err_msg, reply_markup=retry_kb.as_markup())
                return
            response_text = result["text"]

        elapsed = time.monotonic() - gen_start
        elapsed_ms_value = int(elapsed * 1000)
        footer = f"\n\n<i>🤖 {model} · −{cost} CR · {elapsed:.1f}с · Остаток: {remaining} CR</i>"

        # Save history + log analytics in parallel
        await asyncio.gather(
            append_chat_pair(user_id, prompt, response_text),
            log_ai_success(user_id, "text", model, prompt[:200], cost, elapsed_ms_value, success_event="message_sent"),
            return_exceptions=True,
        )

        truncated = len(response_text) > RESPONSE_MAX_CHARS
        if truncated:
            response_text = response_text[:RESPONSE_MAX_CHARS] + "\n\n… <i>(ответ обрезан)</i>"

        rate_b = InlineKeyboardBuilder()
        if truncated:
            rate_b.row(types.InlineKeyboardButton(text="▶️ Продолжить", callback_data=f"continue:{user_id}"))
        rate_b.row(
            types.InlineKeyboardButton(text="👍", callback_data=f"rate_up:{user_id}"),
            types.InlineKeyboardButton(text="👎", callback_data=f"rate_down:{user_id}"),
            types.InlineKeyboardButton(text="🔊", callback_data=f"tts_last:{user_id}"),
        )

        low_warn = f"\n\n⚠️ <i>Осталось {remaining} CR — </i>/balance" if remaining < 10 else ""
        final_message = response_text + footer + low_warn
        if len(final_message) > 4090:
            final_message = final_message[:4080] + "…</i>"

        if status_msg:
            try:
                await status_msg.edit_text(final_message, reply_markup=rate_b.as_markup())
            except Exception:
                await message.answer(final_message, reply_markup=rate_b.as_markup())
                with contextlib.suppress(Exception):
                    await status_msg.delete()
        else:
            await message.answer(final_message, reply_markup=rate_b.as_markup())

        # Мягкий пейволл: напоминание если CR < 5
        try:
            await soft_paywall_hint(user_id, message.bot)
        except Exception:
            pass


@router.message(F.text.startswith("/"))
async def handle_unknown_command(message: types.Message):
    """Любая команда, не обработанная другими роутерами (например /xyz)."""
    await message.answer("Неизвестная команда. Нажми /start для меню.")
