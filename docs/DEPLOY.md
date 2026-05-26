# Деплой NeuroBox

## Требования

- Сервер: Ubuntu, Docker + Docker Compose v2
- Nginx на хосте (проксирует 8091 и 8092)
- `.env` файл на сервере: `/opt/neurobox/.env`

## Структура Docker

| Сервис | Dockerfile | Порт | Resources |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | internal | — |
| `redis` | `redis:7-alpine` | internal | — |
| `backend` | `docker/backend.Dockerfile` | 127.0.0.1:8092 | 512M |
| `bot` | `docker/bot.Dockerfile` | internal | 384M |
| `worker` | `docker/worker.Dockerfile` | internal | 512M |
| `admin` | `docker/admin.Dockerfile` | 127.0.0.1:8091 | 256M |

`bot` и `admin` не имеют `DATABASE_URL` — не ходят в БД напрямую.

## Деплой (ручной)

```bash
# 1. Бэкап БД (на сервере)
docker compose exec postgres pg_dump -U neurobox neurobox > backup-$(date +%Y%m%d).sql

# 2. Синхронизация кода (с локальной машины)
rsync -az --delete \
  --exclude='.env' \
  --exclude='backups' \
  --exclude='logs' \
  --exclude='.venv' \
  ./ user@host:/opt/neurobox/

# 3. Пересборка и перезапуск (на сервере)
cd /opt/neurobox
docker compose up -d --build --remove-orphans
docker image prune -f
```

## Первый запуск на чистом сервере

```bash
# Сервер должен иметь .env с реальными секретами
cp .env.example .env
# ... заполнить .env ...

docker compose up -d --build
docker compose logs -f backend  # ждём "alembic upgrade head" + "uvicorn started"
```

## Проверка после деплоя (smoke)

```bash
docker compose ps                          # все healthy
docker compose logs --tail 50 backend     # Alembic applied, uvicorn listening
docker compose logs --tail 50 worker      # worker_ready_polling_queue
docker compose logs --tail 50 bot         # Bot ready

# Функциональная проверка
curl http://127.0.0.1:8092/health         # {"ok": true}
# В Telegram: /start → ответ, /balance → ответ
```

## Entrypoints

**backend.sh**:
```bash
alembic upgrade head
exec uvicorn services.backend.main:app --host 0.0.0.0 --port 8092
```

**bot.sh**: `python -m services.bot.main`  
**worker.sh**: `python -m services.worker.main`  
**admin.sh**: `flask --app services.admin.app run --host 0.0.0.0 --port 8091`

## Переменные окружения (обязательные)

```bash
BOT_TOKEN=                   # токен Telegram бота
POSTGRES_DB=neurobox
POSTGRES_USER=neurobox
POSTGRES_PASSWORD=           # сильный пароль
REDIS_PASSWORD=              # сильный пароль
ADMIN_API_SECRET_KEY=        # 32+ байт случайной строки
ADMIN_PANEL_USER=admin
ADMIN_PANEL_PASSWORD=        # пароль веб-админки
ADMIN_PANEL_SECRET=          # 32+ байт для Flask-сессий
DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
```

Остальные переменные — опциональные. Полный список: `.env.example`.

## Nginx (пример конфига)

```nginx
# /etc/nginx/sites-enabled/neurobox-admin
server {
    listen 443 ssl;
    server_name admin.yourdomain.com;
    
    location / {
        proxy_pass http://127.0.0.1:8091;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}

server {
    listen 443 ssl;
    server_name api.yourdomain.com;
    
    location / {
        proxy_pass http://127.0.0.1:8092;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

## Troubleshooting

**backend не стартует** — смотреть `docker compose logs backend`: Alembic мог не найти БД. Проверить `DATABASE_URL` и что postgres healthy.

**bot FSM не работает** — смотреть `docker compose logs bot`: "Redis FSM unavailable, using MemoryStorage". Проверить `REDIS_URL` и что redis healthy.

**Worker не обрабатывает задачи** — `docker compose logs worker`: должно быть `worker_ready_polling_queue`. Dead-letter queue: `redis-cli LRANGE neurobox:tasks:dlq 0 -1`.

**Alembic: "Table already exists"** — миграция уже применена. Проверить: `alembic current`.
