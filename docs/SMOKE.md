# Smoke Commands

## Local stack

Build and start:

```bash
docker compose up -d --build
```

Optional dev overlay with bind mounts:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

Runtime checks:

```bash
docker compose ps
curl -fsS http://127.0.0.1:8092/health
curl -fsS http://127.0.0.1:8091/health
docker compose logs bot --tail 50
docker compose logs worker --tail 50
```

## Production-style stack

Use the prod overlay when PostgreSQL runs outside Compose:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Production smoke checks:

```bash
docker compose ps
curl -fsS http://127.0.0.1:8092/health
curl -fsS http://127.0.0.1:8091/health
docker compose logs backend --tail 50
docker compose logs bot --tail 50
docker compose logs worker --tail 50
```
