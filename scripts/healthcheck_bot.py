#!/usr/bin/env python3
"""Healthcheck for the bot container without direct DATABASE_URL dependency."""

import asyncio
import os
import sys

import httpx
import redis.asyncio as aioredis

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from shared.config.runtime_urls import redis_url_from_env


async def check_backend() -> bool:
    try:
        from shared.config import settings

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{settings.backend_url.rstrip('/')}/health")
        return response.status_code == 200
    except Exception as exc:
        print(f"Backend: {exc}", file=sys.stderr)
        return False


async def check_redis() -> bool:
    try:
        client = aioredis.from_url(redis_url_from_env(), socket_timeout=3)
        await client.ping()
        await client.aclose()
        return True
    except Exception as exc:
        print(f"Redis: {exc}", file=sys.stderr)
        return False


async def main():
    backend_ok, redis_ok = await asyncio.gather(check_backend(), check_redis())
    if backend_ok and redis_ok:
        print("OK: backend=yes redis=yes")
        sys.exit(0)
    print(f"UNHEALTHY: backend={'yes' if backend_ok else 'no'} redis={'yes' if redis_ok else 'no'}")
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
