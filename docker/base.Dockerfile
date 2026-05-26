FROM python:3.12-slim-bookworm

RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update -o Acquire::Retries=5 \
    && apt-get install -y --no-install-recommends \
        curl \
        fonts-dejavu-core \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
