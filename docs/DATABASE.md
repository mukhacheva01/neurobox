# База данных NeuroBox

## Стек

- PostgreSQL 16
- SQLAlchemy 2 async (`sqlalchemy[asyncio]` + `asyncpg`)
- Alembic 1.16 — управление миграциями

## Подключение

```python
# shared/db/session.py
from shared.config import settings

engine = create_async_engine(settings.database_url, pool_size=5, max_overflow=10)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            yield session
        # коммит при чистом выходе, rollback при исключении
```

Переменная окружения: `DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/neurobox`

## Схема таблиц

### users
Основная таблица пользователей (PK = Telegram user_id).

| Колонка | Тип | Описание |
|---|---|---|
| `id` | BIGINT PK | Telegram user ID |
| `username` | VARCHAR(255) | @username |
| `first_name` | VARCHAR(255) | имя |
| `referral_code` | VARCHAR(64) UNIQUE | код для приглашений |
| `referred_by` | BIGINT | user_id пригласившего |
| `referral_count` | INT | кол-во приглашённых |
| `credits_bought` | INT | купленные кредиты (остаток) |
| `credits_free_today` | INT | бесплатные кредиты на сегодня |
| `credits_free_reset` | DATE | дата последнего сброса free-кредитов |
| `credits_total_spent` | INT | всего потрачено кредитов |
| `unlimited_ends_at` | TIMESTAMPTZ | окончание безлимитного доступа |
| `full_access_48h_ends_at` | TIMESTAMPTZ | окончание 48ч-доступа |
| `trial_started_at` | TIMESTAMPTZ | начало триального периода |
| `onboarded` | BOOL | прошёл онбординг |
| `is_blocked` | BOOL | заблокирован администратором |
| `text_model` | VARCHAR(128) | выбранная текстовая модель |
| `image_model` | VARCHAR(128) | выбранная модель изображений |
| `tts_model` | VARCHAR(128) | выбранная TTS-модель |
| `tts_voice` | VARCHAR(128) | выбранный голос TTS |
| `video_model` | VARCHAR(128) | выбранная видео-модель |
| `music_model` | VARCHAR(128) | выбранная музыкальная модель |
| `last_daily_bonus_date` | DATE | дата последнего дневного бонуса |
| `login_streak` | INT | серия дней входа |
| `last_active_at` | TIMESTAMPTZ | последняя активность |
| `total_payments_rub` | NUMERIC(14,2) | всего оплачено рублей |
| `first_paid_at` | TIMESTAMPTZ | дата первой оплаты |
| `last_paid_at` | TIMESTAMPTZ | дата последней оплаты |
| `created_at` | TIMESTAMPTZ | регистрация |
| `updated_at` | TIMESTAMPTZ | last update (onupdate=now()) |

### payments
Записи платежей.

| Колонка | Тип | Описание |
|---|---|---|
| `id` | INT PK | |
| `user_id` | BIGINT INDEX | FK → users.id |
| `payment_id` | VARCHAR(128) UNIQUE | ID платежа у провайдера |
| `amount_rub` | NUMERIC(12,2) | сумма в рублях |
| `credits_amount` | INT | кредиты за платёж |
| `pack_name` | VARCHAR(128) | название тарифа |
| `status` | VARCHAR(32) | `pending` / `succeeded` / `canceled` / `refunded` |
| `created_at` | TIMESTAMPTZ | |
| `confirmed_at` | TIMESTAMPTZ | |
| `canceled_at` | TIMESTAMPTZ | |
| `refunded_at` | TIMESTAMPTZ | |
| `payment_method` | VARCHAR(64) | `yookassa` / `stars` / `cryptobot` |
| `idempotency_key` | VARCHAR(128) UNIQUE | защита от дублирования |

### credit_transactions
Лог списаний и пополнений кредитов.

| Колонка | Тип | Описание |
|---|---|---|
| `id` | INT PK | |
| `user_id` | BIGINT INDEX | |
| `amount` | INT | сумма (отрицательная = списание) |
| `credits_bought_after` | INT | купленных кредитов после операции |
| `credits_free_after` | INT | бесплатных кредитов после операции |
| `type` | VARCHAR(32) | `spend` / `purchase` / `bonus` / `refund` / `promo` |
| `description` | VARCHAR(500) | описание |
| `model` | VARCHAR(128) | AI-модель (для spend) |
| `task_type` | VARCHAR(64) | тип задачи |
| `created_at` | TIMESTAMPTZ | |

### ai_requests
Телеметрия AI-запросов.

| Колонка | Тип | Описание |
|---|---|---|
| `id` | INT PK | |
| `user_id` | BIGINT INDEX | |
| `task_type` | VARCHAR(64) | `text` / `image` / `video` / `tts` / `stt` / `music` |
| `model` | VARCHAR(128) | название модели |
| `prompt` | VARCHAR(200) | первые 200 символов промпта |
| `status` | VARCHAR(32) | `completed` / `error` / `cancelled` |
| `credits_charged` | INT | списано кредитов |
| `duration_ms` | INT | время выполнения |
| `error_message` | VARCHAR(500) | сообщение об ошибке |
| `cost_usd` | NUMERIC(16,6) | стоимость в USD (от провайдера) |
| `started_at` | TIMESTAMPTZ | |

### events
Аналитические события (funnel, действия пользователей).

| Колонка | Тип | Описание |
|---|---|---|
| `id` | INT PK | |
| `event_name` | VARCHAR(128) INDEX | `bot_start` / `paywall_hit` / `purchase` … |
| `user_id` | BIGINT INDEX | |
| `properties` | JSONB | произвольные параметры события |
| `created_at` | TIMESTAMPTZ | |

### daily_stats
Агрегированная ежедневная статистика (key-value схема).

| Колонка | Тип | Описание |
|---|---|---|
| `id` | INT PK | |
| `date` | DATE | |
| `metric` | VARCHAR(128) | имя метрики |
| `value` | NUMERIC(16,4) | значение |
| `meta` | JSONB | доп. данные |

Уникальный constraint: `(date, metric)`. Пример метрик: `new_users`, `revenue_rub`, `ai_requests`, `funnel_start_users`, `funnel_purchase_users` и др.

### admin_audit_log
Лог действий администраторов.

| Колонка | Тип | Описание |
|---|---|---|
| `id` | INT PK | |
| `action` | VARCHAR(256) | название действия |
| `admin_user` | VARCHAR(128) | логин администратора |
| `target` | VARCHAR(256) | объект действия |
| `details` | JSONB | детали |
| `created_at` | TIMESTAMPTZ | |

### error_logs
Лог ошибок приложения.

| Колонка | Тип | Описание |
|---|---|---|
| `id` | INT PK | |
| `level` | VARCHAR(32) INDEX | `ERROR` / `WARNING` |
| `message` | TEXT | |
| `user_id` | BIGINT | если ошибка контекстная |
| `count` | INT | счётчик повторений |
| `created_at` | TIMESTAMPTZ | |

### response_ratings
Оценки ответов AI.

| Колонка | Тип | Описание |
|---|---|---|
| `id` | INT PK | |
| `user_id` | BIGINT INDEX | |
| `message_id` | INT | Telegram message_id |
| `rating` | VARCHAR(16) | `like` / `dislike` |
| `task_type` | VARCHAR(64) | |
| `model` | VARCHAR(128) | |
| `created_at` | TIMESTAMPTZ | |

### promocodes / promo_uses
Промокоды и история их использования.

`promocodes`: `id`, `code` UNIQUE, `credits`, `max_uses`, `used_count`, `expires_at`, `created_at`

`promo_uses`: составной PK `(user_id, code)`, `created_at` — каждый пользователь может использовать код один раз.

### billing_plans
Тарифные планы (хранятся в БД, синхронизируются при старте).

| Колонка | Тип | Описание |
|---|---|---|
| `id` | INT PK | |
| `plan_key` | VARCHAR(128) UNIQUE | `starter_100`, `unlimited_30d` … |
| `label` | VARCHAR(256) | отображаемое название |
| `credits` | INT | количество кредитов |
| `price_rub` | NUMERIC(12,2) | цена в рублях |
| `price_stars` | INT | цена в Telegram Stars |
| `price_usd` | NUMERIC(12,2) | цена в USD |
| `is_unlimited` | BOOL | безлимитный тариф |
| `period_days` | INT | срок действия (для unlimited) |
| `enabled` / `is_active` | BOOL | показывать / доступен |
| `sort_order` | INT | порядок отображения |

### user_notes
Заметки администраторов о пользователях.

`id`, `user_id` INDEX, `note` TEXT, `admin_user`, `created_at`

## Репозитории

Все запросы к БД в backend и worker идут через `shared/db/session.get_session()`.

```python
# Паттерн использования
async with get_session() as session:
    result = await session.execute(text("SELECT ..."), {"param": value})
    row = result.mappings().first()   # одна строка → dict-like
    rows = result.mappings().all()    # все строки → list[dict-like]
    scalar = result.scalar()          # одно значение
```

`BaseRepository[T]` в `shared/db/repositories/base.py` предоставляет типизированные методы:
- `get(id)` — по первичному ключу
- `get_by(field, value)` — по произвольному полю
- `list(**filters)` — с фильтрами
- `create(**data)` → объект с flush+refresh
- `update(id, **data)` → обновление полей
- `delete(id)` → bool

## Миграции

Единственная миграция: `alembic/versions/278eb10ce51b_initial_schema.py`

Создаёт все 13 таблиц с нуля. Запускается автоматически в entrypoint backend-контейнера:

```bash
alembic upgrade head
```

Для добавления новой таблицы/колонки:
1. Добавить модель в `shared/db/models/`
2. Создать новую миграцию: `alembic revision --autogenerate -m "add_feature"`
3. Проверить файл в `alembic/versions/`
4. `alembic upgrade head` (локально и на проде через entrypoint)
