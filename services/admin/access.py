"""Auth, RBAC and session helpers for Flask admin panel."""
from __future__ import annotations

from functools import wraps

import httpx
from flask import redirect, request, session, url_for

from services.admin.backend_client import post_json

ROLE_VIEWER = "viewer"
ROLE_SUPPORT = "support"
ROLE_ADMIN = "admin"
ROLE_OWNER = "owner"
ALL_ROLES = {ROLE_VIEWER, ROLE_SUPPORT, ROLE_ADMIN, ROLE_OWNER}


def ensure_admin_bootstrap() -> None:
    """Bootstrap now belongs to backend auth config."""
    return None


def authenticate_admin(login: str, password: str, otp: str | None = None) -> dict | None:
    try:
        response = post_json(
            "/api/v1/admin/auth/login",
            payload={
                "login": login,
                "password": password,
                "otp": otp,
            },
        )
    except httpx.HTTPError:
        return None

    if response.status_code == 429:
        return {"rate_limited": True}
    if response.status_code == 401:
        return None
    try:
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None

    if payload.get("otp_required"):
        return {"otp_required": True, "login": login}

    role = (payload.get("admin_role") or ROLE_OWNER).strip().lower()
    if role not in ALL_ROLES:
        role = ROLE_OWNER if role == "superadmin" else ROLE_VIEWER
    token = (payload.get("token") or "").strip()
    if not token:
        return None
    return {
        "id": payload.get("admin_user_id"),
        "login": payload.get("admin_login") or login,
        "role": role,
        "tg_id": payload.get("admin_tg_id"),
        "token": token,
    }


def current_admin() -> dict:
    return {
        "id": session.get("admin_user_id"),
        "login": session.get("admin_login"),
        "role": session.get("admin_role", ROLE_VIEWER),
        "token": session.get("admin_api_token"),
    }


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("login", next=request.url))
        return view(*args, **kwargs)

    return wrapped


def role_required(*allowed_roles: str):
    allowed = set(allowed_roles)

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("admin_logged_in"):
                return redirect(url_for("login", next=request.url))
            role = session.get("admin_role", ROLE_VIEWER)
            if role not in allowed:
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)

        return wrapped

    return decorator
