"""NeuroBox configuration."""
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from shared.config.runtime_urls import (
    DEFAULT_REDIS_PASSWORD,
    build_async_database_url,
    build_redis_url,
)

BOT_VERSION = "4.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    bot_username: str = ""
    admin_ids: str = ""
    backend_url: str = "http://backend:8092"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "neurobox"
    postgres_user: str = "neurobox"
    postgres_password: str = "password"
    database_url: str = ""
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str = DEFAULT_REDIS_PASSWORD
    redis_url: str = ""
    openai_api_key: str = ""
    falai_api_key: str = ""
    suno_api_key: str = ""
    fal_song_endpoint: str = "fal-ai/diffrhythm"
    fal_song_timeout_sec: int = 420
    anthropic_api_key: str = ""
    google_ai_api_key: str = ""
    deepseek_api_key: str = ""
    grok_api_key: str = ""
    midjourney_api_key: str = ""
    openrouter_api_key: str = ""
    serper_api_key: str = ""
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    yookassa_receipt_email: str = ""

    @field_validator("yookassa_shop_id", "yookassa_secret_key", "bot_username", mode="before")
    @classmethod
    def strip_str(cls, value):
        return (value or "").strip() if value is not None else ""

    @model_validator(mode="after")
    def apply_runtime_urls(self):
        if not (self.database_url or "").strip():
            self.database_url = build_async_database_url(
                host=self.postgres_host,
                port=self.postgres_port,
                database=self.postgres_db,
                user=self.postgres_user,
                password=self.postgres_password,
            )
        if not (self.redis_url or "").strip():
            self.redis_url = build_redis_url(
                host=self.redis_host,
                port=self.redis_port,
                password=self.redis_password,
                db=0,
            )
        return self

    cryptobot_api_token: str = ""
    payment_notify_bot_token: str = ""
    payment_notify_chat_id: str = "72916668"
    free_daily_credits: int = 10
    log_level: str = "INFO"
    sentry_dsn: str = ""
    chat_history_limit: int = 20
    response_max_chars: int = 4000
    code_timeout_sec: float = 10.0
    code_credits: int = 2
    daily_login_bonus_credits: int = 5
    prompt_max_chars: int = 10000
    admin_panel_url: str = ""
    legal_base_url: str = ""
    use_video_queue: bool = False
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
    enable_tts: bool = False
    enable_video: bool = False
    enable_music: bool = False
    enable_full_access_48h: bool = False
    enable_test_payments: bool = False
    enable_stars_payment: bool = True
    enable_yookassa_payment: bool = False
    enable_cryptobot_payment: bool = False
    payment_reconcile_interval_sec: int = 600
    payment_reconcile_batch_size: int = 25
    infra_monthly_cost_usd: float = 25.0
    usd_to_rub: float = 95.0
    openrouter_cost_guard_enabled: bool = True
    openrouter_smart_max_tokens_cap: int = 2200
    openrouter_power_max_tokens_cap: int = 1600
    openrouter_elite_max_tokens_cap: int = 1200
    heavy_video_cooldown_sec: int = 45
    heavy_music_cooldown_sec: int = 30
    heavy_upscale_cooldown_sec: int = 15
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
