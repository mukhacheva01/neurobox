"""Worker job: send Telegram notification to a user."""
import structlog

log = structlog.get_logger()


async def handle(payload: dict, bot=None) -> None:
    """Send a Telegram notification message.

    payload keys:
        user_id (int): Telegram user/chat ID
        text (str): Message text (HTML)
    """
    user_id = payload.get("user_id")
    text = payload.get("text", "")
    if not user_id or not text:
        log.warning("notify_missing_fields", user_id=user_id)
        return

    import httpx

    from shared.config import settings

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{settings.bot_token}/sendMessage",
                json={"chat_id": user_id, "text": text, "parse_mode": "HTML"},
            )
    except Exception as e:
        log.warning("notify_failed", user_id=user_id, error=str(e))
