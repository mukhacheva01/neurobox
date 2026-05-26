"""Redis queue client: enqueue tasks."""
import json

import redis.asyncio as aioredis


async def enqueue(redis_client: aioredis.Redis, task_type: str, payload: dict) -> None:
    task = {"type": task_type, "payload": payload}
    await redis_client.rpush("worker_queue", json.dumps(task))
