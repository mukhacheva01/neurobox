"""Worker job: background video generation."""
import time

import structlog

log = structlog.get_logger()


async def _send_telegram_async(chat_id: int, text: str) -> None:
    import httpx

    from shared.config import settings

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(
                f"https://api.telegram.org/bot{settings.bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            )
    except Exception as e:
        log.warning("send_telegram_failed", chat_id=chat_id, error=str(e))


async def _send_telegram_video_url(chat_id: int, video_url: str, caption: str) -> None:
    import httpx

    from shared.config import settings

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            await client.post(
                f"https://api.telegram.org/bot{settings.bot_token}/sendVideo",
                json={"chat_id": chat_id, "video": video_url, "caption": caption, "parse_mode": "HTML"},
            )
    except Exception as e:
        log.warning("send_video_url_failed", chat_id=chat_id, error=str(e))


async def _send_telegram_video_file(chat_id: int, video_bytes: bytes, caption: str) -> None:
    import httpx

    from shared.config import settings

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            await client.post(
                f"https://api.telegram.org/bot{settings.bot_token}/sendVideo",
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"video": ("video.mp4", video_bytes, "video/mp4")},
            )
    except Exception as e:
        log.warning("send_video_file_failed", chat_id=chat_id, error=str(e))


async def handle(payload: dict, bot=None) -> None:
    """Run video generation in the background and deliver result to user.

    payload keys:
        user_id (int): Telegram user ID
        chat_id (int, optional): Telegram chat ID (defaults to user_id)
        prompt (str): Generation prompt
        model (str): Model identifier
        cost (int): Credits cost already spent
        label (str, optional): Display label
        trial (bool, optional): Was a trial spend
        unlimited (bool, optional): Was unlimited spend
        policy_usage (any, optional): Policy usage context
    """
    user_id = payload.get("user_id")
    chat_id = payload.get("chat_id", user_id)
    prompt = payload.get("prompt", "")
    model = payload.get("model", "")
    cost = int(payload.get("cost") or 0)
    label = payload.get("label", "Видео")
    queued_spend = {
        "cost": cost,
        "trial": bool(payload.get("trial")),
        "unlimited": bool(payload.get("unlimited")),
        "policy_usage": payload.get("policy_usage"),
    }
    gen_started = time.monotonic()

    if not prompt or not model:
        log.warning("video_generate_missing_fields", user_id=user_id)
        return

    try:
        from shared.domain.telemetry import elapsed_ms, log_ai_error, log_ai_success
        from shared.domain.video import run_video_generation

        result = await run_video_generation(prompt, model, timeout_sec=400)
    except Exception as e:
        log.exception("video_generate_run_error", user_id=user_id, error=str(e))
        try:
            from shared.domain.telemetry import elapsed_ms, log_ai_error
            await log_ai_error(
                user_id, "video", model, prompt[:200], cost, elapsed_ms(gen_started), str(e),
                status="exception", error_event="video_generation_error", event_props={"source": "queue"},
            )
        except Exception:
            pass
        if user_id:
            try:
                from shared.domain.credits import refund_spend_credits
                await refund_spend_credits(user_id, queued_spend, "ошибка генерации видео")
            except Exception:
                pass
        await _send_telegram_async(chat_id, f"❌ Ошибка генерации видео.\n\n💚 Возвращено {cost} CR.")
        return

    if not result.get("ok"):
        err = result.get("error", "Неизвестная ошибка")
        try:
            from shared.domain.telemetry import elapsed_ms, log_ai_error
            await log_ai_error(
                user_id, "video", model, prompt[:200], cost, elapsed_ms(gen_started), err,
                error_event="video_generation_error", event_props={"source": "queue"},
            )
        except Exception:
            pass
        if user_id:
            try:
                from shared.domain.credits import refund_spend_credits
                await refund_spend_credits(user_id, queued_spend, "ошибка генерации видео")
            except Exception:
                pass
        await _send_telegram_async(chat_id, f"❌ {err[:200]}\n\n💚 Возвращено {cost} CR.")
        return

    video_url = result.get("video_url")
    video_bytes = result.get("video_bytes")

    if not video_url and not video_bytes:
        try:
            from shared.domain.telemetry import elapsed_ms, log_ai_error
            await log_ai_error(
                user_id, "video", model, prompt[:200], cost, elapsed_ms(gen_started), "Видео не получено",
                error_event="video_generation_error", event_props={"source": "queue"},
            )
        except Exception:
            pass
        if user_id:
            try:
                from shared.domain.credits import refund_spend_credits
                await refund_spend_credits(user_id, queued_spend, "видео не получено")
            except Exception:
                pass
        await _send_telegram_async(chat_id, "❌ Не удалось получить видео. Кредиты возвращены.")
        return

    try:
        from shared.domain.credits import get_balance

        bal = await get_balance(user_id)
        rem = bal.get("total", 0)
    except Exception:
        rem = 0

    caption = f"🎬 <b>{prompt[:200]}</b>\n\n<i>💰 −{cost} CR | Остаток: {rem} CR | {label}</i>"

    try:
        from shared.domain.telemetry import elapsed_ms, log_ai_success
        await log_ai_success(
            user_id, "video", model, prompt[:200], cost, elapsed_ms(gen_started),
            success_event="video_generated", event_props={"source": "queue"},
        )
    except Exception:
        pass

    if video_bytes:
        await _send_telegram_video_file(chat_id, video_bytes, caption)
    else:
        await _send_telegram_video_url(chat_id, video_url, caption)
