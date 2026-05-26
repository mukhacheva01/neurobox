"""YooKassa and CryptoBot webhook endpoints."""
import ipaddress
import json
import os

import structlog
from fastapi import APIRouter, Request, Response

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
_log = structlog.get_logger()

YOOKASSA_IPS = {
    "185.71.76.0/27", "185.71.77.0/27", "77.75.153.0/25", "77.75.156.11",
    "77.75.156.35", "77.75.154.128/25", "2a02:5180::/32",
}


def _get_client_ip(request: Request) -> str:
    x_real = (request.headers.get("X-Real-IP") or "").strip()
    if x_real:
        return x_real
    xff = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    if xff:
        return xff
    if request.client:
        return str(request.client.host)
    return ""


def _ip_in_yookassa(ip: str) -> bool:
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip.strip())
        for net in YOOKASSA_IPS:
            if "/" in net:
                if addr in ipaddress.ip_network(net, strict=False):
                    return True
            else:
                if addr == ipaddress.ip_address(net):
                    return True
    except Exception:
        pass
    return False


@router.post("/yookassa")
async def yookassa_webhook(request: Request) -> Response:
    skip_ip_check = os.environ.get("SKIP_YOOKASSA_IP_CHECK", "").strip().lower() in ("1", "true", "yes")
    client_ip = _get_client_ip(request)

    if not skip_ip_check and not _ip_in_yookassa(client_ip):
        _log.warning("yookassa_webhook_rejected", client_ip=client_ip)
        return Response(status_code=403, content="Forbidden")

    try:
        body = await request.json()
    except Exception as e:
        _log.warning("yookassa_webhook_invalid_json", error=str(e))
        return Response(status_code=400, content="Invalid JSON")

    event = body.get("event")
    obj = body.get("object") or body.get("payment") or {}
    if not isinstance(obj, dict):
        obj = {}
    payment_id = obj.get("id")
    if not payment_id and isinstance(body.get("id"), str):
        payment_id = body.get("id")

    if event == "payment.canceled" and payment_id:
        from shared.domain.yookassa import log_payment_canceled
        await log_payment_canceled(str(payment_id).strip())
        return Response(content=json.dumps({"ok": True, "event": "payment.canceled"}), media_type="application/json")

    if event == "refund.succeeded":
        from shared.domain.yookassa import process_refund_webhook
        result = await process_refund_webhook(obj)
        return Response(content=json.dumps({"ok": result.get("ok"), "event": "refund.succeeded"}), media_type="application/json")

    if event != "payment.succeeded" or not payment_id:
        return Response(content="ignored")

    payment_id = str(payment_id).strip()
    from shared.domain.yookassa import process_payment_webhook
    result = await process_payment_webhook(payment_id)
    if result.get("ok"):
        _log.info("yookassa_webhook_processed", payment_id=payment_id, credits=result.get("credits", 0))
        return Response(content=json.dumps({"ok": True, "credits": result.get("credits", 0)}), media_type="application/json")

    _log.warning("yookassa_webhook_failed", payment_id=payment_id, error=result.get("error"))
    return Response(content=json.dumps({"ok": False, "error": result.get("error", "unknown")}), media_type="application/json")


@router.post("/cryptobot")
async def cryptobot_webhook(request: Request) -> Response:
    try:
        body = await request.json()
    except Exception:
        return Response(status_code=400, content="Invalid JSON")

    if body.get("update_type") != "invoice_paid":
        return Response(content="ignored")

    payload = body.get("payload", {})
    from shared.domain.cryptobot import process_crypto_webhook
    result = await process_crypto_webhook(payload)
    return Response(content=json.dumps(result), media_type="application/json")
