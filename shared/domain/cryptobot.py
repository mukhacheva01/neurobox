"""НейроБокс — CryptoBot (@CryptoBot) платежи: USDT, TON, BTC."""
import httpx
import structlog

log = structlog.get_logger()
API_URL = "https://pay.crypt.bot/api"


async def create_crypto_invoice(amount_usd: float, pack_name: str, credits: int, user_id: int) -> dict:
    """Создать инвойс в CryptoBot. Возвращает {ok, invoice_id, pay_url} или {ok: False, error}."""
    from shared.config import settings
    token = settings.cryptobot_api_token
    if not token:
        return {"ok": False, "error": "CryptoBot не настроен"}
    headers = {"Crypto-Pay-API-Token": token}
    payload = {
        "asset": "USDT",
        "amount": f"{amount_usd:.2f}",
        "description": f"НейроБокс: {pack_name} — {credits} CR",
        "payload": f"{user_id}:{pack_name}:{credits}",
        "expires_in": 3600,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{API_URL}/createInvoice", headers=headers, json=payload)
            data = r.json()
        if not data.get("ok"):
            log.warning("CryptoBot create failed", data=data)
            return {"ok": False, "error": data.get("error", {}).get("name", "Ошибка CryptoBot")}
        result = data.get("result", {})
        return {
            "ok": True,
            "invoice_id": result.get("invoice_id"),
            "pay_url": result.get("pay_url") or result.get("bot_invoice_url") or result.get("mini_app_invoice_url"),
        }
    except Exception as e:
        log.error("CryptoBot error", error=str(e))
        return {"ok": False, "error": "Ошибка связи с CryptoBot"}


async def get_crypto_invoice(invoice_id: int) -> dict:
    """Получить статус инвойса (проверка из CryptoBot API, а не из payload webhook)."""
    from shared.config import settings
    token = settings.cryptobot_api_token
    if not token:
        return {"ok": False}
    headers = {"Crypto-Pay-API-Token": token}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{API_URL}/getInvoices", headers=headers, params={"invoice_ids": str(invoice_id)})
            data = r.json()
        if data.get("ok") and data.get("result", {}).get("items"):
            item = data["result"]["items"][0]
            return {
                "ok": True,
                "invoice_id": item.get("invoice_id"),
                "status": item.get("status"),
                "amount": item.get("amount"),
                "asset": item.get("asset"),
                "payload": item.get("payload"),
            }
        return {"ok": False}
    except Exception as e:
        log.error("CryptoBot get error", error=str(e), invoice_id=invoice_id)
        return {"ok": False}


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def process_crypto_webhook(update: dict) -> dict:
    """Обработка webhook от CryptoBot (update_type=invoice_paid)."""
    from shared.domain.credits import (
        UNLIMITED_DAYS,
        add_credits,
        confirm_payment_record,
        create_payment_record,
        get_credit_pack,
        get_payment_by_yookassa_id,
        set_unlimited_until,
    )

    status = (update.get("status") or "").strip().lower()
    if status != "paid":
        return {"ok": False, "error": "not_paid"}

    raw_invoice_id = update.get("invoice_id")
    try:
        invoice_id = int(raw_invoice_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_invoice_id"}

    # Ключевая проверка: подтверждаем факт оплаты и payload через CryptoBot API.
    verified = await get_crypto_invoice(invoice_id)
    if not verified.get("ok") or (verified.get("status") or "").lower() != "paid":
        return {"ok": False, "error": "invoice_not_paid_or_unknown"}

    webhook_payload = str(update.get("payload") or "").strip()
    verified_payload = str(verified.get("payload") or "").strip()

    if webhook_payload and verified_payload and webhook_payload != verified_payload:
        log.warning(
            "Crypto webhook payload mismatch",
            invoice_id=invoice_id,
            webhook_payload=webhook_payload,
            verified_payload=verified_payload,
        )
        return {"ok": False, "error": "payload_mismatch"}

    payload_str = verified_payload or webhook_payload
    parts = payload_str.split(":")
    if len(parts) < 3:
        return {"ok": False, "error": "invalid_payload"}

    try:
        user_id = int(parts[0])
        pack_name = parts[1]
        credits = int(parts[2])
    except (ValueError, IndexError):
        return {"ok": False, "error": "invalid_payload"}

    pack = await get_credit_pack(pack_name) or {}
    if not pack:
        return {"ok": False, "error": "unknown_pack"}

    expected_credits = int(pack.get("credits", 0))
    if credits != expected_credits:
        log.warning(
            "Crypto webhook credits mismatch",
            invoice_id=invoice_id,
            pack_name=pack_name,
            payload_credits=credits,
            expected_credits=expected_credits,
        )
        return {"ok": False, "error": "credits_mismatch"}

    payment_id = f"crypto_{invoice_id}"

    existing = await get_payment_by_yookassa_id(payment_id)
    if existing and existing["status"] == "confirmed":
        return {"ok": True, "already": True}

    amount = _safe_float(verified.get("amount"), 0.0)
    await create_payment_record(user_id, payment_id, amount, credits, pack_name)

    confirmed = await confirm_payment_record(payment_id)
    if not confirmed:
        return {"ok": True, "already": True}

    if pack_name == "unlimited":
        await set_unlimited_until(user_id, days=UNLIMITED_DAYS)
    else:
        await add_credits(user_id, credits, "purchase", f"{pack.get('label', pack_name)} (CryptoBot {amount} USDT)")

    try:
        from shared.domain.analytics import track_payment_success
        await track_payment_success(
            user_id=user_id,
            payment_id=payment_id,
            method="cryptobot",
            pack_name=pack_name,
            amount_rub=0.0,
            credits=int(credits or 0),
            is_test=False,
            amount_usd=float(amount or 0),
        )
    except Exception:
        pass

    try:
        from shared.config import settings
        from shared.domain.payment_notify import send_payment_notification_to_admin
        pack_label = pack.get("label", pack_name)
        if pack_name == "unlimited":
            pack_label = "♾️ Безлимит 30 дн."
        else:
            pack_label = f"{pack_label} — {credits} CR"
        bot_name = f"@{settings.bot_username}" if getattr(settings, "bot_username", None) else "НейроБокс"
        await send_payment_notification_to_admin(
            bot_name=bot_name,
            pack_label=pack_label,
            user_id=user_id,
            amount_str=f"{amount} USDT" if amount else "",
            method="cryptobot",
        )
    except Exception:
        pass

    return {"ok": True, "user_id": user_id, "credits": credits}
