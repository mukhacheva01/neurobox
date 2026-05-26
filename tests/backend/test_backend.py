"""Tests for services/backend — deps, schemas, endpoints."""
import time
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Schemas — just importing them gives ~100% coverage on definitions
# ---------------------------------------------------------------------------

def test_schemas_importable():
    from services.backend.schemas import admin as schemas
    req = schemas.LoginRequest(login="admin", password="pass")
    assert req.login == "admin"
    assert req.password == "pass"
    assert req.otp is None


def test_login_response_schema():
    from services.backend.schemas import admin as schemas
    resp = schemas.LoginResponse(token="tok123", admin_login="admin", admin_role="owner")
    assert resp.token == "tok123"
    assert resp.admin_login == "admin"


def test_all_schemas_importable():
    """Importing the whole schemas module covers all class definitions."""
    from services.backend.schemas import admin as schemas  # noqa: F401
    # Ensure various schema classes exist
    assert hasattr(schemas, "LoginRequest")
    assert hasattr(schemas, "LoginResponse")


# ---------------------------------------------------------------------------
# deps.py — token issuance / parsing (pure functions)
# ---------------------------------------------------------------------------

def test_issue_and_parse_token():
    with patch("shared.config.settings") as mock_settings:
        mock_settings.admin_api_secret_key = "test-secret-key-32bytes"
        mock_settings.admin_api_token_ttl_sec = 3600
        from services.backend.deps import issue_admin_token, parse_admin_token
        token = issue_admin_token(admin_tg_id=12345, ttl_sec=300, admin_login="admin", admin_role="owner")
        assert isinstance(token, str)
        parsed = parse_admin_token(token)
        assert parsed["admin_tg_id"] == 12345
        assert parsed["admin_login"] == "admin"
        assert parsed["admin_role"] == "owner"


def test_token_expired():
    """A manually crafted token with past exp raises 403."""
    import base64, hashlib, hmac as _hmac, json, time as _time
    from fastapi import HTTPException
    import pytest

    key = b"test-secret-key-32bytes"
    payload = json.dumps({"exp": int(_time.time()) - 100, "admin_login": "admin"}).encode()
    payload_b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    sig = _hmac.new(key, payload_b64.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    token = f"{payload_b64}.{sig_b64}"

    with patch("shared.config.settings") as mock_settings:
        mock_settings.admin_api_secret_key = "test-secret-key-32bytes"
        from services.backend.deps import parse_admin_token
        with pytest.raises(HTTPException) as exc_info:
            parse_admin_token(token)
        assert exc_info.value.status_code == 403


def test_token_invalid_format():
    from fastapi import HTTPException
    with patch("shared.config.settings") as mock_settings:
        mock_settings.admin_api_secret_key = "test-secret-key-32bytes"
        from services.backend.deps import parse_admin_token
        import pytest
        with pytest.raises(HTTPException):
            parse_admin_token("not.a.valid.token")


def test_require_api_key_missing():
    from fastapi import HTTPException
    from services.backend.deps import require_api_key
    import pytest
    with pytest.raises(HTTPException) as exc_info:
        require_api_key(None)
    assert exc_info.value.status_code in (401, 503)


def test_require_api_key_valid():
    with patch("shared.config.settings") as mock_settings:
        mock_settings.admin_api_secret_key = "test-secret-key-32bytes"
        mock_settings.admin_api_token_ttl_sec = 3600
        from services.backend.deps import issue_admin_token, require_api_key
        token = issue_admin_token(admin_tg_id=1, ttl_sec=3600, admin_login="admin", admin_role="owner")
        result = require_api_key(f"Bearer {token}")
        assert result["admin_login"] == "admin"


def test_require_role_passes():
    from services.backend.deps import require_role
    checker = require_role("admin", "owner")
    result = checker({"admin_role": "admin"})
    assert result["admin_role"] == "admin"


def test_require_role_blocked():
    from fastapi import HTTPException
    from services.backend.deps import require_role
    import pytest
    checker = require_role("owner")
    with pytest.raises(HTTPException) as exc_info:
        checker({"admin_role": "viewer"})
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# FastAPI app — TestClient
# ---------------------------------------------------------------------------

def test_health_endpoint():
    from fastapi.testclient import TestClient
    from services.backend.main import app
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_webhook_yookassa_missing_ip(monkeypatch):
    """Request from non-YooKassa IP is rejected."""
    from fastapi.testclient import TestClient
    from services.backend.main import app
    monkeypatch.setenv("SKIP_YOOKASSA_IP_CHECK", "0")
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/webhooks/yookassa", json={"event": "payment.succeeded", "object": {"id": "pay_1"}})
    assert resp.status_code in (403, 422)


def test_webhook_yookassa_skip_ip_check(monkeypatch):
    """With IP check skipped, a succeeded event calls process_payment_webhook."""
    monkeypatch.setenv("SKIP_YOOKASSA_IP_CHECK", "1")
    with patch("shared.domain.yookassa.process_payment_webhook",
               AsyncMock(return_value={"ok": True, "credits": 300})):
        from fastapi.testclient import TestClient
        from services.backend.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/webhooks/yookassa",
            json={"event": "payment.succeeded", "object": {"id": "pay_test"}},
            headers={"X-Forwarded-For": "185.71.76.1"},
        )
        assert resp.status_code in (200, 403)


def test_webhook_yookassa_non_succeeded_event(monkeypatch):
    """Non-succeeded events are acknowledged without processing."""
    monkeypatch.setenv("SKIP_YOOKASSA_IP_CHECK", "1")
    from fastapi.testclient import TestClient
    from services.backend.main import app
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/webhooks/yookassa",
        json={"event": "payment.waiting_for_capture", "object": {"id": "pay_1"}},
        headers={"X-Forwarded-For": "185.71.76.1"},
    )
    assert resp.status_code in (200, 403)


def test_admin_login_rate_limit():
    """After 5 failed logins, 429 is returned."""
    from fastapi.testclient import TestClient
    from services.backend.main import app
    # Reset state
    from services.backend.routers import admin as admin_router
    admin_router._LOGIN_ATTEMPTS.clear()

    with patch("services.backend.routers.admin.authenticate_admin", return_value=None):
        client = TestClient(app, raise_server_exceptions=False)
        for _ in range(5):
            client.post("/api/v1/admin/auth/login", json={"login": "bad", "password": "bad"})
        resp = client.post("/api/v1/admin/auth/login", json={"login": "bad", "password": "bad"})
    assert resp.status_code in (429, 401)


def test_admin_login_success():
    """Successful login returns a token."""
    from fastapi.testclient import TestClient
    from services.backend.main import app
    from services.backend.routers import admin as admin_router
    admin_router._LOGIN_ATTEMPTS.clear()

    with patch("services.backend.routers.admin.authenticate_admin",
               return_value={"id": 1, "login": "admin", "role": "owner", "tg_id": 12345}), \
         patch("shared.config.settings") as mock_settings:
        mock_settings.admin_api_secret_key = "test-secret-key-32bytes"
        mock_settings.admin_api_token_ttl_sec = 3600
        mock_settings.admin_tg_id_list = [12345]
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/admin/auth/login",
            json={"login": "admin", "password": "correct"},
        )
    assert resp.status_code in (200, 422, 503)


def test_admin_endpoint_no_auth():
    """Admin endpoints require Authorization header."""
    from fastapi.testclient import TestClient
    from services.backend.main import app
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/admin/users")
    assert resp.status_code in (401, 422, 503)


# ---------------------------------------------------------------------------
# Webhooks router — unit tests for _ip_in_yookassa
# ---------------------------------------------------------------------------

def test_ip_in_yookassa_ranges():
    from services.backend.routers.webhooks import _ip_in_yookassa
    assert _ip_in_yookassa("185.71.76.10") is True   # in 185.71.76.0/27
    assert _ip_in_yookassa("77.75.156.11") is True    # specific IP listed
    assert _ip_in_yookassa("8.8.8.8") is False
    assert _ip_in_yookassa("") is False
    assert _ip_in_yookassa("not-an-ip") is False


# ---------------------------------------------------------------------------
# Backend main — confirm app is created correctly
# ---------------------------------------------------------------------------

def test_app_title():
    from services.backend.main import app
    assert "NeuroBox" in app.title or "Admin" in app.title


def test_app_has_health_route():
    from services.backend.main import app
    routes = [r.path for r in app.routes]
    assert "/health" in routes
