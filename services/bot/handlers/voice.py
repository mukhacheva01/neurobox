"""НейроБокс — Voice: STT, TTS, voice/model selection."""
import io
import math

from aiogram import Bot, F, Router, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from shared.config import settings
from shared.domain.credits import (
    CREDIT_PRICES,
    TTS_VOICES,
    get_balance,
    get_or_create_user,
    get_user_model,
    refund_spend_credits,
    set_user_model,
    spend_credits,
)
from shared.domain.telemetry import elapsed_ms, log_ai_error, log_ai_success

router = Router()


def _friendly_tts_error(err: str) -> str:
    msg = (err or "").strip()
    low = msg.lower()
    if "openai_api_key" in low or "invalid_api_key" in low or "authentication" in low:
        return "OpenAI TTS временно недоступен."
    if "speech.platform.bing.com" in low or "invalid response status" in low:
        return "Edge TTS временно недоступен."
    if "<!doctype html" in low or "openrouter" in low:
        return "Сервис озвучки временно недоступен."
    return (msg or "Ошибка озвучки")[:180]


def _tts_disabled_kb():
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="💬 Поддержка", callback_data="screen_support"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    return b.as_markup()


async def _reply_tts_disabled(target) -> None:
    await target.answer(
        "🔊 Озвучка текста сейчас временно отключена.\n\n"
        "Голосовые сообщения и кружки продолжают работать: бот распознает речь и ответит текстом.",
        reply_markup=_tts_disabled_kb(),
    )


def _voice_actions_keyboard():
    """Кнопки после распознавания голоса/кружка: только для активных модулей."""
    b = InlineKeyboardBuilder()
    row = [types.InlineKeyboardButton(text="🎨 Картинка", callback_data="voice_use:image")]
    if settings.enable_video:
        row.append(types.InlineKeyboardButton(text="🎬 Видео", callback_data="voice_use:video"))
    if settings.enable_music:
        row.append(types.InlineKeyboardButton(text="🎵 Музыка", callback_data="voice_use:music"))
    b.row(*row)
    return b.as_markup()


# ── STT: голосовое → текст ───────────────────────────────────────────────

MAX_VOICE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


@router.message(Command("voice"))
async def cmd_voice(message: types.Message):
    uid = message.from_user.id
    await get_or_create_user(uid, message.from_user.username, message.from_user.first_name)

    if not settings.enable_tts:
        await _reply_tts_disabled(message)
        return

    args = (message.text or "").split(maxsplit=1)
    text = args[1].strip() if len(args) > 1 else ""
    if not text:
        await message.answer(
            "🔊 Напиши текст для озвучки:\n\n"
            "<code>/voice Привет! Это тест озвучки.</code>"
        )
        return

    tts_model = await get_user_model(uid, "tts")
    voice_key = await get_user_model(uid, "tts_voice")

    voices = TTS_VOICES.get(tts_model, TTS_VOICES["edge-tts"])
    if voice_key not in voices:
        voice_key = next(iter(voices.keys()))
        await set_user_model(uid, "tts_voice", voice_key)
    voice_info = voices[voice_key]

    cost = CREDIT_PRICES.get(tts_model, 0)
    spend = await spend_credits(uid, tts_model, f"TTS: {text[:40]}")
    if not spend["ok"]:
        if spend.get("message"):
            await message.answer(spend["message"])
            return
        from services.bot.utils.paywall import smart_paywall_message
        need_cr = spend.get("cost") or cost
        pay_text, kb = await smart_paywall_message("Озвучка текста", need_cr, uid)
        await message.answer(pay_text, reply_markup=kb)
        return

    import time as _time
    _tts_started = _time.monotonic()
    status = await message.answer("🔊 Озвучиваю...")

    result = {"ok": False, "error": "unknown"}
    used_model = tts_model
    used_voice_label = voice_info["label"]
    fallback_note = ""

    try:
        from shared.providers.edge_tts_provider import (
            generate_speech as edge_generate_speech,
        )
        result = await edge_generate_speech(text, voice_id=voice_info["id"])
    except Exception as e:
        result = {"ok": False, "error": str(e)}

    if not result.get("ok"):
        err = _friendly_tts_error(result.get("error", "Ошибка TTS"))
        await log_ai_error(uid, "tts", tts_model, text[:200], cost, elapsed_ms(_tts_started), err, error_event="tts_error")
        c = spend.get("cost", 0)
        if c and not spend.get("trial") and not spend.get("unlimited"):
            await refund_spend_credits(uid, spend, "ошибка TTS")
        err_kb = InlineKeyboardBuilder()
        err_kb.row(types.InlineKeyboardButton(text="💬 Поддержка", callback_data="screen_support"))
        err_kb.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
        await status.edit_text(
            f"❌ {err}\n\n💚 Кредиты возвращены.",
            reply_markup=err_kb.as_markup(),
        )
        return

    bal = await get_balance(uid)
    remaining = bal.get("total", 0)
    await log_ai_success(uid, "tts", used_model, text[:200], cost, elapsed_ms(_tts_started))
    audio = BufferedInputFile(result["audio_bytes"], filename="voice.mp3")
    await message.answer_voice(
        voice=audio,
        caption=(
            "🔊 <b>Озвучка готова</b>\n"
            f"<i>Модель: {used_model} | Голос: {used_voice_label} | −{cost} CR | Остаток: {remaining} CR</i>{fallback_note}"
        ),
    )
    try:
        await status.delete()
    except Exception:
        pass


@router.message(F.voice)
async def handle_voice(message: types.Message, bot: Bot):
    uid = message.from_user.id
    await get_or_create_user(uid, message.from_user.username, message.from_user.first_name)

    # Проверка размера файла
    if message.voice.file_size and message.voice.file_size > MAX_VOICE_SIZE_BYTES:
        await message.answer(f"⚠️ Голосовое сообщение слишком большое ({message.voice.file_size // 1024 // 1024} MB). Максимум 10 MB.")
        return

    dur_min = max(1, math.ceil(message.voice.duration / 60))
    cost = CREDIT_PRICES["whisper"] * dur_min

    spend = await spend_credits(uid, "whisper", f"STT {dur_min}мин")
    if not spend["ok"]:
        if spend.get("message"):
            await message.answer(spend["message"])
            return
        from services.bot.utils.paywall import smart_paywall_message
        text_pay, kb = await smart_paywall_message("Распознавание голоса (Whisper)", cost, uid)
        await message.answer(text_pay, reply_markup=kb)
        return

    import time as _time
    _stt_started = _time.monotonic()
    status = await message.answer("🎤 Распознаю речь...")
    try:
        file = await bot.get_file(message.voice.file_id)
        buf = io.BytesIO()
        await bot.download_file(file.file_path, buf)
        filename = (getattr(file, "file_path", "") or "voice.ogg").rsplit("/", 1)[-1]

        from shared.providers.openai_stt import transcribe_audio
        result = await transcribe_audio(buf.getvalue(), filename)
    except Exception as e:
        import structlog
        await log_ai_error(uid, "stt", "whisper", "voice", cost, elapsed_ms(_stt_started), str(e), status="exception", error_event="stt_error")
        structlog.get_logger().error("voice stt error", error=str(e), user_id=uid)
        if cost and not spend.get("trial"):
            await refund_spend_credits(uid, spend, "ошибка распознавания речи")
        await status.edit_text("❌ Ошибка распознавания речи. Попробуй позже.\n\n💚 Кредиты возвращены.")
        return

    if not result["ok"]:
        await log_ai_error(uid, "stt", "whisper", "voice", cost, elapsed_ms(_stt_started), result.get("error", "Ошибка STT"), error_event="stt_error")
        if cost and not spend.get("trial"):
            await refund_spend_credits(uid, spend, "ошибка распознавания речи")
        await status.edit_text(f"❌ {result['error']}\n\n💚 Кредиты возвращены.")
        return

    rem = spend.get("bought", 0) + spend.get("free", 0)
    text = result["text"][:4000].strip()
    await log_ai_success(uid, "stt", "whisper", text[:200], cost, elapsed_ms(_stt_started))
    # Сохраняем текст для кнопок «Картинка / Видео / Музыка»
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if r and text:
            await r.set(f"voice_text:{uid}", text[:2000], ex=600)
    except Exception:
        pass

    # Ответ в чат (как у кружка): отправляем текст в AI и показываем ответ
    from services.bot.services.chat_service import (
        append_chat_message,
        get_chat_history,
        get_system_prompt,
    )
    from shared.domain.credits import CREDIT_PRICES as _CP
    from shared.domain.credits import get_user_model as _get_text_model
    model = await _get_text_model(uid, "text")
    text_cost = _CP.get(model, 1)
    text_spend = await spend_credits(uid, model, f"Голос→AI: {text[:30]}")
    if not text_spend["ok"]:
        # Не хватило на AI / сработал policy — показываем только распознанный текст и кнопки
        _voice_actions_kb = _voice_actions_keyboard()
        deny_message = text_spend.get("message") or "⚠️ Не хватило CR для ответа AI."
        await status.edit_text(
            f"📝 <b>Распознано:</b>\n\n{text}\n\n"
            f"<i>💰 −{cost} CR | Остаток: {rem} CR</i>\n\n"
            f"{deny_message}\nИспользуй кнопки ниже:",
            reply_markup=_voice_actions_kb)
        return

    await status.edit_text(f"📝 Распознано. Отвечаю в чат ({model})...")
    await message.chat.do("typing")
    history = await get_chat_history(uid)
    system_prompt = await get_system_prompt(uid)
    from shared.providers.openai_text import generate_text
    _ai_started = _time.monotonic()
    ai_result = await generate_text(text, model, history=history, system_prompt=system_prompt)
    text_rem = text_spend.get("bought", 0) + text_spend.get("free", 0)

    if not ai_result.get("ok"):
        await log_ai_error(uid, "text", model, text[:200], text_cost, elapsed_ms(_ai_started), ai_result.get("error", "Ошибка AI"), error_event="message_error", event_props={"source": "voice"})
        c = text_spend.get("cost", 0)
        if c and not text_spend.get("trial") and not text_spend.get("unlimited"):
            await refund_spend_credits(uid, text_spend, "ошибка AI после голоса")
        await status.edit_text(
            f"📝 <b>Из голоса:</b>\n\n{text}\n\n"
            f"❌ Ошибка AI. Кредиты за ответ возвращены.\n\n"
            f"<i>−{cost} CR (STT) | Остаток: {text_rem} CR</i>",
            reply_markup=_voice_actions_keyboard())
        return

    response_text = ai_result["text"]
    await log_ai_success(uid, "text", model, text[:200], text_cost, elapsed_ms(_ai_started), success_event="message_sent", event_props={"source": "voice"})
    await append_chat_message(uid, "user", f"[голос] {text}")
    await append_chat_message(uid, "assistant", response_text)
    if len(response_text) > 3800:
        response_text = response_text[:3800] + "\n\n… <i>(обрезано)</i>"
    total_cost = cost + text_spend.get("cost", 0)
    await status.edit_text(
        f"📝 <b>Из голоса:</b> <i>{text[:200]}{'…' if len(text) > 200 else ''}</i>\n\n"
        f"{response_text}\n\n"
        f"<i>💰 −{total_cost} CR (STT+AI) | Остаток: {text_rem} CR</i>",
        reply_markup=_voice_actions_keyboard())

# ── Кружки (video_note): распознавание аудиодорожки ──────────────────────

@router.message(F.video_note)
async def handle_video_note(message: types.Message, bot: Bot):
    """Кружок (видеосообщение) → распознаём аудио через Whisper + ответ AI."""
    uid = message.from_user.id
    await get_or_create_user(uid, message.from_user.username, message.from_user.first_name)

    vn = message.video_note
    if vn.file_size and vn.file_size > MAX_VOICE_SIZE_BYTES:
        await message.answer("⚠️ Кружок слишком большой. Максимум 10 MB.")
        return

    dur_min = max(1, math.ceil((vn.duration or 10) / 60))
    cost = CREDIT_PRICES["whisper"] * dur_min

    spend = await spend_credits(uid, "whisper", f"Кружок STT {dur_min}мин")
    if not spend["ok"]:
        if spend.get("message"):
            await message.answer(spend["message"])
            return
        from services.bot.utils.paywall import smart_paywall_message
        text_pay, kb = await smart_paywall_message("Распознавание кружка (Whisper)", cost, uid)
        await message.answer(text_pay, reply_markup=kb)
        return

    import time as _time
    _stt_started = _time.monotonic()
    status = await message.answer("🎤 Распознаю речь из кружка...")
    try:
        file = await bot.get_file(vn.file_id)
        buf = io.BytesIO()
        await bot.download_file(file.file_path, buf)
        filename = (getattr(file, "file_path", "") or "video_note.mp4").rsplit("/", 1)[-1]

        from shared.providers.openai_stt import transcribe_audio
        result = await transcribe_audio(buf.getvalue(), filename)
    except Exception as e:
        import structlog
        await log_ai_error(uid, "stt", "whisper", "video_note", cost, elapsed_ms(_stt_started), str(e), status="exception", error_event="stt_error")
        structlog.get_logger().error("video_note stt error", error=str(e), user_id=uid)
        if cost and not spend.get("trial") and not spend.get("unlimited"):
            await refund_spend_credits(uid, spend, "ошибка распознавания кружка")
        await status.edit_text("❌ Не удалось распознать речь из кружка.\n\n💚 Кредиты возвращены.")
        return

    if not result["ok"]:
        await log_ai_error(uid, "stt", "whisper", "video_note", cost, elapsed_ms(_stt_started), result.get("error", "Ошибка STT"), error_event="stt_error")
        if cost and not spend.get("trial") and not spend.get("unlimited"):
            await refund_spend_credits(uid, spend, "ошибка STT кружка")
        await status.edit_text(f"❌ {result['error']}\n\n💚 Кредиты возвращены.")
        return

    recognized = result["text"][:4000].strip()
    rem = spend.get("bought", 0) + spend.get("free", 0)
    await log_ai_success(uid, "stt", "whisper", recognized[:200], cost, elapsed_ms(_stt_started))
    # Сохраняем для кнопок «Картинка / Видео / Музыка»
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if r and recognized:
            await r.set(f"voice_text:{uid}", recognized[:2000], ex=600)
    except Exception:
        pass

    # Распознали — теперь отправляем как запрос к AI
    from services.bot.services.chat_service import (
        append_chat_message,
        get_chat_history,
        get_system_prompt,
    )
    from shared.domain.credits import CREDIT_PRICES as CP
    from shared.domain.credits import get_user_model
    model = await get_user_model(uid, "text")
    text_cost = CP.get(model, 1)
    text_spend = await spend_credits(uid, model, f"Кружок→AI: {recognized[:30]}")
    if not text_spend["ok"]:
        deny_message = text_spend.get("message") or "⚠️ Не хватило CR для ответа AI."
        await status.edit_text(
            f"📝 <b>Распознано из кружка:</b>\n\n{recognized}\n\n"
            f"<i>💰 −{cost} CR | Остаток: {rem} CR</i>\n\n"
            f"{deny_message}\nИспользуй кнопки ниже:",
            reply_markup=_voice_actions_keyboard())
        return

    await status.edit_text(f"📝 Распознано. Отвечаю через AI ({model})...")
    await message.chat.do("typing")

    history = await get_chat_history(uid)
    system_prompt = await get_system_prompt(uid)
    from shared.providers.openai_text import generate_text
    _ai_started = _time.monotonic()
    ai_result = await generate_text(recognized, model, history=history, system_prompt=system_prompt)
    text_rem = text_spend.get("bought", 0) + text_spend.get("free", 0)

    if not ai_result.get("ok"):
        await log_ai_error(uid, "text", model, recognized[:200], text_cost, elapsed_ms(_ai_started), ai_result.get("error", "Ошибка AI"), error_event="message_error", event_props={"source": "video_note"})
        c = text_spend.get("cost", 0)
        if c and not text_spend.get("trial") and not text_spend.get("unlimited"):
            await refund_spend_credits(uid, text_spend, "ошибка AI после кружка")
        await status.edit_text(
            f"📝 <b>Из кружка:</b>\n\n{recognized}\n\n"
            f"❌ Ошибка AI. Кредиты за ответ возвращены.\n\n"
            f"<i>−{cost} CR (STT) | Остаток: {text_rem} CR</i>",
            reply_markup=_voice_actions_keyboard())
        return

    response_text = ai_result["text"]
    await log_ai_success(uid, "text", model, recognized[:200], text_cost, elapsed_ms(_ai_started), success_event="message_sent", event_props={"source": "video_note"})
    await append_chat_message(uid, "user", f"[кружок] {recognized}")
    await append_chat_message(uid, "assistant", response_text)

    if len(response_text) > 3800:
        response_text = response_text[:3800] + "\n\n… <i>(обрезано)</i>"

    total_cost = cost + text_spend.get("cost", 0)
    await status.edit_text(
        f"📝 <b>Из кружка:</b> <i>{recognized[:200]}{'…' if len(recognized) > 200 else ''}</i>\n\n"
        f"{response_text}\n\n"
        f"<i>💰 −{total_cost} CR (STT+AI) | Остаток: {text_rem} CR</i>",
        reply_markup=_voice_actions_keyboard())


@router.callback_query(F.data.startswith("voice_use:"))
async def cb_voice_use(callback: types.CallbackQuery):
    """Использовать распознанный из голоса/кружка текст для Картинки / Видео / Музыки."""
    await callback.answer()
    uid = callback.from_user.id
    action = (callback.data or "").replace("voice_use:", "").strip()
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        raw = await r.get(f"voice_text:{uid}") if r else None
        text = raw.decode() if raw and hasattr(raw, "decode") else (raw or "")
    except Exception:
        text = ""
    if not text or len(text) < 2:
        await callback.message.answer("⏱ Текст устарел. Отправь голосовое или кружок заново.")
        return
    if action == "image":
        from services.bot.handlers.image import run_image_gen_for_user
        await run_image_gen_for_user(callback.message, uid, text)
    elif action == "video":
        if not settings.enable_video:
            await callback.message.answer("🎬 Генерация видео временно недоступна.")
            return
        from services.bot.handlers.video import _generate_video_text
        from shared.domain.credits import VIDEO_MODELS
        model = await get_user_model(uid, "video")
        info = VIDEO_MODELS.get(model)
        if not info:
            await callback.message.answer("❌ Модель видео не найдена. Выбери в ⚙️ Модели → Видео.")
            return
        cost = info.get("cr", CREDIT_PRICES.get(model, 0))
        await _generate_video_text(callback.message, uid, text, model, info, cost)
    elif action == "music":
        if not settings.enable_music:
            await callback.message.answer("🎵 Генерация музыки временно недоступна.")
            return
        from services.bot.handlers.music import run_music_gen_for_user
        await run_music_gen_for_user(callback.message, uid, text)
    else:
        await callback.message.answer("Неизвестное действие.")


@router.message(Command("setvoice"))
async def cmd_setvoice(message: types.Message):
    uid = message.from_user.id
    await get_or_create_user(uid, message.from_user.username, message.from_user.first_name)
    if not settings.enable_tts:
        await _reply_tts_disabled(message)
        return
    tts_model = await get_user_model(uid, "tts")
    current = await get_user_model(uid, "tts_voice")
    voices = TTS_VOICES.get(tts_model, TTS_VOICES["edge-tts"])
    b = InlineKeyboardBuilder()
    for key, info in voices.items():
        mark = " ✅" if key == current else ""
        b.row(types.InlineKeyboardButton(text=f"{info['label']}{mark}", callback_data=f"setv_{key}"))
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu"))
    await message.answer(f"🎤 <b>Выбери голос</b> ({tts_model})", reply_markup=b.as_markup())


@router.callback_query(F.data == "voice_select_menu")
async def cb_voice_select_menu(callback: types.CallbackQuery):
    """Открыть выбор голоса по кнопке из экрана озвучки."""
    await callback.answer()
    uid = callback.from_user.id
    await get_or_create_user(uid, callback.from_user.username, callback.from_user.first_name)
    if not settings.enable_tts:
        await _reply_tts_disabled(callback.message)
        return
    tts_model = await get_user_model(uid, "tts")
    current = await get_user_model(uid, "tts_voice")
    voices = TTS_VOICES.get(tts_model, TTS_VOICES["edge-tts"])
    b = InlineKeyboardBuilder()
    for key, info in voices.items():
        mark = " ✅" if key == current else ""
        b.row(types.InlineKeyboardButton(
            text=f"{info['label']}{mark}", callback_data=f"setv_{key}"))
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="screen_voice"))
    await callback.message.answer(f"🎤 <b>Выбери голос</b> ({tts_model})", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("setv_"))
async def cb_set_voice(callback: types.CallbackQuery):
    key = callback.data.replace("setv_", "")
    if not settings.enable_tts:
        await callback.answer("Озвучка временно отключена", show_alert=True)
        await _reply_tts_disabled(callback.message)
        return
    await set_user_model(callback.from_user.id, "tts_voice", key)
    await callback.answer(f"✅ Голос: {key}", show_alert=True)
    await callback.message.answer(f"✅ Голос: <b>{key}</b>")

# ── /settts и callback tts_select_model — выбор TTS-модели ────────────────

def _available_tts_models():
    return [("Edge TTS", "edge-tts", "🆓 0 CR")]


def _tts_models_kb(current: str, back_to_select_model: bool = False):
    b = InlineKeyboardBuilder()
    for name, mid, price in _available_tts_models():
        mark = " ✅" if mid == current else ""
        b.row(types.InlineKeyboardButton(text=f"{name} — {price}{mark}", callback_data=f"stts_{mid}"))
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="select_model" if back_to_select_model else "main_menu"))
    return b.as_markup()


def _tts_model_display_name(mid: str) -> str:
    for name, model_id, _ in _available_tts_models():
        if model_id == mid:
            return name
    return mid

@router.message(Command("settts"))
async def cmd_settts(message: types.Message):
    uid = message.from_user.id
    await get_or_create_user(uid, message.from_user.username, message.from_user.first_name)
    if not settings.enable_tts:
        await _reply_tts_disabled(message)
        return
    current = await get_user_model(uid, "tts")
    available = {m for _, m, _ in _available_tts_models()}
    if current not in available:
        current = "edge-tts"
        await set_user_model(uid, "tts", current)
        await set_user_model(uid, "tts_voice", "svetlana")
    current_label = _tts_model_display_name(current)
    cost = CREDIT_PRICES.get(current, 0)
    await message.answer(
        f"🔊 <b>Выбери TTS модель</b>\n\nТекущая: <b>{current_label}</b> ({cost} CR)",
        reply_markup=_tts_models_kb(current, back_to_select_model=False),
    )


@router.callback_query(F.data == "tts_select_model")
async def cb_tts_select(callback: types.CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    await get_or_create_user(uid, callback.from_user.username, callback.from_user.first_name)
    if not settings.enable_tts:
        await _reply_tts_disabled(callback.message)
        return
    current = await get_user_model(uid, "tts")
    available = {m for _, m, _ in _available_tts_models()}
    if current not in available:
        current = "edge-tts"
        await set_user_model(uid, "tts", current)
        await set_user_model(uid, "tts_voice", "svetlana")
    current_label = _tts_model_display_name(current)
    cost = CREDIT_PRICES.get(current, 0)
    await callback.message.answer(
        f"🔊 <b>Выбери TTS модель</b>\n\nТекущая: <b>{current_label}</b> ({cost} CR)",
        reply_markup=_tts_models_kb(current, back_to_select_model=True))

@router.callback_query(F.data.startswith("stts_"))
async def cb_set_tts(callback: types.CallbackQuery):
    mid = callback.data.replace("stts_", "")
    if not settings.enable_tts:
        await callback.answer("Озвучка временно отключена", show_alert=True)
        await _reply_tts_disabled(callback.message)
        return
    valid = tuple(m for _, m, _ in _available_tts_models())
    if mid not in valid:
        await callback.answer("Не найдена", show_alert=True)
        return
    await set_user_model(callback.from_user.id, "tts", mid)
    default_voice = "svetlana" if mid == "edge-tts" else "nova"
    await set_user_model(callback.from_user.id, "tts_voice", default_voice)
    cost = CREDIT_PRICES.get(mid, 0)
    await callback.answer(f"✅ {mid}", show_alert=True)
    await callback.message.answer(
        f"✅ TTS: <b>{mid}</b> ({cost} CR)\n"
        f"Голос: <b>{default_voice}</b>\n\nСменить голос: /setvoice")
