"""НейроБокс — Music generation (меню и /music)."""
import asyncio
import time

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from shared.config import settings
from shared.domain.credits import (
    CREDIT_PRICES,
    get_or_create_user,
    get_user_model,
    refund_spend_credits,
    spend_credits,
)
from shared.domain.telemetry import elapsed_ms, log_ai_error, log_ai_success
from shared.providers.music_router import generate_music

router = Router()


def _music_unavailable_kb():
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="💬 Поддержка", callback_data="screen_support"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    return b.as_markup()


async def run_music_gen_for_user(target: types.Message, user_id: int, prompt: str) -> None:
    """Сгенерировать музыку по промпту и отправить в target (для голоса/кружка → Музыка)."""
    if not settings.enable_music:
        await target.answer("🎵 Генерация музыки временно недоступна.", reply_markup=_music_unavailable_kb())
        return
    prompt = (prompt or "").strip()[:500]
    if not prompt:
        await target.answer("Нужен текст описания для музыки.")
        return
    model = await get_user_model(user_id, "music")
    cost = CREDIT_PRICES.get(model, 15)
    spend = await spend_credits(user_id, model, f"Музыка (голос): {prompt[:40]}")
    if not spend["ok"]:
        if spend.get("message"):
            await target.answer(spend["message"])
            return
        from services.bot.utils.paywall import smart_paywall_message
        need_cr = spend.get("cost") or cost
        text, kb = await smart_paywall_message("Генерация музыки", need_cr, user_id)
        await target.answer(text, reply_markup=kb)
        return
    status = await target.answer("🎵 Генерирую музыку... (до 2 мин)")
    task = asyncio.create_task(asyncio.wait_for(generate_music(prompt, model=model), timeout=180))
    start = time.monotonic()
    last_edit = 0.0
    while not task.done():
        await asyncio.sleep(1)
        elapsed = time.monotonic() - start
        if elapsed - last_edit >= 15:
            last_edit = elapsed
            try:
                await status.edit_text("🎵 Почти готово...")
            except Exception:
                pass
    try:
        result = task.result()
    except asyncio.TimeoutError:
        result = None
    if result is None:
        await log_ai_error(user_id, "music", model, prompt[:200], cost, elapsed_ms(start), "Таймаут генерации музыки", status="timeout", error_event="music_generation_error")
        if spend.get("cost", 0) and not spend.get("trial"):
            await refund_spend_credits(user_id, spend, "таймаут генерации музыки")
        await status.edit_text("⏱ Слишком долго.\n\n💚 Кредиты возвращены.")
        return
    if not result["ok"]:
        await log_ai_error(user_id, "music", model, prompt[:200], cost, elapsed_ms(start), result.get("error", "Ошибка"), error_event="music_generation_error")
        if spend.get("cost", 0) and not spend.get("trial"):
            await refund_spend_credits(user_id, spend, "ошибка генерации музыки")
        await status.edit_text(f"❌ {result['error']}\n\n💚 Кредиты возвращены.")
        return
    rem = spend.get("bought", 0) + spend.get("free", 0)
    await log_ai_success(user_id, "music", model, prompt[:200], cost, elapsed_ms(start), success_event="music_generated")
    caption = f"🎵 <b>{prompt[:200]}</b>\n\n<i>💰 −{cost} CR | Остаток: {rem} CR</i>"
    mus_kb = InlineKeyboardBuilder()
    mus_kb.row(
        types.InlineKeyboardButton(text="🔄 Ещё раз", callback_data=f"regen_mus:{user_id}"),
        types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"),
    )
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if r:
            await r.set(f"regen_mus_prompt:{user_id}", prompt[:500], ex=3600)
    except Exception:
        pass
    try:
        await target.answer_audio(
            audio=result["audio_url"], caption=caption, title=prompt[:60], reply_markup=mus_kb.as_markup())
        await status.delete()
    except Exception:
        await status.edit_text(f"🎵 Готово!\n\n🔗 {result['audio_url']}\n\n{caption}")


@router.message(Command("music"))
async def cmd_music(message: types.Message):
    if not settings.enable_music:
        await message.answer("🎵 Генерация музыки временно недоступна.", reply_markup=_music_unavailable_kb())
        return
    uid = message.from_user.id
    await get_or_create_user(uid, message.from_user.username, message.from_user.first_name)
    args = (message.text or "").split(maxsplit=1)
    prompt = args[1].strip() if len(args) > 1 else ""
    if not prompt:
        model = await get_user_model(uid, "music")
        cost = CREDIT_PRICES.get(model, 15)
        await message.answer(
            f"🎵 <b>Музыка</b>\n\n"
            f"Напиши описание: <code>/music энергичный synthwave трек</code>\n\n"
            f"Текущая модель: <b>{model}</b> ({cost} CR)"
        )
        return
    await run_music_gen_for_user(message, uid, prompt)


@router.callback_query(F.data.startswith("regen_mus:"))
async def cb_regen_mus(cb: types.CallbackQuery):
    if not settings.enable_music:
        await cb.answer("Музыка временно недоступна", show_alert=True)
        return
    uid = int(cb.data.split(":")[1])
    if cb.from_user.id != uid:
        await cb.answer("Это не твоя кнопка.", show_alert=True)
        return
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        prompt = (await r.get(f"regen_mus_prompt:{uid}")).decode() if r else None
    except Exception:
        prompt = None
    if not prompt:
        await cb.answer("Промпт устарел. Открой Музыку из меню и введи описание заново.", show_alert=True)
        return
    model = await get_user_model(uid, "music")
    cost = CREDIT_PRICES.get(model, 15)
    spend = await spend_credits(uid, model, f"Музыка: {prompt[:40]}")
    if not spend["ok"]:
        if spend.get("message"):
            await cb.message.answer(spend["message"])
            return
        from services.bot.utils.paywall import smart_paywall_message
        need_cr = spend.get("cost") or cost
        text, kb = await smart_paywall_message("Генерация музыки", need_cr, uid)
        await cb.message.answer(text, reply_markup=kb)
        return
    await cb.answer("🎵 Генерирую...")
    status = await cb.message.answer("🎵 Генерирую музыку... (до 2 мин)")
    task = asyncio.create_task(asyncio.wait_for(generate_music(prompt, model=model), timeout=180))
    import time
    start = time.monotonic()
    last_edit = 0.0
    while not task.done():
        await asyncio.sleep(1)
        elapsed = time.monotonic() - start
        if elapsed - last_edit >= 15:
            last_edit = elapsed
            try:
                await status.edit_text("🎵 Почти готово...")
            except Exception:
                pass
    try:
        result = task.result()
    except asyncio.TimeoutError:
        result = None
    if result is None:
        await log_ai_error(uid, "music", model, prompt[:200], cost, elapsed_ms(start), "Таймаут генерации музыки", status="timeout", error_event="music_generation_error")
        if spend.get("cost", 0) and not spend.get("trial"):
            await refund_spend_credits(uid, spend, "таймаут генерации музыки")
        await status.edit_text("⏱ Слишком долго.\n\n💚 Кредиты возвращены.")
        return
    if not result["ok"]:
        await log_ai_error(uid, "music", model, prompt[:200], cost, elapsed_ms(start), result.get("error", "Ошибка"), error_event="music_generation_error")
        if spend.get("cost", 0) and not spend.get("trial"):
            await refund_spend_credits(uid, spend, "ошибка генерации музыки")
        await status.edit_text(f"❌ {result['error']}\n\n💚 Кредиты возвращены.")
        return
    rem = spend.get("bought", 0) + spend.get("free", 0)
    await log_ai_success(uid, "music", model, prompt[:200], cost, elapsed_ms(start), success_event="music_generated")
    caption = f"🎵 <b>{prompt[:200]}</b>\n\n<i>💰 −{cost} CR | Остаток: {rem} CR</i>"
    mus_kb = InlineKeyboardBuilder()
    mus_kb.row(
        types.InlineKeyboardButton(text="🔄 Ещё раз", callback_data=f"regen_mus:{uid}"),
        types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"),
    )
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if r:
            await r.set(f"regen_mus_prompt:{uid}", prompt[:500], ex=3600)
    except Exception:
        pass
    try:
        await cb.message.answer_audio(
            audio=result["audio_url"], caption=caption, title=prompt[:60], reply_markup=mus_kb.as_markup())
        await status.delete()
    except Exception:
        await status.edit_text(f"🎵 Готово!\n\n🔗 {result['audio_url']}\n\n{caption}")
