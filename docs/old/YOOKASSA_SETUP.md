# Настройка ЮKassa (ЮКасса)

## 1. Переменные в `.env`

```env
YOOKASSA_SHOP_ID=123456
YOOKASSA_SECRET_KEY=test_xxxxxxxxxxxx
BOT_USERNAME=YourBotName
YOOKASSA_RECEIPT_EMAIL=payments@yourdomain.com
```

Если в ЛК ЮKassa включена передача чеков (54-ФЗ), нужен **YOOKASSA_RECEIPT_EMAIL** — без него будет ошибка «receipt is missing or illegal». Укажи реальный email (на него ЮKassa отправит ссылку на чек). Если ошибка «illegal» остаётся: проверь логи бота (`docker compose logs bot`) — там будет полный ответ API; в ЛК ЮKassa в разделе «Интеграция» можно временно отключить передачу чеков, если чеки ведёшь через другой сервис.

- **YOOKASSA_SHOP_ID** и **YOOKASSA_SECRET_KEY** — из [личного кабинета ЮKassa](https://yookassa.ru/my).
- **BOT_USERNAME** — ник бота в Telegram **без @** (нужен для ссылки возврата после оплаты). Если не указан, при нажатии «Карта / СБП» бот покажет подсказку.

## 2. Webhook в личном кабинете ЮKassa

1. Зайди в [Интеграция → HTTP-уведомления](https://yookassa.ru/my/http-notifications-settings).
2. Укажи **URL уведомлений**: `https://ТВОЙ_ДОМЕН/webhook/yookassa`.
   - Обязательно **HTTPS** и порт **443** (или 8443). ЮKassa не отправляет на HTTP или на произвольный порт.
3. Включи событие **payment.succeeded**.

Если бот поднят в Docker и слушает порт 8090, нужен обратный прокси (nginx/caddy) с SSL, который проксирует запросы с `https://домен/webhook/yookassa` на `http://webhook:8090/webhook/yookassa`.

## 3. Проверка

- В боте: 💰 Баланс → 🛒 Купить кредиты → выбрать пакет → **Карта / СБП**. Должна открыться страница оплаты ЮKassa.
- Если видишь сообщение «ЮKassa не настроена» или «укажи BOT_USERNAME» — добавь недостающие переменные в `.env` и перезапусти контейнеры.
- Если после оплаты кредиты не начисляются:
  - Убедись, что webhook доступен с интернета по HTTPS.
  - В логах контейнера **webhook** смотри сообщения `YooKassa webhook rejected: IP not in allowlist` — значит запрос пришёл не с IP ЮKassa. **Решение:** настрой прокси так, чтобы он передавал реальный IP клиента в заголовке `X-Forwarded-For` (см. ниже). Либо задай в `.env` переменную `SKIP_YOOKASSA_IP_CHECK=1` (менее безопасно, но webhook всё равно проверяет платёж через API).
  - В личном кабинете ЮKassa проверь раздел «Уведомления» / логи — доходят ли запросы до твоего URL и какой ответ возвращается (должен быть 200).

## 4. Прокси (nginx): передача IP клиента

Чтобы webhook не возвращал 403, запросы от ЮKassa должны доходить с реальным IP в заголовке. Пример для nginx:

```nginx
location /webhook/ {
    proxy_pass http://webhook:8090;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Если прокси не передаёт `X-Forwarded-For`, в логах webhook будет `client_ip=(empty)` или IP прокси. Тогда либо настрой заголовок, либо включи обход проверки IP: в `.env` добавь `SKIP_YOOKASSA_IP_CHECK=1` и перезапусти контейнер webhook.

## 5. IP-адреса ЮKassa

Сервер webhook проверяет, что запрос пришёл с IP ЮKassa. Список актуален на момент разработки; при изменении его нужно обновить в `scripts/webhook_server.py` (переменная `YOOKASSA_IPS`). Официальный список: [документация ЮKassa](https://yookassa.ru/developers/using-api/webhooks#ip).
