# НейроБокс

Telegram-бот для текста, картинок, документов и транскрибации. Внутри Telegram бот работает в честном stable-режиме: опубликованы только живые функции, а отключённые модули скрываются фичефлагами.

**Текущий production-режим:**
- текст через OpenRouter
- картинки через OpenRouter
- документы и суммаризация
- транскрибация голосовых, аудио и кружков
- оплата внутри Telegram через Stars
- risky-модули `video / music / tts` выключаются флагами, пока провайдеры не подтверждены live

## Быстрый старт

### Docker

```bash
cp .env.example .env
# заполни обязательные переменные

docker compose up -d --build

docker compose ps
docker compose logs bot --tail 50
```

### Локально без Docker

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m bot.db.migrate
python -m bot.main
```

Нужны PostgreSQL 16 и Redis.

## Обязательные env

| Переменная | Описание |
|---|---|
| `BOT_TOKEN` | токен бота от BotFather |
| `BOT_USERNAME` | username бота без `@` |
| `POSTGRES_PASSWORD` | пароль PostgreSQL |
| `REDIS_PASSWORD` | пароль Redis |
| `OPENROUTER_API_KEY` | основной AI-провайдер для текста/STT/изображений |
| `ADMIN_PANEL_SECRET` | обязательный секрет для Flask admin session |
| `ADMIN_PANEL_PASSWORD` | пароль входа в веб-админку |
| `ADMIN_API_SECRET_KEY` | Bearer-token для admin API |

## Опциональные env и фичефлаги

- `SERPER_API_KEY` — веб-поиск
- `FALAI_API_KEY` — только если включаешь `ENABLE_VIDEO=true` или `ENABLE_MUSIC=true`
- `OPENAI_API_KEY` — только если включаешь `ENABLE_TTS=true`
- `ENABLE_VIDEO=false`
- `ENABLE_MUSIC=false`
- `ENABLE_TTS=false`
- `ENABLE_STARS_PAYMENT=true`
- `ENABLE_YOOKASSA_PAYMENT=false`
- `ENABLE_CRYPTOBOT_PAYMENT=false`
- `QA_TESTER_IDS=` — список Telegram ID без списания CR для QA
- `LEGAL_BASE_URL=` — публичные `/privacy` и `/terms`

Полный список переменных — в `.env.example`.

## Тесты

```bash
docker compose exec bot pytest -q
docker compose exec bot python /app/scripts/smoke_user_flow.py
docker compose exec bot python /app/scripts/smoke_user_flow.py --with-contract-tests
```

## Деплой

```bash
cd /opt/neurobox
docker compose up -d --build
docker compose restart bot worker webhook admin api
```

Если менялся только Python-код, обычно достаточно `docker compose restart ...` без rebuild.
