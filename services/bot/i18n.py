"""НейроБокс — Мультиязычность (RU / EN). Функция t(key, lang) для переводов."""

TEXTS = {
    "ru": {
        # Start / Menu
        "welcome": "🤖 <b>НейроБокс</b> — AI-бот для текста, картинок, документов и транскрибации\n\n✍️ Тексты · 🎨 Картинки · 📄 Документы · 🎙 Транскрибация\n\n💰 Баланс: <b>{credits}</b> кредитов",
        "welcome_trial": "🤖 <b>НейроБокс</b> — AI-бот для текста, картинок, документов и транскрибации\n\n✍️ Тексты · 🎨 Картинки · 📄 Документы · 🎙 Транскрибация\n\n⏱ <b>Безлимит: осталось {expires}</b>\n💰 Баланс: <b>{credits}</b> кредитов",
        "onboarding": "👋 Добро пожаловать в <b>НейроБокс</b>!\n\nБыстрый AI-бот для текста, картинок, документов и транскрибации.\n\nЧто умею:\n✍️ Тексты — посты, рерайт, переводы, идеи, код\n🎨 Картинки — арт, логотипы, иллюстрации\n📄 Документы — анализ PDF, фото и файлов\n🎙 Транскрибация — голосовые, аудио и кружки в текст\n\n🎁 Тебе начислено <b>{free} бесплатных кредитов</b>!\nЕщё {free} CR каждый день.\n\nНапиши вопрос, пришли фото или отправь голосовое — и я отвечу!",
        "daily_bonus": "🎁 <b>Ежедневный бонус:</b> +{amount} CR!",
        "streak": "🔥 Серия входов: <b>{streak} дн. подряд</b>",
        "choose_lang": "🌍 Выбери язык / Choose language:",
        "lang_set": "✅ Язык: Русский",
        # Balance
        "balance_title": "💰 <b>Твой баланс</b>",
        "balance_free": "🆓 Бесплатные: <b>{free} CR</b> (обновятся в 00:00)",
        "balance_bought": "💎 Купленные: <b>{bought} CR</b> (бессрочные)",
        "balance_total": "📊 Всего: <b>{total} CR</b>",
        "balance_spent_today": "📉 Расход за сегодня: {amount} CR",
        "balance_spent_week": "📉 Расход за 7 дней: {amount} CR",
        "balance_free_daily": "🆓 Бесплатно каждый день: {amount} CR",
        # Credits
        "credits_low": "😔 Кредиты закончились.\n\n💡 <b>Пакет Старт:</b> 300 CR за 159 ₽.\nХватит на 60 картинок или 300 вопросов.",
        "credits_need_bought": "⚠️ Модель <b>{model}</b> стоит {cost} CR.\n\n💡 <b>Пакет Старт:</b> 300 CR за 159 ₽.",
        # Errors
        "error_generic": "Произошла ошибка. Попробуйте ещё раз или напишите /start.",
        "error_timeout": "⏱ Операция заняла слишком долго. Попробуй позже.",
        "error_refunded": "💚 Кредиты возвращены.",
        # Generation
        "generating_text": "⏳ Печатаю...",
        "generating_image": "🎨 Генерирую картинку ({model})...",
        "generating_video": "🎬 Генерирую видео... до 5 мин",
        "generating_music": "🎵 Генерирую музыку... (до 2 мин)",
        "generating_rmbg": "🖼 Удаляю фон...",
        # Buttons
        "btn_text": "💬 Текст",
        "btn_images": "🎨 Картинки",
        "btn_video": "🎬 Видео",
        "btn_voice": "🎤 Транскрибация",
        "btn_docs": "📄 Документы",
        "btn_tools": "🛠 Инструменты",
        "btn_mode": "🎭 Режим чата",
        "btn_ref": "🤝 Рефералы",
        "btn_profile": "👤 Профиль",
        "btn_balance": "💰 Баланс",
        "btn_buy": "💳 Пополнить",
        "btn_models": "⚙️ Модели",
        "btn_guide": "📖 Гайд",
        "btn_back": "◀️ Назад",
        "btn_menu": "◀️ Меню",
        "btn_again": "🔄 Ещё раз",
        "btn_cancel": "❌ Отмена",
        # Help
        "help_title": "📖 <b>Все команды бота</b>",
        # Cancel
        "cancelled": "❌ Отменено.",
        "stale_callback": "Сообщение устарело. Нажми /start",
    },
    "en": {
        # Start / Menu
        "welcome": "🤖 <b>NeuroBox</b> — AI bot for text, images, documents and transcription\n\n✍️ Text · 🎨 Images · 📄 Docs · 🎙 Transcription\n\n💰 Balance: <b>{credits}</b> credits",
        "welcome_trial": "🤖 <b>NeuroBox</b> — AI bot for text, images, documents and transcription\n\n✍️ Text · 🎨 Images · 📄 Docs · 🎙 Transcription\n\n⏱ <b>Unlimited: {expires} left</b>\n💰 Balance: <b>{credits}</b> credits",
        "onboarding": "👋 Welcome to <b>NeuroBox</b>!\n\nFast AI bot for text, images, documents and transcription.\n\nWhat I can do:\n✍️ Text — posts, rewrites, translations, ideas, code\n🎨 Images — art, logos, illustrations\n📄 Documents — analyze PDFs, photos and files\n🎙 Transcription — voice notes, audio and video notes to text\n\n🎁 You got <b>{free} free credits</b>!\n{free} more every day.\n\nSend a prompt, a photo or a voice note — I'll respond!",
        "daily_bonus": "🎁 <b>Daily bonus:</b> +{amount} CR!",
        "streak": "🔥 Login streak: <b>{streak} days</b>",
        "choose_lang": "🌍 Выбери язык / Choose language:",
        "lang_set": "✅ Language: English",
        # Balance
        "balance_title": "💰 <b>Your balance</b>",
        "balance_free": "🆓 Free: <b>{free} CR</b> (resets at 00:00)",
        "balance_bought": "💎 Purchased: <b>{bought} CR</b> (permanent)",
        "balance_total": "📊 Total: <b>{total} CR</b>",
        "balance_spent_today": "📉 Spent today: {amount} CR",
        "balance_spent_week": "📉 Spent this week: {amount} CR",
        "balance_free_daily": "🆓 Free daily: {amount} CR",
        # Credits
        "credits_low": "😔 Out of credits.\n\n💡 <b>Start pack:</b> 300 CR for 159 ₽.\nEnough for 60 images or 300 chats.",
        "credits_need_bought": "⚠️ Model <b>{model}</b> costs {cost} CR.\n\n💡 <b>Start pack:</b> 300 CR for 159 ₽.",
        # Errors
        "error_generic": "An error occurred. Try again or press /start.",
        "error_timeout": "⏱ Operation timed out. Try again later.",
        "error_refunded": "💚 Credits refunded.",
        # Generation
        "generating_text": "⏳ Typing...",
        "generating_image": "🎨 Generating image ({model})...",
        "generating_video": "🎬 Generating video... up to 5 min",
        "generating_music": "🎵 Generating music... (up to 2 min)",
        "generating_rmbg": "🖼 Removing background...",
        # Buttons
        "btn_text": "💬 Text",
        "btn_images": "🎨 Images",
        "btn_video": "🎬 Video",
        "btn_voice": "🎤 Transcription",
        "btn_docs": "📄 Documents",
        "btn_tools": "🛠 Tools",
        "btn_mode": "🎭 Chat mode",
        "btn_ref": "🤝 Referrals",
        "btn_profile": "👤 Profile",
        "btn_balance": "💰 Balance",
        "btn_buy": "💳 Top up",
        "btn_models": "⚙️ Models",
        "btn_guide": "📖 Guide",
        "btn_back": "◀️ Back",
        "btn_menu": "◀️ Menu",
        "btn_again": "🔄 Again",
        "btn_cancel": "❌ Cancel",
        # Help
        "help_title": "📖 <b>All commands</b>",
        # Cancel
        "cancelled": "❌ Cancelled.",
        "stale_callback": "Message expired. Press /start",
    },
}


def t(key: str, lang: str = "ru", **kwargs) -> str:
    """Получить перевод по ключу. Fallback: ru -> key."""
    texts = TEXTS.get(lang, TEXTS["ru"])
    text = texts.get(key)
    if text is None:
        text = TEXTS["ru"].get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


async def get_user_lang(user_id: int) -> str:
    """Получить язык пользователя из Redis-кеша или БД."""
    # Кеш в Redis
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if r:
            cached = await r.get(f"lang:{user_id}")
            if cached:
                return cached.decode()
    except Exception:
        pass
    # БД
    try:
        from shared.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            lang = await conn.fetchval("SELECT language_code FROM users WHERE id = $1", user_id)
            if lang:
                # Кешируем
                try:
                    from shared.redis.store import _get_redis
                    r = await _get_redis()
                    if r:
                        await r.set(f"lang:{user_id}", lang, ex=300)
                except Exception:
                    pass
                return lang
    except Exception:
        pass
    return "ru"


async def set_user_lang(user_id: int, lang: str) -> None:
    """Установить язык пользователя."""
    try:
        from shared.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE users SET language_code = $1 WHERE id = $2", lang, user_id)
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if r:
            await r.set(f"lang:{user_id}", lang, ex=300)
    except Exception:
        pass
