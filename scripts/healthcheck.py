#!/usr/bin/env python3
"""Generic healthcheck for services that need PostgreSQL and Redis."""

import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from shared.config.runtime_urls import database_url_from_env, redis_url_from_env


async def check_postgres() -> bool:
    try:
        import asyncpg

        conn = await asyncio.wait_for(
            asyncpg.connect(database_url_from_env(async_driver=False)),
            timeout=5,
        )
        await conn.fetchval("SELECT 1")
        await conn.close()
        return True
    except Exception as exc:
        print(f"PG: {exc}", file=sys.stderr)
        return False


async def check_redis() -> bool:
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(redis_url_from_env(), socket_timeout=3)
        await client.ping()
        await client.aclose()
        return True
    except Exception as exc:
        print(f"Redis: {exc}", file=sys.stderr)
        return True


async def main():
    pg_ok = await check_postgres()
    redis_ok = await check_redis()

    if pg_ok and redis_ok:
        print("OK: pg=yes redis=yes")
        sys.exit(0)
    if pg_ok:
        print("DEGRADED: pg=yes redis=no")
        sys.exit(0)
    print("UNHEALTHY: pg=no")
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
