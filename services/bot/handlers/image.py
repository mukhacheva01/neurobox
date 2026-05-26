"""НейроБокс — Image generation: /img, /img4, кнопка Апскейл."""
import asyncio
import base64
import re

import structlog
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from shared.domain.credits import (
    CREDIT_PRICES,
    get_or_create_user,
    get_user_model,
    refund_spend_credits,
    spend_credits,
)
from shared.domain.telemetry import elapsed_ms, log_ai_error, log_ai_success
from shared.providers.openrouter_image import UPSCALE_CR
from shared.providers.openrouter_image import (
    remove_background_openrouter as remove_background,
)
from shared.providers.openrouter_image import upscale_openrouter_image as upscale_image
from shared.redis.store import get_upscale_url, set_upscale_url

log = structlog.get_logger()

RMBG_CR = 5

_CYRILLIC_RE = re.compile(r'[а-яА-ЯёЁ]')


def _photo_input(url_or_data_uri):
    """Convert base64 data URI to BufferedInputFile for Telegram.
    Telegram does not accept data: URIs directly — need bytes."""
    if isinstance(url_or_data_uri, str) and url_or_data_uri.startswith("data:image/"):
        try:
            b64_part = url_or_data_uri.split(",", 1)[1] if "," in url_or_data_uri else url_or_data_uri
            raw_bytes = base64.b64decode(b64_part)
            return BufferedInputFile(raw_bytes, filename="image.png")
        except Exception:
            pass
    return url_or_data_uri

async def _maybe_translate(prompt: str) -> tuple[str, str | None]:
    """If prompt contains Cyrillic, translate to English for better image gen. Returns (eng_prompt, original_ru)."""
    if not _CYRILLIC_RE.search(prompt):
        return prompt, None
    try:
        from shared.providers.openai_text import generate_text
        result = await generate_text(
            f"Translate this image generation prompt to English. Return ONLY the translated prompt, nothing else:\n\n{prompt[:500]}",
            "gpt-5-nano", history=None)
        if result.get("ok") and result.get("text"):
            translated = result["text"].strip().strip('"').strip("'")
            if translated and len(translated) > 3:
                return translated, prompt
    except Exception:
        pass
    return prompt, None

router = Router()


async def _route_image_gen(prompt: str, model: str, num_images: int = 1, size: str = "landscape") -> dict:
    """Все модели изображений → OpenRouter (единый API)."""
    from shared.providers.openrouter_image import generate_openrouter_image
    return await generate_openrouter_image(prompt, model, num_images=num_images, size=size)


def _img_credits(model: str, num: int = 1) -> int:
    base = CREDIT_PRICES.get(model, 5)
    return base * num

IMG_PROMPT_MIN = 3
IMG_PROMPT_MAX = 2000


async def run_image_gen_for_user(target: types.Message, user_id: int, prompt: str, size: str = "landscape") -> None:
    """Сгенерировать картинку по промпту и отправить в target (для голоса/кружка → Картинка)."""
    import time as _time

    from shared.redis.store import gen_lock
    prompt = (prompt or "").strip()[:2000]
    if len(prompt) < IMG_PROMPT_MIN:
        await target.answer("Слишком короткий промпт для картинки. Нужно минимум 3 символа.")
        return
    async with gen_lock(user_id) as acquired:
        if not acquired:
            await target.answer("⏳ Предыдущий запрос ещё обрабатывается.")
            return
        model = await get_user_model(user_id, "image")
        cost = CREDIT_PRICES.get(model, 5)
        spend = await spend_credits(user_id, model, f"Картинка (голос): {prompt[:50]}")
        if not spend["ok"]:
            if spend.get("message"):
                await target.answer(spend["message"])
                return
            from services.bot.utils.paywall import smart_paywall_message
            need_cr = spend.get("cost") or cost
            text, kb = await smart_paywall_message("Генерация картинки", need_cr, user_id)
            await target.answer(text, reply_markup=kb)
            return
        _gen_start = _time.monotonic()
        await target.chat.do("upload_photo")
        status_msg = await target.answer("⏳ Генерирую картинку... ~15 сек")
        task = asyncio.create_task(asyncio.wait_for(_route_image_gen(prompt, model, size=size), timeout=150))
        last_edit = 0.0
        while not task.done():
            await asyncio.sleep(1)
            elapsed = _time.monotonic() - _gen_start
            if elapsed - last_edit >= 5:
                last_edit = elapsed
                try:
                    await status_msg.edit_text("⏳ Почти готово...")
                except Exception:
                    pass
        try:
            result = task.result()
        except asyncio.TimeoutError:
            result = None
        try:
            await status_msg.delete()
        except Exception:
            pass
        if result is None:
            await log_ai_error(user_id, "image", model, prompt[:200], cost, elapsed_ms(_gen_start), "Таймаут генерации изображения", status="timeout", error_event="image_generation_error")
            if spend.get("cost", 0) and not spend.get("trial") and not spend.get("unlimited"):
                await refund_spend_credits(user_id, spend, "таймаут регенерации")
            await target.answer("⏱ Таймаут.\n\n💚 Кредиты возвращены.")
            return
        if not result["ok"]:
            await log_ai_error(user_id, "image", model, prompt[:200], cost, elapsed_ms(_gen_start), result.get("error", "Ошибка"), error_event="image_generation_error")
            if spend.get("cost", 0) and not spend.get("trial") and not spend.get("unlimited"):
                await refund_spend_credits(user_id, spend, "ошибка регенерации")
            await target.answer(f"❌ {result['error']}\n\n💚 Кредиты возвращены.")
            return
        remaining = spend.get("bought", 0) + spend.get("free", 0)
        _elapsed = _time.monotonic() - _gen_start
        await log_ai_success(user_id, "image", model, prompt[:200], cost, int(_elapsed * 1000), success_event="image_generated")
        caption = f"🎨 <b>{prompt[:200]}</b>\n\n<i>🤖 {model} · −{cost} CR · {_elapsed:.1f}с · Остаток: {remaining} CR</i>"
        regen_kb = InlineKeyboardBuilder()
        regen_kb.row(
            types.InlineKeyboardButton(text="🔄 Ещё раз", callback_data=f"regen_img:{user_id}"),
            types.InlineKeyboardButton(text="🔍 Апскейл", callback_data="upscale"),
            types.InlineKeyboardButton(text="✂️ Убрать фон", callback_data="rmbg_under"),
        )
        regen_kb.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
        try:
            from shared.redis.store import _get_redis
            r = await _get_redis()
            if r:
                await r.set(f"regen_prompt:{user_id}", prompt[:500], ex=3600)
        except Exception:
            pass
        try:
            sent = await target.answer_photo(photo=_photo_input(result["image_url"]), caption=caption, reply_markup=regen_kb.as_markup())
            await set_upscale_url(sent.chat.id, sent.message_id, result["image_url"])
        except Exception:
            await target.answer(f"🎨 Готово!\n\n{caption}")


def _parse_size(text: str) -> tuple[str, str]:
    """Извлечь размер из текста промпта. Возвращает (prompt, size)."""
    for flag, sz in [("--square", "square"), ("--portrait", "portrait"), ("--landscape", "landscape"),
                     ("--квадрат", "square"), ("--вертик", "portrait"), ("--горизонт", "landscape")]:
        if flag in text.lower():
            return text.replace(flag, "").replace(flag.upper(), "").strip(), sz
    return text, "landscape"


@router.callback_query(F.data.startswith("regen_img:"))
async def cb_regen_img(cb: types.CallbackQuery):
    """Регенерация картинки с тем же промптом."""
    from shared.redis.store import _get_redis, gen_lock
    owner_id = int(cb.data.split(":")[1])
    if cb.from_user.id != owner_id:
        await cb.answer("Это не твоя кнопка.", show_alert=True)
        return
    async with gen_lock(owner_id) as acquired:
        if not acquired:
            await cb.answer("⏳ Предыдущий запрос ещё обрабатывается.", show_alert=True)
            return
        await cb.answer("🎨 Генерирую ещё раз...")
        try:
            r = await _get_redis()
            raw = await r.get(f"regen_prompt:{owner_id}") if r else None
            prompt = raw.decode() if raw else None
        except Exception:
            prompt = None
        if not prompt:
            await cb.message.answer("Промпт устарел. Напиши /img заново.")
            return
        model = await get_user_model(owner_id, "image")
        cost = CREDIT_PRICES.get(model, 5)
        spend = await spend_credits(owner_id, model, f"Регенерация: {prompt[:50]}")
        if not spend["ok"]:
            if spend.get("message"):
                await cb.message.answer(spend["message"])
                return
            from services.bot.utils.paywall import smart_paywall_message
            need_cr = spend.get("cost") or cost
            text, kb = await smart_paywall_message("Генерация картинки", need_cr, owner_id)
            await cb.message.answer(text, reply_markup=kb)
            return
        import time as _time
        _gen_start = _time.monotonic()
        await cb.message.chat.do("upload_photo")
        status_msg = await cb.message.answer("⏳ Генерирую картинку... ~15 сек")
        task = asyncio.create_task(asyncio.wait_for(_route_image_gen(prompt, model), timeout=150))
        last_edit = 0.0
        while not task.done():
            await asyncio.sleep(1)
            elapsed = _time.monotonic() - _gen_start
            if elapsed - last_edit >= 5:
                last_edit = elapsed
                try:
                    await status_msg.edit_text("⏳ Почти готово...")
                except Exception:
                    pass
        try:
            result = task.result()
        except asyncio.TimeoutError:
            result = None
        try:
            await status_msg.delete()
        except Exception:
            pass
        if result is None:
            await log_ai_error(owner_id, "image", model, prompt[:200], cost, elapsed_ms(_gen_start), "Таймаут генерации изображения", status="timeout", error_event="image_generation_error")
            if spend.get("cost", 0) and not spend.get("trial") and not spend.get("unlimited"):
                await refund_spend_credits(owner_id, spend, "таймаут регенерации")
            await cb.message.answer("⏱ Таймаут.\n\n💚 Кредиты возвращены.")
            return
        if not result["ok"]:
            await log_ai_error(owner_id, "image", model, prompt[:200], cost, elapsed_ms(_gen_start), result.get("error", "Ошибка"), error_event="image_generation_error")
            if spend.get("cost", 0) and not spend.get("trial") and not spend.get("unlimited"):
                await refund_spend_credits(owner_id, spend, "ошибка регенерации")
            await cb.message.answer(f"❌ {result['error']}\n\n💚 Кредиты возвращены.")
            return
        remaining = spend.get("bought", 0) + spend.get("free", 0)
        _elapsed = _time.monotonic() - _gen_start
        await log_ai_success(owner_id, "image", model, prompt[:200], cost, int(_elapsed * 1000), success_event="image_generated")
        caption = f"🎨 <b>{prompt[:200]}</b>\n\n<i>🤖 {model} · −{cost} CR · {_elapsed:.1f}с · Остаток: {remaining} CR</i>"
        regen_kb = InlineKeyboardBuilder()
        regen_kb.row(
            types.InlineKeyboardButton(text="🔄 Ещё раз", callback_data=f"regen_img:{owner_id}"),
            types.InlineKeyboardButton(text="🔍 Апскейл", callback_data="upscale"),
            types.InlineKeyboardButton(text="✂️ Убрать фон", callback_data="rmbg_under"),
        )
        regen_kb.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
        try:
            sent = await cb.message.answer_photo(photo=_photo_input(result["image_url"]), caption=caption, reply_markup=regen_kb.as_markup())
            await set_upscale_url(sent.chat.id, sent.message_id, result["image_url"])
        except Exception:
            await cb.message.answer(f"🎨 Готово!\n\n{caption}")


@router.callback_query(F.data == "upscale")
async def cb_upscale(cb: types.CallbackQuery):
    """Апскейл картинки по нажатию кнопки под сообщением с фото."""
    user_id = cb.from_user.id
    chat_id = cb.message.chat.id
    message_id = cb.message.message_id
    image_url = await get_upscale_url(chat_id, message_id)
    if not image_url:
        await cb.answer("Ссылка устарела. Сгенерируй картинку заново и нажми Апскейл.", show_alert=True)
        return
    await get_or_create_user(user_id, cb.from_user.username, cb.from_user.first_name)
    spend = await spend_credits(user_id, "upscale", "upscale", cost_override=UPSCALE_CR)
    if not spend["ok"]:
        if spend.get("message"):
            await cb.answer(spend["message"][:180], show_alert=True)
            return
        await cb.answer(f"Нужно {UPSCALE_CR} CR. Баланс: /balance", show_alert=True)
        return
    await cb.answer("🔍 Апскейлю...")
    import time as _time
    _tool_start = _time.monotonic()
    status_msg = await cb.message.answer("🔍 Улучшаю качество...")
    result = await upscale_image(image_url)
    if not result["ok"]:
        await log_ai_error(user_id, "upscale", "upscale", "upscale", UPSCALE_CR, elapsed_ms(_tool_start), result.get("error", "Ошибка"), error_event="upscale_error")
        await refund_spend_credits(user_id, spend, "ошибка апскейла")
        await status_msg.edit_text(f"❌ {result['error']}\n\n💚 Кредиты возвращены.")
        return
    remaining = spend.get("bought", 0) + spend.get("free", 0)
    await log_ai_success(user_id, "upscale", "upscale", "upscale", UPSCALE_CR, elapsed_ms(_tool_start))
    await cb.message.answer_photo(
        photo=_photo_input(result["image_url"]),
        caption=f"🔍 Апскейл | −{UPSCALE_CR} CR | Остаток: {remaining} CR",
    )
    await status_msg.delete()


@router.callback_query(F.data == "rmbg_under")
async def cb_rmbg_under(cb: types.CallbackQuery):
    """Убрать фон у картинки под сообщением (по URL из кеша апскейла)."""
    user_id = cb.from_user.id
    chat_id = cb.message.chat.id
    message_id = cb.message.message_id
    image_url = await get_upscale_url(chat_id, message_id)
    if not image_url:
        await cb.answer("Ссылка устарела. Сгенерируй картинку заново.", show_alert=True)
        return
    await get_or_create_user(user_id, cb.from_user.username, cb.from_user.first_name)
    spend = await spend_credits(user_id, "rmbg", "rmbg", cost_override=RMBG_CR)
    if not spend["ok"]:
        if spend.get("message"):
            await cb.answer(spend["message"][:180], show_alert=True)
            return
        await cb.answer(f"Нужно {RMBG_CR} CR. Баланс: /balance", show_alert=True)
        return
    await cb.answer("✂️ Убираю фон...")
    import time as _time
    _tool_start = _time.monotonic()
    status_msg = await cb.message.answer("✂️ Удаляю фон...")
    result = await remove_background(image_url=image_url)
    if not result.get("ok"):
        await log_ai_error(user_id, "rmbg", "rmbg", "rmbg_under", RMBG_CR, elapsed_ms(_tool_start), result.get("error", "Ошибка"), error_event="rmbg_error")
        await refund_spend_credits(user_id, spend, "ошибка удаления фона")
        await status_msg.edit_text(f"❌ {result.get('error', 'Ошибка')}\n\n💚 Кредиты возвращены.")
        return
    remaining = spend.get("bought", 0) + spend.get("free", 0)
    await log_ai_success(user_id, "rmbg", "rmbg", "rmbg_under", RMBG_CR, elapsed_ms(_tool_start))
    await cb.message.answer_photo(
        photo=_photo_input(result["image_url"]),
        caption=f"✂️ Фон удалён | −{RMBG_CR} CR | Остаток: {remaining} CR",
    )
    await status_msg.delete()


@router.message(Command('img'))
async def cmd_img(message: types.Message):
    """Генерация картинки: /img описание [--square|--portrait|--landscape]."""
    user_id = message.from_user.id
    args = (message.text or '').split(maxsplit=1)
    prompt = args[1].strip() if len(args) > 1 else ''
    if len(prompt) < IMG_PROMPT_MIN:
        await message.answer('🎨 Напиши описание картинки:\n\n<code>/img белый волк в Audi</code>\n\nФлаги размера: <code>--square</code> <code>--portrait</code> <code>--landscape</code>')
        return
    prompt, size = _parse_size(prompt)
    await run_image_gen_for_user(message, user_id, prompt, size=size)


@router.message(Command('img4'))
async def cmd_img4(message: types.Message):
    """Генерация 4 вариантов картинки: /img4 описание."""
    from shared.redis.store import gen_lock
    user_id = message.from_user.id
    args = (message.text or '').split(maxsplit=1)
    prompt = args[1].strip() if len(args) > 1 else ''
    if len(prompt) < IMG_PROMPT_MIN:
        await message.answer('🎨 Напиши описание для 4 вариантов:\n\n<code>/img4 белый волк в Audi</code>')
        return
    prompt, size = _parse_size(prompt)
    async with gen_lock(user_id) as acquired:
        if not acquired:
            await message.answer("⏳ Предыдущий запрос ещё обрабатывается.")
            return
        model = await get_user_model(user_id, 'image')
        cost = _img_credits(model, 4)
        spend = await spend_credits(user_id, model, f'Картинка x4: {prompt[:50]}', cost_override=cost)
        if not spend['ok']:
            from services.bot.utils.paywall import smart_paywall_message
            text, kb = await smart_paywall_message('Генерация 4 картинок', cost, user_id)
            await message.answer(text, reply_markup=kb)
            return
        import time as _time
        _gen_start = _time.monotonic()
        await message.chat.do('upload_photo')
        status_msg = await message.answer('⏳ Генерирую 4 варианта... ~30 сек')
        result = await _route_image_gen(prompt, model, num_images=4, size=size)
        try:
            await status_msg.delete()
        except Exception:
            pass
        if not result or not result.get('ok'):
            await log_ai_error(user_id, "image", model, prompt[:200], cost, elapsed_ms(_gen_start), (result or {}).get("error", "Ошибка"), error_event="image_generation_error", event_props={"variants": 4})
            await refund_spend_credits(user_id, spend, 'ошибка img4')
            await message.answer(f"❌ {result.get('error', 'Ошибка')}\n\n💚 Кредиты возвращены.")
            return
        remaining = spend.get('bought', 0) + spend.get('free', 0)
        urls = result.get('image_urls') or ([result['image_url']] if result.get('image_url') else [])
        await log_ai_success(user_id, "image", model, prompt[:200], cost, elapsed_ms(_gen_start), success_event="image_generated", event_props={"variants": len(urls) or 1})
        for i, url in enumerate(urls, 1):
            cap = f'🎨 Вариант {i}/4 — <b>{prompt[:150]}</b>' if i < len(urls) else f'🎨 Вариант {i}/4 | −{cost} CR | Остаток: {remaining} CR'
            await message.answer_photo(photo=_photo_input(url), caption=cap)
