# Архитектура NeuroBox

## Обзор

NeuroBox — Telegram-бот с AI-функциями (текст, изображения, видео, музыка, TTS, документы). Развёрнут как 6 Docker-контейнеров, управляется через `docker compose`.

## Сервисы

```
┌─────────────────────────────────────────────────────────────┐
│                        nb_net (bridge)                      │
│                                                             │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │   bot    │───▶│   backend    │◀───│     admin        │  │
│  │ polling  │    │   :8092      │    │    :8091         │  │
│  └────┬─────┘    └──────┬───────┘    └──────────────────┘  │
│       │                 │                                   │
│       │         ┌───────▼───────┐                          │
│       │         │   postgres    │                          │
│       │         │   :5432       │                          │
│       │         └───────────────┘                          │
│       │                                                     │
│  ┌────▼─────┐    ┌──────────────┐                          │
│  │  redis   │◀───│    worker    │                          │
│  │  :6379   │    │              │                          │
│  └──────────┘    └──────────────┘                          │
└─────────────────────────────────────────────────────────────┘
```

| Сервис | Dockerfile | Порт | Назначение |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | 5432 (internal) | База данных |
| `redis` | `redis:7-alpine` | 6379 (internal) | FSM-хранилище бота + очередь задач worker'а |
| `bot` | `docker/bot.Dockerfile` | — (internal, polling) | aiogram 3, Telegram Long Polling |
| `backend` | `docker/backend.Dockerfile` | 127.0.0.1:8092 | FastAPI: Admin REST API + YooKassa webhook |
| `worker` | `docker/worker.Dockerfile` | — (internal) | Фоновые задачи из Redis-очереди |
| `admin` | `docker/admin.Dockerfile` | 127.0.0.1:8091 | Flask UI для администраторов |

## Граф зависимостей кода

```
shared/              ← импортируется всеми сервисами
├── config/          ← Settings (pydantic-settings, .env)
├── db/              ← SQLAlchemy 2, модели, репозитории, сессия
├── domain/          ← бизнес-логика (credits, yookassa, telemetry …)
├── providers/       ← внешние AI API (OpenRouter, FAL, OpenAI …)
├── redis/           ← Redis store (кэш, rate-limit, история чата)
├── queue/           ← контракт задач очереди
└── logging.py       ← structlog + Sentry

services/bot/        → импортирует shared/*
services/backend/    → импортирует shared/*
services/worker/     → импортирует shared/*
services/admin/      → импортирует shared/*

ЗАПРЕЩЕНО: services/X/* ↔ services/Y/* (кросс-импорты между сервисами)
```

## Потоки данных

### Пользователь → бот → ответ
```
Telegram → bot (aiogram polling)
         → middlewares: BanCheck → RateLimit → LogContext
         → handler → shared.domain.credits (списание кредитов)
         → shared.providers.* (AI API вызов)
         → bot → Telegram (ответ пользователю)
```

### Платёж YooKassa
```
YooKassa webhook → backend POST /webhooks/yookassa
                 → IP-фильтр (185.71.76.0/27 и др.)
                 → idempotency-check (payments.idempotency_key)
                 → shared.domain.yookassa (зачисление кредитов)
                 → DB update: payments + users.credits_bought
```

### Worker задача
```
bot → redis RPUSH "neurobox:tasks" (JSON)
    → worker BLPOP (timeout=5s)
    → dispatch: notify | video_generate | daily_stats | metrics_alert
    → shared.db.session.get_session() + Telegram Bot API (output-only)
    → при ошибке: retry ×3, затем RPUSH "neurobox:tasks:dlq"
```

### Периодические задачи worker'а
```
Каждые ~720 итераций (≈1 час):
  → daily_stats.handle(): агрегация метрик → INSERT daily_stats (key-value)
  → alerts.handle(): проверка KPI порогов → уведомление в Telegram
```

### Администратор → Flask UI → backend
```
admin (Flask routes.py) → backend HTTP API (httpx)
                        → Authorization: Bearer {HMAC-token}
                        → services/backend/services/admin.py (SQLAlchemy)
                        → PostgreSQL
```

## Аутентификация Backend API

Custom HMAC токен (не JWT):
- Выдаётся через `POST /api/v1/admin/login`
- Подписан `ADMIN_API_SECRET_KEY` (HMAC-SHA256), формат: `{base64url(payload)}.{base64url(sig)}`
- TTL: `ADMIN_API_TOKEN_TTL_SEC` (по умолч. 3600s)
- Роли: `viewer` (чтение), `editor` (запись), `superadmin`
- Передаётся как `Authorization: Bearer <token>`
- Rate-limit на login: 5 попыток за 15 минут с одного IP

## Feature flags

Все включены через `.env` / `Settings`:

| Флаг | По умолч. | Что включает |
|---|---|---|
| `ENABLE_VIDEO` | false | handler /video, видео-модели |
| `ENABLE_MUSIC` | false | handler /music |
| `ENABLE_TTS` | false | handler /voice, /tts |
| `ENABLE_STARS_PAYMENT` | true | Telegram Stars |
| `ENABLE_YOOKASSA_PAYMENT` | false | YooKassa рублёвые платежи |
| `ENABLE_CRYPTOBOT_PAYMENT` | false | крипто через CryptoBot |
| `ENABLE_FULL_ACCESS_48H` | false | промо-доступ на 48ч |

## Внешние зависимости

| Сервис | Переменная | Назначение |
|---|---|---|
| Telegram Bot API | `BOT_TOKEN` | aiogram polling + worker output |
| OpenRouter | `OPENROUTER_API_KEY` | текстовые LLM (Claude, GPT, Gemini …) |
| OpenAI | `OPENAI_API_KEY` | STT Whisper, DALL-E |
| FAL.ai | `FALAI_API_KEY` | видео (Wan), изображения, музыка |
| Google AI | `GOOGLE_AI_API_KEY` | Gemini, Veo-видео |
| Anthropic | `ANTHROPIC_API_KEY` | Claude напрямую |
| xAI | `GROK_API_KEY` | Grok/Aurora |
| YooKassa | `YOOKASSA_SHOP_ID` + `YOOKASSA_SECRET_KEY` | RUB-платежи |
| CryptoBot | `CRYPTOBOT_API_TOKEN` | крипто-платежи |
| Serper | `SERPER_API_KEY` | веб-поиск (`/search`) |
| Sentry | `SENTRY_DSN` | error tracking |

## Ключевые архитектурные решения (не пересматриваются)

- **Worker → Telegram**: `Bot(token=BOT_TOKEN)` singleton в процессе worker, только исходящие методы (`send_message`, `send_photo` …). Запрещено: `set_webhook`, `get_updates`, `Dispatcher`.
- **Alembic в entrypoint**: `alembic upgrade head` запускается в `docker/entrypoints/backend.sh` перед uvicorn.
- **FSM**: RedisStorage, fallback → MemoryStorage если Redis недоступен.
- **No git / no CI**: проект ведётся без VCS, деплой вручную через rsync.
- **Секреты**: только `.env` на сервере, у архитектора. В коде секретов нет.
