"""Проверка Authorization: Bearer {token} с HMAC-подписью и сроком жизни."""
import base64
import hashlib
import hmac
import json
import time

from fastapi import Depends, Header, HTTPException, status


def _secret_key() -> str:
    from shared.config import settings
    key = (settings.admin_api_secret_key or "").strip()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API not configured (ADMIN_API_SECRET_KEY)",
        )
    return key


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def issue_admin_token(
    admin_tg_id: int | None = None,
    ttl_sec: int = 3600,
    admin_user_id: int | None = None,
    admin_login: str | None = None,
    admin_role: str | None = None,
) -> str:
    key = _secret_key().encode()
    now = int(time.time())
    payload = {
        "sub": "admin",
        "iat": now,
        "exp": now + max(60, int(ttl_sec)),
        "admin_tg_id": admin_tg_id,
        "admin_user_id": admin_user_id,
        "admin_login": admin_login,
        "admin_role": admin_role or "viewer",
    }
    payload_raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    payload_b64 = _b64url_encode(payload_raw)
    sig = hmac.new(key, payload_b64.encode(), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64url_encode(sig)}"


def parse_admin_token(token: str) -> dict:
    key = _secret_key().encode()
    if "." not in token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token format")
    payload_b64, sig_b64 = token.split(".", 1)
    expected_sig = hmac.new(key, payload_b64.encode(), hashlib.sha256).digest()
    got_sig = _b64url_decode(sig_b64)
    if not hmac.compare_digest(expected_sig, got_sig):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token signature")
    try:
        payload = json.loads(_b64url_decode(payload_b64).decode())
    except Exception:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token payload")
    now = int(time.time())
    exp = int(payload.get("exp") or 0)
    if exp <= now:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token expired")
    return payload


def require_api_key(authorization: str | None = Header(None, alias="Authorization")):
    _secret_key()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing or invalid Authorization header")
    token = authorization[7:].strip()
    payload = parse_admin_token(token)
    return payload


def require_role(*allowed_roles: str):
    allowed = set(allowed_roles)

    def _checker(payload: dict = Depends(require_api_key)):
        role = (payload.get("admin_role") or "viewer").strip().lower()
        if role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return payload

    return _checker
