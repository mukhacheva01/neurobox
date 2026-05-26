FROM python:3.12-slim AS base

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        fonts-dejavu-core \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

FROM base AS deps
COPY requirements-worker.txt .
RUN pip install --no-cache-dir -r requirements-worker.txt

FROM deps AS final
COPY . .
RUN chmod +x docker/entrypoints/worker.sh
ENTRYPOINT ["/app/docker/entrypoints/worker.sh"]
