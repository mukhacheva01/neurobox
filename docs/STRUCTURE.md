# Структура проекта NeuroBox

## Дерево каталогов

```
neurobox/
├── .env                         # секреты (не в репо)
├── .env.example                 # шаблон переменных
├── .dockerignore
├── alembic.ini                  # конфиг Alembic
├── requirements.txt             # полный список зависимостей
├── requirements-bot.txt         # subset для bot-контейнера
├── requirements-backend.txt     # subset для backend-контейнера
├── requirements-worker.txt      # subset для worker-контейнера
├── requirements-admin.txt       # subset для admin-контейнера
│
├── alembic/
│   ├── env.py                   # подключение к shared.db.models.Base
│   └── versions/
│       └── 278eb10ce51b_initial_schema.py   # единственная миграция, создаёт все 13 таблиц
│
├── docker/
│   ├── base.Dockerfile          # python:3.12-slim + ffmpeg + fonts
│   ├── bot.Dockerfile
│   ├── backend.Dockerfile
│   ├── worker.Dockerfile
│   ├── admin.Dockerfile
│   └── entrypoints/
│       ├── bot.sh               # python -m services.bot.main
│       ├── backend.sh           # alembic upgrade head && uvicorn
│       ├── worker.sh            # python -m services.worker.main
│       └── admin.sh             # flask run
│
├── shared/                      # общий код для всех сервисов
│   ├── config/
│   │   ├── settings.py          # Settings(BaseSettings) — все env-переменные
│   │   └── text_models.py       # реестр текстовых моделей (имена, тиры, цены)
│   ├── db/
│   │   ├── session.py           # create_async_engine, get_session() asynccontextmanager
│   │   ├── database.py          # asyncpg pool (используется только в services/bot/*)
│   │   ├── models/
│   │   │   ├── base.py          # Base = DeclarativeBase()
│   │   │   ├── user.py          # User
│   │   │   ├── payment.py       # Payment, CreditTransaction
│   │   │   ├── ai_request.py    # AIRequest (телеметрия запросов)
│   │   │   ├── worker_task.py   # Promocode, PromoUse, BillingPlan, DailyStats, UserNote
│   │   │   └── event.py         # Event, AdminAuditLog, ErrorLog, ResponseRating
│   │   └── repositories/
│   │       ├── base.py          # BaseRepository[T]: get/get_by/list/create/update/delete
│   │       ├── user.py          # UserRepository
│   │       ├── payment.py       # PaymentRepository
│   │       ├── ai_request.py    # AIRequestRepository
│   │       ├── credit_transaction.py
│   │       └── event.py
│   ├── domain/
│   │   ├── credits.py           # вся логика кредитов, тарифов, paywall (~700 строк)
│   │   ├── yookassa.py          # платёж YooKassa: создание, подтверждение, reconcile
│   │   ├── cryptobot.py         # CryptoBot платежи
│   │   ├── telemetry.py         # запись ai_requests, логирование ошибок
│   │   ├── analytics.py         # аналитические хелперы
│   │   ├── admin_log.py         # запись admin_audit_log
│   │   ├── admin_runtime.py     # runtime-настройки бота (тексты, промпты)
│   │   ├── payment_notify.py    # уведомление в admin-чат об оплатах
│   │   └── video.py             # видео-генерация через FAL/Veo
│   ├── providers/
│   │   ├── openai_text.py       # OpenRouter + OpenAI текстовые модели
│   │   ├── openai_stt.py        # Whisper STT
│   │   ├── openrouter_image.py  # изображения через OpenRouter
│   │   ├── falai_image.py       # FAL FLUX/Wan images
│   │   ├── falai_video.py       # FAL видео
│   │   ├── falai_photo.py       # FAL фото-инструменты (upscale, …)
│   │   ├── falai_song.py        # FAL музыка (DiffRhythm)
│   │   ├── google_image.py      # Google Imagen
│   │   ├── google_veo.py        # Google Veo видео
│   │   ├── xai_image.py         # xAI Aurora изображения
│   │   ├── midjourney_image.py  # Midjourney через MidAPI
│   │   ├── edge_tts_provider.py # Microsoft Edge TTS
│   │   ├── musicgen.py          # MusicGen
│   │   └── music_router.py      # роутер музыкальных провайдеров
│   ├── redis/
│   │   └── store.py             # get_redis(), история чата, rate-limit, кэш
│   ├── queue/
│   │   ├── client.py            # enqueue(redis, task_type, payload)
│   │   └── tasks.py             # BaseTask TypedDict
│   └── logging.py               # setup_logging(): structlog + Sentry init
│
├── services/
│   ├── bot/                     # Telegram-бот (aiogram 3)
│   │   ├── main.py              # точка входа: Bot, Dispatcher, middlewares, polling
│   │   ├── backend_client.py    # httpx-клиент к backend (частично используется)
│   │   ├── i18n.py              # локализация (ru)
│   │   ├── bot_description.py   # описание бота для BotFather
│   │   ├── handlers/            # хендлеры команд и callback-кнопок
│   │   │   ├── start.py         # /start, онбординг, меню (~1000 строк)
│   │   │   ├── text.py          # обработка текстового ввода, AI-чат
│   │   │   ├── balance.py       # /balance, тарифы, оплата
│   │   │   ├── image.py         # /img, /img4
│   │   │   ├── video.py         # /video
│   │   │   ├── voice.py         # голосовые сообщения
│   │   │   ├── music.py         # /music
│   │   │   ├── transcribe.py    # /transcribe
│   │   │   ├── docgen.py        # /doc, /gendoc
│   │   │   ├── audiogen.py      # аудио-генерация
│   │   │   ├── guide.py         # /help, /guide
│   │   │   ├── modes.py         # режимы AI-ассистента
│   │   │   ├── model_select.py  # /model
│   │   │   ├── photo_tools.py   # upscale, edit фото
│   │   │   ├── tools.py         # /code, /summary, /search
│   │   │   ├── ref_promo_stats.py # рефералы и промокоды
│   │   │   └── admin/           # admin-команды (broadcast, stats, moderation …)
│   │   ├── keyboards/           # inline и reply клавиатуры
│   │   ├── middlewares/
│   │   │   ├── ban_check.py     # блокировка заблокированных пользователей
│   │   │   ├── rate_limit.py    # rate limiting через Redis
│   │   │   └── log_context.py   # structlog context vars
│   │   ├── services/
│   │   │   ├── chat_service.py  # история чата, напоминания
│   │   │   ├── board_service.py # доска сохранённых промптов
│   │   │   ├── mode_service.py  # режимы и системные промпты
│   │   │   └── doc_extract.py   # извлечение текста из файлов
│   │   ├── states/              # FSM-состояния (aiogram FSM)
│   │   ├── utils/
│   │   │   └── paywall.py       # проверка доступа к платным функциям
│   │   └── config/
│   │       ├── text_models.py   # переопределение реестра моделей
│   │       └── model_registry_guard.py # assert соответствия реестра
│   │
│   ├── backend/                 # FastAPI API-сервер
│   │   ├── main.py              # FastAPI app, CORS, lifespan (close_engine)
│   │   ├── deps.py              # issue_admin_token, require_api_key, require_role
│   │   ├── routers/
│   │   │   ├── admin.py         # все /api/v1/admin/* endpoints (~500 строк)
│   │   │   └── webhooks.py      # POST /webhooks/yookassa, POST /webhooks/cryptobot
│   │   ├── services/
│   │   │   └── admin.py         # бизнес-логика для admin endpoints (SQLAlchemy, ~900 строк)
│   │   └── schemas/
│   │       └── admin.py         # Pydantic схемы запросов/ответов
│   │
│   ├── worker/                  # фоновый воркер
│   │   ├── main.py              # while True: BLPOP → dispatch → retry/DLQ
│   │   ├── telegram.py          # get_bot() singleton, close_bot()
│   │   └── jobs/
│   │       ├── notify.py        # тип задачи: отправить сообщение пользователю
│   │       ├── video_generate.py # тип задачи: генерация видео
│   │       ├── daily_stats.py   # агрегация дневной статистики в daily_stats
│   │       └── alerts.py        # проверка KPI-порогов, уведомления в Telegram
│   │
│   └── admin/                   # Flask веб-интерфейс администратора
│       ├── app.py               # Flask app, session, Sentry
│       ├── routes.py            # все маршруты Flask (~1200 строк)
│       ├── backend_client.py    # httpx к backend API
│       ├── access.py            # проверка логина/пароля, TOTP
│       ├── audit.py             # запись аудит-лога через backend
│       └── templates/           # Jinja2 HTML шаблоны
│
├── tests/
│   ├── conftest.py              # sys.path, .env загрузка, BOT_TOKEN stub
│   ├── shared/                  # тесты shared/*
│   ├── backend/                 # тесты services/backend/*
│   ├── worker/                  # тесты services/worker/*
│   ├── bot/                     # тесты services/bot/*
│   ├── admin/                   # тесты services/admin/*
│   └── test_*.py                # smoke, contract, cross-cutting тесты
│
├── scripts/
│   ├── healthcheck.py           # проверка что процесс жив (для Docker healthcheck)
│   ├── smoke_user_flow.py       # smoke-тест пользовательского сценария
│   ├── check_apis.py            # проверка доступности AI API
│   └── daily_report.py          # генерация дневного отчёта
│
└── docs/
    ├── ARCHITECTURE.md          # этот файл + общая архитектура
    ├── STRUCTURE.md             # структура каталогов (этот файл)
    ├── SERVICES.md              # детали каждого сервиса
    ├── DATABASE.md              # схема БД, модели, миграции
    ├── TESTING.md               # как запускать тесты, структура, паттерны
    ├── REFACTORING_PLAN.md      # история рефакторинга
    └── old/                     # устаревшие документы
```

## Принципы организации

- `shared/` — единственный источник общего кода. Сервисы импортируют только отсюда.
- Каждый сервис — отдельный Docker-образ со своим `requirements-{service}.txt`.
- Алembic — единственный способ изменить схему БД. Raw `.sql`-файлов нет.
- Нет git. Деплой: rsync → `docker compose up -d --build`.
