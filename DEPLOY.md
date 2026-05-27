# НейроБокс — деплой

## Базовый сценарий

```bash
cd /opt/neurobox
cp .env.example .env
# заполнить env

docker compose up -d --build
docker compose ps
```

Если на сервер уже залит код и менялись только Python-файлы:

```bash
cd /opt/neurobox
docker compose up -d --build --remove-orphans
docker compose ps
```

## GitHub Actions CD

Фаза 5 использует `.github/workflows/cd.yml`.

Нужные secrets в GitHub:

- `SSH_HOST`
- `SSH_PORT`
- `SSH_USER`
- `SSH_PRIVATE_KEY`
- `DEPLOY_PATH`

Что должно быть подготовлено на сервере до первого запуска CD:

- существует директория из `DEPLOY_PATH`
- у `SSH_USER` есть права на запись в `DEPLOY_PATH`
- на сервере установлен Docker с Compose plugin
- в `DEPLOY_PATH/.env` лежит актуальный production `.env`

## Dry Run Перед Включением CD

Перед первым merge в `main` нужно руками проверить тот же сценарий, который потом будет выполнять workflow:

```bash
cd /opt/neurobox
docker compose up -d --build --remove-orphans
docker compose ps
curl -fsS http://127.0.0.1:8092/health
curl -fsS http://127.0.0.1:8091/health
docker compose exec -T bot python /app/scripts/healthcheck_bot.py
```

Если это не проходит вручную, CD включать нельзя.

## Что Проверять После Деплоя

```bash
docker compose ps
curl -fsS http://127.0.0.1:8092/health
curl -fsS http://127.0.0.1:8091/health
docker compose exec -T bot python /app/scripts/healthcheck_bot.py
docker compose logs backend --tail 50
docker compose logs bot --tail 50
docker compose logs worker --tail 50
```

## Production Env Минимум

- `BOT_TOKEN`
- `BOT_USERNAME`
- `POSTGRES_PASSWORD`
- `REDIS_PASSWORD`
- `OPENROUTER_API_KEY`
- `ADMIN_PANEL_SECRET`
- `ADMIN_PANEL_PASSWORD`
- `ADMIN_API_SECRET_KEY`
- `LEGAL_BASE_URL`

## Рекомендуемый Stable Режим

```env
ENABLE_STARS_PAYMENT=true
ENABLE_YOOKASSA_PAYMENT=false
ENABLE_CRYPTOBOT_PAYMENT=false
ENABLE_VIDEO=false
ENABLE_MUSIC=false
ENABLE_TTS=false
```

## Rollback

Минимальная rollback-процедура:

1. На сервере перейти в `DEPLOY_PATH`.
2. Посмотреть последние коммиты: `git log --oneline -5`.
3. Переключить код на предыдущий стабильный коммит: `git checkout <stable-sha>`.
4. Пересобрать стек: `docker compose up -d --build --remove-orphans`.
5. Проверить smoke:

```bash
docker compose ps
curl -fsS http://127.0.0.1:8092/health
curl -fsS http://127.0.0.1:8091/health
docker compose exec -T bot python /app/scripts/healthcheck_bot.py
```

Если rollback выполняется часто, нужно закрепить на сервере отдельный bare-repo или release tags, но для текущей фазы достаточно явной ручной процедуры.

## Release Gate

Деплой считается готовым только если:

1. все контейнеры healthy
2. post-deploy smoke зелёный
3. опубликованные команды совпадают с включёнными фичами
4. legal pages доступны
5. есть хотя бы один подтверждённый live payment сценарий для активного способа оплаты
