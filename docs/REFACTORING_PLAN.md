# План рефакторинга NeuroBox

> Документ для архитектора и агента-исполнителя.
> Цель документа: зафиксировать текущее состояние проекта, целевую архитектуру, правила миграции и порядок фаз.
> Этот документ не является инструкцией на написание бизнес-кода. Это архитектурная спецификация.

## Контекст и рамки

- Архитектор принимает решения, делает ревью и выполняет прод-операции по ssh.
- Агент-исполнитель работает в отдельном чате, без прод-доступа и без секретов.
- Общаемся на русском. Код, файлы, переменные, команды и конфиги оформляются на английском.
- Принятые решения не пересматриваются в рамках этого документа:
  - `bot` не ходит в БД напрямую.
  - `bot` общается с `backend` по HTTP внутри docker network.
  - `worker` ходит в БД напрямую через `shared/db`.
  - `worker` использует тот же `BOT_TOKEN`, что и `bot`, и является output-only клиентом Bot API.
  - Alembic запускается в entrypoint `backend` перед стартом uvicorn.
  - Секреты не попадают к исполнителю; у исполнителя только `.env.example` и fake values.

## Стек

- `aiogram 3`
- `FastAPI`
- `Flask` для текущей admin UI
- `SQLAlchemy 2 + asyncpg`
- `Redis`
- `httpx`
- `Alembic`
- `Postgres`
- `YooKassa`

## Цели рефакторинга

1. Убрать архитектурную кашу при сохранении рабочего прод-поведения.
2. Довести границы сервисов до понятной модели ответственности.
3. Сделать `docker compose up -d --build` каноническим способом запуска окружения.
4. Подготовить проект к CD через GitHub Actions.
5. Довести тестовое покрытие до 75%.

---

## §1. Текущее состояние

### 1.1 Код

Проект уже не является физическим монолитом в смысле каталогов: в репозитории есть `services/`, `shared/`, `docker/`, `alembic/`, `tests/`. Но логически он все еще остается полумонолитом, потому что границы ответственности между сервисами не доведены до конца.

Текущее дерево верхнего уровня:

- `services/admin`
- `services/backend`
- `services/bot`
- `services/worker`
- `shared/config`
- `shared/db`
- `shared/domain`
- `shared/providers`
- `shared/queue`
- `shared/redis`
- `docker`
- `alembic`
- `tests`

### 1.2 Что уже сделано хорошо

- Есть отдельные контейнеры и отдельные Dockerfile для `bot`, `backend`, `worker`, `admin`.
- Есть `shared/` как явное место для общего кода.
- Есть Alembic и старт миграций из entrypoint backend.
- Есть раздельные requirements-файлы по сервисам.
- Есть разложенные по сервисам тесты: `tests/bot`, `tests/backend`, `tests/worker`, `tests/admin`, `tests/shared`.

### 1.3 Главные архитектурные проблемы

#### Проблема 1. `bot` все еще привязан к БД напрямую

Формально целевое решение уже принято: `bot` должен ходить только в `backend`.
Фактически сейчас это не выполнено.

Признаки:

- `services/bot/main.py` открывает соединение с БД через `shared.db.database.get_pool()`.
- `shared/db/database.py` остается живым asyncpg-pool слоем именно для bot-runtime.
- bot-слой использует `shared.domain.*`, а эти доменные модули читают и пишут данные напрямую.

Следствие:

- `bot` знает о схеме БД и доменной модели слишком много.
- backend не является настоящей серверной границей.
- невозможно изолированно эволюционировать `bot` и `backend`.

#### Проблема 2. `admin` тоже нарушает целевую границу

Сейчас `admin` одновременно:

- имеет `backend_client.py`
- и имеет прямое подключение к БД через `services/admin/db.py`

Следствие:

- admin UI остается гибридом: часть данных идет через backend, часть напрямую в Postgres.
- backend не является единым серверным API для внутренних клиентов.
- логика авторизации, аудита и чтения данных размазана между `admin` и `backend`.

#### Проблема 3. `backend` пока не стал настоящим application API

Сейчас `backend` в основном содержит:

- admin API
- webhook endpoints
- сервисный слой `services/backend/services/admin.py`

Но в проекте пока нет полноценного bot-facing API, через который `bot` мог бы получать:

- баланс
- доступность paywall
- создание платежей
- историю диалогов
- runtime-настройки
- модерационные и сервисные действия

Следствие:

- `backend` уже есть как контейнер, но еще не играет роль единственной серверной точки входа для бота.

#### Проблема 4. Толстые файлы и толстые модули

В проекте есть несколько крупных точек концентрации логики:

- `services/bot/handlers/start.py`
- `services/bot/handlers/text.py`
- `services/bot/handlers/balance.py`
- `services/backend/services/admin.py`
- `services/admin/routes.py`
- `shared/domain/credits.py`

Следствие:

- высокая стоимость изменений
- тяжелые ревью
- плохая локализация регрессий
- слабая тестируемость на уровне маленьких блоков

#### Проблема 5. `shared/` смешивает стабильное ядро и прикладной код

Сейчас в `shared/` лежит все сразу:

- настройки
- БД
- доменная логика
- провайдеры AI
- Redis helpers
- queue contract

Это нормальный промежуточный этап, но не финальная форма. Внутри `shared/` нужно яснее разделить:

- инфраструктуру
- доменную логику
- контракты межсервисного взаимодействия
- адаптеры внешних API

#### Проблема 6. Worker-планировщик пока примитивный

`worker` сейчас рабочий, но внутри остается ручной orchestration:

- loop
- polling очереди
- периодические действия вручную из `main.py`

Следствие:

- логика lifecycle смешана с логикой задач
- сложно расширять набор фоновых задач
- трудно отдельно тестировать runner и scheduler behavior

### 1.4 Инфраструктура

Сейчас по факту есть 6 runtime-unit:

- `bot`
- `backend`
- `worker`
- `admin`
- `postgres`
- `redis`

Сильные стороны:

- локальный запуск уже близок к целевому
- миграции применяются на старте backend
- есть healthcheck у сервисов

Слабые стороны:

- текущий `docker-compose.yml` был уже исправлен в ходе отладки, но его стоит нормализовать как спецификацию, а не как набор накопленных правок
- нет `.github/workflows`
- нет канонического CD сценария
- не зафиксированы отдельные `dev` и `prod` режимы compose

### 1.5 Тесты

Сейчас тесты уже разложены лучше, чем в раннем монолите:

- `tests/admin`
- `tests/backend`
- `tests/bot`
- `tests/shared`
- `tests/worker`
- набор cross-cutting тестов в корне `tests/`

Но остаются проблемы:

- нет зафиксированного coverage gate на 75%
- coverage-фокус пока неровный
- самые рискованные толстые файлы требуют отдельного приоритета

### 1.6 Git и CI/CD

- Git-репозиторий уже есть.
- GitHub Actions в проекте отсутствуют.
- `.gitignore` минимальный и рабочий, но не покрывает все артефакты нового CI/CD и локальной сборки.
- CD-процесс как код не зафиксирован.

---

## §2. Предлагаемый состав сервисов с обоснованием

### 2.1 Рекомендуемый итоговый состав

Рекомендую считать целевой архитектурой 6 runtime-компонентов:

1. `bot`
2. `backend`
3. `worker`
4. `admin`
5. `postgres`
6. `redis`

### 2.2 Почему именно так

#### `bot`

Ответственность:

- Telegram transport
- aiogram routing
- FSM
- presentation logic
- вызов backend API

Не должен делать:

- прямые SQL/ORM-вызовы
- прямые вызовы доменной логики, завязанной на БД

#### `backend`

Ответственность:

- единая application boundary
- bot-facing API
- admin-facing API
- webhooks
- orchestration доменной логики
- Alembic startup

Почему это правильно:

- backend становится единственным местом, где прикладная логика видит БД как write/read model для интерактивных запросов
- bot и admin становятся тоньше

#### `worker`

Ответственность:

- background jobs
- async task processing
- scheduled maintenance jobs
- output-only взаимодействие с Telegram

Почему worker должен ходить в БД напрямую:

- это уже принятое решение
- для background jobs не нужен лишний HTTP-hop через backend
- это снижает latency и снижает искусственную связанность

#### `admin`

Ответственность:

- только UI
- только вызовы backend API
- без прямого доступа к БД

Почему admin оставляем отдельным сервисом:

- текущий Flask UI уже существует
- это дешевле, чем сразу переписывать его в backend
- дает безопасный переходный этап

#### `postgres`

Ответственность:

- state store

Почему оставляем как часть целевого runtime-состава:

- локальная и staging parity
- `docker compose up -d` остается полной точкой входа
- проще smoke и onboarding исполнителя

Примечание:

- для production допустим вариант с host-managed Postgres через `docker-compose.prod.yml` или `.env.prod`, но канонический план и документация должны исходить из полного compose-стека

#### `redis`

Ответственность:

- FSM storage
- cache
- queue transport
- rate limiting

### 2.3 Что не добавляем

- отдельный `webhook` сервис не нужен
- отдельный `scheduler` сервис не нужен на текущем масштабе
- отдельный `gateway` или reverse-proxy контейнер не нужен внутри проекта на этой фазе
- `WORKER_BOT_TOKEN` не вводим

---

## §3. Целевая структура каталогов

Принцип: в Фазе 1 не делаем преждевременные сплиты. Сначала фиксируем правильные сервисные границы и правильные зависимости. Дробление толстых файлов переносим в следующие фазы.

```text
neurobox/
├── .env.example
├── .gitignore
├── .dockerignore
├── README.md
├── docker-compose.yml
├── docker-compose.dev.yml
├── docker-compose.prod.yml
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── docker/
│   ├── base.Dockerfile
│   ├── bot.Dockerfile
│   ├── backend.Dockerfile
│   ├── worker.Dockerfile
│   ├── admin.Dockerfile
│   └── entrypoints/
│       ├── bot.sh
│       ├── backend.sh
│       ├── worker.sh
│       └── admin.sh
├── services/
│   ├── bot/
│   │   ├── main.py
│   │   ├── backend_client.py
│   │   ├── handlers/
│   │   ├── keyboards/
│   │   ├── middlewares/
│   │   ├── services/
│   │   ├── states/
│   │   └── utils/
│   ├── backend/
│   │   ├── main.py
│   │   ├── deps.py
│   │   ├── routers/
│   │   ├── schemas/
│   │   └── services/
│   ├── worker/
│   │   ├── main.py
│   │   ├── telegram.py
│   │   └── jobs/
│   └── admin/
│       ├── app.py
│       ├── backend_client.py
│       ├── routes.py
│       ├── access.py
│       ├── audit.py
│       └── templates/
├── shared/
│   ├── config/
│   ├── db/
│   │   ├── models/
│   │   ├── repositories/
│   │   ├── session.py
│   │   └── __init__.py
│   ├── domain/
│   ├── providers/
│   ├── queue/
│   ├── redis/
│   └── logging.py
├── scripts/
│   ├── healthcheck.py
│   ├── smoke_user_flow.py
│   └── check_apis.py
├── tests/
│   ├── admin/
│   ├── backend/
│   ├── bot/
│   ├── shared/
│   ├── worker/
│   └── conftest.py
└── docs/
    ├── ARCHITECTURE.md
    ├── STRUCTURE.md
    ├── SERVICES.md
    ├── DATABASE.md
    ├── TESTING.md
    └── REFACTORING_PLAN.md
```

### 3.1 Что важно в этой структуре

- `services/*` содержат только код конкретного runtime.
- `shared/*` не знает о конкретном сервисе.
- `bot` и `admin` не имеют собственного DB-access слоя.
- `backend` и `worker` могут использовать `shared/db`.
- `scripts/` остаются только для operational и smoke задач, а не как место для runtime-серверов.

---

## §4. Маппинг файлов: было → стало

Принцип: в Фазе 1 толстые файлы не дробятся, а переезжают или остаются целиком в правильной зоне ответственности. Сплиты делаются в Фазе 2+.

| Было | Стало | Комментарий |
|---|---|---|
| `services/bot/main.py` | `services/bot/main.py` | Остается целиком в Фазе 1; позже можно выделить bootstrap/polling lifecycle |
| `services/bot/backend_client.py` | `services/bot/backend_client.py` | Становится обязательным каналом доступа к данным |
| `services/bot/handlers/start.py` | `services/bot/handlers/start.py` | Не дробить в Фазе 1; позже split по onboarding/menu/referral |
| `services/bot/handlers/text.py` | `services/bot/handlers/text.py` | Не дробить в Фазе 1; позже split по chat/context/provider orchestration |
| `services/bot/handlers/balance.py` | `services/bot/handlers/balance.py` | Не дробить в Фазе 1; позже split по billing/paywall/payments |
| `services/bot/services/chat_service.py` | `services/bot/services/chat_service.py` | Оставить в bot-сервисе, но убрать DB coupling через backend API |
| `services/backend/main.py` | `services/backend/main.py` | Остается точкой входа |
| `services/backend/routers/admin.py` | `services/backend/routers/admin.py` | Остается целиком на Фазе 1 |
| `services/backend/routers/webhooks.py` | `services/backend/routers/webhooks.py` | Остается в backend как единая зона для webhooks |
| `services/backend/services/admin.py` | `services/backend/services/admin.py` | Не дробить в Фазе 1; позже split на `users.py`, `payments.py`, `analytics.py`, `content.py`, `tariffs.py` |
| `services/worker/main.py` | `services/worker/main.py` | Остается runner entrypoint; позже выделить runner/scheduler/dispatch |
| `services/worker/jobs/notify.py` | `services/worker/jobs/notify.py` | Оставить |
| `services/worker/jobs/video_generate.py` | `services/worker/jobs/video_generate.py` | Оставить |
| `services/worker/jobs/daily_stats.py` | `services/worker/jobs/daily_stats.py` | Оставить |
| `services/worker/jobs/alerts.py` | `services/worker/jobs/alerts.py` | Оставить |
| `services/admin/app.py` | `services/admin/app.py` | Оставить entrypoint |
| `services/admin/routes.py` | `services/admin/routes.py` | Не дробить в Фазе 1; позже split на `dashboard.py`, `users.py`, `payments.py`, `content.py` |
| `services/admin/db.py` | удалить | Прямой доступ admin к БД должен исчезнуть |
| `shared/db/database.py` | удалить после Фазы 2 | Временный признак старого bot→DB доступа |
| `shared/db/session.py` | `shared/db/session.py` | Канонический DB-access слой для backend/worker |
| `shared/domain/credits.py` | `shared/domain/credits.py` | Не дробить в Фазе 1; позже split на billing/paywall/plans/ledger |
| `shared/domain/yookassa.py` | `shared/domain/yookassa.py` | Оставить в shared domain |
| `shared/providers/openai_text.py` | `shared/providers/openai_text.py` | Оставить; позже возможно split по vendor adapters |
| `scripts/healthcheck.py` | `scripts/healthcheck.py` | Оставить |
| `scripts/smoke_user_flow.py` | `scripts/smoke_user_flow.py` | Оставить как smoke harness |

### 4.1 Сплиты, которые откладываются до следующих фаз

- `services/bot/handlers/start.py`
- `services/bot/handlers/text.py`
- `services/bot/handlers/balance.py`
- `services/backend/services/admin.py`
- `services/admin/routes.py`
- `shared/domain/credits.py`

---

## §5. `docker-compose.yml` черновик

Ниже черновик канонического compose для dev/staging parity. Для production допускается override на внешний Postgres, но базовый документ держим в полном виде.

```yaml
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
    command:
      [
        "redis-server",
        "--requirepass", "${REDIS_PASSWORD}",
        "--appendonly", "yes",
        "--maxmemory", "512mb",
        "--maxmemory-policy", "allkeys-lru"
      ]
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
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks: [nb_net]
    ports:
      - "127.0.0.1:8092:8092"
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://127.0.0.1:8092/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s

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
      backend:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks: [nb_net]
    healthcheck:
      test: ["CMD", "python", "/app/scripts/healthcheck.py"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

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
      backend:
        condition: service_healthy
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks: [nb_net]
    healthcheck:
      test: ["CMD", "python", "/app/scripts/healthcheck.py"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

  admin:
    build:
      context: .
      dockerfile: docker/admin.Dockerfile
    restart: always
    env_file: .env
    environment:
      BACKEND_URL: http://backend:8092
    depends_on:
      backend:
        condition: service_healthy
    networks: [nb_net]
    ports:
      - "127.0.0.1:8091:8091"
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://127.0.0.1:8091/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s

volumes:
  pg_data:
  redis_data:

networks:
  nb_net:
    driver: bridge
```

### 5.1 Замечания к compose

- `bot` не получает `DATABASE_URL`.
- `admin` не получает `DATABASE_URL`.
- `worker` получает `DATABASE_URL` и `BOT_TOKEN`.
- `backend` остается единственным сервисом, который применяет миграции.
- В production можно использовать `docker-compose.prod.yml`, где `postgres` отключен, а `DATABASE_URL` указывает на host-managed Postgres.

---

## §6. `.env.example` и `.gitignore`

### 6.1 Рекомендуемый `.env.example`

```env
BOT_TOKEN=
BOT_USERNAME=

POSTGRES_DB=neurobox
POSTGRES_USER=neurobox
POSTGRES_PASSWORD=
REDIS_PASSWORD=

DATABASE_URL=
REDIS_URL=
BACKEND_URL=http://backend:8092

ADMIN_IDS=
QA_TESTER_IDS=
LEGAL_BASE_URL=

OPENROUTER_API_KEY=
OPENAI_API_KEY=
GOOGLE_AI_API_KEY=
FALAI_API_KEY=
GROK_API_KEY=
SERPER_API_KEY=

ENABLE_VIDEO=false
ENABLE_MUSIC=false
ENABLE_TTS=false
USE_VIDEO_QUEUE=false

ENABLE_STARS_PAYMENT=true
ENABLE_YOOKASSA_PAYMENT=false
ENABLE_CRYPTOBOT_PAYMENT=false
YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=
YOOKASSA_RECEIPT_EMAIL=
CRYPTOBOT_API_TOKEN=

ADMIN_PANEL_URL=http://127.0.0.1:8091
ADMIN_PANEL_SECRET=
ADMIN_PANEL_USER=admin
ADMIN_PANEL_PASSWORD=
ADMIN_API_SECRET_KEY=

PAYMENT_NOTIFY_BOT_TOKEN=
PAYMENT_NOTIFY_CHAT_ID=

FREE_DAILY_CREDITS=10
LOG_LEVEL=INFO
SENTRY_DSN=

NEUROBOX_DB_MIN_SIZE=2
NEUROBOX_DB_MAX_SIZE=10
```

### 6.2 Пояснения

- `BOT_TOKEN` один на `bot` и `worker`.
- `DATABASE_URL` в `.env.example` можно не использовать локально напрямую, если compose сам собирает его из `POSTGRES_*`, но поле полезно как явный контракт.
- Секреты и реальные API keys не хранятся в репозитории.

### 6.3 Рекомендуемый `.gitignore`

```gitignore
# Secrets
.env
.env.*
!.env.example

# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.pytest_cache/
.ruff_cache/
.mypy_cache/
.coverage
.coverage.*
htmlcov/

# Virtualenv
.venv/
venv/

# Build
build/
dist/
*.egg-info/

# OS / IDE
.DS_Store
.idea/
.vscode/

# Logs / runtime
logs/
*.log
tmp/

# Local tooling
.claude/

# CI / artifacts
artifacts/
coverage.xml
pytest-report.xml
```

---

## §7. GitHub Actions CD workflow

Сейчас workflow отсутствует. Ниже черновик рабочего CD pipeline для `push` в `main`.

Файл: `.github/workflows/cd.yml`

```yaml
name: CD

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest pytest-cov

      - name: Run tests
        env:
          BOT_TOKEN: "test-token"
          POSTGRES_PASSWORD: "test-password"
          REDIS_PASSWORD: "test-password"
        run: |
          pytest --cov=shared --cov=services --cov-fail-under=75

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Start ssh-agent
        uses: webfactory/ssh-agent@v0.9.0
        with:
          ssh-private-key: ${{ secrets.SSH_PRIVATE_KEY }}

      - name: Add known hosts
        run: |
          mkdir -p ~/.ssh
          ssh-keyscan -p "${{ secrets.SSH_PORT }}" "${{ secrets.SSH_HOST }}" >> ~/.ssh/known_hosts

      - name: Sync project
        run: |
          rsync -az --delete \
            --exclude '.git' \
            --exclude '.venv' \
            --exclude '__pycache__' \
            ./ "${{ secrets.SSH_USER }}@${{ secrets.SSH_HOST }}:${{ secrets.DEPLOY_PATH }}/"

      - name: Deploy
        run: |
          ssh -p "${{ secrets.SSH_PORT }}" "${{ secrets.SSH_USER }}@${{ secrets.SSH_HOST }}" <<'EOF'
            set -e
            cd "${{ secrets.DEPLOY_PATH }}"
            docker compose up -d --build --remove-orphans
            docker compose ps
          EOF
```

### 7.1 Секреты GitHub

- `SSH_HOST`
- `SSH_PORT`
- `SSH_USER`
- `SSH_PRIVATE_KEY`
- `DEPLOY_PATH`

### 7.2 Что должен делать архитектор на проде после первого включения CD

- проверить актуальность `.env` на сервере
- проверить права на директорию deploy path
- один раз проверить, что `docker compose up -d --build` руками проходит без CI
- добавить smoke-check после deploy

---

## §8. Дорожная карта по фазам с чек-листами

### Фаза 0. Git + cleanup

Цель:

- зафиксировать репозиторий как управляемый проект
- убрать явный мусор
- подготовить базу для рефакторинга

Чек-лист:

- [ ] Проверить, что в репозитории нет реальных секретов.
- [ ] Привести `.gitignore` к целевому виду.
- [ ] Убедиться, что `.env` не отслеживается.
- [ ] Удалить runtime-артефакты из дерева проекта.
- [ ] Проверить, что `README.md`, `docs/ARCHITECTURE.md`, `docs/STRUCTURE.md`, `docs/SERVICES.md` не противоречат реальности.
- [ ] Зафиксировать базовый `pytest` запуск и базовый coverage.

Definition of Done:

- репозиторий чистый
- секретов в Git нет
- базовый тестовый прогон воспроизводим

### Фаза 1. Структура, без сплитов

Цель:

- не дробя толстые файлы, довести проект до правильных сервисных границ

Чек-лист:

- [ ] Оставить физическую структуру `services/*`, `shared/*`, `docker/*`, `alembic/*` как канон.
- [ ] Убрать прямой DB access из `services/admin`.
- [ ] Перевести `admin` полностью на `backend_client`.
- [ ] Подготовить bot-facing API в `backend`.
- [ ] Перевести `bot` на `backend_client` для чтения и записи прикладных данных.
- [ ] Сохранить толстые файлы целиком, не дробить их на этой фазе.
- [ ] Убедиться, что cross-service imports идут только через `shared/*`.

Definition of Done:

- `bot` не импортирует DB access слой
- `admin` не импортирует DB access слой
- границы сервисов соблюдены без больших file-split

### Фаза 2. Разделение сервисов внутри и cleanup домена

Цель:

- разрезать самые тяжелые модули после стабилизации границ

Чек-лист:

- [ ] Разбить `services/backend/services/admin.py` на несколько сервисных модулей.
- [ ] Разбить `services/admin/routes.py` по функциональным группам.
- [ ] Разбить `services/bot/handlers/start.py`.
- [ ] Разбить `services/bot/handlers/text.py`.
- [ ] Разбить `services/bot/handlers/balance.py`.
- [ ] Разбить `shared/domain/credits.py` на submodules.
- [ ] Удалить `shared/db/database.py`, если bot полностью ушел с прямой БД.
- [ ] Выделить в worker отдельные runner/scheduler/dispatch блоки.

Definition of Done:

- не осталось архитектурно критичных god-files
- `shared/domain` и `services/*` стали локально тестируемыми кусками

### Фаза 3. `docker-compose` и операционалка

Цель:

- сделать compose финальной точкой входа

Чек-лист:

- [ ] Нормализовать `docker-compose.yml`.
- [ ] Добавить `docker-compose.dev.yml`.
- [ ] Добавить `docker-compose.prod.yml`, если нужен внешний Postgres.
- [ ] Проверить healthchecks.
- [ ] Проверить, что `backend` поднимает Alembic до uvicorn.
- [ ] Проверить, что `bot` не получает `DATABASE_URL`.
- [ ] Проверить, что `worker` использует тот же `BOT_TOKEN`.
- [ ] Подготовить smoke-команды для локального и прод-запуска.

Definition of Done:

- `docker compose up -d --build` поднимает рабочий стек
- compose-файлы понятны и не содержат исторических артефактов

### Фаза 4. Тесты 75%

Цель:

- довести проект до управляемой скорости изменений

Чек-лист:

- [ ] Включить `pytest --cov=shared --cov=services --cov-fail-under=75`.
- [ ] Выделить приоритетное покрытие для `shared/domain/credits.py`.
- [ ] Покрыть bot-facing API backend.
- [ ] Покрыть billing/payment flows.
- [ ] Покрыть worker job dispatch и retry behavior.
- [ ] Покрыть admin/backend integration contract.
- [ ] Зафиксировать smoke-test сценарий в CI.

Definition of Done:

- coverage gate 75% зеленый
- покрыты самые рискованные зоны, а не только вспомогательные модули

### Фаза 5. CD + smoke на проде

Цель:

- сделать deploy воспроизводимым и безопасным

Чек-лист:

- [ ] Добавить `.github/workflows/cd.yml`.
- [ ] Проверить SSH deploy path и права на сервере.
- [ ] Подготовить серверный `.env`.
- [ ] Выполнить ручной dry-run deploy из main.
- [ ] После deploy выполнять `docker compose ps`.
- [ ] После deploy выполнять smoke-check backend/admin/bot.
- [ ] Зафиксировать rollback-процедуру.

Definition of Done:

- push в `main` запускает тесты и деплой
- архитектурный smoke проходит после деплоя

---

## Приоритеты для исполнителя

Если нужно минимизировать риск, порядок приоритетов такой:

1. Сначала границы сервисов.
2. Потом отказ `bot` и `admin` от прямой БД.
3. Потом стабилизация `backend` как application boundary.
4. Потом file-split толстых модулей.
5. Потом CI/CD и coverage gate.

---

## Краткий вывод для архитектора

Проект уже прошел половину пути: контейнеры, `services/*`, `shared/*`, Alembic и отдельные Dockerfile уже есть. Главная проблема теперь не физическая структура, а незавершенная сервисная декомпозиция. Целевой план не в том, чтобы заново изобретать разбиение каталогов, а в том, чтобы:

- убрать прямую БД из `bot`
- убрать прямую БД из `admin`
- превратить `backend` в обязательную application boundary
- только после этого дробить толстые файлы

Именно такой порядок даст минимальный риск и максимальную управляемость для отдельного агента-исполнителя.
