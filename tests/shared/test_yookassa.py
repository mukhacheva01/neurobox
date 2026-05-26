"""Tests for shared/domain/yookassa.py."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _auth_header
# ---------------------------------------------------------------------------

def test_auth_header():
    from shared.domain.yookassa import _auth_header
    header = _auth_header("shop123", "secret456")
    assert header.startswith("Basic ")
    import base64
    decoded = base64.b64decode(header[6:]).decode()
    assert decoded == "shop123:secret456"


# ---------------------------------------------------------------------------
# _get_yookassa_credentials
# ---------------------------------------------------------------------------

def test_get_yookassa_credentials_empty():
    from shared.config import settings
    with patch.object(settings, "yookassa_shop_id", ""), \
         patch.object(settings, "yookassa_secret_key", ""):
        from shared.domain.yookassa import _get_yookassa_credentials
        shop_id, secret = _get_yookassa_credentials()
        assert shop_id == ""
        assert secret == ""


def test_get_yookassa_credentials_set():
    from shared.config import settings
    with patch.object(settings, "yookassa_shop_id", "  12345  "), \
         patch.object(settings, "yookassa_secret_key", "  mysecret  "):
        from shared.domain.yookassa import _get_yookassa_credentials
        shop_id, secret = _get_yookassa_credentials()
        assert shop_id == "12345"
        assert secret == "mysecret"


# ---------------------------------------------------------------------------
# get_yookassa_availability
# ---------------------------------------------------------------------------

async def test_get_yookassa_availability_no_credentials():
    from shared.config import settings
    with patch.object(settings, "yookassa_shop_id", ""), \
         patch.object(settings, "yookassa_secret_key", ""):
        from shared.domain.yookassa import get_yookassa_availability
        result = await get_yookassa_availability()
        assert result["available"] is False
        assert result["reason"] == "credentials_missing"


async def test_get_yookassa_availability_ok():
    from shared.config import settings
    with patch.object(settings, "yookassa_shop_id", "shop1"), \
         patch.object(settings, "yookassa_secret_key", "secret1"):
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.domain.yookassa.httpx.AsyncClient", return_value=mock_client):
            from shared.domain.yookassa import get_yookassa_availability
            result = await get_yookassa_availability()
            assert result["available"] is True


async def test_get_yookassa_availability_401():
    from shared.config import settings
    with patch.object(settings, "yookassa_shop_id", "shop1"), \
         patch.object(settings, "yookassa_secret_key", "wrong"):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"description": "Unauthorized"}
        mock_resp.text = "Unauthorized"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.domain.yookassa.httpx.AsyncClient", return_value=mock_client):
            from shared.domain.yookassa import get_yookassa_availability
            result = await get_yookassa_availability()
            assert result["available"] is False
            assert result["reason"] == "credentials_invalid"


async def test_get_yookassa_availability_server_error():
    from shared.config import settings
    with patch.object(settings, "yookassa_shop_id", "shop1"), \
         patch.object(settings, "yookassa_secret_key", "secret1"):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {}
        mock_resp.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.domain.yookassa.httpx.AsyncClient", return_value=mock_client):
            from shared.domain.yookassa import get_yookassa_availability
            result = await get_yookassa_availability()
            assert result["available"] is False
            assert result["reason"] == "api_error"


async def test_get_yookassa_availability_network_error():
    import httpx
    from shared.config import settings
    with patch.object(settings, "yookassa_shop_id", "shop1"), \
         patch.object(settings, "yookassa_secret_key", "secret1"):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Network error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.domain.yookassa.httpx.AsyncClient", return_value=mock_client):
            from shared.domain.yookassa import get_yookassa_availability
            result = await get_yookassa_availability()
            assert result["available"] is False
            assert result["reason"] == "network_error"


# ---------------------------------------------------------------------------
# create_payment
# ---------------------------------------------------------------------------

async def test_create_payment_no_credentials():
    from shared.config import settings
    with patch.object(settings, "yookassa_shop_id", ""), \
         patch.object(settings, "yookassa_secret_key", ""):
        from shared.domain.yookassa import create_payment
        result = await create_payment(99.0, "lite", 300, 1, "https://example.com/return")
        assert result["ok"] is False
        assert "не настроена" in result["error"]


async def test_create_payment_success():
    from shared.config import settings
    with patch.object(settings, "yookassa_shop_id", "shop1"), \
         patch.object(settings, "yookassa_secret_key", "secret1"), \
         patch.object(settings, "yookassa_receipt_email", ""):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {
            "id": "pay_abc123",
            "status": "pending",
            "confirmation": {"confirmation_url": "https://yookassa.ru/pay/abc123"},
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.domain.yookassa.httpx.AsyncClient", return_value=mock_client):
            from shared.domain.yookassa import create_payment
            result = await create_payment(99.0, "lite", 300, 1, "https://example.com/return")
            assert result["ok"] is True
            assert result["payment_id"] == "pay_abc123"
            assert "confirmation_url" in result


async def test_create_payment_api_error():
    from shared.config import settings
    with patch.object(settings, "yookassa_shop_id", "shop1"), \
         patch.object(settings, "yookassa_secret_key", "secret1"), \
         patch.object(settings, "yookassa_receipt_email", ""):
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_resp.json.return_value = {"description": "Invalid amount", "code": "invalid_request"}
        mock_resp.text = "Invalid amount"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.domain.yookassa.httpx.AsyncClient", return_value=mock_client):
            from shared.domain.yookassa import create_payment
            result = await create_payment(99.0, "lite", 300, 1, "https://example.com/return")
            assert result["ok"] is False


async def test_create_payment_no_confirmation_url():
    from shared.config import settings
    with patch.object(settings, "yookassa_shop_id", "shop1"), \
         patch.object(settings, "yookassa_secret_key", "secret1"), \
         patch.object(settings, "yookassa_receipt_email", ""):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "pay_xyz",
            "status": "pending",
            "confirmation": {},  # no confirmation_url
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.domain.yookassa.httpx.AsyncClient", return_value=mock_client):
            from shared.domain.yookassa import create_payment
            result = await create_payment(99.0, "lite", 300, 1, "https://example.com/return")
            assert result["ok"] is False
            assert "ссылки" in result["error"]


async def test_create_payment_http_error():
    import httpx
    from shared.config import settings
    with patch.object(settings, "yookassa_shop_id", "shop1"), \
         patch.object(settings, "yookassa_secret_key", "secret1"), \
         patch.object(settings, "yookassa_receipt_email", ""):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.HTTPError("connection failed"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.domain.yookassa.httpx.AsyncClient", return_value=mock_client):
            from shared.domain.yookassa import create_payment
            result = await create_payment(99.0, "lite", 300, 1, "https://example.com/return")
            assert result["ok"] is False


async def test_create_payment_with_receipt():
    """Test that receipt block is added when yookassa_receipt_email is set."""
    from shared.config import settings
    with patch.object(settings, "yookassa_shop_id", "shop1"), \
         patch.object(settings, "yookassa_secret_key", "secret1"), \
         patch.object(settings, "yookassa_receipt_email", "receipt@example.com"):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "pay_with_receipt",
            "status": "pending",
            "confirmation": {"confirmation_url": "https://yookassa.ru/pay/withreceipt"},
        }

        captured_payload = {}

        async def mock_post(url, json=None, headers=None, **kwargs):
            captured_payload.update(json or {})
            return mock_resp

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.domain.yookassa.httpx.AsyncClient", return_value=mock_client):
            from shared.domain.yookassa import create_payment
            result = await create_payment(99.0, "lite", 300, 1, "https://example.com/return")
            assert result["ok"] is True
            assert "receipt" in captured_payload


# ---------------------------------------------------------------------------
# get_payment
# ---------------------------------------------------------------------------

async def test_get_payment_no_credentials():
    from shared.config import settings
    with patch.object(settings, "yookassa_shop_id", ""), \
         patch.object(settings, "yookassa_secret_key", ""):
        from shared.domain.yookassa import get_payment
        result = await get_payment("pay_123")
        assert result["ok"] is False
        assert result["status"] is None


async def test_get_payment_success():
    from shared.config import settings
    with patch.object(settings, "yookassa_shop_id", "shop1"), \
         patch.object(settings, "yookassa_secret_key", "secret1"):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "succeeded",
            "amount": {"value": "99.00", "currency": "RUB"},
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.domain.yookassa.httpx.AsyncClient", return_value=mock_client):
            from shared.domain.yookassa import get_payment
            result = await get_payment("pay_123")
            assert result["ok"] is True
            assert result["status"] == "succeeded"


async def test_get_payment_error_status():
    from shared.config import settings
    with patch.object(settings, "yookassa_shop_id", "shop1"), \
         patch.object(settings, "yookassa_secret_key", "secret1"):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.json.return_value = {"description": "Not found"}
        mock_resp.text = "Not found"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.domain.yookassa.httpx.AsyncClient", return_value=mock_client):
            from shared.domain.yookassa import get_payment
            result = await get_payment("pay_404")
            assert result["ok"] is False


async def test_get_payment_exception():
    from shared.config import settings
    with patch.object(settings, "yookassa_shop_id", "shop1"), \
         patch.object(settings, "yookassa_secret_key", "secret1"):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("connection error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.domain.yookassa.httpx.AsyncClient", return_value=mock_client):
            from shared.domain.yookassa import get_payment
            result = await get_payment("pay_fail")
            assert result["ok"] is False


# ---------------------------------------------------------------------------
# process_payment_webhook
# ---------------------------------------------------------------------------

async def test_process_payment_webhook_not_succeeded():
    with patch("shared.domain.yookassa.get_payment", AsyncMock(return_value={"ok": True, "status": "pending"})):
        from shared.domain.yookassa import process_payment_webhook
        result = await process_payment_webhook("pay_123")
        assert result["ok"] is False
        assert result["error"] == "payment_not_succeeded"


async def test_process_payment_webhook_payment_not_found_in_db():
    with patch("shared.domain.yookassa.get_payment", AsyncMock(return_value={"ok": True, "status": "succeeded"})), \
         patch("shared.domain.credits.get_payment_by_yookassa_id", AsyncMock(return_value=None)):
        from shared.domain.yookassa import process_payment_webhook
        result = await process_payment_webhook("pay_123")
        assert result["ok"] is False
        assert result["error"] == "payment_not_found"


async def test_process_payment_webhook_amount_mismatch():
    with patch("shared.domain.yookassa.get_payment", AsyncMock(return_value={
        "ok": True,
        "status": "succeeded",
        "amount": {"value": "50.00", "currency": "RUB"},
    })), \
    patch("shared.domain.credits.get_payment_by_yookassa_id", AsyncMock(return_value={
        "user_id": 1,
        "amount_rub": 99.0,
        "credits_amount": 300,
        "pack_name": "lite",
        "status": "pending",
    })):
        from shared.domain.yookassa import process_payment_webhook
        result = await process_payment_webhook("pay_123")
        assert result["ok"] is False
        assert result["error"] == "amount_mismatch"


async def test_process_payment_webhook_already_confirmed():
    with patch("shared.domain.yookassa.get_payment", AsyncMock(return_value={
        "ok": True, "status": "succeeded",
    })), \
    patch("shared.domain.credits.get_payment_by_yookassa_id", AsyncMock(return_value={
        "user_id": 1, "amount_rub": 99.0, "credits_amount": 300, "pack_name": "lite",
    })), \
    patch("shared.domain.credits.confirm_payment_record", AsyncMock(return_value=None)):
        from shared.domain.yookassa import process_payment_webhook
        result = await process_payment_webhook("pay_confirmed")
        assert result["ok"] is True
        assert result.get("already_confirmed") is True


async def test_process_payment_webhook_credits_success():
    confirmed_row = {
        "user_id": 1,
        "amount_rub": 99.0,
        "credits_amount": 300,
        "pack_name": "lite",
        "confirmed_at": None,
    }
    with patch("shared.domain.yookassa.get_payment", AsyncMock(return_value={
        "ok": True, "status": "succeeded",
    })), \
    patch("shared.domain.credits.get_payment_by_yookassa_id", AsyncMock(return_value=confirmed_row)), \
    patch("shared.domain.credits.confirm_payment_record", AsyncMock(return_value=confirmed_row)), \
    patch("shared.domain.credits.get_credit_pack", AsyncMock(return_value={"label": "Лайт"})), \
    patch("shared.domain.credits.add_credits", AsyncMock(return_value={"ok": True, "new_balance": 300})), \
    patch("shared.domain.credits.get_balance", AsyncMock(return_value={"total": 300})), \
    patch("shared.domain.yookassa._notify_user", AsyncMock()), \
    patch("shared.domain.yookassa._notify_admins", AsyncMock()):
        from shared.domain.yookassa import process_payment_webhook
        result = await process_payment_webhook("pay_success")
        assert result["ok"] is True
        assert result["credits"] == 300


async def test_process_payment_webhook_unlimited():
    confirmed_row = {
        "user_id": 2,
        "amount_rub": 2990.0,
        "credits_amount": 0,
        "pack_name": "unlimited",
        "confirmed_at": None,
    }
    from datetime import datetime, timezone
    with patch("shared.domain.yookassa.get_payment", AsyncMock(return_value={
        "ok": True, "status": "succeeded",
    })), \
    patch("shared.domain.credits.get_payment_by_yookassa_id", AsyncMock(return_value=confirmed_row)), \
    patch("shared.domain.credits.confirm_payment_record", AsyncMock(return_value=confirmed_row)), \
    patch("shared.domain.credits.set_unlimited_until", AsyncMock()), \
    patch("shared.domain.credits.get_unlimited_ends_at", AsyncMock(return_value=datetime(2026, 6, 1, tzinfo=timezone.utc))), \
    patch("shared.domain.yookassa._notify_user", AsyncMock()), \
    patch("shared.domain.yookassa._notify_admins", AsyncMock()):
        from shared.domain.yookassa import process_payment_webhook
        result = await process_payment_webhook("pay_unlimited")
        assert result["ok"] is True
        assert result.get("unlimited") is True


# ---------------------------------------------------------------------------
# process_refund_webhook
# ---------------------------------------------------------------------------

async def test_process_refund_webhook_no_payment_id():
    from shared.domain.yookassa import process_refund_webhook
    result = await process_refund_webhook({})
    assert result["ok"] is False
    assert result["error"] == "no_payment_id"


async def test_process_refund_webhook_payment_not_found():
    with patch("shared.domain.credits.get_payment_by_yookassa_id", AsyncMock(return_value=None)):
        from shared.domain.yookassa import process_refund_webhook
        result = await process_refund_webhook({"payment_id": "pay_123"})
        assert result["ok"] is False


async def test_process_refund_webhook_not_confirmed():
    with patch("shared.domain.credits.get_payment_by_yookassa_id", AsyncMock(return_value={
        "status": "pending",
        "user_id": 1, "amount_rub": 99.0, "credits_amount": 300
    })):
        from shared.domain.yookassa import process_refund_webhook
        result = await process_refund_webhook({"payment_id": "pay_123"})
        assert result["ok"] is False


async def test_process_refund_webhook_invalid_original_amount():
    with patch("shared.domain.credits.get_payment_by_yookassa_id", AsyncMock(return_value={
        "status": "confirmed",
        "user_id": 1, "amount_rub": 0.0, "credits_amount": 300
    })):
        from shared.domain.yookassa import process_refund_webhook
        result = await process_refund_webhook({
            "payment_id": "pay_123",
            "amount": {"value": "99.00"},
        })
        assert result["ok"] is False
        assert result["error"] == "invalid_original_amount"


async def test_process_refund_webhook_success():
    with patch("shared.domain.credits.get_payment_by_yookassa_id", AsyncMock(return_value={
        "status": "confirmed",
        "user_id": 1, "amount_rub": 99.0, "credits_amount": 300
    })), \
    patch("shared.domain.credits.deduct_credits_refund", AsyncMock(return_value={"ok": True, "deducted": 300})):
        from shared.domain.yookassa import process_refund_webhook
        result = await process_refund_webhook({
            "payment_id": "pay_123",
            "amount": {"value": "99.00"},
        })
        assert result["ok"] is True
        assert result["deducted"] == 300


async def test_process_refund_webhook_zero_deduct():
    """If computed deduct_credits is zero, return ok=True without deducting."""
    with patch("shared.domain.credits.get_payment_by_yookassa_id", AsyncMock(return_value={
        "status": "confirmed",
        "user_id": 1, "amount_rub": 100.0, "credits_amount": 0
    })):
        from shared.domain.yookassa import process_refund_webhook
        result = await process_refund_webhook({
            "payment_id": "pay_123",
            "amount": {"value": "0.00"},
        })
        assert result["ok"] is True
        assert result["deducted"] == 0


# ---------------------------------------------------------------------------
# _ip_in_yookassa (not in yookassa.py but in webhooks.py — test here too)
# ---------------------------------------------------------------------------

def test_ip_in_yookassa_valid():
    from services.backend.routers.webhooks import _ip_in_yookassa
    # Known YooKassa IP range
    assert _ip_in_yookassa("185.71.76.1") is True
    assert _ip_in_yookassa("77.75.156.11") is True


def test_ip_in_yookassa_invalid():
    from services.backend.routers.webhooks import _ip_in_yookassa
    assert _ip_in_yookassa("1.2.3.4") is False
    assert _ip_in_yookassa("") is False


def test_ip_in_yookassa_bad_ip():
    from services.backend.routers.webhooks import _ip_in_yookassa
    assert _ip_in_yookassa("not-an-ip") is False
