"""НейроБокс — Worker: обработка фоновых задач из Redis-очереди."""
import asyncio
import json
import signal

import structlog

log = structlog.get_logger()

QUEUE_KEY = "neurobox:tasks"
DLQ_KEY = "neurobox:tasks:dlq"
MAX_TASK_RETRIES = 3


async def _get_redis():
    try:
        from redis.asyncio import Redis

        from shared.config import settings

        return Redis.from_url(settings.redis_url)
    except Exception:
        return None


async def process_task(task: dict) -> None:
    """Dispatch one task to the appropriate job handler."""
    task_type = task.get("type")
    log.info("processing_task", type=task_type, user_id=task.get("user_id"))

    if task_type == "notify":
        from services.worker.jobs.notify import handle
        await handle(task)

    elif task_type == "video_generate":
        from services.worker.jobs.video_generate import handle
        await handle(task)

    elif task_type == "daily_stats":
        from services.worker.jobs.daily_stats import handle
        await handle(task)

    elif task_type == "metrics_alert":
        from services.worker.jobs.alerts import handle
        await handle(task)

    else:
        log.warning("unknown_task_type", type=task_type)


async def main():
    log.info("starting_neurobox_worker")

    # Прогрев движка SQLAlchemy (создаёт пул при первом запросе)
    try:
        from shared.db.session import get_session
        async with get_session() as session:
            await session.execute(__import__("sqlalchemy").text("SELECT 1"))
    except Exception as e:
        log.error("db_pool_init_failed", error=str(e))

    r = await _get_redis()
    if not r:
        log.error("redis_unavailable_worker_sleeping")
        while True:
            await asyncio.sleep(60)
        return

    log.info("worker_ready_polling_queue", queue=QUEUE_KEY)

    # Ежедневная статистика — раз в час проверяем (~720 итераций по 5 сек)
    stats_counter = 0

    while True:
        try:
            item = await r.blpop(QUEUE_KEY, timeout=5)
            if item:
                _, raw = item
                try:
                    task = json.loads(raw)
                    await process_task(task)
                except json.JSONDecodeError:
                    log.warning("invalid_task_json", raw=raw[:200])
                except Exception as e:
                    log.error("task_processing_error", error=str(e))
                    try:
                        task = json.loads(raw)
                        retry_count = int(task.get("_retry") or 0)
                        task["_retry"] = retry_count + 1
                        if task["_retry"] <= MAX_TASK_RETRIES:
                            await r.rpush(QUEUE_KEY, json.dumps(task, ensure_ascii=False))
                            log.warning("task_requeued", retry=task["_retry"], type=task.get("type"))
                        else:
                            await r.rpush(DLQ_KEY, json.dumps(task, ensure_ascii=False))
                            log.error("task_moved_to_dlq", retry=task["_retry"], type=task.get("type"))
                    except Exception as requeue_err:
                        log.error("task_requeue_failed", error=str(requeue_err))

            # Периодические задачи (каждые ~1800 итераций ≈ раз в час)
            stats_counter += 1
            if stats_counter >= 720:
                stats_counter = 0
                await process_task({"type": "daily_stats"})
                await process_task({"type": "metrics_alert"})

        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("worker_loop_error", error=str(e))
            await asyncio.sleep(10)

    try:
        await r.aclose()
    except Exception:
        pass


if __name__ == "__main__":
    def signal_handler(sig, frame):
        log.info("shutdown_signal", signal=sig)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
