"""НейроБокс — Configuration."""
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BOT_VERSION = "4.0"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    bot_token: str
    bot_username: str = ""
    admin_ids: str = ""
    database_url: str = "postgresql+asyncpg://neurobox:password@postgres:5432/neurobox"
    redis_url: str = "redis://:password@redis:6379/0"
    openai_api_key: str = ""
    falai_api_key: str = ""
    suno_api_key: str = ""
    fal_song_endpoint: str = "fal-ai/diffrhythm"
    fal_song_timeout_sec: int = 420
    anthropic_api_key: str = ""
    google_ai_api_key: str = ""
    deepseek_api_key: str = ""
    grok_api_key: str = ""
    midjourney_api_key: str = ""  # MidAPI (midapi.ai) или аналог — Bearer для Midjourney API
    openrouter_api_key: str = ""  # OpenRouter — единый прокси для текстовых LLM
    serper_api_key: str = ""
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    yookassa_receipt_email: str = ""  # Email для чека 54-ФЗ (если обязателен в ЛК ЮKassa)

    @field_validator("yookassa_shop_id", "yookassa_secret_key", "bot_username", mode="before")
    @classmethod
    def strip_str(cls, v):
        return (v or "").strip() if v is not None else ""
    cryptobot_api_token: str = ""
    # Бот для уведомлений админу об оплатах (отдельный токен, чат — payment_notify_chat_id)
    payment_notify_bot_token: str = ""
    payment_notify_chat_id: str = "72916668"
    free_daily_credits: int = 10
    log_level: str = "INFO"
    sentry_dsn: str = ""
    # Лимиты (можно переопределить в .env)
    chat_history_limit: int = 20
    response_max_chars: int = 4000
    code_timeout_sec: float = 10.0
    code_credits: int = 2
    daily_login_bonus_credits: int = 5
    prompt_max_chars: int = 10000
    # URL веб-админки (порт 8091). Если задан — в боте появится кнопка «Админка (веб)»
    admin_panel_url: str = ""
    # Базовый URL для страниц «Политика конфиденциальности» и «Оферта» (например https://example.com/legal)
    legal_base_url: str = ""
    # Отправлять тяжёлую генерацию видео в очередь worker вместо выполнения в хендлере
    use_video_queue: bool = False
    # Admin API (FastAPI): ключ, логин, пароль, CORS, TG ID админов, идентификатор бота
    admin_api_secret_key: str = ""
    admin_login: str = "admin"
    admin_password: str = ""
    admin_api_token_ttl_sec: int = 3600
    admin_cors_origins: str = ""
    admin_tg_ids: str = ""
    qa_tester_ids: str = ""
    bot_identifier: str = "neurobox"
    balance_reminder_throttle_sec: int = 1
    balance_reminder_max_batch: int = 200

    # Launch flags: keep risky/promotional mechanics behind explicit toggles
    enable_tts: bool = False
    enable_video: bool = False
    enable_music: bool = False
    enable_full_access_48h: bool = False
    enable_test_payments: bool = False
    enable_stars_payment: bool = True  # Оплата через Telegram Stars
    enable_yookassa_payment: bool = False
    enable_cryptobot_payment: bool = False
    payment_reconcile_interval_sec: int = 600
    payment_reconcile_batch_size: int = 25
    infra_monthly_cost_usd: float = 25.0
    usd_to_rub: float = 95.0

    # OpenRouter cost-guard: динамическое ограничение max_tokens по ценовому tier
    openrouter_cost_guard_enabled: bool = True
    openrouter_smart_max_tokens_cap: int = 2200     # модели 10 CR
    openrouter_power_max_tokens_cap: int = 1600     # модели 15 CR
    openrouter_elite_max_tokens_cap: int = 1200     # модели 25 CR

    # Антиабьюз heavy-фич (глобальные cooldown для всех пользователей)
    heavy_video_cooldown_sec: int = 45
    heavy_music_cooldown_sec: int = 30
    heavy_upscale_cooldown_sec: int = 15

    # Дневные hard-лимиты для zero-cost режимов (trial / full48h / unlimited)
    trial_video_daily_limit: int = 2
    trial_music_daily_limit: int = 5
    trial_upscale_daily_limit: int = 20
    trial_elite_text_daily_limit: int = 60

    full48_video_daily_limit: int = 4
    full48_music_daily_limit: int = 10
    full48_upscale_daily_limit: int = 40
    full48_elite_text_daily_limit: int = 120

    unlimited_video_daily_limit: int = 6
    unlimited_music_daily_limit: int = 20
    unlimited_upscale_daily_limit: int = 80
    unlimited_elite_text_daily_limit: int = 250

    # Пороги алертов KPI/экономики
    metrics_402_alert_threshold_24h: int = 5
    metrics_cost_per_paid_user_alert_24h: float = 2500.0
    metrics_cost_per_paid_user_min_paid_users: int = 3
    metrics_funnel_cr_drop_min_paywall_24h: int = 20
    metrics_funnel_cr_drop_ratio: float = 0.6

    @property
    def admin_id_list(self) -> list[int]:
        if not self.admin_ids:
            return []
        return [int(x.strip()) for x in self.admin_ids.split(",") if x.strip()]

    @property
    def admin_tg_id_list(self) -> list[int]:
        if not self.admin_tg_ids:
            return self.admin_id_list
        return [int(x.strip()) for x in self.admin_tg_ids.split(",") if x.strip()]

    @property
    def qa_tester_id_list(self) -> list[int]:
        if not self.qa_tester_ids:
            return []
        return [int(x.strip()) for x in self.qa_tester_ids.split(",") if x.strip()]

settings = Settings()
