# ЮKassa — пошаговая настройка с нуля

## Шаг 1: Регистрация и ключи

1. Зайди в [Личный кабинет ЮKassa](https://yookassa.ru/my)
2. Создай магазин (если ещё нет)
3. Перейди: **Настройки** → **Ключи API**
4. Скопируй:
   - **shopId** (число, например 1252342)
   - **Секретный ключ** (начинается с `test_` для тестов или `live_` для продакшена)

---

## Шаг 2: Переменные в `.env`

Открой `/opt/neurobox/.env` и добавь/проверь:

```env
# Обязательно
YOOKASSA_SHOP_ID=твой_shop_id
YOOKASSA_SECRET_KEY=твой_секретный_ключ
BOT_USERNAME=ai_b0x_bot

# Если в ЛК ЮKassa включены чеки 54-ФЗ — добавь email
YOOKASSA_RECEIPT_EMAIL=email@example.com
```

**Важно про чеки:**
- Если при создании платежа бот пишет «receipt is missing or illegal» — в ЛК ЮKassa включена передача чеков.
- **Вариант А:** добавь `YOOKASSA_RECEIPT_EMAIL=твой@email.ru`
- **Вариант Б:** в ЛК ЮKassa → Интеграция → отключи «Передача чеков»

---

## Шаг 3: Проверка ключей

```bash
cd /opt/neurobox
docker compose exec bot python scripts/check_apis.py
```

Должно быть: `✓ ЮKassa: OK (ключи валидны)`

---

## Шаг 4: Перезапуск бота

```bash
cd /opt/neurobox
docker compose up -d bot --force-recreate
```

---

## Шаг 5: Тест оплаты (без webhook)

1. В боте: **Баланс** → **Купить кредиты** → выбери пакет → **Карта / СБП**
2. Должна появиться кнопка «Оплатить X ₽ — переход в ЮKassa»
3. Нажми — откроется страница оплаты ЮKassa
4. Оплати (тестовой картой или реальной)
5. На странице ЮKassa нажми **«Вернуться в бота»**
6. Кредиты должны начислиться

**Если не работает:**
- `docker compose logs bot --tail=50` — смотри текст ошибки от ЮKassa
- Ошибка «receipt»/«illegal» → добавь `YOOKASSA_RECEIPT_EMAIL` или отключи чеки в ЛК

---

## Шаг 6: Webhook (мгновенное начисление без «Вернуться в бота»)

ЮKassa отправляет уведомления **только на HTTPS**. Порт 8090 по HTTP не подходит.

### Вариант А: Cloudflare Tunnel (без домена)

```bash
# Установи cloudflared
wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
dpkg -i cloudflared-linux-amd64.deb

# Запусти туннель (держать в фоне)
cloudflared tunnel --url http://127.0.0.1:8090
```

В выводе будет `https://xxxx-xx-xx.trycloudflare.com`. В ЛК ЮKassa укажи:

```
https://xxxx-xx-xx.trycloudflare.com/webhook/yookassa
```

Событие: **payment.succeeded**

В `.env` добавь (если webhook возвращает 403):
```env
SKIP_YOOKASSA_IP_CHECK=1
```

Перезапусти webhook: `docker compose restart webhook`

**Минус:** при каждом новом запуске cloudflared URL может меняться — нужно обновлять в ЛК ЮKassa.

### Вариант Б: Домен + nginx + SSL

1. Домен привязан к IP сервера (A-запись)
2. nginx с SSL (Let's Encrypt)
3. Проксирование `/webhook/` на `http://127.0.0.1:8090`
4. В ЛК ЮKassa: `https://твой-домен.ru/webhook/yookassa`

---

## Чек-лист

- [ ] YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY в .env
- [ ] BOT_USERNAME в .env (без @)
- [ ] YOOKASSA_RECEIPT_EMAIL или чеки отключены в ЛК
- [ ] `check_apis.py` показывает ✓ ЮKassa
- [ ] Бот перезапущен
- [ ] Тест: Карта/СБП → оплата → Вернуться в бота
- [ ] (Опционально) Webhook на HTTPS для мгновенного начисления
