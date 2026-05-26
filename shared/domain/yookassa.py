"""НейроБокс — ЮKassa: создание платежа и проверка статуса."""
import base64
import uuid

import httpx
import structlog

log = structlog.get_logger()
API_URL = "https://api.yookassa.ru/v3"


def _auth_header(shop_id: str, secret_key: str) -> str:
    raw = f"{shop_id}:{secret_key}"
    return "Basic " + base64.b64encode(raw.encode()).decode()


def _get_yookassa_credentials():
    """Возвращает (shop_id, secret_key) без пробелов. Пустые — если не настроено."""
    from shared.config import settings

    shop_id = (settings.yookassa_shop_id or "").strip()
    secret_key = (settings.yookassa_secret_key or "").strip()
    return shop_id, secret_key


async def get_yookassa_availability() -> dict:
    """Проверка доступности YooKassa для UI: валидность ключей + доступ к API."""
    shop_id, secret_key = _get_yookassa_credentials()
    if not shop_id or not secret_key:
        return {
            "available": False,
            "reason": "credentials_missing",
            "message": "Карта/СБП недоступны: ЮKassa не настроена.",
        }
    headers = {"Authorization": _auth_header(shop_id, secret_key)}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{API_URL}/me", headers=headers)
        if r.status_code in (200, 201):
            return {"available": True}
        try:
            data = r.json()
        except Exception:
            data = {}
        desc = (data.get("description") or data.get("message") or r.text or "").strip()[:300]
        if r.status_code in (401, 403):
            log.warning("YooKassa availability invalid credentials", status=r.status_code, description=desc)
            return {
                "available": False,
                "reason": "credentials_invalid",
                "message": "Карта/СБП временно недоступны: неверные ключи ЮKassa.",
            }
        log.warning("YooKassa availability api error", status=r.status_code, description=desc)
        return {
            "available": False,
            "reason": "api_error",
            "message": "Карта/СБП временно недоступны. Попробуй позже.",
        }
    except Exception as e:
        log.warning("YooKassa availability network error", error=str(e))
        return {
            "available": False,
            "reason": "network_error",
            "message": "Карта/СБП временно недоступны: ошибка связи с ЮKassa.",
        }


async def create_payment(
    amount_rub: float,
    pack_name: str,
    credits: int,
    user_id: int,
    return_url: str,
) -> dict:
    """Создать платёж в ЮKassa. return_url — куда вернуть пользователя после оплаты."""
    shop_id, secret_key = _get_yookassa_credentials()
    if not shop_id or not secret_key:
        return {"ok": False, "error": "ЮKassa не настроена (YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)"}
    payload = {
        "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": f"НейроБокс — {credits} кредитов",
        "metadata": {"user_id": str(user_id), "bot_name": "neurobox", "pack": pack_name, "credits": str(credits)},
    }
    from shared.config import settings

    receipt_email = (getattr(settings, "yookassa_receipt_email", None) or "").strip()
    value_str = f"{amount_rub:.2f}"
    if receipt_email:
        payload["receipt"] = {
            "customer": {"email": receipt_email},
            "tax_system_code": 2,
            "items": [
                {
                    "description": "Кредиты НейроБокс",
                    "quantity": "1.000",
                    "amount": {"value": value_str, "currency": "RUB"},
                    "vat_code": 1,
                    "payment_subject": "service",
                    "payment_mode": "full_payment",
                    "measure": "piece",
                }
            ],
        }
    headers = {
        "Authorization": _auth_header(shop_id, secret_key),
        "Content-Type": "application/json",
        "Idempotence-Key": str(uuid.uuid4()),
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(f"{API_URL}/payments", json=payload, headers=headers)
        try:
            data = r.json()
        except Exception:
            data = {}
        if r.status_code not in (200, 201):
            desc = (data.get("description") or data.get("message") or r.text or f"HTTP {r.status_code}")[:500]
            code = data.get("code", "")
            log.warning("YooKassa create failed", status=r.status_code, code=code, description=desc, body=data)
            if "receipt" in (desc or "").lower() or "illegal" in (desc or "").lower() or code == "invalid_request":
                desc = f"{desc} Проверь YOOKASSA_RECEIPT_EMAIL в .env или отключи чеки в ЛК ЮKassa."
            return {"ok": False, "error": str(desc)[:250]}
        pid = data.get("id")
        status = data.get("status")
        conf = data.get("confirmation") or {}
        url = conf.get("confirmation_url") if isinstance(conf, dict) else None
        if not url or not isinstance(url, str):
            log.warning("YooKassa create: no confirmation_url in response", data=data)
            return {"ok": False, "error": "Нет ссылки на оплату в ответе ЮKassa"}
        url = url.strip()
        log.info("YooKassa payment created", payment_id=pid, user_id=user_id, amount_rub=amount_rub)
        return {"ok": True, "payment_id": pid, "status": status, "confirmation_url": url}
    except httpx.HTTPError as e:
        log.error("YooKassa request error", error=str(e))
        return {"ok": False, "error": "Ошибка связи с платёжной системой"}


async def get_payment(payment_id: str) -> dict:
    """Получить статус платежа из ЮKassa."""
    shop_id, secret_key = _get_yookassa_credentials()
    if not shop_id or not secret_key:
        return {"ok": False, "status": None, "error": "ЮKassa не настроена"}
    headers = {"Authorization": _auth_header(shop_id, secret_key)}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{API_URL}/payments/{payment_id}", headers=headers)
        try:
            data = r.json() if r.status_code in (200, 201) else {}
        except Exception:
            data = {}
        if r.status_code not in (200, 201):
            desc = (data.get("description") or data.get("message") or r.text or f"HTTP {r.status_code}")[:300]
            return {"ok": False, "status": None, "error": desc}
        return {"ok": True, "status": data.get("status"), "amount": data.get("amount")}
    except Exception as e:
        log.error("YooKassa get payment error", error=str(e), payment_id=payment_id)
        return {"ok": False, "status": None, "error": "Ошибка связи с ЮKassa"}


async def list_pending_yookassa_payments(limit: int = 25) -> list:
    from shared.db.database import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT payment_id, created_at
               FROM payments
               WHERE status = 'pending'
                 AND payment_id NOT LIKE 'stars_%'
                 AND payment_id NOT LIKE 'crypto_%'
                 AND payment_id NOT LIKE 'test_%'
               ORDER BY created_at ASC
               LIMIT $1""",
            int(limit or 25),
        )
    return list(rows)


async def reconcile_pending_payments(limit: int = 25) -> dict:
    rows = await list_pending_yookassa_payments(limit=limit)
    processed = 0
    confirmed = 0
    canceled = 0
    for row in rows:
        payment_id = str(row["payment_id"])
        res = await get_payment(payment_id)
        if not res.get("ok"):
            continue
        processed += 1
        status = (res.get("status") or "").strip().lower()
        if status == "succeeded":
            result = await process_payment_webhook(payment_id)
            if result.get("ok"):
                confirmed += 1
        elif status == "canceled":
            await log_payment_canceled(payment_id)
            canceled += 1
    if processed:
        log.info("yookassa_reconcile", processed=processed, confirmed=confirmed, canceled=canceled)
    return {"processed": processed, "confirmed": confirmed, "canceled": canceled}


async def _notify_user(user_id: int, text: str) -> None:
    """Отправить Telegram-сообщение юзеру напрямую через HTTP API."""
    from shared.config import settings

    if not settings.bot_token:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{settings.bot_token}/sendMessage",
                json={"chat_id": user_id, "text": text, "parse_mode": "HTML"},
            )
    except Exception as e:
        log.warning("notify_user failed", user_id=user_id, error=str(e))


async def _notify_admins(text: str) -> None:
    """Отправить уведомление всем админам (ADMIN_IDS)."""
    from shared.config import settings

    admin_ids = getattr(settings, "admin_id_list", None) or []
    if not admin_ids or not settings.bot_token:
        return
    for aid in admin_ids:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"https://api.telegram.org/bot{settings.bot_token}/sendMessage",
                    json={"chat_id": aid, "text": text, "parse_mode": "HTML"},
                )
        except Exception as e:
            log.warning("notify_admin failed", admin_id=aid, error=str(e))


async def process_payment_webhook(payment_id: str) -> dict:
    """
    Вызвать при получении webhook от ЮKassa (payment.succeeded).
    Проверяет статус в API, подтверждает платёж в БД, начисляет кредиты.
    """
    from shared.domain.credits import (
        UNLIMITED_DAYS,
        add_credits,
        confirm_payment_record,
        get_balance,
        get_credit_pack,
        get_payment_by_yookassa_id,
        get_unlimited_ends_at,
        set_unlimited_until,
    )

    res = await get_payment(payment_id)
    if not res.get("ok") or res.get("status") != "succeeded":
        log.warning("YooKassa webhook: payment not succeeded", payment_id=payment_id, status=res.get("status"))
        return {"ok": False, "error": "payment_not_succeeded"}
    row = await get_payment_by_yookassa_id(payment_id)
    if not row:
        log.warning("YooKassa webhook: payment_not_found in DB", payment_id=payment_id)
        return {"ok": False, "error": "payment_not_found"}
    paid_amount = res.get("amount", {})
    if paid_amount:
        try:
            paid_value = float(paid_amount.get("value", 0))
            expected_value = float(row["amount_rub"])
            if abs(paid_value - expected_value) > 0.01:
                log.error(
                    "Payment amount mismatch",
                    payment_id=payment_id,
                    paid=paid_value,
                    expected=expected_value,
                    user_id=row["user_id"],
                )
                return {"ok": False, "error": "amount_mismatch"}
        except (ValueError, TypeError):
            pass
    confirmed = await confirm_payment_record(payment_id)
    if not confirmed:
        return {"ok": True, "user_id": row["user_id"], "credits": 0, "already_confirmed": True}
    user_id = confirmed["user_id"]
    if confirmed["pack_name"] == "unlimited":
        await set_unlimited_until(user_id, days=UNLIMITED_DAYS)
        end_at = await get_unlimited_ends_at(user_id)
        end_str = end_at.strftime("%d.%m.%Y") if end_at and hasattr(end_at, "strftime") else ""
        await _notify_user(
            user_id,
            f"✅ <b>Оплата прошла!</b>\n\n♾️ Безлимит активен до <b>{end_str}</b> (30 дн.).\nВсе модели — без списания кредитов.",
        )
        await _notify_admins(
            f"💰 <b>Оплата ЮKassa</b>\nПользователь: <code>{user_id}</code>\nПакет: ♾️ Безлимит\nСумма: {confirmed['amount_rub']} ₽"
        )
        try:
            from shared.config import settings
            from shared.domain.payment_notify import send_payment_notification_to_admin

            bot_name = f"@{settings.bot_username}" if getattr(settings, "bot_username", None) else "НейроБокс"
            await send_payment_notification_to_admin(
                bot_name=bot_name,
                pack_label="♾️ Безлимит 30 дн.",
                user_id=user_id,
                amount_str=f"{confirmed['amount_rub']} ₽",
                method="yookassa",
            )
        except Exception:
            pass
        try:
            from shared.domain.analytics import track_payment_success

            await track_payment_success(
                user_id=user_id,
                payment_id=payment_id,
                method="yookassa",
                pack_name=confirmed.get("pack_name", ""),
                amount_rub=float(confirmed.get("amount_rub") or 0),
                credits=int(confirmed.get("credits_amount") or 0),
                is_test=False,
            )
        except Exception:
            pass
        return {"ok": True, "user_id": user_id, "credits": 0, "unlimited": True}

    pack = await get_credit_pack(confirmed["pack_name"]) or {}
    await add_credits(
        user_id,
        confirmed["credits_amount"],
        "purchase",
        f"{pack.get('label', confirmed['pack_name'])} ({confirmed['amount_rub']} ₽)",
    )
    bal = await get_balance(user_id)
    await _notify_user(
        user_id,
        f"✅ <b>Оплата прошла!</b>\n\n💎 +{confirmed['credits_amount']:,} CR зачислены.\n💰 Баланс: <b>{bal['total']} CR</b>",
    )
    pack_label = pack.get("label", confirmed["pack_name"])
    await _notify_admins(
        f"💰 <b>Оплата ЮKassa</b>\nПользователь: <code>{user_id}</code>\nПакет: {pack_label} — {confirmed['credits_amount']} CR\nСумма: {confirmed['amount_rub']} ₽"
    )
    try:
        from shared.config import settings
        from shared.domain.payment_notify import send_payment_notification_to_admin

        bot_name = f"@{settings.bot_username}" if getattr(settings, "bot_username", None) else "НейроБокс"
        await send_payment_notification_to_admin(
            bot_name=bot_name,
            pack_label=f"{pack_label} — {confirmed['credits_amount']} CR",
            user_id=user_id,
            amount_str=f"{confirmed['amount_rub']} ₽",
            method="yookassa",
        )
    except Exception:
        pass
    try:
        from shared.domain.analytics import track_payment_success

        await track_payment_success(
            user_id=user_id,
            payment_id=payment_id,
            method="yookassa",
            pack_name=confirmed.get("pack_name", ""),
            amount_rub=float(confirmed.get("amount_rub") or 0),
            credits=int(confirmed.get("credits_amount") or 0),
            is_test=False,
        )
    except Exception:
        pass
    return {"ok": True, "user_id": user_id, "credits": confirmed["credits_amount"]}


async def log_payment_canceled(payment_id: str) -> None:
    """При получении payment.canceled — обновить статус в БД и залогировать."""
    from shared.db.database import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, amount_rub, pack_name, credits_amount FROM payments WHERE payment_id = $1",
            payment_id,
        )
        await conn.execute(
            "UPDATE payments SET status = 'canceled' WHERE payment_id = $1 AND status = 'pending'",
            payment_id,
        )
    if row:
        log.info("YooKassa payment canceled", payment_id=payment_id, user_id=row["user_id"], amount_rub=row["amount_rub"])
        try:
            from shared.domain.analytics import track_payment_failed

            await track_payment_failed(
                user_id=row["user_id"],
                method="yookassa",
                pack_name=row["pack_name"],
                amount_rub=float(row["amount_rub"] or 0),
                credits=int(row["credits_amount"] or 0),
                reason="canceled",
                payment_id=payment_id,
            )
        except Exception:
            pass


async def process_refund_webhook(refund_obj: dict) -> dict:
    """Обработка refund.succeeded: списание кредитов у пользователя по исходному платежу."""
    payment_id = refund_obj.get("payment_id")
    if not payment_id:
        return {"ok": False, "error": "no_payment_id"}
    from shared.domain.credits import deduct_credits_refund, get_payment_by_yookassa_id

    row = await get_payment_by_yookassa_id(str(payment_id))
    if not row or row["status"] != "confirmed":
        log.warning("YooKassa refund: payment not found or not confirmed", payment_id=payment_id)
        return {"ok": False, "error": "payment_not_found_or_not_confirmed"}
    amount_refund_rub = refund_obj.get("amount", {})
    if isinstance(amount_refund_rub, dict):
        amount_refund_rub = float(amount_refund_rub.get("value", 0))
    else:
        amount_refund_rub = float(amount_refund_rub or 0)
    original_rub = float(row["amount_rub"])
    credits_amount = int(row["credits_amount"])
    if original_rub <= 0:
        return {"ok": False, "error": "invalid_original_amount"}
    deduct_credits = max(0, int(round(credits_amount * amount_refund_rub / original_rub)))
    if deduct_credits <= 0:
        return {"ok": True, "deducted": 0}
    result = await deduct_credits_refund(
        row["user_id"],
        deduct_credits,
        description=f"Возврат ЮKassa {amount_refund_rub:.0f} ₽ (платёж {payment_id})",
    )
    if result.get("ok"):
        log.info("YooKassa refund processed", payment_id=payment_id, user_id=row["user_id"], deducted=result.get("deducted", 0))
    return result
