# Гайд для нового агента — NeuroBox

Прочитай этот файл перед любой работой над проектом. Он даёт полный контекст.

## Что это

NeuroBox — Telegram-бот с AI-функциями. Python 3.12, aiogram 3, FastAPI, Flask, SQLAlchemy 2 async, PostgreSQL, Redis. Развёрнут в Docker (6 контейнеров).

## Ключевые ограничения (не нарушать)

- **Git не используется.** Нет веток, коммитов, PR. Нет CI/CD.
- **Деплой**: rsync на сервер → `docker compose up -d --build`. Ручной.
- **Секреты** только в `.env` на сервере. В коде секретов нет.
- **Алembic** — единственный способ менять схему БД. Raw SQL-файлов нет.
- **Кросс-импорты между сервисами запрещены**: `services/bot` не импортирует из `services/worker` и наоборот. Общее — только `shared/`.

## Как устроен проект

```
shared/      ← общий код (config, db, domain, providers, redis, queue)
services/
  bot/       ← aiogram Telegram бот (polling)
  backend/   ← FastAPI REST API (порт 8092) + YooKassa webhook
  worker/    ← фоновый воркер (Redis BLPOP)
  admin/     ← Flask веб-админка (порт 8091)
tests/       ← pytest тесты (75%+ покрытие)
alembic/     ← миграции БД
docker/      ← Dockerfiles + entrypoints
docs/        ← документация (ты читаешь её)
```

Детали → `docs/STRUCTURE.md`.

## Важнейшие файлы

| Файл | Зачем |
|---|---|
| `shared/config/settings.py` | все env-переменные, feature flags, лимиты |
| `shared/db/session.py` | `get_session()` — asynccontextmanager для SQLAlchemy |
| `shared/db/models/` | ORM-модели всех 13 таблиц |
| `shared/domain/credits.py` | вся логика кредитов (~700 строк) |
| `services/bot/main.py` | точка входа бота, регистрация хендлеров |
| `services/backend/main.py` | FastAPI app |
| `services/backend/services/admin.py` | бизнес-логика admin API (~900 строк) |
| `services/worker/main.py` | цикл воркера + dispatch задач |
| `alembic/versions/278eb10ce51b_initial_schema.py` | единственная миграция |

## Как работать с БД

Используй `get_session()` из `shared/db/session.py`:

```python
from sqlalchemy import text
from shared.db.session import get_session

async with get_session() as session:
    result = await session.execute(text("SELECT id FROM users WHERE id = :uid"), {"uid": user_id})
    row = result.mappings().first()    # dict-like или None
    rows = result.mappings().all()     # list[dict-like]
    val = result.scalar()             # одно значение
```

Параметры — именованные (`:param_name`), не позиционные (`$1`).

Репозитории (`shared/db/repositories/`) для CRUD-операций:
```python
from shared.db.repositories.user import UserRepository
repo = UserRepository(session)
user = await repo.get(user_id)
```

## Как писать тесты

Все тесты — без реальной БД. Мокируем `get_session()`:

```python
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

def _make_mock_result(scalar=0, first=None, all_rows=None):
    result = MagicMock()
    result.scalar = MagicMock(return_value=scalar)
    mappings = MagicMock()
    mappings.first = MagicMock(return_value=first)
    mappings.all = MagicMock(return_value=list(all_rows or []))
    result.mappings = MagicMock(return_value=mappings)
    return result

def _patch_session(mock_session, module_path="services.backend.services.admin"):
    @asynccontextmanager
    async def _fake():
        yield mock_session
    return patch(f"{module_path}.get_session", _fake)
```

`asyncio_mode = auto` → все `async def test_*` запускаются автоматически.  
Подробнее → `docs/TESTING.md`.

## Таблицы БД (краткий список)

`users`, `payments`, `credit_transactions`, `ai_requests`, `events`, `admin_audit_log`, `error_logs`, `response_ratings`, `daily_stats`, `billing_plans`, `promocodes`, `promo_uses`, `user_notes`

Детальная схема → `docs/DATABASE.md`.

## Worker задачи

Задачи в Redis-очереди `neurobox:tasks`. Формат:
```json
{"type": "notify", "payload": {"user_id": 123, "text": "msg"}}
```

Типы: `notify`, `video_generate`, `daily_stats`, `metrics_alert`.  
DLQ: `neurobox:tasks:dlq` (после 3 неудачных попыток).

## Backend API

REST API на порту 8092. Аутентификация: `Authorization: Bearer <HMAC-token>`.  
Токен выдаётся через `POST /api/v1/admin/login`.

Endpoint'ы → `docs/SERVICES.md` раздел backend.

## Feature flags

Включаются в `.env`:
- `ENABLE_VIDEO=true` — видео-генерация
- `ENABLE_MUSIC=true` — музыка
- `ENABLE_TTS=true` — TTS
- `ENABLE_YOOKASSA_PAYMENT=true` — рублёвые платежи
- `ENABLE_STARS_PAYMENT=true` — Telegram Stars (по умолч. включено)

## Запуск тестов

```bash
source .venv/bin/activate
pytest tests/ -q --cov=shared --cov=services --cov-fail-under=75
```

## Что сделано, что нет

**Готово:**
- Вся инфраструктура Docker (4 Dockerfile + docker-compose.yml)
- SQLAlchemy 2 async (backend + worker полностью на ORM)
- Alembic миграция (создаёт все 13 таблиц)
- Тесты: 1451, покрытие 75.27%

**Не готово (будущие инициативы):**
- `services/bot/` всё ещё использует `shared.db.database` (asyncpg pool напрямую) — полный переход на httpx к backend требует ~20 новых API endpoint'ов
- `services/admin/routes.py` — ещё не полностью использует `backend_client`
- Нет CI/CD (осознанное решение)

## Ссылки на документацию

- `docs/ARCHITECTURE.md` — граф сервисов, потоки данных
- `docs/STRUCTURE.md` — полное дерево каталогов
- `docs/SERVICES.md` — детали каждого сервиса и API
- `docs/DATABASE.md` — схема таблиц, репозитории, миграции
- `docs/TESTING.md` — как писать и запускать тесты
- `docs/DEPLOY.md` — деплой на прод
