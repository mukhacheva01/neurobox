FROM python:3.12-slim-bookworm AS base

RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update -o Acquire::Retries=5 \
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
