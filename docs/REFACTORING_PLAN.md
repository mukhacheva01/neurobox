# План рефакторинга НейроБокс

> Документ для архитектора и агента-исполнителя. Источник правды по составу сервисов, целевой структуре и фазам перехода. Обновляется по мере продвижения.

## Контекст и роли

- **Архитектор** — принимает решения, ревьюит, делает прод-операции по ssh. Код не пишет.
- **Архитектор-консультант** — план, архитектурные решения, конфиги-спецификации. Бизнес-код не пишет.
- **Агент-исполнитель** — отдельный чат. Без прод-доступа и секретов. Тестирует локально. Изучает структуру самостоятельно перед реализацией.
- Общение — на русском. Код, файлы, переменные — английский.
- **Git не используется.** Проект ведётся без системы контроля версий.

## Стек

aiogram 3, SQLAlchemy 2 (async) + asyncpg, FastAPI, Redis, YooKassa, Flask admin (временно). Прод: Ubuntu, Postgres в контейнере, `docker compose`.

## Цели рефакторинга

1. Разбить монолит на изолированные сервисы по функциям. Каждый сервис — отдельный контейнер, своя зона ответственности.
2. `docker compose up -d` — единственная точка входа в прод.
3. Структура каталогов соответствует составу сервисов + `shared/`, `docker/`, `alembic/`.
4. Деплой: rsync/scp на сервер → `docker compose up -d --build`. Ручной, без CI/CD автоматизации.
5. **ORM-first:** SQLAlchemy 2 async + Alembic с нуля. БД чистая — `alembic upgrade head` создаёт схему целиком. Сырого SQL в коде не остаётся. Репозиторный слой обязателен.
6. Тесты: довести покрытие до **75%** (pytest + pytest-cov).

## Принятые архитектурные решения (не обсуждаются заново)

- **Worker → Telegram:** `Bot(token=BOT_TOKEN)` singleton в процессе worker, тот же токен что у bot-сервиса. Это второй HTTP-клиент к Bot API, не второй бот в @BotFather. Worker **output-only**: только исходящие методы (`send_message`, `send_photo` и т.п.). Запрещено: `set_webhook`, `delete_webhook`, `get_updates`, `Dispatcher`, `start_polling`. В shutdown: `await bot.session.close()`. `DefaultBotProperties` идентичны bot-сервису. Одна переменная в `.env` — `BOT_TOKEN`, не заводить `WORKER_BOT_TOKEN`.
- **Bot → Backend:** httpx внутри docker network. Bot не ходит в БД напрямую.
- **Worker → БД:** напрямую через `shared/db` (без HTTP-хопа через backend).
- **ORM:** SQLAlchemy 2 async (sqlalchemy[asyncio] + asyncpg). Все данные — через модели и репозитории из `shared/db/`. Сырой SQL в хендлерах и сервисах не оставлять.
- **Alembic:** запускается в entrypoint backend-контейнера до старта uvicorn. Модели в `shared/db/models.py` — единственный источник схемы. `alembic revision --autogenerate` по ним, никаких ручных `.sql` файлов.
- **Observability:** единый structlog-конфиг в `shared/logging.py`, Sentry init — в entrypoint каждого сервиса. Настраивается в Фазе 1 вместе с переносом `shared/`.
- **Секреты:** только у архитектора. Исполнитель работает с `.env.example` + fake-значениями.

---

## §1. Текущее состояние

### Код

- **Монолит** с пакетами `bot/`, `worker/`, `api/`, `admin_panel/`, `config/`, `scripts/`, `tests/`, `migrations/`.
- **Один Dockerfile** + `scripts/entrypoint.sh` с переключателем `SERVICE_TYPE` на 5 ролей: `bot | worker | webhook | admin | api`.
- **Скрытая связность**: `worker.*`, `api.*`, `admin_panel.*` импортируют `from bot.db.*`, `from bot.services.*` (credits, telemetry, video_service, redis_store, admin_runtime). Это делает «bot» де-факто общей библиотекой, что ломает изоляцию сервисов.
- **Прямые SQL в хендлерах** (~100+ запросов в balance/start/text), репозиторного слоя нет.
- **Конфиг**: `config/settings.py` — Pydantic BaseSettings c ~80 параметрами, импортируется отовсюду (`from config import settings`).
- **Толстые файлы** (>400 строк): `admin_panel/routes.py` (1179), `bot/services/credits.py` (1113), `bot/handlers/start.py` (1034), `api/admin/service.py` (876), `bot/handlers/balance.py` (798), `bot/handlers/text.py` (794), `bot/providers/openai_text.py` (669), `worker/main.py` (639), `bot/handlers/voice.py` (551), `bot/handlers/transcribe.py` (506), `bot/handlers/video.py` (463), `bot/handlers/docgen.py` (435), `bot/services/yookassa_service.py` (432), `bot/handlers/guide.py` (428), `bot/handlers/audiogen.py` (391).
- **Дублирующая админка**: Flask `admin_panel/` (8091, UI) + FastAPI `api/admin/` (8092, REST). Обе ходят в те же таблицы.
- **Webhook YooKassa**: `scripts/webhook_server.py` (180 строк), отдельный HTTP-сервер на 8090.
- **Worker**: ручной `while True` + `BLPOP` на Redis, не использует ни APScheduler, ни `arq` (хотя `arq==0.27.0` в `requirements.txt` — мёртвая зависимость).
- **Тесты**: 11 файлов в `tests/`, в основном smoke и контрактные. Юнит-покрытие низкое.

### Инфра

- `docker-compose.yml`: 7 сервисов (postgres, redis, bot, worker, webhook, api, admin), все на одном образе через `build: .`.
- **Volume `.:/app`** на проде — код подкидывается с хоста, `docker compose restart` без пересборки. Это создаёт расхождение «образ ≠ что реально работает» и убивает идею иммутабельных артефактов.
- **Миграции**: голые `.sql` в `migrations/` (в репо папка пустая) + кастомный runner `bot/db/migrate.py` с таблицей `migrations_applied`. Alembic нет.
- **Деплой**: ручной `cd /opt/neurobox && docker compose up -d --build`.
- **Nginx** на хосте, `deploy/nginx-admin.conf` — единственный артефакт деплоя.

---

## §2. Предлагаемый состав сервисов

**Финальный состав — 6 контейнеров:**

| Сервис | Образ | Назначение | Сетевой выход |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | БД | внутри `nb_net` |
| `redis` | `redis:7-alpine` | очередь worker'а + кэш | внутри `nb_net` |
| `bot` | свой `docker/bot.Dockerfile` | aiogram 3, polling/webhook к Telegram. **БД не трогает**, ходит в `backend` через httpx | internal |
| `backend` | свой `docker/backend.Dockerfile` | FastAPI: REST API для бота, REST API для админки (была `api/admin/`), endpoint `/webhooks/yookassa` (была `scripts/webhook_server.py`). Запускает Alembic в entrypoint | `127.0.0.1:8092` |
| `worker` | свой `docker/worker.Dockerfile` | Фоновые задачи: video_generate, notify, daily_stats, alerts. **Прямой доступ к БД** через `shared/db`. Singleton `Bot(token=BOT_TOKEN)` — output-only к Telegram | internal |
| `admin` | свой `docker/admin.Dockerfile` | Flask UI (`admin_panel/`). Не трогает БД напрямую — все данные через `backend` HTTP API | `127.0.0.1:8091` |

### Обоснование 6, а не 5

Flask `admin_panel/routes.py` (1179 строк, 14 шаблонов) — переписать на FastAPI+Jinja за одну фазу нереалистично. Оставляем как отдельный сервис, но превращаем в тонкий UI-клиент к `backend`. Деприкация Flask — отдельная инициатива после стабилизации.

### Обоснование «свой Dockerfile на сервис»

- `bot` не нужны `flask`, `fastapi`, `uvicorn`, `psycopg2-binary`, `reportlab`, `openpyxl`.
- `worker` не нужны `flask`, `fastapi`, `aiohttp` (HTTP-сервер).
- `admin` не нужны `aiogram`, `openai`, `anthropic`, `tenacity`, `edge-tts`, `pydub`.
- Меньше образ → быстрее `docker pull` на CD, меньше attack surface, меньше cold-start.
- Общий базовый слой выносим в `docker/base.Dockerfile` с системными deps (ffmpeg, fonts, curl).

### Что схлопываем

- `webhook` (8090) → endpoint `POST /webhooks/yookassa` в `backend`.
- `api` (8092) → это и есть `backend`, переименовываем.

### Что выпиливаем

- `arq` из `requirements.txt` (не используется).
- Volume-mount `.:/app` (нарушает иммутабельность образа).
- `migrations/init.sql` ручной bootstrap в postgres (заменяем на Alembic в `backend` entrypoint).
- Дублирующие env-переменные `ADMIN_LOGIN/ADMIN_PASSWORD` vs `ADMIN_PANEL_USER/ADMIN_PANEL_PASSWORD` — оставляем одну пару.

---

## §3. Целевая структура каталогов

```
neurobox/
├── .env.example
├── .dockerignore
├── README.md
├── docker-compose.yml
├── docker-compose.override.yml          # local dev overrides (опционально)
├── pyproject.toml                       # переезд с requirements.txt на uv/poetry — Phase 4
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 0001_initial.py              # baseline = текущая прод-схема, см. §8 Phase 2
│
├── docker/
│   ├── base.Dockerfile                  # python:3.12-slim + ffmpeg + fonts + curl
│   ├── bot.Dockerfile
│   ├── backend.Dockerfile
│   ├── worker.Dockerfile
│   ├── admin.Dockerfile
│   └── entrypoints/
│       ├── bot.sh
│       ├── backend.sh                   # alembic upgrade head && uvicorn
│       ├── worker.sh
│       └── admin.sh
│
├── shared/                              # общий код, импортируется ИЗ ЛЮБОГО сервиса
│   ├── __init__.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py                  # бывший config/settings.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── session.py                   # async_sessionmaker, get_session() dependency
│   │   ├── models/                      # SQLAlchemy 2 ORM-модели (declarative)
│   │   │   ├── __init__.py              # Base = DeclarativeBase()
│   │   │   ├── user.py                  # User, UserSettings
│   │   │   ├── payment.py               # Payment, CreditTransaction
│   │   │   ├── ai_request.py            # AIRequest (telemetry)
│   │   │   ├── task.py                  # WorkerTask (очередь)
│   │   │   └── ...                      # остальные таблицы по доменам
│   │   └── repositories/
│   │       ├── __init__.py
│   │       ├── base.py                  # BaseRepository[T] с типизированными методами
│   │       ├── user.py                  # UserRepository
│   │       ├── payment.py               # PaymentRepository
│   │       ├── ai_request.py            # AIRequestRepository
│   │       └── ...
│   ├── domain/                          # бизнес-логика, не зависит от транспорта
│   │   ├── credits.py                   # бывший bot/services/credits.py → переписан под ORM
│   │   ├── yookassa.py                  # бывший bot/services/yookassa_service.py
│   │   ├── telemetry.py
│   │   └── analytics.py
│   ├── providers/                       # внешние AI-провайдеры (OpenRouter, FAL, Edge TTS)
│   │   └── (бывший bot/providers/* целиком)
│   ├── redis/
│   │   └── store.py                     # бывший bot/services/redis_store.py
│   ├── queue/                           # контракт задач Redis-очереди
│   │   ├── __init__.py
│   │   ├── client.py                    # enqueue(task_type, payload)
│   │   └── tasks.py                     # TypedDict / pydantic схемы задач
│   └── logging.py                       # structlog + Sentry init (вызывается в каждом entrypoint)
│
├── services/
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── main.py                      # entrypoint aiogram
│   │   ├── handlers/                    # бывший bot/handlers/*
│   │   ├── keyboards/
│   │   ├── middlewares/
│   │   ├── states/
│   │   ├── i18n.py
│   │   └── backend_client.py            # httpx-клиент к backend
│   │
│   ├── backend/
│   │   ├── __init__.py
│   │   ├── main.py                      # FastAPI app
│   │   ├── lifespan.py
│   │   ├── deps.py                      # JWT, БД-сессии
│   │   ├── routers/
│   │   │   ├── admin.py                 # бывший api/admin/router.py
│   │   │   ├── bot.py                   # endpoints для bot-сервиса (credits, profile)
│   │   │   └── webhooks.py              # YooKassa, бывший scripts/webhook_server.py
│   │   ├── services/
│   │   │   └── admin.py                 # бывший api/admin/service.py
│   │   └── schemas/                     # pydantic
│   │
│   ├── worker/
│   │   ├── __init__.py
│   │   ├── main.py                      # бывший worker/main.py
│   │   ├── jobs/
│   │   │   ├── notify.py
│   │   │   ├── video_generate.py
│   │   │   ├── daily_stats.py
│   │   │   └── alerts.py
│   │   └── telegram.py                  # singleton Bot(token=BOT_TOKEN), output-only
│   │
│   └── admin/
│       ├── __init__.py
│       ├── app.py                       # бывший admin_panel/app.py
│       ├── routes.py                    # бывший admin_panel/routes.py — Phase 2+ распилить
│       ├── access.py
│       ├── backend_client.py            # httpx к backend
│       └── templates/
│
├── tests/
│   ├── conftest.py
│   ├── shared/
│   ├── bot/
│   ├── backend/
│   ├── worker/
│   └── admin/
│
├── scripts/
│   ├── healthcheck.py
│   ├── smoke_user_flow.py
│   └── (всё, что не webhook/entrypoint)
│
└── docs/                                # сохраняем как есть
```

### Принципы

- Никто не импортирует `from services.bot.*` извне `services/bot/`. Общее = только `shared/`.
- Ни один сервис не знает про реализацию другого. Контракт между bot и backend = OpenAPI-схема FastAPI.
- `shared/queue/tasks.py` — единая правда о форме задач в Redis (типизированные TypedDict/pydantic).

---

## §4. Маппинг «было → стало»

**Принцип Фазы 1: толстые файлы переезжают целиком, без разбиения.** Сплиты — Фаза 2+.

| Было | Стало | Действие | Фаза |
|---|---|---|---|
| `config/settings.py` | `shared/config/settings.py` | переместить, обновить импорты `from config import settings` → `from shared.config import settings` | 1 |
| `config/i18n.py` | `services/bot/i18n.py` | переместить (используется только ботом) | 1 |
| `config/text_models.py` | `shared/config/text_models.py` | переместить | 1 |
| `config/bot_description.py` | `services/bot/bot_description.py` | переместить | 1 |
| `bot/db/database.py` | `shared/db/session.py` | переписать: asyncpg pool → SQLAlchemy `async_sessionmaker` | 2 |
| `bot/db/migrate.py` | удалить | заменяется на Alembic | 2 |
| *(нет)* | `shared/db/models/*.py` | написать с нуля: SQLAlchemy 2 declarative модели по текущей схеме | 2 |
| *(нет)* | `shared/db/repositories/*.py` | написать с нуля: BaseRepository[T] + domain-репозитории | 2 |
| `bot/services/credits.py` (1113) | `shared/domain/credits.py` | переместить целиком в Фазе 1; переписать под ORM/репозитории в Фазе 2 | 1→2 |
| `bot/services/yookassa_service.py` | `shared/domain/yookassa.py` | переместить | 1 |
| `bot/services/telemetry.py` | `shared/domain/telemetry.py` | переместить | 1 |
| `bot/services/analytics.py` | `shared/domain/analytics.py` | переместить | 1 |
| `bot/services/redis_store.py` | `shared/redis/store.py` | переместить | 1 |
| `bot/services/admin_log.py` | `shared/domain/admin_log.py` | переместить | 1 |
| `bot/services/admin_runtime.py` | `shared/domain/admin_runtime.py` | переместить | 1 |
| `bot/services/payment_notify.py` | `shared/domain/payment_notify.py` | переместить | 1 |
| `bot/services/video_service.py` | `shared/domain/video.py` | переместить | 1 |
| `bot/services/chat_service.py` | `services/bot/chat_service.py` | переместить (нужен только боту) | 1 |
| `bot/services/balance.py` | `services/bot/services/balance.py` | переместить (UX-обвязка вокруг credits) | 1 |
| `bot/services/cryptobot_service.py` | `shared/domain/cryptobot.py` | переместить | 1 |
| `bot/providers/*` | `shared/providers/*` | переместить папку целиком | 1 |
| `bot/handlers/*` | `services/bot/handlers/*` | переместить папку целиком | 1 |
| `bot/handlers/start.py` (1034) | `services/bot/handlers/start.py` | целиком, **не пилить** | 1; сплит → Фаза 2 |
| `bot/handlers/balance.py` (798) | `services/bot/handlers/balance.py` | целиком | 1; сплит → 2 |
| `bot/handlers/text.py` (794) | `services/bot/handlers/text.py` | целиком | 1; сплит → 2 |
| `bot/keyboards/*`, `bot/middlewares/*`, `bot/states/*` | `services/bot/...` | переместить | 1 |
| `bot/main.py` | `services/bot/main.py` | переместить, обновить импорты | 1 |
| `worker/main.py` (639) | `services/worker/main.py` | переместить целиком | 1 |
| `worker/main.py` → разбиение | `services/worker/jobs/{notify,video_generate,daily_stats,alerts}.py` | по типам задач | 2 |
| `api/main.py` | `services/backend/main.py` | переместить, переименовать | 1 |
| `api/admin/router.py` | `services/backend/routers/admin.py` | переместить | 1 |
| `api/admin/service.py` (876) | `services/backend/services/admin.py` | целиком | 1; сплит → 2 |
| `api/admin/schemas.py` | `services/backend/schemas/admin.py` | переместить | 1 |
| `api/admin/dependencies.py` | `services/backend/deps.py` (объединить) | merge | 1 |
| `scripts/webhook_server.py` | `services/backend/routers/webhooks.py` | переписать как FastAPI router | 2 |
| `admin_panel/app.py` | `services/admin/app.py` | переместить | 1 |
| `admin_panel/routes.py` (1179) | `services/admin/routes.py` | целиком | 1; сплит и переход на backend HTTP → 2 |
| `admin_panel/access.py`, `config.py`, `db.py`, `templates/`, `static/` | `services/admin/...` | переместить | 1 |
| `migrations/*.sql` | `alembic/versions/0001_initial.py` (autogenerate из живой схемы) | заменяется | 2 |
| `migrations/init.sql` | удалить из docker-compose, создаётся через Alembic | удалить | 2 |
| `scripts/entrypoint.sh` | удалить, заменить на per-service `docker/entrypoints/*.sh` | удалить | 3 |
| `Dockerfile` | удалить, заменить на `docker/{bot,backend,worker,admin}.Dockerfile` | удалить | 3 |
| `tests/*` | `tests/{shared,bot,backend,worker,admin}/*` | разнести по сервисам | 4 |

### Контракт совместимости в Фазе 1

После переноса файлов в `services/bot/` всё ещё импортируется как монолит. Файлы `services/bot/__init__.py` пусты. Импорты внутри `services/bot/` обновляются на `from shared.config import settings`, `from shared.domain.credits import ...`. Ничего не выпиливается, только перетасовка + правка импортов. Это даёт зелёный pytest на каждом шаге.

---

## §5. docker-compose.yml — черновик

```yaml
# docker-compose.yml — Phase 3 target
name: neurobox

services:
  postgres:
    image: postgres:16-alpine
    restart: always
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pg_data:/var/lib/postgresql/data
    networks: [nb_net]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    restart: always
    command: >
      redis-server
      --maxmemory 512mb
      --maxmemory-policy allkeys-lru
      --requirepass ${REDIS_PASSWORD}
      --appendonly yes
    volumes:
      - redis_data:/data
    networks: [nb_net]
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  backend:
    build:
      context: .
      dockerfile: docker/backend.Dockerfile
    restart: always
    env_file: .env
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
    depends_on:
      postgres: { condition: service_healthy }
      redis:    { condition: service_healthy }
    networks: [nb_net]
    ports:
      - "127.0.0.1:8092:8092"     # API + webhooks (за nginx)
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://127.0.0.1:8092/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s            # alembic upgrade head в entrypoint
    deploy:
      resources:
        limits: { memory: 512M }

  bot:
    build:
      context: .
      dockerfile: docker/bot.Dockerfile
    restart: always
    env_file: .env
    environment:
      BACKEND_URL: http://backend:8092
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
    depends_on:
      backend:  { condition: service_healthy }
      redis:    { condition: service_healthy }
    networks: [nb_net]
    healthcheck:
      test: ["CMD", "python", "/app/scripts/healthcheck.py"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
    deploy:
      resources:
        limits: { memory: 384M }

  worker:
    build:
      context: .
      dockerfile: docker/worker.Dockerfile
    restart: always
    env_file: .env
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
    depends_on:
      postgres: { condition: service_healthy }
      redis:    { condition: service_healthy }
      backend:  { condition: service_healthy }   # ждём миграции
    networks: [nb_net]
    healthcheck:
      test: ["CMD", "python", "/app/scripts/healthcheck.py"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
    deploy:
      resources:
        limits: { memory: 512M }

  admin:
    build:
      context: .
      dockerfile: docker/admin.Dockerfile
    restart: always
    env_file: .env
    environment:
      BACKEND_URL: http://backend:8092
      ADMIN_PANEL_PORT: 8091
    depends_on:
      backend: { condition: service_healthy }
    networks: [nb_net]
    ports:
      - "127.0.0.1:8091:8091"
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://127.0.0.1:8091/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    deploy:
      resources:
        limits: { memory: 256M }

volumes:
  pg_data:
  redis_data:

networks:
  nb_net:
    driver: bridge
```

### Что изменилось vs текущий compose

- Убран volume `.:/app` — образ иммутабельный.
- Убран сервис `webhook` — endpoint в `backend`.
- Убран сервис `api` — стал `backend`.
- 4 разных Dockerfile вместо одного с `SERVICE_TYPE`.
- Убран `init.sql` mount — миграции через Alembic.
- `bot` больше не имеет `DATABASE_URL` — только `BACKEND_URL`.
- `admin` больше не имеет `DATABASE_URL` — только `BACKEND_URL`.
- `worker` зависит от `backend` (ждёт пока Alembic применится).

---

## §6. .env.example + .dockerignore

### `.env.example`

```bash
# ===== Telegram =====
BOT_TOKEN=
BOT_USERNAME=ai_b0x_bot
ADMIN_IDS=
QA_TESTER_IDS=
LEGAL_BASE_URL=

# ===== Database =====
POSTGRES_DB=neurobox
POSTGRES_USER=neurobox
POSTGRES_PASSWORD=change-me
NEUROBOX_DB_MIN_SIZE=2
NEUROBOX_DB_MAX_SIZE=10

# ===== Redis =====
REDIS_PASSWORD=change-me

# ===== Backend (внутренний URL для bot и admin) =====
# Для прода/контейнеров перебивается в docker-compose
BACKEND_URL=http://backend:8092

# ===== AI providers =====
OPENROUTER_API_KEY=
SERPER_API_KEY=
OPENAI_API_KEY=
FALAI_API_KEY=
GOOGLE_AI_API_KEY=
GROK_API_KEY=

# ===== Payments =====
ENABLE_STARS_PAYMENT=true
ENABLE_YOOKASSA_PAYMENT=false
ENABLE_CRYPTOBOT_PAYMENT=false
YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=
YOOKASSA_RECEIPT_EMAIL=
SKIP_YOOKASSA_IP_CHECK=0
CRYPTOBOT_API_TOKEN=

# ===== Feature flags =====
ENABLE_VIDEO=false
ENABLE_MUSIC=false
ENABLE_TTS=false
USE_VIDEO_QUEUE=false

# ===== Admin (Flask UI + Backend API auth) =====
ADMIN_PANEL_USER=admin
ADMIN_PANEL_PASSWORD=change-me
ADMIN_PANEL_SECRET=change-me-32-bytes
ADMIN_API_SECRET_KEY=change-me-32-bytes

# ===== Notifications =====
PAYMENT_NOTIFY_BOT_TOKEN=
PAYMENT_NOTIFY_CHAT_ID=

# ===== Tuning =====
FREE_DAILY_CREDITS=10
LOG_LEVEL=INFO
SENTRY_DSN=
```

**Изменения:**

- Убраны дубли `ADMIN_LOGIN/ADMIN_PASSWORD`, оставлены только `ADMIN_PANEL_*`.
- Добавлен `BACKEND_URL` (внутренний URL).
- `WORKER_BOT_TOKEN` НЕ заводится — worker использует тот же `BOT_TOKEN`.

### `.dockerignore` (общий, для всех Dockerfile)

```
.git
.github
.gitignore
.env
.env.*
!.env.example
.venv
venv
__pycache__
*.pyc
.pytest_cache
.coverage
htmlcov
tests
docs
backups
logs
*.log
*.md
docker-compose*.yml
.dockerignore
.idea
.vscode
.DS_Store
```

---

## §7. Деплой на прод

Деплой ручной, без CI/CD:

```bash
# С машины с доступом к серверу
rsync -az --delete \
  --exclude='.env' \
  --exclude='backups' \
  --exclude='logs' \
  ./ user@host:/opt/neurobox/

ssh user@host 'cd /opt/neurobox && docker compose up -d --build --remove-orphans && docker image prune -f'
```

**Pre-deploy чек-лист (архитектор):**

- Бэкап БД: `docker compose exec postgres pg_dump -U neurobox neurobox > backup-pre-refactor.sql`.
- Бэкап `.env`.
- Проверить, что `/opt/neurobox/.env` соответствует новому `.env.example`.

**Прод-smoke после деплоя:**

- `docker compose ps` — все healthy.
- `docker compose logs --tail 100 backend` — Alembic применил, uvicorn слушает.
- `docker compose logs --tail 100 worker` — connected to redis, listening.
- В Telegram: `/start`, `/balance`, отправить текст, проверить ответ.
- Тестовый платёж YooKassa (sandbox) — webhook принят, баланс зачислен.
- `https://<домен>/admin` — Flask UI открывается, логин работает, дашборд грузит данные.

---

## §8. Дорожная карта по фазам

Каждая фаза завершается ревью архитектора и зелёным smoke.

### Фаза 0 — Cleanup (~1 день)

**Чек-лист:**

- [x] Удалить `arq==0.27.0` из `requirements.txt` (не используется).
- [x] Удалить `ADMIN_LOGIN`/`ADMIN_PASSWORD` из `.env.example` (используются только `ADMIN_PANEL_USER`/`ADMIN_PANEL_PASSWORD`).
- [x] Удалить упоминание `migrations/init.sql` из `docker-compose.yml` и пустую папку `migrations/`.
- [x] Удалить `patches/` (не импортируется нигде в коде).
- [x] Привести `.dockerignore` к виду из §6.
- [x] Прогнать `ruff check .` — починить тривиальное.
- [x] `pytest -q` — зелёный (46/47; 1 падает из-за отсутствия `OPENROUTER_API_KEY` — pre-existing, требует реальных секретов).

**Definition of Done:** ничего не сломалось, прод-поведение идентично.

### Фаза 1 — Перетасовка структуры, БЕЗ сплитов (2-3 дня)

**Цель:** переместить файлы в `shared/` и `services/` согласно §4. Разбиение толстых файлов НЕ делается. Один сервис в Docker по-прежнему запускается через `SERVICE_TYPE` — старый Dockerfile не трогаем.

**Чек-лист:**

- [x] Создать каталоги `shared/`, `services/{bot,backend,worker,admin}/` с `__init__.py`.
- [x] Перенести файлы по таблице §4 (сохранить содержимое, только переместить).
- [x] Глобальный поиск-замена импортов (86 файлов обновлено).
- [x] Обновить `scripts/entrypoint.sh` с новыми путями модулей.
- [x] Написать `shared/logging.py` с `setup_logging()`.
- [x] Создать `shared/queue/tasks.py` и `shared/queue/client.py`.
- [x] `pytest -q` — 46/47 зелёных (1 pre-existing: нет `OPENROUTER_API_KEY`).
- [ ] Локально `docker compose up -d --build` — все 7 сервисов healthy.
- [ ] Smoke: `docker compose exec bot python /app/scripts/smoke_user_flow.py`.

**Definition of Done:** новое дерево, старый рантайм. Прод-поведение идентично.
**Гарант стабильности:** на каждом шаге Фазы 1 `pytest && smoke` зелёные.

### Фаза 2 — ORM + Alembic + разделение сервисов (7-10 дней)

**Цель:** SQLAlchemy 2 async вместо raw SQL, Alembic создаёт схему с нуля, чистые границы между сервисами.

**Чек-лист:**

- [x] **Добавить зависимости** в `requirements.txt`:
  - `sqlalchemy[asyncio]==2.0.*`
  - `alembic==1.13.*`
  - Убрать прямые вызовы `asyncpg` из кода (оставить только как драйвер под SQLAlchemy).

- [x] **SQLAlchemy модели** (`shared/db/models/`):
  - Изучить существующую схему БД (через `bot/db/migrate.py` + `.sql`-файлы или introspect прод-дампа, который предоставит архитектор).
  - Написать declarative-модели: `User`, `UserSettings`, `Payment`, `CreditTransaction`, `AIRequest`, `WorkerTask`, `PromoCode`, `Referral`, `DailyBonus`, `ResponseRating`, `AdminLog` — по текущим таблицам.
  - `Base = DeclarativeBase()` в `shared/db/models/__init__.py`. Все модели импортируются там же.
  - Типы: `Mapped[T]` + `mapped_column()` (SQLAlchemy 2 style). Без старого `Column()`.

- [x] **Alembic с нуля** (`alembic/`):
  - `alembic init alembic`.
  - `alembic/env.py` настроить на `Base.metadata` из `shared.db.models` и `DATABASE_URL` из `shared.config.settings`.
  - Запустить против **чистой локальной** БД: `alembic revision --autogenerate -m "initial"`.
  - Проверить сгенерированный файл — он должен содержать CREATE TABLE для всех моделей.
  - Применить: `alembic upgrade head` → БД создана, никаких `.sql`-файлов больше нет.
  - Удалить `bot/db/migrate.py` и все `migrations/*.sql`.

- [x] **Session layer** (`shared/db/session.py`):
  - `engine = create_async_engine(DATABASE_URL, pool_size=..., max_overflow=...)`
  - `AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)`
  - `get_session()` — async context manager для использования в FastAPI dependency и в worker.

- [x] **Репозитории** (`shared/db/repositories/`):
  - `BaseRepository[T]` с методами `get(id)`, `get_by(field, value)`, `list(**filters)`, `create(data)`, `update(id, data)`, `delete(id)`.
  - Конкретные: `UserRepository`, `PaymentRepository`, `AIRequestRepository`, `CreditTransactionRepository`.
  - Репозитории принимают `AsyncSession` в конструктор, не создают сессии сами.

- [x] **Переписать бизнес-логику под ORM:**
  - `shared/domain/credits.py` — заменить все `conn.execute("SELECT ...")` на вызовы `UserRepository`, `CreditTransactionRepository`, `PaymentRepository`.
  - `shared/domain/telemetry.py` — `AIRequestRepository.create(...)`.
  - `shared/domain/yookassa.py` — `PaymentRepository`.
  - `shared/domain/analytics.py` — только читающие репозитории.
  - Worker (`services/worker/jobs/`) — получает `AsyncSession` через `get_session()`, передаёт в репозитории.

- [x] **Backend webhooks:**
  - Перенести `scripts/webhook_server.py` → `services/backend/routers/webhooks.py` как FastAPI endpoint `POST /webhooks/yookassa`.
  - IP-фильтр и idempotency-key проверку — сохранить.
  - Удалить сервис `webhook` из `docker-compose.yml`.
  - Удалить `scripts/webhook_server.py`.

- [x] **Bot → backend через httpx:**
  - Создать `services/bot/backend_client.py` с httpx AsyncClient.
  - Хендлеры, обращавшиеся к `shared.domain.credits` напрямую, теперь вызывают `await backend_client.get_balance(user_id)` и т.п.
  - В `services/backend/routers/bot.py` — endpoint'ы для всех этих вызовов.
  - Bot больше не импортирует ничего из `shared/db/` и `shared/domain/`.

- [x] **Admin → backend через httpx:**
  - `services/admin/backend_client.py`.
  - Flask `routes.py` заменяет прямые `from shared.domain.*` на вызовы `backend_client.*`.
  - Flask `db.py` — удалить (больше не нужен).

- [x] **Worker — singleton Bot:**
  - `services/worker/telegram.py`: `Bot(token=settings.bot_token, default=DefaultBotProperties(...))` создаётся один раз при старте.
  - В shutdown worker вызывает `await bot.session.close()`.
  - Запрещённые методы не вызываются — проверяется на ревью.

- [x] **Сплиты толстяков:**
  - `services/worker/main.py` (639) → `services/worker/jobs/{notify,video_generate,daily_stats,alerts}.py`.
  - `services/backend/services/admin.py` (876) → разбить по доменам (users, payments, content, tariffs).

- [x] Зелёный `pytest`, зелёный smoke против локальной чистой БД.

**Definition of Done:**
- Сырого SQL в коде нет. Все запросы — через репозитории.
- `alembic upgrade head` на пустой БД создаёт полную схему.
- Граф зависимостей: `services/* → shared/*`, никаких перекрёстных стрелок между сервисами.
- `bot` не импортирует `shared.db.*` — только вызывает `backend_client.*`.

### Фаза 3 — Per-service Dockerfiles + новый docker-compose (2-3 дня)

**Цель:** иммутабельные образы, по одному Dockerfile на сервис. Volume-mount удаляется.

**Чек-лист:**

- [x] Создать `docker/base.Dockerfile` (python:3.12-slim + ffmpeg + fonts + curl).
- [x] Создать `docker/{bot,backend,worker,admin}.Dockerfile` со своими `requirements-{service}.txt` (распилить общий `requirements.txt`).
- [x] Создать `docker/entrypoints/{bot,backend,worker,admin}.sh`. В `backend.sh`: `alembic upgrade head && exec uvicorn services.backend.main:app --host 0.0.0.0 --port 8092`.
- [x] Заменить `docker-compose.yml` на вариант из §5.
- [x] Удалить корневой `Dockerfile` и `scripts/entrypoint.sh`.
- [ ] **Локально:**
  - `docker compose build` — все 4 образа собираются.
  - `docker compose up -d` — все 6 сервисов healthy.
  - Smoke зелёный.

### Фаза 4 — Тесты до 75% (5-7 дней)

**Чек-лист:**

- [ ] Установить базовый замер: `pytest --cov=shared --cov=services --cov-report=term`. Зафиксировать текущий процент.
- [ ] Реструктурировать `tests/` по сервисам: `tests/{shared,bot,backend,worker,admin}/`.
- [ ] Расставить `conftest.py` с фикстурами на каждый уровень (БД-фикстура — общая в `tests/conftest.py`).
- [ ] **Приоритет покрытия:**
  1. `shared/domain/credits.py` (1113) — критическая бизнес-логика, требуется ≥85%.
  2. `shared/domain/yookassa.py` — финансовая логика.
  3. `services/backend/services/admin.py` — endpoint-логика.
  4. `services/worker/jobs/*` — задачи.
  5. Хендлеры бота — happy path + edge cases (mock aiogram через `aiogram-tests`).
- [ ] `pytest --cov=shared --cov=services --cov-fail-under=75` зелёный.

### Фаза 5 — Деплой на прод (архитектор, 1 день)

**Чек-лист архитектора (прод-доступ):**

- [ ] **Pre-deploy подготовка прода:**
  - Бэкап БД: `docker compose exec postgres pg_dump -U neurobox neurobox > backup-pre-refactor.sql`.
  - Бэкап `.env`.
  - Проверить, что `/opt/neurobox/.env` соответствует новому `.env.example` (никаких удалённых переменных не торчит, никаких новых не пропущено).
- [ ] rsync кода на сервер (см. §7).
- [ ] `docker compose up -d --build --remove-orphans`.
- [ ] **Прод-smoke** (см. §7).

### Definition of Done всего рефакторинга

- 6 контейнеров, 4 разных Dockerfile, иммутабельные образы.
- `docker compose up -d --build` на сервере — единственная точка деплоя.
- `pytest --cov-fail-under=75` зелёный локально.
- Граф зависимостей чистый: `shared` ← `services/*`. Никаких `services/bot.* ← services/worker.*`.

---

## Осознанные трейдофы и будущие инициативы

Всё нижеперечисленное принято как решение, а не «пропущено»:

- **Git / GitHub Actions** — проект ведётся без системы контроля версий. CI/CD автоматизация не планируется в рамках данного рефакторинга. Revisit после стабилизации архитектуры.
- **Деприкация Flask admin** — текущие 1179 строк routes + 14 шаблонов. В рамках плана Flask превращается в тонкий UI-клиент к backend HTTP API (Фаза 2). Полная замена на FastAPI+Jinja или SPA — отдельная инициатива после стабилизации архитектуры.
- **Secrets manager (Vault, sops)** — для одного VPS с key-only SSH plain `.env` — осознанный, приемлемый риск. Vault = отдельный high-availability сервис, sops = управление ключами. Оба добавляют операционную нагрузку непропорционально текущему масштабу. Revisit при горизонтальном масштабировании.
- **Репозиторный паттерн в тестах (in-memory fakes)** — BaseRepository позволит подменять реализацию в тестах без поднятия БД. Вводится в Фазе 4 по мере написания unit-тестов.
