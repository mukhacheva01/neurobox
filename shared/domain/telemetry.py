"""Unified telemetry helpers for AI handlers."""

import asyncio

FIRST_VALUE_EVENTS = {"message_sent", "image_generated", "video_generated", "music_generated"}
FIRST_VALUE_TASKS = {"text", "image", "video", "music", "tts", "stt"}


async def _should_track_first_value(user_id: int) -> bool:
    try:
        from shared.redis.store import _get_redis

        r = await _get_redis()
        if r:
            created = await r.set(f"neurobox:first_value:{user_id}", b"1", nx=True, ex=90 * 24 * 3600)
            return bool(created)
    except Exception:
        pass

    try:
        from sqlalchemy import select

        from shared.db.models.event import Event
        from shared.db.session import get_session

        async with get_session() as session:
            result = await session.execute(
                select(Event)
                .where(
                    Event.user_id == user_id,
                    Event.event_name == "first_value",
                )
                .limit(1)
            )
            row = result.scalar_one_or_none()
            return row is None
    except Exception:
        return False


async def _track_funnel_markers(
    user_id: int,
    task_type: str,
    model: str,
    credits_charged: int,
    success_event: str | None = None,
    event_props: dict | None = None,
) -> None:
    from shared.domain.analytics import track_first_value, track_premium_action

    props = dict(event_props or {})
    tasks = []

    if success_event in FIRST_VALUE_EVENTS or task_type in FIRST_VALUE_TASKS:
        if await _should_track_first_value(user_id):
            tasks.append(track_first_value(user_id, task_type, model, success_event or "", **props))

    if int(credits_charged or 0) > 0:
        tasks.append(track_premium_action(user_id, task_type, model, int(credits_charged or 0), success_event or "", **props))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def log_ai_success(
    user_id: int,
    task_type: str,
    model: str,
    prompt: str = "",
    credits_charged: int = 0,
    duration_ms: int = 0,
    success_event: str | None = None,
    event_props: dict | None = None,
) -> None:
    from shared.domain.analytics import track
    from shared.domain.credits import log_ai_request

    tasks = [
        log_ai_request(
            user_id,
            task_type,
            model,
            (prompt or "")[:200],
            "completed",
            int(credits_charged or 0),
            int(duration_ms or 0),
        )
    ]

    if success_event:
        props = {
            "model": model,
            "cr_cost": int(credits_charged or 0),
            "latency_ms": int(duration_ms or 0),
        }
        if event_props:
            props.update(event_props)
        tasks.append(track(success_event, user_id, **props))

    tasks.append(
        _track_funnel_markers(
            user_id,
            task_type,
            model,
            int(credits_charged or 0),
            success_event=success_event,
            event_props=event_props,
        )
    )

    await asyncio.gather(*tasks, return_exceptions=True)


async def log_ai_error(
    user_id: int,
    task_type: str,
    model: str,
    prompt: str = "",
    credits_charged: int = 0,
    duration_ms: int = 0,
    error_message: str = "",
    status: str = "error",
    error_event: str | None = None,
    event_props: dict | None = None,
) -> None:
    from shared.domain.analytics import track
    from shared.domain.credits import log_ai_request

    err = (error_message or "")[:500]
    tasks = [
        log_ai_request(
            user_id,
            task_type,
            model,
            (prompt or "")[:200],
            status or "error",
            int(credits_charged or 0),
            int(duration_ms or 0),
            err,
        )
    ]

    if error_event:
        props = {
            "model": model,
            "latency_ms": int(duration_ms or 0),
            "status": status or "error",
        }
        if err:
            props["error"] = err[:200]
        if event_props:
            props.update(event_props)
        tasks.append(track(error_event, user_id, **props))

    await asyncio.gather(*tasks, return_exceptions=True)


def elapsed_ms(start_monotonic: float, now_monotonic: float | None = None) -> int:
    import time

    end = time.monotonic() if now_monotonic is None else now_monotonic
    return max(0, int((end - start_monotonic) * 1000))
