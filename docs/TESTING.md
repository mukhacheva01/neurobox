# Тестирование NeuroBox

## Стек

- **pytest** 8.x
- **pytest-asyncio** 0.24 (`asyncio_mode = auto` в `pyproject.toml` / `pytest.ini`)
- **pytest-cov** — покрытие
- **unittest.mock** — `MagicMock`, `AsyncMock`, `patch`

## Запуск

```bash
# Активировать venv
source .venv/bin/activate

# Все тесты
pytest tests/ -q

# С покрытием (требование: ≥75%)
pytest tests/ -q --cov=shared --cov=services --cov-fail-under=75

# Только конкретный модуль
pytest tests/backend/ -q
pytest tests/worker/test_jobs.py -q

# С подробным выводом
pytest tests/ -v --no-header
```

Текущее покрытие: **75.27%** (1451 тест, все зелёные).

## Структура тестов

```
tests/
├── conftest.py                      # sys.path + BOT_TOKEN=0:test_token_for_pytest
├── shared/
│   ├── test_credits.py              # shared/domain/credits.py (~60 тестов)
│   ├── test_yookassa.py             # shared/domain/yookassa.py
│   ├── test_redis_and_domain.py     # redis store, telemetry, analytics
│   ├── test_providers.py            # AI providers
│   └── test_admin_access.py        # admin access control
├── backend/
│   ├── test_admin_service.py        # services/backend/services/admin.py (~135 тестов)
│   └── test_backend.py             # роуты, deps, схемы
├── worker/
│   ├── test_jobs.py                 # worker jobs + telegram singleton (~22 теста)
│   └── test_worker_main.py         # worker main loop
├── bot/
│   ├── test_start_balance.py        # handlers/start.py, handlers/balance.py
│   ├── test_small_handlers.py       # мелкие хендлеры
│   ├── test_misc_handlers.py        # прочие хендлеры
│   ├── test_keyboards_middlewares.py
│   └── test_admin_handlers.py      # admin-хендлеры
├── admin/
│   └── test_routes.py               # Flask routes
└── test_*.py                        # smoke, contract, cross-cutting
    ├── test_smoke_release.py        # smoke: все модули импортируются
    ├── test_config.py               # settings, env-переменные
    ├── test_ban_check.py            # middleware ban check
    ├── test_audit.py                # audit logging
    ├── test_model_registry_consistency.py
    └── ...
```

## Паттерны мокирования

### 1. SQLAlchemy session (backend и worker тесты)

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

def _make_mock_session(scalar=0, fetchrow=None, fetch=None):
    session = AsyncMock()
    result = _make_mock_result(scalar=scalar, first=fetchrow, all_rows=fetch or [])
    session.execute = AsyncMock(return_value=result)
    return session

def _patch_session(mock_session):
    @asynccontextmanager
    async def _fake_get_session():
        yield mock_session
    # Важно: патчить в namespace модуля, где импортирован get_session
    return patch("services.backend.services.admin.get_session", _fake_get_session)

# Использование:
async def test_something():
    session = _make_mock_session(scalar=42)
    with _patch_session(session):
        result = await admin_service.get_something()
    assert result == 42
```

Для worker-тестов путь патча: `shared.db.session.get_session`.

### 2. Несколько последовательных запросов

```python
async def test_multi_query():
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        _make_mock_result(scalar=10),        # первый execute → scalar
        _make_mock_result(first={"key": 1}), # второй execute → mappings().first()
        _make_mock_result(all_rows=[...]),   # третий execute → mappings().all()
    ])
    with _patch_session(session):
        await handle({})
```

### 3. Telegram Bot mock

```python
mock_bot = AsyncMock()
mock_bot.send_message = AsyncMock()

# Или через patch:
with patch("services.worker.telegram.get_bot", return_value=mock_bot):
    await notify.handle({"user_id": 123, "text": "hi"}, bot=mock_bot)
```

### 4. Redis mock

```python
mock_redis = AsyncMock()
mock_redis.rpush = AsyncMock(return_value=1)

from shared.queue.client import enqueue
await enqueue(mock_redis, "notify", {"user_id": 1, "text": "hi"})
mock_redis.rpush.assert_called_once()
```

### 5. httpx mock

```python
mock_response = MagicMock()
mock_response.status_code = 200

mock_client = AsyncMock()
mock_client.post = AsyncMock(return_value=mock_response)
mock_client.__aenter__ = AsyncMock(return_value=mock_client)
mock_client.__aexit__ = AsyncMock(return_value=False)

with patch("httpx.AsyncClient", return_value=mock_client):
    await handle({"user_id": 123, "text": "Test"})
```

## conftest.py

`tests/conftest.py` делает три вещи:
1. Добавляет корень проекта в `sys.path`
2. Загружает `.env` если существует (для запуска с реальными секретами)
3. Устанавливает `BOT_TOKEN=0:test_token_for_pytest` — минимум для `Settings()`

Нет фикстур для реальной БД. Все тесты работают с mock-объектами — реальная БД не нужна.

## Async тесты

`asyncio_mode = auto` означает, что все `async def test_*` автоматически запускаются как asyncio-тесты. Не нужен `@pytest.mark.asyncio`.

```python
async def test_something():
    result = await some_async_function()
    assert result == expected
```

## Что не тестируется (осознанно)

- **services/bot/** хендлеры с реальным aiogram — только unit-тесты с mock
- **Реальная БД** — нет интеграционных тестов с Postgres
- **Docker** — нет container-level тестов
- Smoke-тест с реальным ботом: `scripts/smoke_user_flow.py` (запускается вручную)

## Добавление нового теста

1. Определить нужный namespace для патча: если в `services/backend/services/admin.py` есть `from shared.db.session import get_session`, то патчить нужно `services.backend.services.admin.get_session`, а не `shared.db.session.get_session`.
2. Для worker-модулей: `shared.db.session.get_session` (они импортируют через полный путь).
3. Использовать `_make_mock_result` / `_make_mock_session` из соответствующего тест-файла.
4. Для `side_effect` с несколькими вызовами — строго считать количество `session.execute` вызовов в тестируемой функции.
