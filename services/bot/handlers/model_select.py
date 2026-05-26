"""НейроБокс — Model selection handler. Тарифы на кнопках берутся из CREDIT_PRICES (единый источник)."""
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from shared.config import settings
from shared.config.text_models import TEXT_MODELS
from shared.domain.credits import (
    CREDIT_PRICES,
    FREE_MODELS,
    get_or_create_user,
    get_user_model,
    set_user_model,
)

router = Router()

# (display_name, model_id) — цена и is_free подставляются из CREDIT_PRICES и FREE_MODELS
IMAGE_MODEL_LIST = [
    ("Flux Turbo", "flux-2-turbo"),
    ("Flux Pro", "flux-2-pro"),
    ("Flux Flex", "flux-2-flex"),
    ("Flux Realism", "flux-realism"),
    ("Grok Imagine", "grok-imagine-image"),
    ("Kling Image V3", "kling-image-v3"),
    ("Ideogram V2", "ideogram-v2"),
    ("DALL-E 3", "dall-e-3"),
    ("GPT Image", "gpt-image"),
    ("Nano Banana (Google)", "nano-banana"),
    ("Flux Pro Ultra", "midjourney"),
]


def _image_price_label(model_id: str) -> str:
    """Строка цены для картинок: из CREDIT_PRICES, с эмодзи для бесплатной и midjourney."""
    cr = CREDIT_PRICES.get(model_id, "?")
    if model_id == "flux-2-turbo":
        return f"⚡ {cr} CR"
    if model_id == "midjourney":
        return f"⭐ {cr} CR"
    return f"{cr} CR"


def _image_models_with_prices():
    """(name, model_id, price_str, is_free) для обратной совместимости с guide/balance."""
    return [
        (name, mid, _image_price_label(mid), mid in FREE_MODELS)
        for name, mid in IMAGE_MODEL_LIST
    ]


IMAGE_MODELS = _image_models_with_prices()

MUSIC_MODEL_LIST = [
    ("MusicGen", "musicgen"),
    ("Suno v4", "suno-v4"),
]


def _music_models_with_prices():
    return [
        (name, mid, f"{CREDIT_PRICES.get(mid, '?')} CR", False)
        for name, mid in MUSIC_MODEL_LIST
    ]


MUSIC_MODELS = _music_models_with_prices()


async def _reply_select_model(target, user_id: int):
    b = InlineKeyboardBuilder()
    b.row(
        types.InlineKeyboardButton(text="💬 Текст", callback_data="select_text_model"),
        types.InlineKeyboardButton(text="🎨 Картинки", callback_data="select_image_model"),
    )
    if settings.enable_video:
        b.row(types.InlineKeyboardButton(text="🎬 Видео", callback_data="vmodel_select"))
    if settings.enable_tts:
        b.row(types.InlineKeyboardButton(text="🎤 Голос", callback_data="tts_select_model"))
    if settings.enable_music:
        b.row(types.InlineKeyboardButton(text="🎵 Музыка", callback_data="select_music_model"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))

    ct = await get_user_model(user_id, "text")
    ci = await get_user_model(user_id, "image")
    lines = [
        "⚙️ <b>Модели</b>",
        "",
        f"💬 Текст: <b>{ct}</b> ({CREDIT_PRICES.get(ct, '?')} CR)",
        f"🎨 Картинки: <b>{ci}</b> ({CREDIT_PRICES.get(ci, '?')} CR)",
    ]
    if settings.enable_video:
        cv = await get_user_model(user_id, "video")
        lines.append(f"🎬 Видео: <b>{cv}</b>")
    if settings.enable_music:
        cm = await get_user_model(user_id, "music")
        lines.append(f"🎵 Музыка: <b>{cm}</b> ({CREDIT_PRICES.get(cm, '?')} CR)")
    if settings.enable_tts:
        cvt = await get_user_model(user_id, "tts")
        lines.append(f"🎤 Голос: <b>{cvt}</b> ({CREDIT_PRICES.get(cvt, '?')} CR)")
    lines.extend(["", "⚡ = бесплатные CR"])
    await target.answer("\n".join(lines), reply_markup=b.as_markup())


@router.message(Command("model"))
@router.message(F.text == "⚙️ Модели")
async def msg_select_model(message: types.Message):
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await _reply_select_model(message, message.from_user.id)


@router.callback_query(F.data == "select_model")
async def cb_select_model(callback: types.CallbackQuery):
    await callback.answer()
    await _reply_select_model(callback.message, callback.from_user.id)


def _text_model_display_name(mid: str) -> str:
    for item in TEXT_MODELS:
        if item[1] == mid:
            return item[0]
    return mid


@router.callback_query(F.data == "select_text_model")
async def cb_select_text(callback: types.CallbackQuery):
    """Show all text models as a flat list."""
    await callback.answer()
    current = await get_user_model(callback.from_user.id, "text")
    current_label = _text_model_display_name(current)
    b = InlineKeyboardBuilder()
    for item in TEXT_MODELS:
        name, mid, price_str, is_free = item[0], item[1], item[2], item[3]
        m = " ✅" if mid == current else ""
        del is_free
        b.row(types.InlineKeyboardButton(text=f"{name} — {price_str}{m}", callback_data=f"set_text_{mid}"))
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="select_model"))
    await callback.message.answer(
        f"💬 <b>Текстовая модель</b>\n\nТекущая: <b>{current_label}</b> ({CREDIT_PRICES.get(current, '?')} CR)\n\nВыбери модель:",
        reply_markup=b.as_markup(),
    )


def _image_model_display_name(mid: str) -> str:
    for name, model_id, _, _ in IMAGE_MODELS:
        if model_id == mid:
            return name
    return mid


@router.callback_query(F.data == "select_image_model")
async def cb_select_image(callback: types.CallbackQuery):
    await callback.answer()
    current = await get_user_model(callback.from_user.id, "image")
    current_label = _image_model_display_name(current)
    b = InlineKeyboardBuilder()
    for name, mid, price, is_free in IMAGE_MODELS:
        m = " ✅" if mid == current else ""
        ft = " 🆓" if is_free else " 💎"
        b.row(types.InlineKeyboardButton(text=f"{name} — {price}{ft}{m}", callback_data=f"set_img_{mid}"))
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="select_model"))
    await callback.message.answer(
        f"🎨 <b>Модель картинок</b>\n\nТекущая: <b>{current_label}</b> ({CREDIT_PRICES.get(current, '?')} CR)\n\n🆓 бесплатные CR | 💎 купленные",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data.startswith("set_text_"))
async def cb_set_text(callback: types.CallbackQuery):
    mid = callback.data.replace("set_text_", "")
    valid = {m[1] for m in TEXT_MODELS}
    if mid not in valid:
        await callback.answer("Не найдена", show_alert=True)
        return
    await set_user_model(callback.from_user.id, "text", mid)
    fn = " (🆓 бесплатные CR)" if mid in FREE_MODELS else " (💎 купленные CR)"
    await callback.answer(f"✅ {mid}", show_alert=True)
    await callback.message.answer(f"✅ Текст: <b>{mid}</b> ({CREDIT_PRICES.get(mid, '?')} CR){fn}")


@router.callback_query(F.data.startswith("set_img_"))
async def cb_set_img(callback: types.CallbackQuery):
    mid = callback.data.replace("set_img_", "")
    valid = {m[1] for m in IMAGE_MODELS}
    if mid not in valid:
        await callback.answer("Не найдена", show_alert=True)
        return
    await set_user_model(callback.from_user.id, "image", mid)
    fn = " (🆓 бесплатные CR)" if mid in FREE_MODELS else " (💎 купленные CR)"
    await callback.answer(f"✅ {mid}", show_alert=True)
    await callback.message.answer(f"✅ Картинки: <b>{mid}</b> ({CREDIT_PRICES.get(mid, '?')} CR){fn}")


def _music_model_display_name(mid: str) -> str:
    for name, model_id, _, _ in MUSIC_MODELS:
        if model_id == mid:
            return name
    return mid


@router.callback_query(F.data == "select_music_model")
async def cb_select_music(callback: types.CallbackQuery):
    if not settings.enable_music:
        await callback.answer("Музыка временно недоступна", show_alert=True)
        return
    await callback.answer()
    current = await get_user_model(callback.from_user.id, "music")
    current_label = _music_model_display_name(current)
    b = InlineKeyboardBuilder()
    for name, mid, price, _ in MUSIC_MODELS:
        m = " ✅" if mid == current else ""
        b.row(types.InlineKeyboardButton(text=f"{name} — {price}{m}", callback_data=f"set_music_{mid}"))
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="select_model"))
    await callback.message.answer(
        f"🎵 <b>Модель музыки</b>\n\nТекущая: <b>{current_label}</b> ({CREDIT_PRICES.get(current, '?')} CR)",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data.startswith("set_music_"))
async def cb_set_music(callback: types.CallbackQuery):
    if not settings.enable_music:
        await callback.answer("Музыка временно недоступна", show_alert=True)
        return
    mid = callback.data.replace("set_music_", "")
    valid = {m[1] for m in MUSIC_MODELS}
    if mid not in valid:
        await callback.answer("Не найдена", show_alert=True)
        return
    await set_user_model(callback.from_user.id, "music", mid)
    await callback.answer(f"✅ {mid}", show_alert=True)
    await callback.message.answer(f"✅ Музыка: <b>{mid}</b> ({CREDIT_PRICES.get(mid, '?')} CR)")
