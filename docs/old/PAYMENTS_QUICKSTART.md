# Оплаты ЮKassa — что сделать

## Вариант 1: Работает уже сейчас (без webhook)

Когда пользователь **возвращается в бота** после оплаты (кнопка «Вернуться в бот» на странице ЮKassa), бот сам проверяет статус платежа через API и начисляет кредиты. Webhook для этого **не нужен**.

### Шаги

1. **На сервере открой `.env` и проверь:**
   ```env
   YOOKASSA_SHOP_ID=твой_shop_id
   YOOKASSA_SECRET_KEY=твой_секретный_ключ
   BOT_USERNAME=имя_бота_без_собаки
   ```
   Данные берёшь в [ЛК ЮKassa](https://yookassa.ru/my) → Настройки → Ключи API (или из настроек магазина).

2. **Если в ЛК включена передача чеков (54-ФЗ), добавь:**
   ```env
   YOOKASSA_RECEIPT_EMAIL=твой@email.ru
   ```

3. **Перезапусти бота:**
   ```bash
   cd /opt/neurobox && docker compose restart bot
   ```

4. **Проверь в боте:** Баланс → Купить кредиты → любой пакет → «Карта / СБП». Должна появиться кнопка со ссылкой на оплату ЮKassa. После оплаты нажми «Вернуться в бота» — кредиты должны начислиться.

---

## Вариант 2: Мгновенное начисление (через webhook)

Чтобы кредиты начислялись **сразу** после оплаты, без нажатия «Вернуться в бота», ЮKassa должна слать уведомления на твой сервер. Для этого нужен **HTTPS-адрес** (у тебя нет домена — см. ниже).

### Вариант 2А: Туннель (быстро, без домена)

1. Установи на сервер [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/):
   ```bash
   # пример для Linux (проверь актуальную ссылку на сайте Cloudflare)
   wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
   sudo dpkg -i cloudflared-linux-amd64.deb
   ```

2. Запусти туннель на порт webhook (8090):
   ```bash
   cloudflared tunnel --url http://127.0.0.1:8090
   ```
   В выводе будет строка вида `https://xxxx-xx-xx-xx-xx.xx.trycloudflare.com` — это твой HTTPS-URL.

3. В [ЛК ЮKassa → HTTP-уведомления](https://yookassa.ru/my/http-notifications-settings) укажи:
   - URL: `https://xxxx-xx-xx-xx-xx.xx.trycloudflare.com/webhook/yookassa`
   - Событие: **payment.succeeded**

4. В `.env` добавь (если webhook из туннеля отдаёт 403 по IP):
   ```env
   SKIP_YOOKASSA_IP_CHECK=1
   ```
   И перезапусти webhook: `docker compose restart webhook`.

Минус: при каждом новом запуске `cloudflared` URL может меняться — его нужно снова прописывать в ЮKassa. Для постоянного URL зарегистрируй бесплатный туннель в Cloudflare (см. их доки).

### Вариант 2Б: Домен + nginx + SSL (навсегда)

1. Купи или возьми бесплатный домен, привяжи его к IP `195.133.63.2` (A-запись).
2. Установи nginx и certbot, настрой виртуальный хост с SSL (Let's Encrypt).
3. В nginx настрой проксирование на `http://127.0.0.1:8090` для пути `/webhook/`.
4. В ЮKassa укажи URL: `https://твой-домен.ru/webhook/yookassa`.

---

## Если что-то не работает

- **Не создаётся платёж (ошибка в боте):** смотри логи: `docker compose logs bot` — там будет текст ошибки от ЮKassa (ключи, чек и т.д.).
- **Платёж создаётся, но кредиты не начислились:** после оплаты обязательно нажми в письме/на странице ЮKassa «Вернуться в бота» — тогда бот проверит платёж и начислит. Если настроил webhook — смотри `docker compose logs webhook`.
