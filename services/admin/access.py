"""DB-backed auth, RBAC and optional TOTP for Flask admin panel."""
from __future__ import annotations

import os
from functools import wraps

import pyotp
from flask import redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from services.admin.db import get_conn

ROLE_VIEWER = "viewer"
ROLE_SUPPORT = "support"
ROLE_ADMIN = "admin"
ROLE_OWNER = "owner"
ALL_ROLES = {ROLE_VIEWER, ROLE_SUPPORT, ROLE_ADMIN, ROLE_OWNER}


def ensure_admin_bootstrap() -> None:
    login = (os.environ.get("ADMIN_PANEL_USER", "admin") or "admin").strip()
    password = (os.environ.get("ADMIN_PANEL_PASSWORD", "") or "").strip()
    role = (os.environ.get("ADMIN_PANEL_BOOTSTRAP_ROLE", ROLE_OWNER) or ROLE_OWNER).strip().lower()
    totp_secret = (os.environ.get("ADMIN_PANEL_TOTP_SECRET", "") or "").strip()
    tg_id_raw = (os.environ.get("ADMIN_PANEL_BOOTSTRAP_TG_ID", "") or "").strip()
    if not password:
        return
    if role not in ALL_ROLES:
        role = ROLE_OWNER
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_users (
                id BIGSERIAL PRIMARY KEY,
                login VARCHAR(80) NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'admin',
                tg_id BIGINT,
                totp_secret VARCHAR(64),
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_login_at TIMESTAMPTZ
            )
            """
        )
        cur.execute("SELECT id FROM admin_users WHERE login = %s", (login,))
        row = cur.fetchone()
        tg_id = int(tg_id_raw) if tg_id_raw.isdigit() else None
        if not row:
            cur.execute(
                """
                INSERT INTO admin_users (login, password_hash, role, tg_id, totp_secret, is_active)
                VALUES (%s, %s, %s, %s, %s, TRUE)
                """,
                (
                    login,
                    generate_password_hash(password),
                    role,
                    tg_id,
                    totp_secret or None,
                ),
            )
        else:
            cur.execute(
                """
                UPDATE admin_users
                SET password_hash = %s,
                    role = %s,
                    tg_id = %s,
                    totp_secret = %s,
                    is_active = TRUE,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    generate_password_hash(password),
                    role,
                    tg_id,
                    totp_secret or None,
                    row["id"],
                ),
            )
        conn.commit()
    finally:
        conn.close()


def authenticate_admin(login: str, password: str, otp: str | None = None) -> dict | None:
    ensure_admin_bootstrap()
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, login, password_hash, role, tg_id, totp_secret, is_active
            FROM admin_users
            WHERE login = %s
            """,
            (login,),
        )
        row = cur.fetchone()
        if not row or not row["is_active"]:
            return None
        if not check_password_hash(row["password_hash"], password):
            return None
        secret = (row.get("totp_secret") or "").strip()
        if secret:
            if not otp:
                return {"otp_required": True, "login": row["login"]}
            try:
                if not pyotp.TOTP(secret).verify(otp, valid_window=1):
                    return None
            except Exception:
                return None
        cur.execute("UPDATE admin_users SET last_login_at = NOW(), updated_at = NOW() WHERE id = %s", (row["id"],))
        conn.commit()
        return dict(row)
    finally:
        conn.close()


def current_admin() -> dict:
    return {
        "id": session.get("admin_user_id"),
        "login": session.get("admin_login"),
        "role": session.get("admin_role", ROLE_VIEWER),
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
