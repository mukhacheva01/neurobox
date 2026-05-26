# Сервисы NeuroBox

## bot (`services/bot/`)

**Dockerfile**: `docker/bot.Dockerfile`  
**Entrypoint**: `docker/entrypoints/bot.sh` → `python -m services.bot.main`  
**Зависит от**: redis (FSM), postgres (через shared.db.database asyncpg pool)

### Запуск

```python
# services/bot/main.py
bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=RedisStorage(...))  # fallback: MemoryStorage
await dp.start_polling(bot, polling_timeout=30, allowed_updates=['message','callback_query','pre_checkout_query'])
```

### Middlewares (применяются в этом порядке)

1. `LogContextMiddleware` — устанавливает structlog context vars (user_id, username)
2. `BanCheckMiddleware` — читает `is_blocked` из БД, отклоняет заблокированных
3. `RateLimitMiddleware` — Redis-based rate limit на сообщения

### Обработчики (handlers/)

| Файл | Команды / триггеры |
|---|---|
| `start.py` | `/start`, онбординг, главное меню |
| `text.py` | обычный текст → AI-чат |
| `balance.py` | `/balance`, тарифы, оплата Stars/YooKassa |
| `image.py` | `/img`, `/img4` |
| `video.py` | `/video`, `/setvideo` |
| `voice.py` | голосовые сообщения |
| `music.py` | `/music` |
| `transcribe.py` | `/transcribe` + аудио-файлы |
| `docgen.py` | `/doc`, `/gendoc` |
| `audiogen.py` | аудио-генерация |
| `guide.py` | `/help`, `/guide` |
| `tools.py` | `/code`, `/summary`, `/search` |
| `modes.py` | AI-режимы (ассистент, коуч, …) |
| `model_select.py` | `/model`, `/setimg`, `/settts`, `/setvideo` |
| `ref_promo_stats.py` | `/ref`, промокоды |
| `photo_tools.py` | upscale, редактирование фото |
| `saved_export.py` | `/save`, `/favorites`, `/export` |
| `admin/` | admin-команды (только для ADMIN_IDS) |

### Фоновые задачи в боте

Три `asyncio.Task` запускаются при старте и живут до shutdown:

- **reminder_loop** (каждые 30s): проверяет запланированные напоминания, отправляет
- **balance_reminder_loop** (каждые 24h): пользователям с низким балансом — сообщение
- **payment_reconcile_loop** (каждые `PAYMENT_RECONCILE_INTERVAL_SEC`=600s): проверяет незавершённые YooKassa-платежи

### Логика кредитов

`shared/domain/credits.py` — центральный модуль (~700 строк):
- `spend_credits(user_id, amount, task_type, model)` — списание
- `check_paywall(user_id, task_type)` → bool — проверка доступа
- `add_credits(user_id, amount, type)` — пополнение
- `sync_billing_plans_defaults()` — синхронизация billing_plans в БД

Кредитная система:
- `credits_bought` — купленные, тратятся первыми
- `credits_free_today` — бесплатные, сбрасываются ежедневно (FREE_DAILY_CREDITS=10)
- `unlimited_ends_at` — безлимитный доступ до даты
- `trial_started_at` — trial (ограниченный бесплатный доступ)

---

## backend (`services/backend/`)

**Dockerfile**: `docker/backend.Dockerfile`  
**Entrypoint**: `docker/entrypoints/backend.sh` → `alembic upgrade head && uvicorn services.backend.main:app --host 0.0.0.0 --port 8092`  
**Зависит от**: postgres, redis

### API endpoints

Базовый путь: `/api/v1/admin/`

#### Аутентификация
- `POST /api/v1/admin/login` — логин (login+password из env), возвращает HMAC-токен
- Все остальные endpoint'ы требуют `Authorization: Bearer <token>`

#### Пользователи
- `GET /users` — список с фильтрами и пагинацией
- `GET /users/{user_id}` — детальная карточка
- `POST /users/{user_id}/block` / `/unblock`
- `POST /users/{user_id}/set-unlimited`
- `POST /users/{user_id}/deduct-credits`
- `POST /users/{user_id}/notes` — добавить заметку
- `POST /users/{user_id}/send-message` — отправить сообщение через worker

#### Статистика и аналитика
- `GET /stats` — дашборд (DAU, revenue, ai_requests, сегменты, retention)
- `GET /chart` — временной ряд (day/week/month/year)
- `GET /models-stats` — статистика по AI-моделям
- `GET /trends` — тренды за 14 дней
- `GET /retention` — retention-матрица по неделям
- `GET /hourly-msk` — активность по часам МСК

#### Прочее
- `GET /payments` — список платежей
- `GET /promos` — промокоды
- `POST /promos` — создать промокод
- `GET /referrals-top` — топ рефереров
- `GET /errors` — лог ошибок
- `GET /errors-top` — топ ошибок
- `POST /audit-log` — записать аудит-событие
- `GET /users/export-csv` — экспорт пользователей в CSV

#### Webhooks
- `POST /webhooks/yookassa` — webhook от YooKassa (IP-фильтр + idempotency)
- `POST /webhooks/cryptobot` — webhook от CryptoBot

#### Health
- `GET /health` → `{"ok": true}`

### Авторизация

`services/backend/deps.py`:
- `require_api_key` — проверяет Bearer токен (HMAC-SHA256)
- `require_role("editor", "superadmin")` — проверяет роль в payload токена
- Брутфорс-защита: 5 попыток за 15 минут с одного IP на `/login`

---

## worker (`services/worker/`)

**Dockerfile**: `docker/worker.Dockerfile`  
**Entrypoint**: `docker/entrypoints/worker.sh` → `python -m services.worker.main`  
**Зависит от**: postgres, redis

### Цикл обработки

```
while True:
    item = await redis.blpop("neurobox:tasks", timeout=5)
    if item:
        task = json.loads(raw)
        await process_task(task)          # dispatch по task["type"]
        # при ошибке: retry += 1
        # при retry > 3: RPUSH "neurobox:tasks:dlq"
    
    counter += 1
    if counter >= 720:   # ~1 час при 5s timeout
        counter = 0
        await process_task({"type": "daily_stats"})
        await process_task({"type": "metrics_alert"})
```

### Типы задач

| `type` | Файл | Что делает |
|---|---|---|
| `notify` | `jobs/notify.py` | отправить сообщение пользователю через Telegram Bot API |
| `video_generate` | `jobs/video_generate.py` | генерация видео через FAL/Veo, отправка результата |
| `daily_stats` | `jobs/daily_stats.py` | агрегация метрик → INSERT/UPSERT в daily_stats |
| `metrics_alert` | `jobs/alerts.py` | проверка KPI порогов, уведомление в admin-чат |

### Singleton Bot

```python
# services/worker/telegram.py
_bot: Bot | None = None

def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=settings.bot_token, default=DefaultBotProperties(...))
    return _bot

async def close_bot():
    if _bot:
        await _bot.session.close()
        _bot = None
```

Использует тот же `BOT_TOKEN` что и bot-сервис. Только исходящие методы.

### daily_stats метрики (записываются каждый час)

`new_users`, `revenue_rub`, `ai_requests`, `funnel_start_users`, `funnel_first_gen_users`, `funnel_paywall_users`, `funnel_purchase_users`, `funnel_repeat_users`, `funnel_cr_start_to_gen`, `funnel_cr_gen_to_paywall`, `funnel_cr_paywall_to_purchase`, `funnel_cr_repeat`

---

## admin (`services/admin/`)

**Dockerfile**: `docker/admin.Dockerfile`  
**Entrypoint**: `docker/entrypoints/admin.sh` → `flask run --host 0.0.0.0 --port 8091`  
**Зависит от**: backend (через HTTP)

Flask UI для администраторов. Все данные получает из backend API через httpx (`services/admin/backend_client.py`).

### Разделы интерфейса

- Дашборд (DAU, revenue, воронка, retention)
- Пользователи (список, карточка, блокировка, кредиты, заметки)
- Платежи
- Статистика моделей
- Промокоды
- Рефералы
- Ошибки
- CSV-экспорт

### Аутентификация Flask

- Логин/пароль из `ADMIN_PANEL_USER` / `ADMIN_PANEL_PASSWORD`
- TOTP (если настроен)
- Flask-сессия подписана `ADMIN_PANEL_SECRET`

---

## Конфигурация (`shared/config/settings.py`)

Все переменные из `.env` через `pydantic-settings`. Объект `settings` импортируется как синглтон:

```python
from shared.config import settings
settings.bot_token          # str
settings.database_url       # str
settings.enable_video       # bool
settings.admin_id_list      # list[int] (property)
```

Ключевые группы переменных:

| Группа | Примеры |
|---|---|
| Telegram | `BOT_TOKEN`, `BOT_USERNAME`, `ADMIN_IDS` |
| БД | `DATABASE_URL` |
| Redis | `REDIS_URL` |
| AI провайдеры | `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `FALAI_API_KEY`, … |
| Платежи | `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`, `CRYPTOBOT_API_TOKEN` |
| Feature flags | `ENABLE_VIDEO`, `ENABLE_MUSIC`, `ENABLE_TTS`, … |
| Admin API | `ADMIN_API_SECRET_KEY`, `ADMIN_LOGIN`, `ADMIN_PASSWORD` |
| Лимиты | `FREE_DAILY_CREDITS`, `CHAT_HISTORY_LIMIT`, `TRIAL_VIDEO_DAILY_LIMIT`, … |
| KPI алерты | `METRICS_402_ALERT_THRESHOLD_24H`, `METRICS_FUNNEL_CR_DROP_RATIO`, … |
