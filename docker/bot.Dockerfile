FROM python:3.12-slim-bookworm AS base

RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update -o Acquire::Retries=5 \
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
