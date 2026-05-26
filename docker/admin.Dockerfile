FROM python:3.12-slim AS base

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

FROM base AS deps
COPY requirements-admin.txt .
RUN pip install --no-cache-dir -r requirements-admin.txt

FROM deps AS final
COPY . .
RUN chmod +x docker/entrypoints/admin.sh
ENTRYPOINT ["/app/docker/entrypoints/admin.sh"]
