# План исправления ошибок Telegram-бота

**Стек:** Python, aiogram 3.x.  
**Бот:** [краткое описание — например: бот с меню, командами и inline-кнопками].  
**Список ошибок для исправления:**

1. Бот не отвечает на команду `/start`.
2. Ошибка при обработке inline-кнопок.
3. Задержки при высокой нагрузке.

---

## 1. Анализ ошибок

| # | Ошибка | Возможные причины | Приоритет | Как проверить причину |
|---|--------|-------------------|-----------|------------------------|
| 1 | Бот не отвечает на `/start` | 1) Нет handler для `CommandStart()` или `Command("start")`. 2) Ошибка внутри handler (exception до `answer()`). 3) Неверный порядок роутеров (другой handler перехватывает). 4) Webhook не доходит / polling не запущен. 5) Токен бота неверный или отозван. | **High** | Логи при получении update; проверить регистрацию `@router.message(CommandStart())`; проверить webhook URL или `dp.start_polling()`. |
| 2 | Ошибка при обработке inline-кнопок | 1) Не вызван `callback.answer()` (Telegram показывает "часики"). 2) Exception в handler callback (например KeyError по `callback.data`). 3) Долгая операция без ответа (> ~30 сек) — Telegram отзывает callback. 4) Неверный формат `callback_data` (длина > 64 байт). 5) Race: один callback обработан дважды. | **High** | Логи при `callback_query`; тайминги; проверить вызов `cb.answer()` в начале или конце. |
| 3 | Задержки при высокой нагрузке | 1) Синхронные блокирующие вызовы в async-коде. 2) Нет rate limit — все запросы обрабатываются параллельно, перегрузка API/БД. 3) Долгие внешние вызовы без таймаута. 4) Один воркер/процесс — очередь растёт. 5) Утечка памяти или накопление задач. | **Medium** | Замерить latency под нагрузкой; проверить таймауты и concurrency; логи очередей. |

---

## 2. Предлагаемые фиксы

### 2.1 Бот не отвечает на `/start`

**Шаги по реализации:**

1. Убедиться, что handler зарегистрирован и подключён к Dispatcher.
2. Обернуть тело handler в try/except, логировать исключения, в ответ пользователю отдавать нейтральное сообщение.
3. Проверить, что перед этим handler нет роутера, который перехватывает все сообщения (например `F.text` без фильтра по команде).

**Пример кода (aiogram 3):**

```python
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
import structlog

router = Router()
log = structlog.get_logger()

@router.message(CommandStart())
async def cmd_start(message: Message):
    try:
        # Ваша логика: БД, меню и т.д.
        await message.answer(
            "Привет! Выбери действие:",
            reply_markup=main_menu_kb(),
        )
    except Exception as e:
        log.error("start_handler_error", user_id=message.from_user.id, error=str(e))
        await message.answer("Произошла ошибка. Попробуйте /start ещё раз.")
```

**Риски:** Слишком широкий `except` может скрывать ошибки — логировать полный traceback.  
**Альтернатива:** Глобальный `@dp.errors()` handler, который ловит необработанные исключения и отвечает пользователю + логирует.

---

### 2.2 Ошибка при обработке inline-кнопок

**Шаги по реализации:**

1. Всегда вызывать `callback.answer()` в течение ~30 сек (в начале handler или в конце перед return).
2. Парсить `callback.data` безопасно (split, проверка длины, whitelist).
3. Долгие операции выполнять после `answer()` или с `answer("Ожидайте...")` и затем обновлять сообщение.
4. Защита от гонок: lock по `user_id` (Redis) с TTL, чтобы один и тот же пользователь не обрабатывал два callback параллельно для критичных действий.

**Пример кода (aiogram 3):**

```python
from aiogram import Router, F
from aiogram.types import CallbackQuery
import structlog

router = Router()
log = structlog.get_logger()

@router.callback_query(F.data.startswith("action:"))
async def handle_action(callback: CallbackQuery):
    await callback.answer()  # Сразу снять "часики"
    try:
        parts = callback.data.split(":", 2)
        if len(parts) < 2:
            await callback.message.edit_text("Действие устарело. Нажми /start.")
            return
        action_id = parts[1]
        # Долгая работа — после answer(), обновлять сообщение
        await callback.message.edit_text("Обрабатываю...")
        # ... ваша логика ...
        await callback.message.edit_text("Готово.", reply_markup=...)
    except Exception as e:
        log.error("callback_error", data=callback.data, user_id=callback.from_user.id, error=str(e))
        try:
            await callback.message.edit_text("Ошибка. Попробуйте /start.")
        except Exception:
            pass
```

**Риски:** `edit_text` на уже изменённом сообщении даёт 400 — оборачивать в try/except.  
**Альтернатива:** Для устаревших callback — отдельный catch-all handler в конце: `await callback.answer("Сообщение устарело.", show_alert=True)`.

---

### 2.3 Задержки при высокой нагрузке

**Шаги по реализации:**

1. Ввести rate limit на пользователя (например 30–60 действий в минуту) — middleware, который считает запросы по `user_id` и возвращает «Подождите минуту» при превышении.
2. У всех внешних вызовов (HTTP, БД) задать таймауты (например 30 сек для LLM, 10 для БД).
3. Тяжёлые задачи выносить в очередь (Redis/RQ, Celery, arq) и отвечать пользователю по готовности.
4. Убедиться, что нет блокирующего кода в async-хендлерах (использовать `asyncio.to_thread()` для CPU-bound).

**Пример: rate limit middleware (aiogram 3):**

```python
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
import time

class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: int = 30, window_sec: int = 60):
        self.rate_limit = rate_limit
        self.window = window_sec
        self._counts: dict[int, list[float]] = {}

    async def __call__(self, handler, event: TelegramObject, data: dict):
        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id
        if not user_id:
            return await handler(event, data)
        now = time.monotonic()
        self._counts.setdefault(user_id, [])
        self._counts[user_id] = [t for t in self._counts[user_id] if now - t < self.window]
        if len(self._counts[user_id]) >= self.rate_limit:
            if isinstance(event, Message):
                await event.answer("Слишком много запросов. Подождите около минуты.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Подождите минуту.", show_alert=True)
            return
        self._counts[user_id].append(now)
        return await handler(event, data)
```

**Риски:** In-memory счётчик теряется при рестарте; для нескольких воркеров нужен Redis.  
**Альтернатива:** Redis + скользящее окно (LPUSH + LTRIM + TTL по ключу `ratelimit:{user_id}`).

---

## 3. Тестирование фиксов

| Ошибка | Шаги воспроизведения | Expected result | Тип теста |
|--------|------------------------|-----------------|-----------|
| /start не отвечает | Отправить боту `/start` в Telegram | В течение 5 сек приходит приветствие и меню/кнопки | Manual E2E |
| /start не отвечает | В тесте: создать Update с message.text="/start", вызвать handler | Вызван `message.answer()` с текстом, содержащим приветствие | Unit (mock Bot) |
| Inline-кнопки | Нажать любую inline-кнопку под сообщением бота | Часики исчезают, сообщение обновляется или приходит ответ; в логах нет exception | Manual E2E |
| Inline-кнопки | В тесте: эмулировать CallbackQuery с data="action:123", вызвать handler | Вызван `callback.answer()`, не выброшено исключение | Unit |
| Задержки | Отправить 40 сообщений подряд с интервалом 1 сек | Первые 30 обрабатываются, далее — «Подождите минуту»; бот не падает | Manual / load script |
| Задержки | В тесте: 50 вызовов middleware с одним user_id | После 30-го возврат без вызова handler | Unit |

**Пример unit-теста для /start (pytest + aiogram):**

```python
import pytest
from unittest.mock import AsyncMock
from aiogram.types import Message, User, Chat

@pytest.mark.asyncio
async def test_start_responds():
    from bot.handlers.start import cmd_start  # ваш модуль
    message = AsyncMock(spec=Message)
    message.from_user = User(id=123, is_bot=False, first_name="Test")
    message.answer = AsyncMock()
    message.text = "/start"
    await cmd_start(message)
    message.answer.assert_called_once()
    args = message.answer.call_args
    assert "привет" in args[0][0].lower() or "старт" in args[0][0].lower()
```

---

## 4. Профилактика будущих проблем

| Рекомендация | Реализация | Риск при отсутствии |
|--------------|------------|----------------------|
| **Логирование** | structlog/logging с уровнями; в каждом handler логировать `user_id`, `update_id`, действие; не логировать токены/пароли | Сложно воспроизвести баг в проде |
| **Глобальный error handler** | `@dp.errors()` — ловить все необработанные исключения, логировать, отвечать пользователю «Произошла ошибка. Попробуйте ещё раз.» | Любая необработанная ошибка — молчание бота или падение процесса |
| **Таймауты** | Для всех `httpx`, `aiohttp`, `asyncpg` и т.д. задавать `timeout=...`; для долгих операций — `asyncio.wait_for(..., timeout=30)` | Зависание при падении API |
| **Ретраи с backoff** | Для внешних API: 2–3 повтора с `asyncio.sleep(2**attempt)` при 5xx/RateLimit | Временные сбои воспринимаются как полный отказ |
| **Мониторинг** | Sentry (или аналог): `sentry_sdk.init(dsn=...)`, в error handler вызывать `sentry_sdk.capture_exception()` | Нет оповещений о новых ошибках в проде |
| **Healthcheck** | Эндпоинт или скрипт: проверка БД (SELECT 1), Redis (PING), при необходимости — проверка токена бота (getMe) | Не замечают падение сервиса до жалоб пользователей |

**Пример глобального error handler (aiogram 3):**

```python
from aiogram.types import ErrorEvent

@dp.errors()
async def global_error_handler(event: ErrorEvent):
    log.error("unhandled_error", error=str(event.exception), update=event.update)
    if event.update and event.update.message:
        await event.update.message.answer("Произошла ошибка. Попробуйте /start.")
    elif event.update and event.update.callback_query:
        try:
            await event.update.callback_query.answer("Ошибка. Попробуйте ещё раз.", show_alert=True)
        except Exception:
            pass
```

---

## 5. Влияние на производительность и безопасность

| Фикс | Влияние на производительность | Влияние на безопасность |
|------|-------------------------------|---------------------------|
| Обработка /start + try/except | Минимальное; логирование добавляет микросекунды | Снижение риска: пользователь не видит стектрейсы; в логах не должны попадать секреты |
| Inline: answer() + безопасный разбор data | answer() снижает «часики» и жалобы; разбор по whitelist — меньше лишних вызовов | Защита от инъекции в callback_data (не выполнять eval/exec по data) |
| Rate limit | Снижение пиковой нагрузки на API и БД; часть запросов не обрабатывается (ожидание) | Защита от флуда и злоупотреблений |
| Таймауты и очереди | Меньше «висящих» соединений; очередь может добавить задержку до ответа, но стабилизирует систему | Таймауты ограничивают DoS через медленные ответы внешних сервисов |

**Рекомендация:** Логировать метрики (latency по типам действий, количество rate-limited запросов) для последующей настройки лимитов и таймаутов.

---

## 6. Инструменты и ресурсы

| Инструмент | Назначение |
|------------|------------|
| **Telegram Bot API** | [core.telegram.org/bots/api](https://core.telegram.org/bots/api) — лимиты (30 msg/sec в чат, 64 байта callback_data), форматы update. |
| **getUpdates в браузере** | При polling — смотреть, что бот получает (временно логировать update_id и type). |
| **PyCharm / VS Code debugger** | Точки останова в handler при воспроизведении через тест или при ручной отправке сообщения. |
| **Postman / curl** | Для webhook: отправка POST на URL webhook с телом `update` (JSON) — проверка без Telegram. |
| **pytest + pytest-asyncio** | Unit- и интеграционные тесты; моки `Bot`, `Update`, `Message`, `CallbackQuery`. |
| **structlog / logging** | Единый формат логов (JSON в проде); фильтр по `user_id`, `update_id` для поиска по сессии. |
| **Sentry** | Автоматический сбор исключений, группировка, алерты. |

**Проверка webhook (curl):**

```bash
curl -X POST "https://your-server.com/webhook" \
  -H "Content-Type: application/json" \
  -d '{"update_id":1,"message":{"message_id":1,"from":{"id":123,"first_name":"Test"},"chat":{"id":123,"type":"private"},"date":1234567890,"text":"/start"}}'
```

**Риски:** При смене с polling на webhook нужно вызвать `deleteWebhook` и установить новый URL; иначе апдейты могут не доходить.

---

## Чек-лист перед выкатом фиксов

- [ ] Все затронутые handlers покрыты try/except или глобальным error handler.
- [ ] Для callback везде вызывается `callback.answer()`.
- [ ] Включён rate limit и заданы таймауты на внешние вызовы.
- [ ] Добавлены/обновлены тесты (unit или E2E) для воспроизведения багов.
- [ ] В логах нет вывода токенов и паролей.
- [ ] Проверка на реальном боте: /start, 2–3 inline-кнопки, 10 сообщений подряд (ожидаемый rate limit).
