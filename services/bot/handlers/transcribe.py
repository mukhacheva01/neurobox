"""НейроБокс — Модуль транскрибации: STT, суммаризация, перевод, протокол встречи."""
import time

import structlog
from aiogram import F, Router, types
from aiogram.filters import BaseFilter, Command
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from shared.db.database import get_pool
from shared.domain.credits import (
    get_or_create_user,
    refund_spend_credits,
    spend_credits,
)
from shared.domain.telemetry import elapsed_ms, log_ai_error, log_ai_success
from shared.providers.openai_stt import transcribe_audio
from shared.providers.openai_text import generate_text

router = Router()
_log = structlog.get_logger()

TRANSCRIBE_CR = 5      # базовая транскрибация
TRANSCRIBE_SUMMARY_CR = 8   # + суммаризация
TRANSCRIBE_TRANSLATE_CR = 8  # + перевод
TRANSCRIBE_PROTOCOL_CR = 12  # + протокол встречи
MAX_AUDIO_SIZE = 25 * 1024 * 1024  # 25 MB
MAX_DURATION_SEC = 7200  # 2 часа
RESPONSE_MAX_CHARS = 4000

_SUMMARY_PROMPT = (
    "Ты — ассистент-секретарь. Составь краткое содержание транскрипции. "
    "Выдели ключевые тезисы, решения, задачи, важные цифры. "
    "Формат: структурированный текст с bullet points. "
    "Длина саммари: 20-30% от исходного текста. Язык: русский."
)

_PROTOCOL_PROMPT = (
    "Ты — ассистент-секретарь. Составь протокол встречи из транскрипции. "
    "Разделы: 1) Участники (если упоминаются), 2) Обсуждённые темы, "
    "3) Принятые решения, 4) Назначенные задачи (кто, что, дедлайн), "
    "5) Открытые вопросы. "
    "Формат: структурированный документ с подзаголовками. Язык: русский."
)

_TRANSLATE_PROMPT = (
    "Переведи текст на {lang}. Сохрани форматирование и абзацы. "
    "Не добавляй пояснений — только перевод."
)

TRANSLATE_LANGS = {
    "en": "английский", "es": "испанский", "de": "немецкий",
    "fr": "французский", "zh": "китайский", "ja": "японский",
    "ko": "корейский", "ar": "арабский", "pt": "португальский",
    "it": "итальянский", "tr": "турецкий", "ru": "русский",
}


def _retry_kb(user_id: int):
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="screen_transcribe"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    return b.as_markup()


def _after_kb(user_id: int, has_text: bool = True):
    b = InlineKeyboardBuilder()
    if has_text:
        b.row(
            types.InlineKeyboardButton(text="📄 Сохранить как PDF", callback_data=f"tr_save:pdf:{user_id}"),
            types.InlineKeyboardButton(text="📝 Как TXT", callback_data=f"tr_save:txt:{user_id}"),
        )
        b.row(
            types.InlineKeyboardButton(text="📋 Суммари", callback_data=f"tr_extra:summary:{user_id}"),
            types.InlineKeyboardButton(text="📜 Протокол", callback_data=f"tr_extra:protocol:{user_id}"),
        )
        b.row(types.InlineKeyboardButton(text="🌍 Перевести", callback_data=f"tr_translate:{user_id}"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    return b.as_markup()


def _transcribe_menu_markup(back_callback: str = "more_menu"):
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="📝 Расшифровать", callback_data="tr_mode:plain"))
    b.row(types.InlineKeyboardButton(text="📋 Расшифровать + саммари", callback_data="tr_mode:summary"))
    b.row(types.InlineKeyboardButton(text="✅ Расшифровать + протокол встречи", callback_data="tr_mode:protocol"))
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data=back_callback))
    return b.as_markup()


def _transcribe_menu_text() -> str:
    return (
        "🎤 <b>Транскрибация</b>\n\n"
        "Отправь голосовое, аудиофайл или видео-кружок.\n\n"
        f"📝 Расшифровать — {TRANSCRIBE_CR} CR\n"
        f"📋 + Саммари — {TRANSCRIBE_SUMMARY_CR} CR\n"
        f"✅ + Протокол встречи — {TRANSCRIBE_PROTOCOL_CR} CR"
    )


async def _log_transcription(user_id: int, file_uid: str, duration: int, lang: str, text_len: int, mode: str, cr: int):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO transcriptions (user_id, file_unique_id, duration_sec, language, text_preview, full_text_length, mode, credits_charged) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                user_id, file_uid, duration, lang or "auto", ("" if not text_len else "")[:500], text_len, mode, cr)
    except Exception:
        pass


async def _get_cached_transcription(file_uid: str) -> str | None:
    """Кэш транскрипции по file_unique_id."""
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if r:
            val = await r.get(f"tr_cache:{file_uid}")
            if val:
                return val.decode() if isinstance(val, bytes) else val
    except Exception:
        pass
    return None


async def _set_cached_transcription(file_uid: str, text: str):
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if r:
            await r.set(f"tr_cache:{file_uid}", text[:50000], ex=3600)
    except Exception:
        pass


async def _save_user_transcription(user_id: int, text: str):
    """Сохранить последнюю транскрипцию для дальнейших операций."""
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if r:
            await r.set(f"tr_text:{user_id}", text[:50000], ex=1800)
    except Exception:
        pass


async def _get_user_transcription(user_id: int) -> str | None:
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if r:
            val = await r.get(f"tr_text:{user_id}")
            if val:
                return val.decode() if isinstance(val, bytes) else val
    except Exception:
        pass
    return None


async def _do_transcribe(bot, user_id: int, file_id: str, file_uid: str, duration: int, message: types.Message, mode: str = "plain"):
    """Основная логика транскрибации."""
    cr_map = {
        "plain": TRANSCRIBE_CR, "summary": TRANSCRIBE_SUMMARY_CR,
        "translate": TRANSCRIBE_TRANSLATE_CR, "protocol": TRANSCRIBE_PROTOCOL_CR,
    }
    cr = cr_map.get(mode, TRANSCRIBE_CR)

    # Кэш
    if mode == "plain":
        cached = await _get_cached_transcription(file_uid)
        if cached:
            await _save_user_transcription(user_id, cached)
            if len(cached) > RESPONSE_MAX_CHARS:
                doc = BufferedInputFile(cached.encode("utf-8"), filename="transcription.txt")
                await message.answer_document(document=doc, caption="📝 Транскрипция (из кэша)", reply_markup=_after_kb(user_id))
            else:
                await message.answer(f"📝 <b>Транскрипция</b>\n\n{cached}", reply_markup=_after_kb(user_id))
            return

    spend = await spend_credits(user_id, "whisper", f"transcribe_{mode}", cost_override=cr)
    if not spend["ok"]:
        if spend.get("message"):
            await message.answer(spend["message"])
            return
        from services.bot.utils.paywall import smart_paywall_message
        pw_text, kb = await smart_paywall_message("Транскрибация аудио", cr, user_id)
        await message.answer(pw_text, reply_markup=kb)
        return

    await message.chat.do("typing")
    started = time.monotonic()

    # Скачиваем файл
    try:
        file_obj = await bot.get_file(file_id)
        buf = await bot.download_file(file_obj.file_path)
        file_bytes = buf.read()
    except Exception as e:
        _log.error("transcribe_download_error", error=str(e)[:200])
        await refund_spend_credits(user_id, spend, "ошибка загрузки аудио")
        await message.answer("❌ Не удалось скачать файл.", reply_markup=_retry_kb(user_id))
        return

    if len(file_bytes) > MAX_AUDIO_SIZE:
        await refund_spend_credits(user_id, spend, "файл слишком большой")
        await message.answer(f"❌ Файл слишком большой ({len(file_bytes) // (1024*1024)} МБ). Максимум 25 МБ.")
        return

    # Транскрибация
    filename = getattr(file_obj, "file_path", "audio.ogg").split("/")[-1]
    result = await transcribe_audio(file_bytes, filename)

    if not result.get("ok"):
        await refund_spend_credits(user_id, spend, "ошибка транскрибации")
        await log_ai_error(user_id, "transcribe", "whisper", "", cr, elapsed_ms(started), result.get("error", ""), error_event="transcribe_error")
        await message.answer(f"❌ {result.get('error', 'Ошибка распознавания')}", reply_markup=_retry_kb(user_id))
        return

    text = result["text"]
    if not text.strip():
        await refund_spend_credits(user_id, spend, "пустая транскрипция")
        await message.answer("❌ Не удалось распознать речь.", reply_markup=_retry_kb(user_id))
        return

    # Кэшируем
    await _set_cached_transcription(file_uid, text)
    await _save_user_transcription(user_id, text)
    await _log_transcription(user_id, file_uid, duration, "auto", len(text), mode, cr)

    remaining = spend.get("bought", 0) + spend.get("free", 0)
    footer = f"\n\n<i>−{cr} CR | Остаток: {remaining} CR</i>"

    # Дополнительная обработка
    if mode == "summary":
        await message.chat.do("typing")
        summary_result = await generate_text(
            f"Транскрипция:\n\n{text[:15000]}", "gpt-5-nano",
            history=None, system_prompt=_SUMMARY_PROMPT)
        if summary_result.get("ok"):
            summary = summary_result["text"]
            output = f"📝 <b>Транскрипция</b>\n\n{text[:2000]}{'…' if len(text) > 2000 else ''}\n\n📋 <b>Саммари</b>\n\n{summary}"
        else:
            output = f"📝 <b>Транскрипция</b>\n\n{text[:3500]}\n\n⚠️ Суммаризация не удалась."
    elif mode == "protocol":
        await message.chat.do("typing")
        proto_result = await generate_text(
            f"Транскрипция встречи:\n\n{text[:15000]}", "gpt-5-nano",
            history=None, system_prompt=_PROTOCOL_PROMPT)
        if proto_result.get("ok"):
            output = f"📜 <b>Протокол встречи</b>\n\n{proto_result['text']}"
        else:
            output = f"📝 <b>Транскрипция</b>\n\n{text[:3500]}\n\n⚠️ Протокол не удался."
    else:
        output = f"📝 <b>Транскрипция</b>\n\n{text[:3500]}"

    await log_ai_success(user_id, "transcribe", "whisper", f"mode={mode}", cr, elapsed_ms(started))

    if len(output + footer) > 4000:
        # Отправить как файл
        doc_text = text
        if mode == "summary" and 'summary' in dir():
            doc_text = f"ТРАНСКРИПЦИЯ:\n\n{text}\n\n---\n\nСАММАРИ:\n\n{summary_result.get('text', '')}"
        elif mode == "protocol" and 'proto_result' in dir():
            doc_text = f"ПРОТОКОЛ ВСТРЕЧИ:\n\n{proto_result.get('text', '')}\n\n---\n\nТРАНСКРИПЦИЯ:\n\n{text}"
        doc_file = BufferedInputFile(doc_text.encode("utf-8"), filename="transcription.txt")
        await message.answer_document(
            document=doc_file,
            caption=f"📝 Транскрипция готова{footer}",
            reply_markup=_after_kb(user_id))
    else:
        await message.answer(output + footer, reply_markup=_after_kb(user_id))


# ── Экраны ──

@router.message(Command("transcribe"))
async def cmd_transcribe(message: types.Message):
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await message.answer(_transcribe_menu_text(), reply_markup=_transcribe_menu_markup())


@router.callback_query(F.data == "screen_transcribe")
async def cb_screen_transcribe(cb: types.CallbackQuery):
    await cb.answer()
    await cb.message.answer(_transcribe_menu_text(), reply_markup=_transcribe_menu_markup())


@router.callback_query(F.data.startswith("tr_mode:"))
async def cb_tr_mode(cb: types.CallbackQuery):
    mode = cb.data.replace("tr_mode:", "")
    await cb.answer()
    # Сохраняем режим в Redis
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if r:
            await r.set(f"tr_mode:{cb.from_user.id}", mode, ex=300)
    except Exception:
        pass
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="screen_transcribe"))
    mode_names = {"plain": "📝 Расшифровка", "summary": "📋 + Саммари", "protocol": "✅ + Протокол"}
    await cb.message.answer(
        f"Режим: <b>{mode_names.get(mode, mode)}</b>\n\n"
        "Теперь отправь голосовое сообщение, аудиофайл или видео-кружок.",
        reply_markup=b.as_markup())


# Сохранение транскрипции как документ
@router.callback_query(F.data.startswith("tr_save:"))
async def cb_tr_save(cb: types.CallbackQuery):
    parts = cb.data.split(":")
    if len(parts) < 3:
        await cb.answer()
        return
    fmt, uid_str = parts[1], parts[2]
    user_id = int(uid_str)
    if cb.from_user.id != user_id:
        await cb.answer("Не твоя кнопка.", show_alert=True)
        return
    await cb.answer()
    text = await _get_user_transcription(user_id)
    if not text:
        await cb.message.answer("Текст транскрипции не найден. Транскрибируй заново.")
        return
    if fmt == "pdf":
        try:
            from services.bot.handlers.docgen import _build_pdf
            file_bytes = _build_pdf(text, "Транскрипция")
            filename = "transcription.pdf"
        except Exception:
            file_bytes = text.encode("utf-8")
            filename = "transcription.txt"
    else:
        file_bytes = text.encode("utf-8")
        filename = "transcription.txt"
    doc_file = BufferedInputFile(file_bytes, filename=filename)
    await cb.message.answer_document(document=doc_file, caption=f"📄 Транскрипция ({fmt.upper()})")


# Дополнительная обработка: суммари / протокол для уже готовой транскрипции
@router.callback_query(F.data.startswith("tr_extra:"))
async def cb_tr_extra(cb: types.CallbackQuery):
    parts = cb.data.split(":")
    if len(parts) < 3:
        await cb.answer()
        return
    action, uid_str = parts[1], parts[2]
    user_id = int(uid_str)
    if cb.from_user.id != user_id:
        await cb.answer("Не твоя кнопка.", show_alert=True)
        return
    await cb.answer("⏳ Обрабатываю...")
    text = await _get_user_transcription(user_id)
    if not text:
        await cb.message.answer("Текст не найден. Транскрибируй заново.")
        return

    cr = TRANSCRIBE_SUMMARY_CR if action == "summary" else TRANSCRIBE_PROTOCOL_CR
    spend = await spend_credits(user_id, "gpt-5-nano", f"tr_{action}", cost_override=cr)
    if not spend["ok"]:
        if spend.get("message"):
            await cb.message.answer(spend["message"])
            return
        from services.bot.utils.paywall import smart_paywall_message
        pw, kb = await smart_paywall_message("Обработка транскрипции", cr, user_id)
        await cb.message.answer(pw, reply_markup=kb)
        return

    await cb.message.chat.do("typing")
    prompt_map = {"summary": _SUMMARY_PROMPT, "protocol": _PROTOCOL_PROMPT}
    result = await generate_text(
        f"Транскрипция:\n\n{text[:15000]}", "gpt-5-nano",
        history=None, system_prompt=prompt_map.get(action, _SUMMARY_PROMPT))

    if not result.get("ok"):
        await refund_spend_credits(user_id, spend, f"ошибка {action}")
        await cb.message.answer(f"❌ {result.get('error', 'Ошибка')}")
        return

    remaining = spend.get("bought", 0) + spend.get("free", 0)
    title = "📋 Саммари" if action == "summary" else "📜 Протокол встречи"
    output = f"{title}\n\n{result['text']}\n\n<i>−{cr} CR | Остаток: {remaining} CR</i>"

    if len(output) > 4000:
        doc_file = BufferedInputFile(result["text"].encode("utf-8"), filename=f"{action}.txt")
        await cb.message.answer_document(document=doc_file, caption=f"{title} | −{cr} CR")
    else:
        await cb.message.answer(output, reply_markup=_after_kb(user_id))


# Выбор языка для перевода
@router.callback_query(F.data.startswith("tr_translate:"))
async def cb_tr_translate(cb: types.CallbackQuery):
    uid_str = cb.data.split(":")[1]
    user_id = int(uid_str)
    if cb.from_user.id != user_id:
        await cb.answer("Не твоя кнопка.", show_alert=True)
        return
    await cb.answer()
    b = InlineKeyboardBuilder()
    for code, name in list(TRANSLATE_LANGS.items())[:8]:
        b.button(text=name.capitalize(), callback_data=f"tr_do_translate:{code}:{user_id}")
    b.adjust(2)
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="screen_transcribe"))
    await cb.message.answer("🌍 <b>Выбери язык перевода</b>", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("tr_do_translate:"))
async def cb_tr_do_translate(cb: types.CallbackQuery):
    parts = cb.data.split(":")
    if len(parts) < 3:
        await cb.answer()
        return
    lang_code, uid_str = parts[1], parts[2]
    user_id = int(uid_str)
    if cb.from_user.id != user_id:
        await cb.answer("Не твоя кнопка.", show_alert=True)
        return
    await cb.answer("🌍 Перевожу...")
    text = await _get_user_transcription(user_id)
    if not text:
        await cb.message.answer("Текст не найден. Транскрибируй заново.")
        return

    lang_name = TRANSLATE_LANGS.get(lang_code, lang_code)
    cr = TRANSCRIBE_TRANSLATE_CR
    spend = await spend_credits(user_id, "gpt-5-nano", f"translate_{lang_code}", cost_override=cr)
    if not spend["ok"]:
        if spend.get("message"):
            await cb.message.answer(spend["message"])
            return
        from services.bot.utils.paywall import smart_paywall_message
        pw, kb = await smart_paywall_message("Перевод транскрипции", cr, user_id)
        await cb.message.answer(pw, reply_markup=kb)
        return

    await cb.message.chat.do("typing")
    prompt = _TRANSLATE_PROMPT.format(lang=lang_name)
    result = await generate_text(text[:15000], "gpt-5-nano", history=None, system_prompt=prompt)
    if not result.get("ok"):
        await refund_spend_credits(user_id, spend, "ошибка перевода")
        await cb.message.answer(f"❌ {result.get('error', 'Ошибка перевода')}")
        return

    remaining = spend.get("bought", 0) + spend.get("free", 0)
    output = f"🌍 <b>Перевод ({lang_name})</b>\n\n{result['text']}\n\n<i>−{cr} CR | Остаток: {remaining} CR</i>"
    if len(output) > 4000:
        doc_file = BufferedInputFile(result["text"].encode("utf-8"), filename=f"translation_{lang_code}.txt")
        await cb.message.answer_document(document=doc_file, caption=f"🌍 Перевод ({lang_name}) | −{cr} CR")
    else:
        await cb.message.answer(output)


# ── Автоматическая транскрибация при пересылке голосового/аудио ──

class HasTranscribeMode(BaseFilter):
    """True если у пользователя активен режим транскрибации."""
    async def __call__(self, message: types.Message) -> bool | dict:
        try:
            from shared.redis.store import _get_redis
            r = await _get_redis()
            if not r:
                return False
            user_id = message.from_user.id
            mode = await r.get(f"tr_mode:{user_id}")
            if mode:
                mode = mode.decode() if isinstance(mode, bytes) else mode
                await r.delete(f"tr_mode:{user_id}")
                return {"tr_mode": mode}
            return False
        except Exception:
            return False




@router.message(HasTranscribeMode(), F.voice)
async def handle_voice_transcribe(message: types.Message, tr_mode: str = "plain"):
    """Транскрибация голосовых (только при активном режиме)."""
    user_id = message.from_user.id
    await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)
    voice = message.voice
    duration = voice.duration or 0
    await _do_transcribe(message.bot, user_id, voice.file_id, voice.file_unique_id, duration, message, tr_mode)


@router.message(HasTranscribeMode(), F.audio)
async def handle_audio_transcribe(message: types.Message, tr_mode: str = "plain"):
    """Транскрибация аудиофайлов (только при активном режиме)."""
    user_id = message.from_user.id
    await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)
    audio = message.audio
    duration = audio.duration or 0
    await _do_transcribe(message.bot, user_id, audio.file_id, audio.file_unique_id, duration, message, tr_mode)


@router.message(HasTranscribeMode(), F.video_note)
async def handle_video_note_transcribe(message: types.Message, tr_mode: str = "plain"):
    """Транскрибация видео-кружков (только при активном режиме)."""
    user_id = message.from_user.id
    await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)
    vn = message.video_note
    duration = vn.duration or 0
    await _do_transcribe(message.bot, user_id, vn.file_id, vn.file_unique_id, duration, message, "plain")
