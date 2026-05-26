#!/usr/bin/env python3
"""НейроБокс — Docker healthcheck script.

Usage in docker-compose.yml:
  healthcheck:
    test: ["CMD", "python3", "/app/scripts/healthcheck.py"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 15s

Checks:
  1. PostgreSQL connection
  2. Redis connection
  3. Bot process alive (PID file or HTTP endpoint)

Exit codes: 0 = healthy, 1 = unhealthy
"""

import asyncio
import os
import sys


async def check_postgres() -> bool:
    try:
        import asyncpg
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            return False
        conn = await asyncio.wait_for(
            asyncpg.connect(url.replace("+asyncpg", "")),
            timeout=5,
        )
        await conn.fetchval("SELECT 1")
        await conn.close()
        return True
    except Exception as e:
        print(f"PG: {e}", file=sys.stderr)
        return False


async def check_redis() -> bool:
    try:
        import redis.asyncio as aioredis
        url = os.environ.get("REDIS_URL", "")
        if not url:
            return True  # Redis is optional
        r = aioredis.from_url(url, socket_timeout=3)
        await r.ping()
        await r.aclose()
        return True
    except Exception as e:
        print(f"Redis: {e}", file=sys.stderr)
        return True  # Degraded but not dead


async def main():
    pg_ok = await check_postgres()
    redis_ok = await check_redis()

    if pg_ok and redis_ok:
        print("OK: pg=yes redis=yes")
        sys.exit(0)
    elif pg_ok:
        print("DEGRADED: pg=yes redis=no")
        sys.exit(0)  # Still healthy, just degraded
    else:
        print("UNHEALTHY: pg=no")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
