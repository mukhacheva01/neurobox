"""НейроБокс — Модуль генерации аудио: TTS (озвучка) + музыка."""
import asyncio
import time

import structlog
from aiogram import F, Router, types
from aiogram.filters import BaseFilter, Command
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from shared.db.database import get_pool
from shared.config import settings
from shared.domain.credits import (
    CREDIT_PRICES,
    TTS_VOICES,
    get_or_create_user,
    get_user_model,
    refund_spend_credits,
    set_user_model,
    spend_credits,
)
from shared.domain.telemetry import elapsed_ms, log_ai_success

router = Router()
_log = structlog.get_logger()

# Стоимость
TTS_CR = {"edge-tts": 0, "openai-tts-mini": 5, "openai-tts-hd": 10}
MUSIC_CR = {"musicgen": 15, "suno-v4": 50}
TTS_MAX_CHARS = 4000

# Голоса для inline-выбора
VOICE_OPTIONS = [
    ("👩 Светлана (RU)", "edge-tts", "svetlana"),
    ("👨 Дмитрий (RU)", "edge-tts", "dmitry"),
    ("👩 Emma (EN)", "edge-tts", "emma"),
    ("👨 Guy (EN)", "edge-tts", "guy"),
    ("🔵 Alloy", "openai-tts-mini", "alloy"),
    ("🟣 Echo", "openai-tts-mini", "echo"),
    ("🟢 Nova", "openai-tts-mini", "nova"),
    ("⚫ Onyx", "openai-tts-mini", "onyx"),
    ("🟡 Shimmer", "openai-tts-mini", "shimmer"),
]


def _retry_kb(user_id: int, action: str = "tts"):
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="🔄 Попробовать снова", callback_data=f"audio_retry:{action}:{user_id}"))
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="screen_audio"))
    return b.as_markup()


def _after_tts_kb(user_id: int):
    b = InlineKeyboardBuilder()
    b.row(
        types.InlineKeyboardButton(text="🔄 Другой голос", callback_data="audio_choose_voice"),
        types.InlineKeyboardButton(text="📝 Новый текст", callback_data="audio_tts"),
    )
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    return b.as_markup()


def _after_music_kb(user_id: int):
    b = InlineKeyboardBuilder()
    b.row(
        types.InlineKeyboardButton(text="🔄 Переделать", callback_data=f"audio_retry:music:{user_id}"),
        types.InlineKeyboardButton(text="🎶 Новый трек", callback_data="audio_music"),
    )
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    return b.as_markup()


def _audio_unavailable_kb():
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="💬 Поддержка", callback_data="screen_support"))
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="more_menu"))
    return b.as_markup()


async def _log_audio(user_id: int, audio_type: str, voice: str, text_len: int, duration: int, cr: int):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO audio_generations (user_id, audio_type, voice, text_length, duration_sec, credits_charged) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                user_id, audio_type, voice, text_len, duration, cr)
    except Exception:
        pass


async def _generate_tts(user_id: int, text: str, tts_model: str, voice_key: str, message: types.Message):
    """Генерация TTS и отправка пользователю."""
    if len(text) > TTS_MAX_CHARS:
        text = text[:TTS_MAX_CHARS]

    cr = TTS_CR.get(tts_model, 5)
    if cr > 0:
        spend = await spend_credits(user_id, tts_model, f"tts: {text[:40]}", cost_override=cr)
        if not spend["ok"]:
            if spend.get("message"):
                await message.answer(spend["message"])
                return
            from services.bot.utils.paywall import smart_paywall_message
            pw_text, kb = await smart_paywall_message("Озвучка текста", cr, user_id)
            await message.answer(pw_text, reply_markup=kb)
            return
    else:
        spend = {"ok": True, "cost": 0, "bought": 0, "free": 0}

    await message.chat.do("record_voice")
    started = time.monotonic()

    voices = TTS_VOICES.get(tts_model, {})
    voice_info = voices.get(voice_key) or next(iter(voices.values()), None)
    if not voice_info:
        await message.answer("❌ Голос не найден.", reply_markup=_retry_kb(user_id, "tts"))
        return

    try:
        if tts_model == "edge-tts":
            from shared.providers.edge_tts_provider import generate_speech
            result = await asyncio.wait_for(generate_speech(text, voice_info["id"]), timeout=60)
        else:
            # OpenAI TTS
            import openai
            client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
            model_name = "tts-1-hd" if tts_model == "openai-tts-hd" else "tts-1"
            response = await asyncio.wait_for(
                client.audio.speech.create(model=model_name, voice=voice_info["id"], input=text),
                timeout=60)
            audio_bytes = await response.aread() if hasattr(response, 'aread') else response.read()
            result = {"ok": True, "audio_bytes": audio_bytes}
    except asyncio.TimeoutError:
        if cr > 0:
            await refund_spend_credits(user_id, spend, "тайм-аут TTS")
        await message.answer("⏱ Таймаут озвучки.", reply_markup=_retry_kb(user_id, "tts"))
        return
    except Exception as e:
        _log.error("tts_error", error=str(e)[:200], model=tts_model)
        if cr > 0:
            await refund_spend_credits(user_id, spend, "ошибка TTS")
        await message.answer(f"❌ Ошибка озвучки: {str(e)[:80]}", reply_markup=_retry_kb(user_id, "tts"))
        return

    if not result.get("ok") or not result.get("audio_bytes"):
        if cr > 0:
            await refund_spend_credits(user_id, spend, "пустой TTS")
        err = result.get("error", "Не удалось озвучить")
        await message.answer(f"❌ {err}", reply_markup=_retry_kb(user_id, "tts"))
        return

    remaining = spend.get("bought", 0) + spend.get("free", 0)
    duration = len(result["audio_bytes"]) // 8000  # примерная оценка
    await log_ai_success(user_id, "tts", tts_model, text[:200], cr, elapsed_ms(started))
    await _log_audio(user_id, "tts", voice_key, len(text), duration, cr)

    audio_file = BufferedInputFile(result["audio_bytes"], filename="voice.ogg")
    cost_text = f"−{cr} CR | " if cr > 0 else "🆓 | "
    await message.answer_voice(
        voice=audio_file,
        caption=f"<i>🔊 {voice_info['label']} | {cost_text}Остаток: {remaining} CR</i>",
        reply_markup=_after_tts_kb(user_id))


# ── Экраны ──

@router.callback_query(F.data == "screen_audio")
async def cb_screen_audio(cb: types.CallbackQuery):
    await cb.answer()
    if not settings.enable_tts and not settings.enable_music:
        await cb.message.answer("🎵 Аудио-модуль временно недоступен.", reply_markup=_audio_unavailable_kb())
        return
    b = InlineKeyboardBuilder()
    lines = ["🎵 <b>Аудио</b>", ""]
    if settings.enable_tts:
        b.row(types.InlineKeyboardButton(text="🗣 Озвучить текст", callback_data="audio_tts"))
        lines.append("🗣 Озвучить текст — AI-голоса")
    if settings.enable_music:
        b.row(types.InlineKeyboardButton(text="🎶 Создать музыку", callback_data="audio_music"))
        lines.append("🎶 Создать музыку — описание → трек")
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="more_menu"))
    await cb.message.answer("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(F.data == "audio_tts")
async def cb_audio_tts(cb: types.CallbackQuery):
    await cb.answer()
    if not settings.enable_tts:
        await cb.message.answer("🗣 Озвучка текста временно недоступна.", reply_markup=_audio_unavailable_kb())
        return
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="🎤 Выбрать голос", callback_data="audio_choose_voice"))
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="screen_audio"))
    # Проверить, есть ли pending текст от модуля документов
    has_pending = False
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if r:
            pending = await r.get(f"tts_pending:{cb.from_user.id}")
            if pending:
                has_pending = True
                b = InlineKeyboardBuilder()
                b.row(types.InlineKeyboardButton(text="🗣 Озвучить документ", callback_data="audio_tts_pending"))
                b.row(types.InlineKeyboardButton(text="🎤 Выбрать голос", callback_data="audio_choose_voice"))
                b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="screen_audio"))
    except Exception:
        pass

    text = "🗣 <b>Озвучка текста</b>\n\nОтправь текст — бот озвучит голосом AI."
    if has_pending:
        text += "\n\n📄 Есть текст из документа — можно озвучить сразу!"
    tts_model = await get_user_model(cb.from_user.id, "tts")
    voice_key = await get_user_model(cb.from_user.id, "tts_voice")
    voices = TTS_VOICES.get(tts_model, {})
    v = voices.get(voice_key, next(iter(voices.values()), None))
    label = v["label"] if v else "?"
    cr = TTS_CR.get(tts_model, 5)
    text += f"\n\n🎤 Голос: <b>{label}</b> ({cr} CR)" if cr else f"\n\n🎤 Голос: <b>{label}</b> (🆓)"
    await cb.message.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data == "audio_choose_voice")
async def cb_audio_choose_voice(cb: types.CallbackQuery):
    await cb.answer()
    if not settings.enable_tts:
        await cb.message.answer("🗣 Озвучка текста временно недоступна.", reply_markup=_audio_unavailable_kb())
        return
    b = InlineKeyboardBuilder()
    for label, model, key in VOICE_OPTIONS:
        cr = TTS_CR.get(model, 0)
        cr_txt = " 🆓" if cr == 0 else f" {cr} CR"
        b.row(types.InlineKeyboardButton(text=f"{label}{cr_txt}", callback_data=f"audio_setvoice:{model}:{key}"))
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="audio_tts"))
    await cb.message.answer("🎤 <b>Выбери голос</b>", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("audio_setvoice:"))
async def cb_audio_setvoice(cb: types.CallbackQuery):
    parts = cb.data.split(":")
    if len(parts) < 3:
        await cb.answer("Ошибка формата.")
        return
    tts_model, voice_key = parts[1], parts[2]
    user_id = cb.from_user.id
    await set_user_model(user_id, "tts", tts_model)
    await set_user_model(user_id, "tts_voice", voice_key)
    voices = TTS_VOICES.get(tts_model, {})
    v = voices.get(voice_key)
    label = v["label"] if v else voice_key
    await cb.answer(f"Голос: {label}")

    # Сохранить в Redis для перехвата текста
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if r:
            await r.set(f"tts_mode:{user_id}", f"{tts_model}:{voice_key}", ex=300)
    except Exception:
        pass

    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="audio_tts"))
    await cb.message.answer(
        f"✅ Голос: <b>{label}</b>\n\n"
        "Теперь отправь текст для озвучки (до 4000 символов).",
        reply_markup=b.as_markup())


@router.callback_query(F.data == "audio_tts_pending")
async def cb_audio_tts_pending(cb: types.CallbackQuery):
    if not settings.enable_tts:
        await cb.answer("Озвучка временно недоступна", show_alert=True)
        return
    """Озвучить текст из модуля документов."""
    await cb.answer("🔊 Озвучиваю...")
    user_id = cb.from_user.id
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if r:
            text = await r.get(f"tts_pending:{user_id}")
            if text:
                text = text.decode() if isinstance(text, bytes) else text
                await r.delete(f"tts_pending:{user_id}")
                tts_model = await get_user_model(user_id, "tts")
                voice_key = await get_user_model(user_id, "tts_voice")
                await get_or_create_user(user_id, cb.from_user.username, cb.from_user.first_name)
                await _generate_tts(user_id, text, tts_model, voice_key, cb.message)
                return
    except Exception:
        pass
    await cb.message.answer("Текст не найден. Сгенерируй документ заново.")


@router.callback_query(F.data == "audio_music")
async def cb_audio_music(cb: types.CallbackQuery):
    await cb.answer()
    if not settings.enable_music:
        await cb.message.answer("🎵 Генерация музыки временно недоступна.", reply_markup=_audio_unavailable_kb())
        return
    music_model = await get_user_model(cb.from_user.id, "music")
    cr = CREDIT_PRICES.get(music_model, 15)
    # Установить флаг в Redis
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if r:
            await r.set(f"music_mode:{cb.from_user.id}", "1", ex=300)
    except Exception:
        pass
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="screen_audio"))
    await cb.message.answer(
        f"🎶 <b>Создать музыку</b> ({cr} CR)\n\n"
        "Опиши трек: жанр, настроение, инструменты.\n\n"
        "Пример: <code>спокойный lo-fi бит с пианино и мягкими ударными, 30 секунд</code>",
        reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("audio_retry:"))
async def cb_audio_retry(cb: types.CallbackQuery):
    parts = cb.data.split(":")
    action = parts[1] if len(parts) > 1 else "tts"
    await cb.answer()
    if action == "music":
        await cb_audio_music(cb)
    else:
        await cb_audio_tts(cb)


# ── Async Filter для перехвата текста TTS/музыки ──

class HasAudioMode(BaseFilter):
    """True если у пользователя активен TTS или музыка-режим в Redis."""
    async def __call__(self, message: types.Message) -> bool | dict:
        try:
            from shared.redis.store import _get_redis
            r = await _get_redis()
            if not r:
                return False
            user_id = message.from_user.id
            tts_mode = await r.get(f"tts_mode:{user_id}")
            if tts_mode:
                tts_mode = tts_mode.decode() if isinstance(tts_mode, bytes) else tts_mode
                await r.delete(f"tts_mode:{user_id}")
                return {"audio_action": "tts", "audio_mode_data": tts_mode}
            music_mode = await r.get(f"music_mode:{user_id}")
            if music_mode:
                await r.delete(f"music_mode:{user_id}")
                return {"audio_action": "music", "audio_mode_data": "1"}
            return False
        except Exception:
            return False


@router.message(HasAudioMode(), F.text & ~F.text.startswith("/"))
async def handle_audio_text(message: types.Message, audio_action: str = "", audio_mode_data: str = ""):
    """Перехват текста для TTS или музыки."""
    user_id = message.from_user.id
    await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)
    if audio_action == "tts":
        if not settings.enable_tts:
            await message.answer("🗣 Озвучка текста временно недоступна.", reply_markup=_audio_unavailable_kb())
            return
        parts = audio_mode_data.split(":", 1)
        tts_model = parts[0] if parts else "edge-tts"
        voice_key = parts[1] if len(parts) > 1 else "svetlana"
        await _generate_tts(user_id, message.text.strip(), tts_model, voice_key, message)
    elif audio_action == "music":
        if not settings.enable_music:
            await message.answer("🎵 Генерация музыки временно недоступна.", reply_markup=_audio_unavailable_kb())
            return
        from services.bot.handlers.music import _process_music_request
        await _process_music_request(message, user_id, message.text.strip())


@router.message(Command("tts"))
async def cmd_tts(message: types.Message):
    """Команда /tts текст — быстрая озвучка."""
    if not settings.enable_tts:
        await message.answer("🗣 Озвучка текста временно недоступна.", reply_markup=_audio_unavailable_kb())
        return
    user_id = message.from_user.id
    await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("🗣 Пример: <code>/tts Привет, это тест озвучки!</code>")
        return
    text = args[1].strip()
    tts_model = await get_user_model(user_id, "tts")
    voice_key = await get_user_model(user_id, "tts_voice")
    await _generate_tts(user_id, text, tts_model, voice_key, message)
