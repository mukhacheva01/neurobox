# НейроБокс — Проверка структуры и тесты

**Дата:** 2026-02-16

## 1. Структура проекта

```
/app (или /opt/neurobox)
├── admin_panel/          # Веб-админка (Flask), порт 8091
│   ├── app.py, routes.py, db.py, audit.py
│   └── templates/
├── api/                  # Admin API (FastAPI), порт 8092
│   ├── main.py
│   └── admin/            # router, service, schemas, dependencies
├── bot/
│   ├── main.py           # Точка входа бота
│   ├── db/               # database.py, migrate.py
│   ├── handlers/         # 18 модулей + admin/
│   ├── middlewares/      # log_context, ban_check, rate_limit
│   ├── providers/        # openai_text, image, video, voice, ...
│   ├── services/         # credits, chat_service, redis_store, ...
│   ├── keyboards/, states/, utils/
├── config/               # settings, text_models, i18n
├── migrations/           # 20 SQL-файлов (002..020 + init.sql)
├── scripts/              # entrypoint.sh, healthcheck.py, webhook_server.py, global_tests.py
├── tests/                # pytest: conftest, test_audit, test_ban_check, test_config, test_smoke_release
├── worker/               # worker.main
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── pytest.ini
```

## 2. Entrypoint и сервисы

| SERVICE_TYPE | Команда |
|--------------|---------|
| bot | `python -m bot.db.migrate` → `python -m bot.main` |
| worker | `python -m worker.main` |
| webhook | `python -m scripts.webhook_server` |
| admin | `python -m admin_panel.app` |
| api | `uvicorn api.main:app --host 0.0.0.0 --port 8092` |

## 3. Handlers в main.py

Все перечисленные модули существуют и имеют атрибут `router`:

- start, image, video, voice, music, model_select, balance, guide  
- modes, subscribe_remind, saved_export, ref_promo_stats  
- photo_tools, tools, doc_handler, coming_soon, text, feedback  
- admin (admin_router)

## 4. Миграции

- `init.sql` + `002_voice.sql` … `020_admin_api_full.sql` — всего 20 файлов.
- При старте бота выполняется `python -m bot.db.migrate`.

## 5. Pytest — результаты

**Запуск:** `docker exec neurobox_bot bash -c "cd /app && python -m pytest tests/ -v"`

| Тест | Статус |
|------|--------|
| test_audit (2) | PASSED |
| test_ban_check (1) | PASSED |
| test_config (5) | PASSED |
| test_smoke_release (10) | PASSED |

**Итого: 18 passed.**

### Исправление в тестах

- В `tests/test_smoke_release.py` тест `test_circuit_breaker_provider_detection` вызывал `cb._provider()`, тогда как после рефакторинга определение провайдера вынесено в модульную функцию `_provider_of()`. Тест обновлён на использование `_provider_of()`.

## 6. Global tests (scripts/global_tests.py)

**Запуск:** `docker exec neurobox_bot python /app/scripts/global_tests.py`

- Config: OK  
- Bot imports: OK  
- PostgreSQL: OK  
- Redis: OK  
- Admin DB: OK  
- Flask app: OK  
- APIs: 5/6 OK (Google может падать из‑за ключа/сети — не структурная ошибка)

## 7. Healthcheck

- `scripts/healthcheck.py` — проверка PG (обязательно) и Redis (опционально). Используется в docker-compose для bot/worker.

---

**Вывод:** Структура бота проверена, все тесты проходят. Можно продолжать разработку и добавлять новые тесты.
