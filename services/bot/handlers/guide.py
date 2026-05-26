"""НейроБокс — Интерактивный гайд: кнопка «📖 Гайд», команды /guide и /help."""
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.bot.handlers.model_select import IMAGE_MODELS, MUSIC_MODELS, TEXT_MODELS
from shared.config import settings
from shared.domain.credits import (
    CREDIT_PRICES,
    FREE_MODELS,
    REFEREE_CR,
    REFERRAL_LEVELS,
    REFERRER_CR,
    STREAK_BONUSES,
    TRIAL_DURATION_MINUTES,
    VIDEO_MODELS,
    get_credit_packs,
)

router = Router()

# ── Порядок разделов для навигации «▶️ Далее» ──
SECTIONS_ORDER = [
    "start",
    "text",
    "images",
    "video",
    "voice",
    "tools",
    "credits",
    "packs",
    "bonuses",
    "referral",
    "choose_model",
    "faq",
]


def _guide_menu_kb():
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="🚀 Быстрый старт", callback_data="guide:start"))
    b.row(types.InlineKeyboardButton(text="💬 Текст (GPT-5, Claude, Gemini...)", callback_data="guide:text"))
    b.row(types.InlineKeyboardButton(text="🎨 Картинки (Flux, DALL-E, GPT Image)", callback_data="guide:images"))
    if settings.enable_video:
        b.row(types.InlineKeyboardButton(text="🎬 Видео", callback_data="guide:video"))
    else:
        b.row(types.InlineKeyboardButton(text="🎬 Видео (временно недоступно)", callback_data="guide:video"))
    voice_label = "🎤 Транскрибация и голос" if settings.enable_tts or settings.enable_music else "🎤 Транскрибация"
    b.row(types.InlineKeyboardButton(text=voice_label, callback_data="guide:voice"))
    tools_label = "🛠 Инструменты (фон, OCR, поиск)" if (settings.serper_api_key or "").strip() else "🛠 Инструменты (фон, OCR, резюме)"
    b.row(types.InlineKeyboardButton(text=tools_label, callback_data="guide:tools"))
    b.row(types.InlineKeyboardButton(text="💰 Кредиты — как устроены", callback_data="guide:credits"))
    b.row(types.InlineKeyboardButton(text="🛒 Пакеты и цены", callback_data="guide:packs"))
    b.row(types.InlineKeyboardButton(text="🎁 Бонусы и промокоды", callback_data="guide:bonuses"))
    b.row(types.InlineKeyboardButton(text="🤝 Пригласи друга", callback_data="guide:referral"))
    b.row(types.InlineKeyboardButton(text="🤖 Какую модель выбрать", callback_data="guide:choose_model"))
    b.row(types.InlineKeyboardButton(text="❓ FAQ", callback_data="guide:faq"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    return b.as_markup()


def _section_nav_kb(section: str):
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="📖 К разделам", callback_data="guide:menu"))
    nav_buttons = []
    idx = SECTIONS_ORDER.index(section) if section in SECTIONS_ORDER else -1
    if idx > 0:
        nav_buttons.append(
            types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"guide:{SECTIONS_ORDER[idx - 1]}")
        )
    if 0 <= idx < len(SECTIONS_ORDER) - 1:
        nav_buttons.append(
            types.InlineKeyboardButton(text="▶️ Далее", callback_data=f"guide:{SECTIONS_ORDER[idx + 1]}")
        )
    if nav_buttons:
        b.row(*nav_buttons)
    return b.as_markup()


# ── 1. Что такое НейроБокс + Быстрый старт ──

def _text_quick_start():
    free = settings.free_daily_credits
    bonus = getattr(settings, "daily_login_bonus_credits", 5)
    trial_m = TRIAL_DURATION_MINUTES
    return (
        "🚀 <b>Что такое НейроБокс?</b>\n\n"
        "AI-бот для текста, картинок, документов и транскрибации — всё в одном Telegram-боте.\n\n"
        "<b>Как начать за 30 секунд:</b>\n"
        f"1️⃣ Нажми «🚀 {trial_m} мин безлимита» в меню — тестируй без ограничений.\n"
        "2️⃣ Просто напиши сообщение — бот ответит через AI.\n"
        "3️⃣ Хочешь картинку? Напиши <code>/img кот в космосе</code>.\n\n"
        f"Каждый день ты получаешь <b>{free} бесплатных CR</b> + <b>{bonus} CR</b> за вход.\n\n"
        "💡 Просто пиши боту — как в обычный чат!"
    )


# ── 2. Текст ──

def _text_models_section():
    count = len(TEXT_MODELS)
    lines = [f"💬 <b>Текстовые нейросети</b> ({count} моделей)\n"]
    # Группировка по цене
    groups = {}
    for name, mid, price_str, is_free, *desc in TEXT_MODELS:
        cr = CREDIT_PRICES.get(mid, 0)
        groups.setdefault(cr, []).append((name, mid, is_free))
    for cr_val in sorted(groups.keys()):
        items = groups[cr_val]
        names = ", ".join(n for n, _, _ in items)
        free_tag = " 🆓" if any(f for _, _, f in items) else ""
        lines.append(f"<b>{cr_val} CR{free_tag}:</b> {names}")
    lines.append(
        "\n<b>Как пользоваться:</b>\n"
        "→ Напиши сообщение — бот ответит текущей моделью.\n"
        "→ Сменить: меню ⚙️ Модели → Текст, или /model.\n"
        "→ /clear — очистить контекст диалога.\n"
        "→ 🎙 Голосовое сообщение — бот распознает и ответит текстом."
    )
    return "\n".join(lines)


# ── 3. Картинки ──

def _text_images_section():
    count = len(IMAGE_MODELS)
    lines = [f"🎨 <b>Генерация картинок</b> ({count} моделей)\n"]
    for name, mid, price_str, is_free in IMAGE_MODELS:
        cr = CREDIT_PRICES.get(mid, "?")
        free = " 🆓" if is_free else ""
        lines.append(f"• {name} — {cr} CR{free}")
    lines.append(
        "\n<b>Команды:</b>\n"
        "<code>/img описание</code> — одна картинка\n"
        "<code>/img4 описание</code> — 4 варианта (×4 CR)\n"
        "Размеры: <code>--landscape</code>, <code>--square</code>, <code>--portrait</code>\n\n"
        "После генерации: 🔄 Ещё раз, 🔍 Апскейл.\n"
        "📷 Фото + подпись «измени...» — редактирование."
    )
    return "\n".join(lines)


# ── 4. Видео ──

def _text_video_section():
    count = len(VIDEO_MODELS)
    lines = [f"🎬 <b>Генерация видео</b> ({count} моделей)\n"]
    for mid, info in VIDEO_MODELS.items():
        cr = info.get("cr", CREDIT_PRICES.get(mid, "?"))
        label = info.get("label", mid)
        icons = ""
        if info.get("img"):
            icons += " 🖼"
        if info.get("vid"):
            icons += " 📹"
        if info.get("audio"):
            icons += " 🔊"
        lines.append(f"• {label} — {cr} CR{icons}")
    lines.append(
        "\n🖼 = из фото | 📹 = из видео | 🔊 = со звуком\n\n"
        "<b>Команды:</b>\n"
        "<code>/video описание</code> — из текста\n"
        "📷 Фото + <code>/video промпт</code> — из картинки\n\n"
        "⏳ Генерация занимает 1–5 мин. Выбор модели: /setvideo."
    )
    return "\n".join(lines)


# ── 5. Голос и музыка ──

def _text_voice_section():
    lines = ["🎤 <b>Голос и музыка</b>\n"]
    if settings.enable_tts:
        lines.extend([
            "\n<b>Озвучка (TTS):</b>\n"
            f"• Edge TTS — {CREDIT_PRICES.get('edge-tts', 0)} CR 🆓\n"
            f"• OpenAI TTS — {CREDIT_PRICES.get('openai-tts-mini', 3)} CR\n"
            f"• OpenAI TTS HD — {CREDIT_PRICES.get('openai-tts-hd', 8)} CR\n"
            "→ <code>/voice текст</code> — озвучить.\n"
            "→ /settts — модель, /setvoice — голос.\n"
        ])
    else:
        lines.extend([
            "\n<b>Голос:</b>\n"
            "• Озвучка текста временно отключена до восстановления провайдера.\n"
            "• Голосовые сообщения и кружки продолжают работать.\n"
        ])
    lines.append("\n<b>Музыка:</b>\n")
    for name, mid, price_str, _ in MUSIC_MODELS:
        del price_str
        cr = CREDIT_PRICES.get(mid, "?")
        lines.append(f"• {name} — {cr} CR")
    lines.append(
        "\n→ <code>/music описание</code> — генерация трека.\n\n"
        "<b>Распознавание речи:</b>\n"
        f"🎙 Голосовое → текст (Whisper, {CREDIT_PRICES.get('whisper', 5)} CR/мин)."
    )
    return "\n".join(lines)


# ── 6. Инструменты ──

def _text_tools_section():
    search_enabled = bool((settings.serper_api_key or "").strip())
    text_lines = []
    if search_enabled:
        text_lines.append("• <code>/search запрос</code> — AI + веб-поиск")
    text_lines.extend([
        "• <code>/summary URL</code> — резюме статьи",
        "• <code>/code код</code> — AI-разбор кода и улучшения (2 CR)",
    ])

    return (
        "🛠 <b>Инструменты</b>\n\n"
        "<b>Фото:</b>\n"
        f"• <code>/rmbg</code> — удаление фона ({CREDIT_PRICES.get('rmbg', 5)} CR)\n"
        f"• <code>/ocr</code> — текст из фото ({CREDIT_PRICES.get('ocr', 3)} CR)\n"
        f"• <code>/style описание</code> — стилизация ({CREDIT_PRICES.get('style', 8)} CR)\n"
        "→ Отправь фото с подписью-командой или ответь командой на фото.\n\n"
        "<b>Текстовые:</b>\n"
        + "\n".join(text_lines)
        + "\n\n"
        "<b>Документы:</b>\n"
        "• <code>/doc описание</code> — сгенерировать текстовый документ\n"
        "• Отправь PDF/DOCX — бот проанализирует\n\n"
        "<b>Прочее:</b>\n"
        "• /save — сохранить промпт в избранное\n"
        "• /favorites — список избранного\n"
        "• /export — экспорт чата"
    )


# ── 7. Кредиты ──

def _text_credits_section():
    free = settings.free_daily_credits
    bonus = getattr(settings, "daily_login_bonus_credits", 5)
    free_names = []
    for name, mid, *_ in TEXT_MODELS:
        if mid in FREE_MODELS:
            free_names.append(name)
    for name, mid, *_ in IMAGE_MODELS:
        if mid in FREE_MODELS:
            free_names.append(name)
    free_line = f"<b>Бесплатные модели:</b> {', '.join(free_names)}"
    if settings.enable_tts:
        free_line += ", Edge TTS"
    free_line += ", Whisper."
    basic_usage = "Хватает для базовых задач: вопросы, простые картинки, озвучка." if settings.enable_tts else "Хватает для базовых задач: вопросы, простые картинки, распознавание голоса."
    return (
        "💰 <b>Как работают кредиты</b>\n\n"
        "Каждое действие стоит кредиты (CR). Чем мощнее модель — тем дороже.\n\n"
        f"🆓 <b>Бесплатно каждый день:</b> {free} CR (в 00:00) + {bonus} CR за вход.\n"
        "💎 <b>Купленные CR</b> — бессрочные, не сгорают.\n\n"
        f"{free_line}\n"
        f"{basic_usage}\n\n"
        "Премиум-модели (GPT-5, Claude, GPT Image и другие) — за купленные CR.\n\n"
        "Баланс: /balance или 💰 Баланс в меню."
    )


# ── 8. Пакеты ──

async def _text_packs_section():
    packs = await get_credit_packs()
    lines = ["🛒 <b>Пакеты кредитов</b>\n"]
    for pid, p in packs.items():
        if pid.startswith("sub_"):
            continue
        disc = f" (скидка {p['discount']})" if p.get("discount") else ""
        lines.append(f"• {p['label']} — <b>{p['credits']:,} CR</b> за {p['price_rub']} ₽{disc}")

    methods = []
    if settings.enable_stars_payment:
        methods.append("⭐ Telegram Stars")
    if settings.enable_yookassa_payment:
        methods.append("💳 Карта / СБП (ЮKassa)")
    if settings.enable_cryptobot_payment:
        methods.append("💰 Крипта USDT/TON (CryptoBot)")

    if methods:
        payment_block = "\n".join(methods)
        footer = "Нажми 💳 Пополнить в меню → выбери пакет → способ оплаты."
    else:
        payment_block = "⚠️ Покупки временно недоступны. Напиши в поддержку."
        footer = "Как только оплаты будут доступны, кнопка пополнения снова появится в меню."

    lines.append(
        "\nЧем больше пакет — тем дешевле каждый кредит.\n"
        "Купленные CR не сгорают.\n\n"
        "<b>Способы оплаты:</b>\n"
        f"{payment_block}\n\n"
        f"{footer}"
    )
    return "\n".join(lines)


# ── 9. Бонусы ──

def _text_bonuses_section():
    trial_m = TRIAL_DURATION_MINUTES
    free = settings.free_daily_credits
    bonus = getattr(settings, "daily_login_bonus_credits", 5)
    streak_text = ", ".join(f"{d} дн. → +{cr} CR" for d, cr in sorted(STREAK_BONUSES.items()))
    return (
        "🎁 <b>Бонусы</b>\n\n"
        f"<b>🚀 Пробный период:</b> {trial_m} мин безлимита — все модели без списания CR. "
        "Активация: кнопка в меню при первом входе (один раз).\n\n"
        f"<b>🎁 Ежедневный бонус:</b> +{bonus} CR за каждый вход (раз в сутки).\n\n"
        f"<b>🔥 Серия входов (страйки):</b>\n{streak_text}.\n"
        "Заходи каждый день — бонус растёт!\n\n"
        f"<b>🆓 Бесплатные CR:</b> {free} CR начисляются в 00:00 каждый день.\n\n"
        "<b>🎟 Промокоды:</b> <code>/promo КОД</code> — моментальное начисление CR."
    )


# ── 10. Рефералы ──

def _text_referral_section():
    levels_text = "Старт (×1)"
    for min_ref, mult, name in REFERRAL_LEVELS:
        levels_text += f" → {name} ({min_ref}+ друзей, ×{mult})"
    return (
        "🤝 <b>Пригласи друга</b>\n\n"
        f"За каждого друга:\n"
        f"• Тебе: <b>+{REFERRER_CR} CR</b> (×множитель уровня)\n"
        f"• Другу: <b>+{REFEREE_CR} CR</b> на старте.\n\n"
        f"<b>Уровни:</b> {levels_text}\n\n"
        "Чем выше уровень — тем больше бонус за каждого нового друга.\n\n"
        "Твоя ссылка: /ref или 🤝 Рефералы в меню. Просто скопируй и отправь!"
    )


# ── 11. Какую модель выбрать ──

def _text_choose_model():
    return (
        "🤖 <b>Какую модель выбрать?</b>\n\n"
        "<b>Текст (быстрые вопросы):</b>\n"
        "→ GPT-5 nano или Gemini Flash — 1 CR, быстро 🆓\n\n"
        "<b>Текст (сложные задачи, код):</b>\n"
        "→ GPT-5, Claude Sonnet 4 — 15 CR, глубокий анализ\n"
        "→ Claude Opus 4.6, GPT-5.2 — 25 CR, максимум\n\n"
        "<b>Картинки (быстро):</b>\n"
        "→ Flux Turbo — 5 CR, хорошее качество 🆓\n\n"
        "<b>Картинки (премиум):</b>\n"
        "→ GPT Image — 12 CR, фотореализм\n"
        "→ Flux Pro+ — 20 CR, максимальное качество\n\n"
        "<b>Транскрибация:</b>\n"
        "→ Просто отправь голосовое, аудио или видео-кружок.\n\n"
        "💡 Начни с бесплатных моделей, переключайся на премиум для важных задач."
    )


# ── 12. FAQ ──

def _text_faq():
    free = settings.free_daily_credits
    return (
        "❓ <b>Часто задаваемые вопросы</b>\n\n"
        "<b>Сколько стоит пользоваться ботом?</b>\n"
        f"Базовые функции бесплатны: {free} CR каждый день + бонус за вход.\n\n"
        "<b>Купленные кредиты сгорают?</b>\n"
        "Нет. Купленные CR хранятся бессрочно. Сгорают только бесплатные (обновляются ежедневно).\n\n"
        "<b>Как сменить модель?</b>\n"
        "Меню → ⚙️ Модели → выбери категорию. Или /model.\n\n"
        "<b>Бот не отвечает — что делать?</b>\n"
        "Напиши /start — перезагрузка. Или /cancel — сброс FSM.\n\n"
        "<b>Как получить бесплатные кредиты?</b>\n"
        "Заходи каждый день (бонус + страйки), приглашай друзей (/ref), используй промокоды (/promo)."
    )


# ── Роутинг ──

async def _get_section_text(section: str) -> str:
    _map = {
        "start": _text_quick_start,
        "text": _text_models_section,
        "images": _text_images_section,
        "video": _text_video_section,
        "voice": _text_voice_section,
        "tools": _text_tools_section,
        "credits": _text_credits_section,
        "packs": _text_packs_section,
        "bonuses": _text_bonuses_section,
        "referral": _text_referral_section,
        "choose_model": _text_choose_model,
        "faq": _text_faq,
    }
    fn = _map.get(section, _text_quick_start)
    if section == "packs":
        return await fn()
    return fn()


@router.message(Command("guide"))
@router.message(Command("help"))
@router.message(F.text == "📖 Гайд")
async def msg_guide(message: types.Message):
    await message.answer(
        "📖 <b>Гайд по НейроБокс</b>\n\n"
        "Здесь всё о возможностях бота. Выбери раздел:",
        reply_markup=_guide_menu_kb(),
    )


GUIDE_MENU_TEXT = (
    "📖 <b>Гайд по НейроБокс</b>\n\n"
    "Здесь всё о возможностях бота. Выбери раздел:"
)


@router.callback_query(F.data.in_({"guide:menu", "guide"}))
async def cb_guide_menu(cb: types.CallbackQuery):
    await cb.answer()
    await cb.message.answer(GUIDE_MENU_TEXT, reply_markup=_guide_menu_kb())


@router.callback_query(F.data.startswith("guide:"))
async def cb_guide_section(cb: types.CallbackQuery):
    part = cb.data.replace("guide:", "").strip()
    if not part or part == "menu":
        await cb.answer()
        await cb.message.answer(GUIDE_MENU_TEXT, reply_markup=_guide_menu_kb())
        return
    if part not in SECTIONS_ORDER:
        await cb.answer()
        return
    await cb.answer()
    text = await _get_section_text(part)
    await cb.message.answer(text, reply_markup=_section_nav_kb(part))
