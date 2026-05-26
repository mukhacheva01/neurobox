"""НейроБокс — уведомление админу об оплате через отдельный бот (название бота, подписка, юзер)."""
import httpx
import structlog

log = structlog.get_logger()


async def send_payment_notification_to_admin(
    bot_name: str,
    pack_label: str,
    user_id: int,
    amount_str: str = "",
    method: str = "yookassa",
    username: str | None = None,
) -> None:
    """
    Отправить админу сообщение об оплате через бот из payment_notify_bot_token.
    Текст: бот, подписка, пользователь (id + @username если есть).
    """
    from shared.config import settings
    token = (getattr(settings, "payment_notify_bot_token", None) or "").strip()
    chat_id = (getattr(settings, "payment_notify_chat_id", None) or "").strip() or "72916668"
    if not token:
        return
    if username is None:
        try:
            from shared.db.database import get_pool
            pool = await get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT username FROM users WHERE id = $1", user_id)
                username = (row["username"] or "").strip() if row else ""
        except Exception:
            username = ""
    user_part = f"{user_id}"
    if username and username.strip():
        user_part = f"{user_id} (@{username.strip()})"
    method_label = "ЮKassa" if method == "yookassa" else "CryptoBot" if method == "cryptobot" else method
    lines = [
        "💰 <b>Оплата подписки</b>",
        "",
        f"🤖 Бот: <b>{bot_name or 'НейроБокс'}</b>",
        f"📦 Подписка: {pack_label}",
        f"👤 Пользователь: <code>{user_part}</code>",
        f"💳 Способ: {method_label}",
    ]
    if amount_str:
        lines.append(f"💵 Сумма: {amount_str}")
    text = "\n".join(lines)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            )
            if r.status_code != 200:
                log.warning("payment_notify_failed", status=r.status_code, body=r.text[:200])
    except Exception as e:
        log.warning("payment_notify_error", error=str(e)[:150])
