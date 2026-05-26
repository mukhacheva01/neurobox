"""НейроБокс — Video generation + model selection + confirm + progress."""
import asyncio
import time

from aiogram import Bot, F, Router, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from shared.config import settings
from shared.domain.credits import (
    CREDIT_PRICES,
    VIDEO_MODELS,
    get_or_create_user,
    get_user_model,
    refund_spend_credits,
    set_user_model,
    spend_credits,
)
from shared.domain.telemetry import elapsed_ms, log_ai_error, log_ai_success


def _video_input(result: dict):
    """video_url (str) или BufferedInputFile из video_bytes для answer_video."""
    if result.get("video_bytes"):
        return BufferedInputFile(result["video_bytes"], filename="video.mp4")
    return result.get("video_url", "")

router = Router()


def _video_unavailable_kb():
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="💬 Поддержка", callback_data="screen_support"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    return b.as_markup()

# Порог CR для подтверждения перед генерацией
CONFIRM_THRESHOLD = 75


def _is_video_request(text: str) -> bool:
    """Проверка: пользователь просит сгенерировать видео."""
    t = (text or "").strip().lower()
    phrases = [
        "создай видео", "сгенерируй видео", "сделай видео", "нарисуй видео",
        "хочу видео", "нужно видео", "сними видео", "видео про ", "видео с ",
        "create video", "generate video", "make video", "video of ",
    ]
    return any(p in t for p in phrases)


def _extract_video_prompt(text: str) -> str:
    """Извлечь описание видео из запроса типа 'создай видео X'."""
    t = (text or "").strip()
    for phrase in [
        "создай видео ", "сгенерируй видео ", "сделай видео ", "нарисуй видео ",
        "хочу видео ", "нужно видео ", "сними видео ", "видео про ", "видео с ",
        "create video ", "generate video ", "make video ", "video of ",
    ]:
        if t.lower().startswith(phrase):
            return t[len(phrase):].strip()
    return t.strip()


## /video поддерживается + доступен через Reply-кнопку «🎬 Видео» и callback «screen_video»
## /setvideo поддерживается + доступен через callback «vmodel_select»


@router.message(Command("video"))
async def cmd_video(message: types.Message):
    if not settings.enable_video:
        await message.answer("🎬 Видео временно недоступно.", reply_markup=_video_unavailable_kb())
        return
    args = (message.text or "").split(maxsplit=1)
    prompt = args[1].strip() if len(args) > 1 else ""
    await _video_from_prompt(message, prompt)


@router.message(Command("setvideo"))
async def cmd_setvideo(message: types.Message):
    if not settings.enable_video:
        await message.answer("🎬 Видео временно недоступно.", reply_markup=_video_unavailable_kb())
        return
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await _show_models(message, message.from_user.id, False)


async def _video_from_prompt(message: types.Message, prompt: str):
    """Общая логика генерации видео по промпту (используется из callback и текстового ввода)."""
    if not settings.enable_video:
        await message.answer("🎬 Видео временно недоступно.", reply_markup=_video_unavailable_kb())
        return
    uid = message.from_user.id
    await get_or_create_user(uid, message.from_user.username, message.from_user.first_name)
    if not prompt:
        await message.answer(
            "🎬 <b>Генерация видео</b>\n\n"
            "Напиши описание, например:\n"
            "<i>красный Porsche едет по Дубаю на закате</i>\n\n"
            "Или нажми 🎬 Видео в меню.",
        )
        return
    await _process_video_text_request(message, uid, prompt)


async def _process_video_text_request(target, uid: int, prompt: str, username=None, first_name=None):
    """Обработать запрос на видео из текста. Вызывается из /video или из text handler."""
    if not settings.enable_video:
        await target.answer("🎬 Видео временно недоступно.", reply_markup=_video_unavailable_kb())
        return
    await get_or_create_user(uid, username, first_name)
    model = await get_user_model(uid, "video")
    info = VIDEO_MODELS.get(model)
    if not info:
        await target.answer("❌ Модель не найдена. /setvideo")
        return
    cost = info.get("cr", CREDIT_PRICES.get(model, 75))
    if cost >= CONFIRM_THRESHOLD:
        try:
            from shared.redis.store import _get_redis
            r = await _get_redis()
            if r:
                await r.set(f"vidprompt:{uid}", prompt[:500], ex=600)
        except Exception:
            pass
        b = InlineKeyboardBuilder()
        b.row(types.InlineKeyboardButton(text="🎬 Создать видео", callback_data=f"vidgo:{uid}"))
        b.row(types.InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu"))
        await target.answer(
            f"🎬 <b>{info['label']}</b> — {cost} CR\n\n"
            f"<i>{prompt[:200]}</i>\n\n"
            f"Подтвердить генерацию?",
            reply_markup=b.as_markup(),
        )
        return
    await _generate_video_text(target, uid, prompt, model, info, cost)


def _features(m):
    info = VIDEO_MODELS[m]
    icons = ""
    if info.get("img"):
        icons += " 🖼"
    if info.get("vid"):
        icons += " 📹"
    if info.get("audio"):
        icons += " 🔊"
    return icons


def _progress_bar(elapsed: float, total: float = 300) -> str:
    """Текстовый прогресс-бар."""
    pct = min(elapsed / total, 0.95)
    filled = int(pct * 10)
    bar = "█" * filled + "░" * (10 - filled)
    mins = int(elapsed) // 60
    secs = int(elapsed) % 60
    return f"{bar} {mins}:{secs:02d}"


async def _run_with_progress(status_msg, coro, label: str, timeout_sec: int = 400):
    """Запустить корутину с обновлением прогресса каждые 5 сек; при >2 мин — подсказка «напишу когда готово»."""
    task = asyncio.create_task(coro)
    start = time.monotonic()
    update_interval = 5
    long_wait_shown = False
    try:
        while not task.done():
            try:
                return await asyncio.wait_for(asyncio.shield(task), timeout=update_interval)
            except asyncio.TimeoutError:
                elapsed = time.monotonic() - start
                if elapsed > timeout_sec:
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
                    raise asyncio.TimeoutError()
                bar = _progress_bar(elapsed, timeout_sec)
                almost = "⏳ Почти готово..." if elapsed > 0.8 * min(timeout_sec, 120) else "⏳ Генерирую..."
                if elapsed > 120 and not long_wait_shown:
                    long_wait_shown = True
                    try:
                        await status_msg.edit_text(
                            f"🎬 {label}\n\n{bar}\n\n"
                            "⏳ Это займёт пару минут. Напишу когда будет готово — можешь пока задать другой вопрос.")
                    except Exception:
                        pass
                else:
                    try:
                        await status_msg.edit_text(
                            f"🎬 {almost} ({label})\n\n{bar}\n\n"
                            f"⏳ Обычно 1–5 мин. Не закрывай чат.")
                    except Exception:
                        pass
        return task.result()
    except asyncio.CancelledError:
        task.cancel()
        raise


@router.callback_query(F.data.startswith("vidgo:"))
async def cb_vidgo(cb: types.CallbackQuery):
    """Подтверждение генерации дорогого видео."""
    if not settings.enable_video:
        await cb.answer("Видео временно недоступно", show_alert=True)
        return
    owner_id = int(cb.data.split(":")[1])
    if cb.from_user.id != owner_id:
        await cb.answer("Это не твоя кнопка.", show_alert=True)
        return
    await cb.answer("🎬 Запускаю генерацию...")
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        prompt = (await r.get(f"vidprompt:{owner_id}")).decode() if r else None
    except Exception:
        prompt = None
    if not prompt:
        await cb.message.answer("Промпт устарел. Отправь /video заново.")
        return
    model = await get_user_model(owner_id, "video")
    info = VIDEO_MODELS.get(model)
    if not info:
        await cb.message.answer("❌ Модель не найдена. /setvideo")
        return
    cost = CREDIT_PRICES.get(model, 0)
    await _generate_video_text(cb.message, owner_id, prompt, model, info, cost)


@router.callback_query(F.data.startswith("regen_vid:"))
async def cb_regen_vid(cb: types.CallbackQuery):
    """Регенерация видео с тем же промптом."""
    if not settings.enable_video:
        await cb.answer("Видео временно недоступно", show_alert=True)
        return
    owner_id = int(cb.data.split(":")[1])
    if cb.from_user.id != owner_id:
        await cb.answer("Это не твоя кнопка.", show_alert=True)
        return
    await cb.answer("🎬 Генерирую ещё раз...")
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        prompt = (await r.get(f"regen_vid_prompt:{owner_id}")).decode() if r else None
    except Exception:
        prompt = None
    if not prompt:
        await cb.message.answer("Промпт устарел. Отправь /video заново.")
        return
    model = await get_user_model(owner_id, "video")
    info = VIDEO_MODELS.get(model)
    if not info:
        await cb.message.answer("❌ Модель не найдена.")
        return
    cost = CREDIT_PRICES.get(model, 0)
    await _generate_video_text(cb.message, owner_id, prompt, model, info, cost)


async def _generate_video_text(target, uid, prompt, model, info, cost):
    """Общая логика генерации видео из текста с прогрессом."""
    spend = await spend_credits(uid, model, "Видео: " + prompt[:40])
    if not spend["ok"]:
        if spend.get("message"):
            await target.answer(spend["message"])
            return
        from services.bot.utils.paywall import smart_paywall_message
        text, kb = await smart_paywall_message(f"Видео {info['label']}", cost, uid)
        await target.answer(text, reply_markup=kb)
        return
    _gen_start = time.monotonic()
    if getattr(settings, "use_video_queue", False):
        from shared.redis.store import push_task
        chat_id = target.chat.id if hasattr(target, "chat") else uid
        task = {
            "type": "video_generate",
            "user_id": uid,
            "chat_id": chat_id,
            "prompt": prompt[:500],
            "model": model,
            "cost": cost,
            "label": info.get("label", "Видео"),
            "trial": bool(spend.get("trial")),
            "unlimited": bool(spend.get("unlimited")),
            "policy_usage": spend.get("policy_usage"),
        }
        if await push_task(task):
            await target.answer(
                f"🎬 <b>{info['label']}</b> — видео поставлено в очередь.\n\n"
                f"Пришлю результат в чат в течение 1–5 мин. Не закрывай бота."
            )
            return
    status = await target.answer(f"🎬 Генерирую ({info['label']})...\n\n░░░░░░░░░░ 0:00\n\n⏳ Обычно занимает 1–5 мин.")
    try:
        await target.chat.do("upload_video")
    except Exception:
        pass
    try:
        from shared.providers.falai_video import generate_video
        result = await _run_with_progress(status, generate_video(prompt, info["endpoint"]), info["label"], 400)
    except asyncio.TimeoutError:
        await log_ai_error(uid, "video", model, prompt[:200], cost, elapsed_ms(_gen_start), "Таймаут генерации видео", status="timeout", error_event="video_generation_error")
        if spend.get("cost", 0) and not spend.get("trial") and not spend.get("unlimited"):
            await refund_spend_credits(uid, spend, "таймаут генерации видео")
        try:
            await status.edit_text("⏱ Генерация видео заняла слишком долго. Попробуй позже.\n\n💚 Кредиты возвращены.")
        except Exception:
            await target.answer("⏱ Генерация видео заняла слишком долго. Кредиты возвращены.")
        return
    except Exception as e:
        import structlog
        await log_ai_error(uid, "video", model, prompt[:200], cost, elapsed_ms(_gen_start), str(e), status="exception", error_event="video_generation_error")
        structlog.get_logger().error("video gen error", error=str(e), user_id=uid)
        if spend.get("cost", 0) and not spend.get("trial") and not spend.get("unlimited"):
            await refund_spend_credits(uid, spend, "ошибка генерации видео")
        try:
            await status.edit_text(f"❌ Ошибка генерации: {str(e)[:150]}\n\n💚 Кредиты возвращены.")
        except Exception:
            await target.answer("❌ Ошибка генерации. Кредиты возвращены.")
        return
    if not result["ok"]:
        await log_ai_error(uid, "video", model, prompt[:200], cost, elapsed_ms(_gen_start), result.get("error", "Ошибка"), error_event="video_generation_error")
        if spend.get("cost", 0) and not spend.get("trial") and not spend.get("unlimited"):
            await refund_spend_credits(uid, spend, "ошибка генерации видео")
        await status.edit_text("❌ " + result["error"] + "\n\n💚 Кредиты возвращены.")
        return
    rem = spend.get("bought", 0) + spend.get("free", 0)
    caption = f"🎬 <b>{prompt[:200]}</b>\n\n<i>💰 −{cost} CR | Остаток: {rem} CR | {info['label']}</i>"
    vid_kb = InlineKeyboardBuilder()
    vid_kb.row(
        types.InlineKeyboardButton(text="🔄 Ещё раз", callback_data=f"regen_vid:{uid}"),
        types.InlineKeyboardButton(text="⚙️ Модель", callback_data="vmodel_select"),
    )
    vid_kb.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if r:
            await r.set(f"regen_vid_prompt:{uid}", prompt[:500], ex=3600)
    except Exception:
        pass
    video_input = _video_input(result)
    if not video_input:
        await log_ai_error(uid, "video", model, prompt[:200], cost, elapsed_ms(_gen_start), "Видео не получено", error_event="video_generation_error")
        if spend.get("cost", 0) and not spend.get("trial") and not spend.get("unlimited"):
            await refund_spend_credits(uid, spend, "видео не получено")
        await status.edit_text("❌ Не удалось получить видео. Попробуй другую модель или позже.\n\n💚 Кредиты возвращены.")
        return
    await log_ai_success(uid, "video", model, prompt[:200], cost, elapsed_ms(_gen_start), success_event="video_generated")
    try:
        await target.answer_video(video=video_input, caption=caption, reply_markup=vid_kb.as_markup())
        await status.delete()
    except Exception as e:
        import structlog
        structlog.get_logger().error("answer_video failed", error=str(e), user_id=uid)
        link = result.get("video_url") or "(файл не загружен)"
        await status.edit_text(f"🎬 Видео готово!\n\n{link}\n\n{caption}")


@router.message(F.photo & F.caption.startswith("/video"))
async def handle_photo_video(message: types.Message, bot: Bot):
    uid = message.from_user.id
    await get_or_create_user(uid, message.from_user.username, message.from_user.first_name)
    cap_parts = message.caption.split(maxsplit=1)
    prompt = cap_parts[1] if len(cap_parts) > 1 else ""
    model = await get_user_model(uid, "video")
    info = VIDEO_MODELS.get(model)
    if not info:
        await message.answer("❌ Модель не найдена. /setvideo")
        return
    if not info.get("img"):
        await message.answer(f"❌ {info['label']} не поддерживает image-to-video.")
        return
    cost = CREDIT_PRICES.get(model, 0)
    spend = await spend_credits(uid, model, "Видео i2v: " + prompt[:30])
    if not spend["ok"]:
        if spend.get("message"):
            await message.answer(spend["message"])
            return
        from services.bot.utils.paywall import smart_paywall_message
        text, kb = await smart_paywall_message(f"Видео из фото ({info.get('label', model)})", cost, uid)
        await message.answer(text, reply_markup=kb)
        return
    _gen_start = time.monotonic()
    status = await message.answer(f"🎬 Из фото ({info['label']})...\n\n░░░░░░░░░░ 0:00\n\n⏳ Обычно 1–5 мин.")
    await message.chat.do("upload_video")
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    try:
        image_url = f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"
        from shared.providers.falai_video import generate_video
        result = await _run_with_progress(
            status, generate_video(prompt, info["endpoint"], image_url=image_url), info["label"], 400)
    except asyncio.TimeoutError:
        await log_ai_error(uid, "video", model, prompt[:200], cost, elapsed_ms(_gen_start), "Таймаут генерации видео i2v", status="timeout", error_event="video_generation_error", event_props={"source": "i2v"})
        if spend.get("cost", 0) and not spend.get("trial") and not spend.get("unlimited"):
            await refund_spend_credits(uid, spend, "таймаут генерации видео i2v")
        await status.edit_text("⏱ Генерация видео заняла слишком долго.\n\n💚 Кредиты возвращены.")
        return
    if not result["ok"]:
        await log_ai_error(uid, "video", model, prompt[:200], cost, elapsed_ms(_gen_start), result.get("error", "Ошибка"), error_event="video_generation_error", event_props={"source": "i2v"})
        if spend.get("cost", 0) and not spend.get("trial") and not spend.get("unlimited"):
            await refund_spend_credits(uid, spend, "ошибка генерации видео i2v")
        await status.edit_text("❌ " + result["error"] + "\n\n💚 Кредиты возвращены.")
        return
    rem = spend.get("bought", 0) + spend.get("free", 0)
    caption = f"🎬 <b>i2v: {prompt[:150]}</b>\n\n<i>💰 −{cost} CR | Остаток: {rem} CR | {info['label']}</i>"
    video_input = _video_input(result)
    if not video_input:
        await log_ai_error(uid, "video", model, prompt[:200], cost, elapsed_ms(_gen_start), "Видео i2v не получено", error_event="video_generation_error", event_props={"source": "i2v"})
        if spend.get("cost", 0) and not spend.get("trial") and not spend.get("unlimited"):
            await refund_spend_credits(uid, spend, "видео i2v не получено")
        await status.edit_text("❌ Не удалось получить видео. Попробуй другую модель.\n\n💚 Кредиты возвращены.")
        return
    await log_ai_success(uid, "video", model, prompt[:200], cost, elapsed_ms(_gen_start), success_event="video_generated", event_props={"source": "i2v"})
    try:
        await message.answer_video(video=video_input, caption=caption)
        await status.delete()
    except Exception as e:
        import structlog
        structlog.get_logger().error("answer_video i2v failed", error=str(e), user_id=uid)
        link = result.get("video_url") or "(файл не загружен)"
        await status.edit_text(f"🎬 Готово!\n\n{link}\n\n{caption}")


async def _show_models(target, uid, edit):
    """Показать все видео-модели."""
    current = await get_user_model(uid, "video")
    b = InlineKeyboardBuilder()
    for mid, info in VIDEO_MODELS.items():
        mark = "✅ " if mid == current else ""
        feat = _features(mid)
        b.row(types.InlineKeyboardButton(
            text=f"{mark}{info['label']} — {info['cr']} CR{feat}",
            callback_data=f"svid_{mid}"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    current_info = VIDEO_MODELS.get(current, {})
    current_label = current_info.get("label", current)
    current_cr = current_info.get("cr", CREDIT_PRICES.get(current, "?"))
    text = f"🎬 <b>Выбор модели видео</b>\n\nТекущая: <b>{current_label}</b> ({current_cr} CR)\n\n🖼 картинка | 📹 видео | 🔊 звук"
    if edit and hasattr(target, "message"):
        try:
            await target.message.edit_text(text, reply_markup=b.as_markup())
        except Exception:
            await target.message.answer(text, reply_markup=b.as_markup())
    else:
        await target.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data == "vmodel_select")
async def cb_vmodel_select(callback: types.CallbackQuery):
    await callback.answer()
    await _show_models(callback, callback.from_user.id, True)


@router.callback_query(F.data.startswith("svid_"))
async def cb_setvid(callback: types.CallbackQuery):
    mid = callback.data.replace("svid_", "")
    if mid not in VIDEO_MODELS:
        await callback.answer("Не найдена", show_alert=True)
        return
    info = VIDEO_MODELS[mid]
    await set_user_model(callback.from_user.id, "video", mid)
    feat = _features(mid)
    await callback.answer(f"✅ {info['label']}", show_alert=True)
    await callback.message.answer(f"✅ Видео: <b>{info['label']}</b> ({info['cr']} CR){feat}")
