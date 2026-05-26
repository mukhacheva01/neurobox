FROM python:3.12-slim AS base

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        fonts-dejavu-core \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

FROM base AS deps
COPY requirements-bot.txt .
RUN pip install --no-cache-dir -r requirements-bot.txt

FROM deps AS final
COPY . .
RUN chmod +x docker/entrypoints/bot.sh
ENTRYPOINT ["/app/docker/entrypoints/bot.sh"]
