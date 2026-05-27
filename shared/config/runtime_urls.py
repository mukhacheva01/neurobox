"""Helpers for building runtime DSNs from env-style pieces."""
from __future__ import annotations

import os


DEFAULT_POSTGRES_HOST = "postgres"
DEFAULT_POSTGRES_PORT = 5432
DEFAULT_POSTGRES_DB = "neurobox"
DEFAULT_POSTGRES_USER = "neurobox"
DEFAULT_POSTGRES_PASSWORD = "password"
DEFAULT_REDIS_HOST = "redis"
DEFAULT_REDIS_PORT = 6379
DEFAULT_REDIS_PASSWORD = "password"


def build_async_database_url(
    *,
    host: str = DEFAULT_POSTGRES_HOST,
    port: int = DEFAULT_POSTGRES_PORT,
    database: str = DEFAULT_POSTGRES_DB,
    user: str = DEFAULT_POSTGRES_USER,
    password: str = DEFAULT_POSTGRES_PASSWORD,
) -> str:
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"


def build_sync_database_url(
    *,
    host: str = DEFAULT_POSTGRES_HOST,
    port: int = DEFAULT_POSTGRES_PORT,
    database: str = DEFAULT_POSTGRES_DB,
    user: str = DEFAULT_POSTGRES_USER,
    password: str = DEFAULT_POSTGRES_PASSWORD,
) -> str:
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def normalize_sync_database_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


def build_redis_url(
    *,
    host: str = DEFAULT_REDIS_HOST,
    port: int = DEFAULT_REDIS_PORT,
    password: str = DEFAULT_REDIS_PASSWORD,
    db: int = 0,
) -> str:
    return f"redis://:{password}@{host}:{port}/{db}"


def database_url_from_env(*, async_driver: bool = True) -> str:
    raw = (os.environ.get("DATABASE_URL") or "").strip()
    if raw:
        return raw if async_driver else normalize_sync_database_url(raw)
    host = (os.environ.get("POSTGRES_HOST") or DEFAULT_POSTGRES_HOST).strip()
    port = int((os.environ.get("POSTGRES_PORT") or str(DEFAULT_POSTGRES_PORT)).strip())
    database = (os.environ.get("POSTGRES_DB") or DEFAULT_POSTGRES_DB).strip()
    user = (os.environ.get("POSTGRES_USER") or DEFAULT_POSTGRES_USER).strip()
    password = os.environ.get("POSTGRES_PASSWORD") or DEFAULT_POSTGRES_PASSWORD
    if async_driver:
        return build_async_database_url(host=host, port=port, database=database, user=user, password=password)
    return build_sync_database_url(host=host, port=port, database=database, user=user, password=password)


def redis_url_from_env(*, db: int = 0) -> str:
    raw = (os.environ.get("REDIS_URL") or "").strip()
    if raw:
        return raw
    host = (os.environ.get("REDIS_HOST") or DEFAULT_REDIS_HOST).strip()
    port = int((os.environ.get("REDIS_PORT") or str(DEFAULT_REDIS_PORT)).strip())
    password = os.environ.get("REDIS_PASSWORD") or DEFAULT_REDIS_PASSWORD
    return build_redis_url(host=host, port=port, password=password, db=db)
