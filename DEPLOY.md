# НейроБокс — деплой

## Базовый сценарий

```bash
cd /opt/neurobox
cp .env.example .env
# заполни env

docker compose up -d --build
docker compose ps
```

Если код уже смонтирован на сервере и менялись только `.py` файлы:

```bash
cd /opt/neurobox
docker compose restart bot worker webhook admin api
```

## Что обязательно проверить после деплоя

```bash
docker compose ps
docker compose logs bot --tail 50
docker compose exec -T bot pytest -q
docker compose exec -T bot python /app/scripts/smoke_user_flow.py
```

## Production env минимум

- `BOT_TOKEN`
- `BOT_USERNAME`
- `POSTGRES_PASSWORD`
- `REDIS_PASSWORD`
- `OPENROUTER_API_KEY`
- `ADMIN_PANEL_SECRET`
- `ADMIN_PANEL_PASSWORD`
- `ADMIN_API_SECRET_KEY`
- `LEGAL_BASE_URL`

## Рекомендуемый stable-режим

```env
ENABLE_STARS_PAYMENT=true
ENABLE_YOOKASSA_PAYMENT=false
ENABLE_CRYPTOBOT_PAYMENT=false
ENABLE_VIDEO=false
ENABLE_MUSIC=false
ENABLE_TTS=false
```

В таком режиме бот продаёт и публикует только рабочее ядро.

## Когда включать дополнительные модули

- `ENABLE_VIDEO=true` только после live-проверки `FALAI_API_KEY`
- `ENABLE_MUSIC=true` только после live-проверки `FALAI_API_KEY`
- `ENABLE_TTS=true` только после live-проверки TTS-провайдера
- `ENABLE_YOOKASSA_PAYMENT=true` и `ENABLE_CRYPTOBOT_PAYMENT=true` только если это не конфликтует с текущей платформенной политикой и сценарий вынесен из forbidden in-app digital sales flow

## Release gate

Деплой считается готовым к продажам только если:
1. все контейнеры healthy
2. смоук зелёный
3. published commands совпадают с включёнными фичами
4. legal pages доступны
5. есть хотя бы один подтверждённый live payment сценарий для активного платёжного метода
