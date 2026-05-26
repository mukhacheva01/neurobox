"""Главное меню и вспомогательные клавиатуры."""
from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from shared.config import settings


def persistent_menu_kb(credits: int = 0, add_trial: bool = False):
    """Постоянная Reply-клавиатура — компактная, с учетом активных фич."""
    b = ReplyKeyboardBuilder()
    if add_trial:
        b.row(types.KeyboardButton(text="🚀 45 мин безлимита"))

    primary = [
        types.KeyboardButton(text="💬 Чат"),
        types.KeyboardButton(text="🎨 Картинка"),
    ]
    if settings.enable_video:
        primary.append(types.KeyboardButton(text="🎬 Видео"))
    b.row(*primary)

    b.row(
        types.KeyboardButton(text="💰 Баланс"),
        types.KeyboardButton(text="⚙️ Модели"),
        types.KeyboardButton(text="📖 Гайд"),
    )

    audio_row = []
    if settings.enable_tts or settings.enable_music:
        audio_row.append(types.KeyboardButton(text="🎵 Аудио"))
    audio_row.append(types.KeyboardButton(text="🎤 Транскриб."))
    b.row(*audio_row)
    return b.as_markup(resize_keyboard=True, is_persistent=True)

# Короткие display-имена моделей для кнопок (макс ~15 символов)
_SHORT_NAMES = {
    # Text
    "gpt-5-nano": "GPT-5 nano", "gpt-4.1-nano": "GPT-4.1 nano", "gpt-4.1-mini": "GPT-4.1 mini",
    "gpt-4.1": "GPT-4.1", "gpt-5-mini": "GPT-5 mini", "gpt-5": "GPT-5", "gpt-5.1": "GPT-5.1",
    "gpt-5.2": "GPT-5.2", "gpt-5.2-pro": "GPT-5.2 Pro",
    "gemini-2.0-flash": "Gemini Flash", "gemini-2.5-flash": "Gemini 2.5", "gemini-2.5-pro": "Gemini Pro",
    "gemini-3-flash-preview": "Gemini 3", "gemini-3-pro-preview": "Gemini 3 Pro",
    "claude-haiku-4-5-20251001": "Claude Haiku", "claude-sonnet-4-5-20250929": "Claude Sonnet",
    "claude-sonnet-4-20250514": "Claude Son.4", "claude-opus-4-6": "Claude Opus",
    "claude-opus-4-1-20250805": "Claude Op.4.1",
    "deepseek-chat": "DeepSeek", "deepseek-reasoner": "DeepSeek R",
    "grok-3-mini": "Grok 3 mini", "grok-2": "Grok 2", "grok-3": "Grok 3", "grok-4": "Grok 4",
    "grok-4-1-fast-non-reasoning": "Grok 4 Fast", "grok-4-1-fast-reasoning": "Grok 4 Think",
    # Image
    "flux-2-turbo": "Flux Turbo", "flux-2-pro": "Flux Pro", "flux-2-flex": "Flux Flex",
    "flux-realism": "Flux Real", "grok-imagine-image": "Grok Img",
    "kling-image-v3": "Kling Img", "ideogram-v2": "Ideogram",
    "nano-banana": "Nano Banana", "dall-e-3": "DALL-E 3",
    "gpt-image": "GPT Image", "midjourney": "Flux Pro Ultra",
    # Video
    "kling-2.6": "Kling 2.6", "veo-3.1": "Veo 3.1", "veo-3.1-audio": "Veo 3.1+🔊",
    "sora2": "Sora 2", "runway": "Runway", "seedance": "Seedance",
    "grok-video": "Grok Video", "wanx": "WanX", "luma": "Luma",
    "freely-ai": "Freely AI", "hailuo": "Hailuo",
    # TTS
    "edge-tts": "Edge TTS 🆓", "openai-tts-mini": "OpenAI TTS", "openai-tts-hd": "OpenAI HD",
    # Music
    "musicgen": "MusicGen", "suno-v4": "Suno v4",
}


def _short(model_id: str) -> str:
    """Короткое имя модели для кнопки."""
    return _SHORT_NAMES.get(model_id, model_id)


def get_main_menu_kb(credits: int, add_trial_button: bool = False, add_48h_button: bool = False, user_id: int = 0, **kwargs):
    """Главное меню с учетом реально включенных фич."""
    b = InlineKeyboardBuilder()

    if add_trial_button:
        b.row(types.InlineKeyboardButton(text="🚀 45 мин безлимита", callback_data="trial_activate"))
    if add_48h_button:
        b.row(types.InlineKeyboardButton(text="🎁 48 часов полного доступа", callback_data="full_access_48h_activate"))

    primary = [
        types.InlineKeyboardButton(text="💬 Чат", callback_data="screen_text"),
        types.InlineKeyboardButton(text="🎨 Картинка", callback_data="screen_images"),
    ]
    if settings.enable_video:
        primary.append(types.InlineKeyboardButton(text="🎬 Видео", callback_data="screen_video"))
    b.row(*primary)

    b.row(
        types.InlineKeyboardButton(text="💳 Пополнить", callback_data="buy_credits"),
        types.InlineKeyboardButton(text="💰 Баланс", callback_data="balance"),
    )
    b.row(types.InlineKeyboardButton(text="📂 Ещё функции", callback_data="more_menu"))
    if user_id and user_id in settings.admin_id_list:
        b.row(types.InlineKeyboardButton(text="🔧 Админка", callback_data="open_admin"))
    return b.as_markup()


def get_more_menu_kb():
    """Подменю «Ещё функции» — только для активных модулей."""
    b = InlineKeyboardBuilder()
    voice_label = "🎤 Озвучка" if settings.enable_tts else "🎙 Голос"

    media_row = [types.InlineKeyboardButton(text=voice_label, callback_data="screen_voice")]
    if settings.enable_music:
        media_row.insert(0, types.InlineKeyboardButton(text="🎵 Музыка", callback_data="screen_music"))
    b.row(*media_row)

    b.row(
        types.InlineKeyboardButton(text="📷 Фото → AI", callback_data="screen_photo"),
        types.InlineKeyboardButton(text="📄 Документы", callback_data="screen_docs"),
    )
    b.row(types.InlineKeyboardButton(text="📄 Генератор док.", callback_data="screen_docgen"))
    if settings.enable_tts or settings.enable_music:
        b.row(types.InlineKeyboardButton(text="🎵 Аудио", callback_data="screen_audio"))
    b.row(types.InlineKeyboardButton(text="🎤 Транскрибация", callback_data="screen_transcribe"))
    b.row(
        types.InlineKeyboardButton(text="🛠 Инструменты", callback_data="screen_tools"),
        types.InlineKeyboardButton(text="🎭 Режим чата", callback_data="mode_open"),
    )
    b.row(
        types.InlineKeyboardButton(text="⚙️ Модели", callback_data="select_model"),
        types.InlineKeyboardButton(text="🤝 Рефералы", callback_data="screen_ref"),
    )
    b.row(
        types.InlineKeyboardButton(text="👤 Профиль", callback_data="screen_profile"),
        types.InlineKeyboardButton(text="📖 Гайд", callback_data="guide:menu"),
    )
    b.row(types.InlineKeyboardButton(text="💬 Поддержка", callback_data="screen_support"))
    b.row(
        types.InlineKeyboardButton(text="🗑 Очистить контекст", callback_data="clear_confirm"),
        types.InlineKeyboardButton(text="🤖 Наши боты", callback_data="our_bots"),
    )
    b.row(types.InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu"))
    return b.as_markup()


def back_to_main_kb():
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    return b.as_markup()


def buy_credits_kb():
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="🛒 Купить кредиты", callback_data="buy_credits"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    return b.as_markup()


def promo_credits_kb():
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="🟢 Старт: 100 CR — 49 ₽", callback_data="buy_credits"))
    b.row(types.InlineKeyboardButton(text="🛒 Все пакеты", callback_data="buy_credits"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    return b.as_markup()


def change_model_kb(callback_data: str):
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="⚙️ Сменить модель", callback_data=callback_data))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    return b.as_markup()
