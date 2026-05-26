# HTTPS для веб-админки НейроБокс

Админка (Flask) по умолчанию работает по HTTP на порту 8091. В production доступ должен быть только по HTTPS.

В репозитории есть пример конфига: **`deploy/nginx-admin.conf`** — скопируйте на хост и замените `admin.yourdomain.com` на свой домен.

## Варианты

### 1. Nginx перед контейнером admin

На хосте или в отдельном контейнере:

```nginx
server {
    listen 443 ssl;
    server_name admin.yourdomain.com;
    ssl_certificate     /etc/letsencrypt/live/admin.yourdomain.com/fullchain.pem;
    ssl_certificate_key  /etc/letsencrypt/live/admin.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8091;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 2. Caddy (авто-TLS)

```text
admin.yourdomain.com {
    reverse_proxy neurobox_admin:8091
}
```

### 3. Облачный балансировщик (AWS ALB, Cloudflare, и т.д.)

Включить TLS на балансировщике и направить трафик на `host:8091` (HTTP внутри сети).

## После настройки HTTPS

- Открывать админку только по `https://...`.
- В .env задать `ADMIN_PANEL_URL=https://admin.yourdomain.com` (если бот показывает ссылку на админку).
- Убедиться, что `ADMIN_PANEL_SECRET` и `ADMIN_PANEL_PASSWORD` заданы и не дефолтные.
