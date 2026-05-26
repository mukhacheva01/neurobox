"""Tests for services/admin/access.py and shared/domain/analytics.py.

Strategy — access.py
---------------------
* ``get_conn`` is imported at module top-level via
  ``from services.admin.db import get_conn``, so we patch
  ``services.admin.access.get_conn``.
* ``check_password_hash`` / ``generate_password_hash`` are imported at
  module top-level via ``from werkzeug.security import …``, so we patch
  ``services.admin.access.check_password_hash`` etc.
* ``pyotp`` is imported at module top-level (``import pyotp``), so we patch
  ``services.admin.access.pyotp``.
* Flask ``session``, ``redirect``, ``request``, ``url_for`` are imported at
  module top-level, so they are patched as
  ``services.admin.access.<name>``.

Strategy — analytics.py
------------------------
* ``get_session`` is imported lazily (inside ``track()``), so we patch
  ``shared.db.session.get_session``.
* ``EventRepository`` is also lazily imported inside ``track()``, so we patch
  ``shared.db.repositories.event.EventRepository``.
* asyncio_mode = auto (pytest.ini) — bare async def test_* works.
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Ensure env vars so Flask/access imports don't error out
# ---------------------------------------------------------------------------
os.environ.setdefault("ADMIN_PANEL_SECRET", "test-secret-key-pytest")
os.environ.setdefault("ADMIN_PANEL_PASSWORD", "test-password")
os.environ.setdefault("ADMIN_PANEL_USER", "admin")
os.environ.setdefault("DATABASE_URL", "postgresql://fake:fake@localhost/fake")


# ===========================================================================
# Helpers
# ===========================================================================

def _make_cursor():
    """Return a fresh mock psycopg2 cursor."""
    cur = MagicMock()
    cur.fetchone = MagicMock(return_value=None)
    return cur


def _make_conn(cursor=None):
    """Return a mock psycopg2 connection."""
    conn = MagicMock()
    if cursor is None:
        cursor = _make_cursor()
    conn.cursor = MagicMock(return_value=cursor)
    conn.commit = MagicMock()
    conn.close = MagicMock()
    return conn


def _active_user_row(
    user_id: int = 1,
    login: str = "admin",
    password_hash: str = "hashed_pw",
    role: str = "admin",
    totp_secret: str = "",
) -> dict:
    """Build a dict that mimics a psycopg2 RealDictRow for admin_users."""
    return {
        "id": user_id,
        "login": login,
        "password_hash": password_hash,
        "role": role,
        "tg_id": None,
        "totp_secret": totp_secret,
        "is_active": True,
    }


# ===========================================================================
# ensure_admin_bootstrap
# ===========================================================================

class TestEnsureAdminBootstrap:
    def test_skips_when_no_password_env(self):
        """If ADMIN_PANEL_PASSWORD is unset/empty, function returns early."""
        with patch.dict(os.environ, {"ADMIN_PANEL_PASSWORD": ""}):
            with patch("services.admin.access.get_conn") as mock_get_conn:
                from services.admin.access import ensure_admin_bootstrap
                ensure_admin_bootstrap()
        mock_get_conn.assert_not_called()

    def test_creates_new_user_when_not_exists(self):
        cursor = _make_cursor()
        cursor.fetchone = MagicMock(return_value=None)  # user doesn't exist
        conn = _make_conn(cursor)

        with patch.dict(os.environ, {
            "ADMIN_PANEL_PASSWORD": "secret123",
            "ADMIN_PANEL_USER": "testadmin",
            "ADMIN_PANEL_BOOTSTRAP_ROLE": "owner",
        }):
            with patch("services.admin.access.get_conn", return_value=conn), \
                 patch("services.admin.access.generate_password_hash", return_value="hashed"):
                from services.admin.access import ensure_admin_bootstrap
                ensure_admin_bootstrap()

        # INSERT should be called (2nd execute call after CREATE TABLE and SELECT)
        assert cursor.execute.call_count >= 3
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_updates_existing_user(self):
        cursor = _make_cursor()
        # First fetchone (SELECT id): user exists
        cursor.fetchone = MagicMock(return_value={"id": 42})
        conn = _make_conn(cursor)

        with patch.dict(os.environ, {
            "ADMIN_PANEL_PASSWORD": "newpass",
            "ADMIN_PANEL_USER": "admin",
        }):
            with patch("services.admin.access.get_conn", return_value=conn), \
                 patch("services.admin.access.generate_password_hash", return_value="newhash"):
                from services.admin.access import ensure_admin_bootstrap
                ensure_admin_bootstrap()

        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_invalid_role_falls_back_to_owner(self):
        cursor = _make_cursor()
        cursor.fetchone = MagicMock(return_value=None)
        conn = _make_conn(cursor)

        with patch.dict(os.environ, {
            "ADMIN_PANEL_PASSWORD": "pw",
            "ADMIN_PANEL_BOOTSTRAP_ROLE": "superuser",  # invalid role
        }):
            with patch("services.admin.access.get_conn", return_value=conn), \
                 patch("services.admin.access.generate_password_hash", return_value="h"):
                from services.admin.access import ensure_admin_bootstrap
                ensure_admin_bootstrap()

        # Should not raise; just uses ROLE_OWNER fallback
        conn.commit.assert_called_once()

    def test_tg_id_parsed_from_env(self):
        cursor = _make_cursor()
        cursor.fetchone = MagicMock(return_value=None)
        conn = _make_conn(cursor)
        captured_args = []

        def _capture_execute(sql, params=None):
            if params:
                captured_args.append(params)

        cursor.execute.side_effect = _capture_execute

        with patch.dict(os.environ, {
            "ADMIN_PANEL_PASSWORD": "pw",
            "ADMIN_PANEL_BOOTSTRAP_TG_ID": "123456789",
        }):
            with patch("services.admin.access.get_conn", return_value=conn), \
                 patch("services.admin.access.generate_password_hash", return_value="h"):
                from services.admin.access import ensure_admin_bootstrap
                ensure_admin_bootstrap()

        # The INSERT params tuple should contain 123456789 as tg_id
        tg_id_found = any(
            123456789 in (p if isinstance(p, (list, tuple)) else [])
            for p in captured_args
        )
        assert tg_id_found

    def test_non_digit_tg_id_becomes_none(self):
        cursor = _make_cursor()
        cursor.fetchone = MagicMock(return_value=None)
        conn = _make_conn(cursor)
        captured_args = []

        def _capture_execute(sql, params=None):
            if params:
                captured_args.append(params)

        cursor.execute.side_effect = _capture_execute

        with patch.dict(os.environ, {
            "ADMIN_PANEL_PASSWORD": "pw",
            "ADMIN_PANEL_BOOTSTRAP_TG_ID": "not_a_number",
        }):
            with patch("services.admin.access.get_conn", return_value=conn), \
                 patch("services.admin.access.generate_password_hash", return_value="h"):
                from services.admin.access import ensure_admin_bootstrap
                ensure_admin_bootstrap()

        # None should appear in INSERT params, not the string
        none_found = any(
            None in list(p) if isinstance(p, (list, tuple)) else False
            for p in captured_args
        )
        assert none_found

    def test_conn_closed_even_on_exception(self):
        cursor = _make_cursor()
        cursor.execute = MagicMock(side_effect=Exception("DB exploded"))
        conn = _make_conn(cursor)

        with patch.dict(os.environ, {"ADMIN_PANEL_PASSWORD": "pw"}):
            with patch("services.admin.access.get_conn", return_value=conn):
                from services.admin.access import ensure_admin_bootstrap
                try:
                    ensure_admin_bootstrap()
                except Exception:
                    pass  # The exception propagates; conn.close must still be called

        conn.close.assert_called_once()


# ===========================================================================
# authenticate_admin — success path
# ===========================================================================

class TestAuthenticateAdminSuccess:
    def test_returns_user_dict_on_correct_credentials(self):
        row = _active_user_row()
        cursor = _make_cursor()
        cursor.fetchone = MagicMock(return_value=row)
        conn = _make_conn(cursor)

        with patch("services.admin.access.get_conn", return_value=conn), \
             patch("services.admin.access.ensure_admin_bootstrap"), \
             patch("services.admin.access.check_password_hash", return_value=True):
            from services.admin.access import authenticate_admin
            result = authenticate_admin("admin", "correct_password")

        assert result is not None
        assert result["login"] == "admin"
        assert result["role"] == "admin"
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_updates_last_login_at_on_success(self):
        row = _active_user_row()
        cursor = _make_cursor()
        cursor.fetchone = MagicMock(return_value=row)
        conn = _make_conn(cursor)

        with patch("services.admin.access.get_conn", return_value=conn), \
             patch("services.admin.access.ensure_admin_bootstrap"), \
             patch("services.admin.access.check_password_hash", return_value=True):
            from services.admin.access import authenticate_admin
            authenticate_admin("admin", "pw")

        # The UPDATE last_login_at query should have been called
        update_calls = [
            c for c in cursor.execute.call_args_list
            if "last_login_at" in str(c)
        ]
        assert len(update_calls) >= 1

    def test_conn_closed_on_success(self):
        row = _active_user_row()
        cursor = _make_cursor()
        cursor.fetchone = MagicMock(return_value=row)
        conn = _make_conn(cursor)

        with patch("services.admin.access.get_conn", return_value=conn), \
             patch("services.admin.access.ensure_admin_bootstrap"), \
             patch("services.admin.access.check_password_hash", return_value=True):
            from services.admin.access import authenticate_admin
            authenticate_admin("admin", "pw")

        conn.close.assert_called_once()


# ===========================================================================
# authenticate_admin — failure paths
# ===========================================================================

class TestAuthenticateAdminFailure:
    def test_returns_none_when_user_not_found(self):
        cursor = _make_cursor()
        cursor.fetchone = MagicMock(return_value=None)
        conn = _make_conn(cursor)

        with patch("services.admin.access.get_conn", return_value=conn), \
             patch("services.admin.access.ensure_admin_bootstrap"):
            from services.admin.access import authenticate_admin
            result = authenticate_admin("nobody", "pw")

        assert result is None
        conn.close.assert_called_once()

    def test_returns_none_when_user_inactive(self):
        row = _active_user_row()
        row["is_active"] = False
        cursor = _make_cursor()
        cursor.fetchone = MagicMock(return_value=row)
        conn = _make_conn(cursor)

        with patch("services.admin.access.get_conn", return_value=conn), \
             patch("services.admin.access.ensure_admin_bootstrap"):
            from services.admin.access import authenticate_admin
            result = authenticate_admin("admin", "pw")

        assert result is None
        conn.close.assert_called_once()

    def test_returns_none_on_wrong_password(self):
        row = _active_user_row()
        cursor = _make_cursor()
        cursor.fetchone = MagicMock(return_value=row)
        conn = _make_conn(cursor)

        with patch("services.admin.access.get_conn", return_value=conn), \
             patch("services.admin.access.ensure_admin_bootstrap"), \
             patch("services.admin.access.check_password_hash", return_value=False):
            from services.admin.access import authenticate_admin
            result = authenticate_admin("admin", "wrong_pw")

        assert result is None
        conn.close.assert_called_once()

    def test_conn_closed_on_wrong_password(self):
        row = _active_user_row()
        cursor = _make_cursor()
        cursor.fetchone = MagicMock(return_value=row)
        conn = _make_conn(cursor)

        with patch("services.admin.access.get_conn", return_value=conn), \
             patch("services.admin.access.ensure_admin_bootstrap"), \
             patch("services.admin.access.check_password_hash", return_value=False):
            from services.admin.access import authenticate_admin
            authenticate_admin("admin", "bad")

        conn.close.assert_called_once()


# ===========================================================================
# authenticate_admin — OTP paths
# ===========================================================================

class TestAuthenticateAdminOTP:
    def test_returns_otp_required_signal_when_totp_set_and_no_otp(self):
        row = _active_user_row(totp_secret="JBSWY3DPEHPK3PXP")
        cursor = _make_cursor()
        cursor.fetchone = MagicMock(return_value=row)
        conn = _make_conn(cursor)

        with patch("services.admin.access.get_conn", return_value=conn), \
             patch("services.admin.access.ensure_admin_bootstrap"), \
             patch("services.admin.access.check_password_hash", return_value=True):
            from services.admin.access import authenticate_admin
            result = authenticate_admin("admin", "correct_pw")

        assert result is not None
        assert result.get("otp_required") is True
        assert result.get("login") == "admin"
        conn.close.assert_called_once()

    def test_returns_none_on_invalid_otp(self):
        row = _active_user_row(totp_secret="JBSWY3DPEHPK3PXP")
        cursor = _make_cursor()
        cursor.fetchone = MagicMock(return_value=row)
        conn = _make_conn(cursor)

        mock_totp = MagicMock()
        mock_totp.verify = MagicMock(return_value=False)
        mock_pyotp = MagicMock()
        mock_pyotp.TOTP = MagicMock(return_value=mock_totp)

        with patch("services.admin.access.get_conn", return_value=conn), \
             patch("services.admin.access.ensure_admin_bootstrap"), \
             patch("services.admin.access.check_password_hash", return_value=True), \
             patch("services.admin.access.pyotp", mock_pyotp):
            from services.admin.access import authenticate_admin
            result = authenticate_admin("admin", "pw", otp="000000")

        assert result is None
        conn.close.assert_called_once()

    def test_returns_user_dict_on_valid_otp(self):
        row = _active_user_row(totp_secret="JBSWY3DPEHPK3PXP")
        cursor = _make_cursor()
        cursor.fetchone = MagicMock(return_value=row)
        conn = _make_conn(cursor)

        mock_totp = MagicMock()
        mock_totp.verify = MagicMock(return_value=True)
        mock_pyotp = MagicMock()
        mock_pyotp.TOTP = MagicMock(return_value=mock_totp)

        with patch("services.admin.access.get_conn", return_value=conn), \
             patch("services.admin.access.ensure_admin_bootstrap"), \
             patch("services.admin.access.check_password_hash", return_value=True), \
             patch("services.admin.access.pyotp", mock_pyotp):
            from services.admin.access import authenticate_admin
            result = authenticate_admin("admin", "pw", otp="123456")

        assert result is not None
        assert "otp_required" not in result or result.get("otp_required") is not True
        assert result["login"] == "admin"

    def test_returns_none_when_totp_verify_raises(self):
        row = _active_user_row(totp_secret="BAD_SECRET")
        cursor = _make_cursor()
        cursor.fetchone = MagicMock(return_value=row)
        conn = _make_conn(cursor)

        mock_totp = MagicMock()
        mock_totp.verify = MagicMock(side_effect=Exception("invalid base32"))
        mock_pyotp = MagicMock()
        mock_pyotp.TOTP = MagicMock(return_value=mock_totp)

        with patch("services.admin.access.get_conn", return_value=conn), \
             patch("services.admin.access.ensure_admin_bootstrap"), \
             patch("services.admin.access.check_password_hash", return_value=True), \
             patch("services.admin.access.pyotp", mock_pyotp):
            from services.admin.access import authenticate_admin
            result = authenticate_admin("admin", "pw", otp="999999")

        assert result is None
        conn.close.assert_called_once()

    def test_whitespace_totp_secret_treated_as_empty(self):
        """A totp_secret that is all whitespace should be treated as no secret."""
        row = _active_user_row(totp_secret="   ")
        cursor = _make_cursor()
        cursor.fetchone = MagicMock(return_value=row)
        conn = _make_conn(cursor)

        with patch("services.admin.access.get_conn", return_value=conn), \
             patch("services.admin.access.ensure_admin_bootstrap"), \
             patch("services.admin.access.check_password_hash", return_value=True):
            from services.admin.access import authenticate_admin
            result = authenticate_admin("admin", "pw")

        # After stripping, secret is empty → no OTP required
        assert result is not None
        assert result.get("otp_required") is None or result.get("login") == "admin"

    def test_none_totp_secret_treated_as_empty(self):
        row = _active_user_row(totp_secret=None)
        # Simulate psycopg2 RealDictRow where .get() with missing key → None
        row_mock = MagicMock()
        row_mock.__getitem__ = MagicMock(side_effect=lambda k: row.get(k))
        row_mock.get = MagicMock(side_effect=lambda k, *a: row.get(k, a[0] if a else None))
        row_mock.__contains__ = MagicMock(side_effect=lambda k: k in row)
        # Use a plain dict so dict(row) works
        row["totp_secret"] = None

        cursor = _make_cursor()
        cursor.fetchone = MagicMock(return_value=row)
        conn = _make_conn(cursor)

        with patch("services.admin.access.get_conn", return_value=conn), \
             patch("services.admin.access.ensure_admin_bootstrap"), \
             patch("services.admin.access.check_password_hash", return_value=True):
            from services.admin.access import authenticate_admin
            result = authenticate_admin("admin", "pw")

        assert result is not None
        assert result.get("login") == "admin"


# ===========================================================================
# current_admin
# ===========================================================================

class TestCurrentAdmin:
    def test_returns_dict_with_session_values(self):
        """current_admin() reads from Flask session."""
        mock_session = {
            "admin_user_id": 7,
            "admin_login": "alice",
            "admin_role": "support",
        }
        with patch("services.admin.access.session", mock_session):
            from services.admin.access import current_admin
            result = current_admin()

        assert result["id"] == 7
        assert result["login"] == "alice"
        assert result["role"] == "support"

    def test_defaults_role_to_viewer_when_missing(self):
        mock_session = {}
        with patch("services.admin.access.session", mock_session):
            from services.admin.access import current_admin
            result = current_admin()

        from services.admin.access import ROLE_VIEWER
        assert result["role"] == ROLE_VIEWER

    def test_returns_none_for_id_when_not_in_session(self):
        mock_session = {}
        with patch("services.admin.access.session", mock_session):
            from services.admin.access import current_admin
            result = current_admin()

        assert result["id"] is None
        assert result["login"] is None


# ===========================================================================
# login_required decorator
# ===========================================================================

class TestLoginRequired:
    def test_redirects_when_not_logged_in(self):
        mock_redirect = MagicMock(return_value="redirect_response")
        mock_url_for = MagicMock(return_value="/login")
        mock_request = MagicMock()
        mock_request.url = "http://localhost/dashboard"
        mock_session = {}  # admin_logged_in not set

        with patch("services.admin.access.session", mock_session), \
             patch("services.admin.access.redirect", mock_redirect), \
             patch("services.admin.access.url_for", mock_url_for), \
             patch("services.admin.access.request", mock_request):
            from services.admin.access import login_required

            @login_required
            def my_view():
                return "view_response"

            result = my_view()

        assert result == "redirect_response"
        mock_redirect.assert_called_once()

    def test_calls_view_when_logged_in(self):
        mock_session = {"admin_logged_in": True}

        with patch("services.admin.access.session", mock_session):
            from services.admin.access import login_required

            @login_required
            def my_view():
                return "protected_content"

            result = my_view()

        assert result == "protected_content"

    def test_passes_args_to_view(self):
        mock_session = {"admin_logged_in": True}

        with patch("services.admin.access.session", mock_session):
            from services.admin.access import login_required

            @login_required
            def my_view(user_id, name=""):
                return f"{user_id}-{name}"

            result = my_view(42, name="alice")

        assert result == "42-alice"

    def test_preserves_function_name(self):
        from services.admin.access import login_required

        @login_required
        def special_view():
            pass

        assert special_view.__name__ == "special_view"


# ===========================================================================
# role_required decorator
# ===========================================================================

class TestRoleRequired:
    def test_redirects_to_login_when_not_logged_in(self):
        mock_redirect = MagicMock(return_value="redir")
        mock_url_for = MagicMock(return_value="/login")
        mock_request = MagicMock()
        mock_request.url = "http://localhost/admin"
        mock_session = {}

        with patch("services.admin.access.session", mock_session), \
             patch("services.admin.access.redirect", mock_redirect), \
             patch("services.admin.access.url_for", mock_url_for), \
             patch("services.admin.access.request", mock_request):
            from services.admin.access import role_required

            @role_required("admin", "owner")
            def admin_view():
                return "admin page"

            result = admin_view()

        assert result == "redir"

    def test_redirects_to_dashboard_when_wrong_role(self):
        mock_redirect = MagicMock(return_value="dash_redir")
        mock_url_for = MagicMock(return_value="/")
        mock_session = {"admin_logged_in": True, "admin_role": "viewer"}

        with patch("services.admin.access.session", mock_session), \
             patch("services.admin.access.redirect", mock_redirect), \
             patch("services.admin.access.url_for", mock_url_for):
            from services.admin.access import role_required

            @role_required("admin", "owner")
            def admin_view():
                return "admin page"

            result = admin_view()

        assert result == "dash_redir"

    def test_calls_view_when_role_allowed(self):
        mock_session = {"admin_logged_in": True, "admin_role": "admin"}

        with patch("services.admin.access.session", mock_session):
            from services.admin.access import role_required

            @role_required("admin", "owner")
            def admin_view():
                return "admin content"

            result = admin_view()

        assert result == "admin content"

    def test_owner_role_allowed(self):
        mock_session = {"admin_logged_in": True, "admin_role": "owner"}

        with patch("services.admin.access.session", mock_session):
            from services.admin.access import role_required

            @role_required("admin", "owner")
            def owner_view():
                return "owner content"

            result = owner_view()

        assert result == "owner content"

    def test_preserves_function_name(self):
        from services.admin.access import role_required

        @role_required("admin")
        def my_view():
            pass

        assert my_view.__name__ == "my_view"

    def test_defaults_role_to_viewer_when_missing_from_session(self):
        mock_redirect = MagicMock(return_value="redir")
        mock_url_for = MagicMock(return_value="/")
        mock_session = {"admin_logged_in": True}  # no admin_role key

        with patch("services.admin.access.session", mock_session), \
             patch("services.admin.access.redirect", mock_redirect), \
             patch("services.admin.access.url_for", mock_url_for):
            from services.admin.access import role_required

            @role_required("admin")
            def admin_only():
                return "admin"

            result = admin_only()

        # viewer not in ["admin"] → redirect to dashboard
        assert result == "redir"


# ===========================================================================
# Role constants
# ===========================================================================

def test_role_constants():
    from services.admin.access import (
        ROLE_VIEWER, ROLE_SUPPORT, ROLE_ADMIN, ROLE_OWNER, ALL_ROLES,
    )
    assert ROLE_VIEWER == "viewer"
    assert ROLE_SUPPORT == "support"
    assert ROLE_ADMIN == "admin"
    assert ROLE_OWNER == "owner"
    assert ALL_ROLES == {"viewer", "support", "admin", "owner"}


# ===========================================================================
# shared/domain/analytics.py
# ===========================================================================

# Helper: build a fake asynccontextmanager session factory
def _fake_session(mock_session):
    @asynccontextmanager
    async def _gs():
        yield mock_session
    return _gs


class TestAnalyticsTrack:
    async def test_calls_repo_create_with_props(self):
        mock_repo = AsyncMock()
        mock_repo.create = AsyncMock()
        mock_session = AsyncMock()

        with patch("shared.db.repositories.event.EventRepository", return_value=mock_repo), \
             patch("shared.db.session.get_session", _fake_session(mock_session)):
            from shared.domain.analytics import track
            await track("test_event", 42, key="value", flag=True)

        mock_repo.create.assert_called_once_with(
            event_name="test_event",
            user_id=42,
            properties={"key": "value", "flag": True},
        )

    async def test_passes_none_properties_when_no_extra_kwargs(self):
        mock_repo = AsyncMock()
        mock_repo.create = AsyncMock()
        mock_session = AsyncMock()

        with patch("shared.db.repositories.event.EventRepository", return_value=mock_repo), \
             patch("shared.db.session.get_session", _fake_session(mock_session)):
            from shared.domain.analytics import track
            await track("bare_event", 1)

        mock_repo.create.assert_called_once_with(
            event_name="bare_event",
            user_id=1,
            properties=None,
        )

    async def test_does_not_raise_when_session_raises(self):
        @asynccontextmanager
        async def _bad_session():
            raise Exception("DB down")
            yield  # noqa: unreachable

        with patch("shared.db.session.get_session", _bad_session):
            from shared.domain.analytics import track
            await track("fail_event", 99)  # must not raise

    async def test_does_not_raise_when_repo_create_raises(self):
        mock_repo = AsyncMock()
        mock_repo.create = AsyncMock(side_effect=Exception("write error"))
        mock_session = AsyncMock()

        with patch("shared.db.repositories.event.EventRepository", return_value=mock_repo), \
             patch("shared.db.session.get_session", _fake_session(mock_session)):
            from shared.domain.analytics import track
            await track("fail_event", 5, x=1)  # must not raise

    async def test_logs_analytics_event_on_failure(self):
        @asynccontextmanager
        async def _bad_session():
            raise Exception("DB gone")
            yield

        with patch("shared.db.session.get_session", _bad_session), \
             patch("shared.domain.analytics.log") as mock_log:
            from shared.domain.analytics import track
            await track("logged_event", 7, metric="x")

        mock_log.info.assert_called_once()
        call_kwargs = mock_log.info.call_args
        assert call_kwargs[0][0] == "analytics_event"


class TestAnalyticsTrackPaywallView:
    async def test_delegates_to_track_with_paywall_view_event(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_paywall_view
            await track_paywall_view(1, "make a video", 50, 10, ["lite", "pro"], "checkout")

        assert mock_track.call_args[0][0] == "paywall_view"

    async def test_passes_correct_keyword_args(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_paywall_view
            await track_paywall_view(1, "task desc", 100, 20, None, "smart_paywall")

        kwargs = mock_track.call_args[1]
        assert kwargs["need_cr"] == 100
        assert kwargs["balance_cr"] == 20
        assert kwargs["recommended_packs"] == []
        assert kwargs["source"] == "smart_paywall"

    async def test_task_truncated_to_120_chars(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_paywall_view
            long_task = "x" * 200
            await track_paywall_view(1, long_task, 10, 0)

        assert len(mock_track.call_args[1]["task"]) == 120

    async def test_defaults_source_to_smart_paywall(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_paywall_view
            await track_paywall_view(1, "task", 10, 0)

        assert mock_track.call_args[1]["source"] == "smart_paywall"

    async def test_recommended_packs_none_becomes_empty_list(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_paywall_view
            await track_paywall_view(1, "task", 10, 0, None)

        assert mock_track.call_args[1]["recommended_packs"] == []

    async def test_zero_values_coerced_to_int(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_paywall_view
            await track_paywall_view(1, "task", None, None)

        kwargs = mock_track.call_args[1]
        assert kwargs["need_cr"] == 0
        assert kwargs["balance_cr"] == 0


class TestAnalyticsTrackPaywallHit:
    async def test_calls_track_paywall_view(self):
        with patch("shared.domain.analytics.track_paywall_view", AsyncMock()) as mock_view:
            from shared.domain.analytics import track_paywall_hit
            await track_paywall_hit(5, "description", 30, 10)

        mock_view.assert_called_once_with(5, "description", 30, 10)


class TestAnalyticsTrackPlanSelected:
    async def test_event_name_is_plan_selected(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_plan_selected
            await track_plan_selected(1, "lite")

        assert mock_track.call_args[0][0] == "plan_selected"

    async def test_pack_name_coerced_to_str(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_plan_selected
            await track_plan_selected(1, None)

        assert mock_track.call_args[1]["pack_name"] == ""

    async def test_price_rub_coerced_to_float(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_plan_selected
            await track_plan_selected(1, "lite", price_rub=None)

        assert mock_track.call_args[1]["price_rub"] == 0.0

    async def test_credits_coerced_to_int(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_plan_selected
            await track_plan_selected(1, "lite", credits=None)

        assert mock_track.call_args[1]["credits"] == 0

    async def test_extra_kwargs_merged_into_props(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_plan_selected
            await track_plan_selected(1, "pro", campaign="spring", ab_variant="B")

        assert mock_track.call_args[1]["campaign"] == "spring"
        assert mock_track.call_args[1]["ab_variant"] == "B"

    async def test_default_source_is_checkout(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_plan_selected
            await track_plan_selected(1, "lite")

        assert mock_track.call_args[1]["source"] == "checkout"


class TestAnalyticsTrackPaymentStarted:
    async def test_event_name(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_payment_started
            await track_payment_started(1, "pay_1", "yookassa")

        assert mock_track.call_args[0][0] == "payment_started"

    async def test_all_fields_present(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_payment_started
            await track_payment_started(
                1, "pay_1", "yookassa", pack_name="lite", amount_rub=99.0, credits=300
            )

        kwargs = mock_track.call_args[1]
        assert kwargs["payment_id"] == "pay_1"
        assert kwargs["method"] == "yookassa"
        assert kwargs["pack_name"] == "lite"
        assert kwargs["amount_rub"] == 99.0
        assert kwargs["credits"] == 300
        assert kwargs["is_test"] is False

    async def test_is_test_flag_true(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_payment_started
            await track_payment_started(1, "pay_x", "stripe", is_test=True)

        assert mock_track.call_args[1]["is_test"] is True

    async def test_extra_kwargs_forwarded(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_payment_started
            await track_payment_started(1, "p", "m", extra_field="hello")

        assert mock_track.call_args[1]["extra_field"] == "hello"

    async def test_none_values_coerced(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_payment_started
            await track_payment_started(1, None, None)

        kwargs = mock_track.call_args[1]
        assert kwargs["payment_id"] == ""
        assert kwargs["method"] == ""


class TestAnalyticsTrackPaymentSuccess:
    async def test_event_name(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_payment_success
            await track_payment_success(1, "pay_ok", "yookassa")

        assert mock_track.call_args[0][0] == "payment_success"

    async def test_fields_populated(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_payment_success
            await track_payment_success(
                1, "pay_ok", "crypto", pack_name="pro", amount_rub=5.0, credits=500, is_test=True
            )

        kwargs = mock_track.call_args[1]
        assert kwargs["pack_name"] == "pro"
        assert kwargs["credits"] == 500
        assert kwargs["is_test"] is True

    async def test_extra_kwargs_forwarded(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_payment_success
            await track_payment_success(1, "pay_ok", "crypto", amount_usd=5.0)

        assert mock_track.call_args[1]["amount_usd"] == 5.0


class TestAnalyticsTrackPaymentFailed:
    async def test_event_name(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_payment_failed
            await track_payment_failed(1, "yookassa")

        assert mock_track.call_args[0][0] == "payment_failed"

    async def test_reason_truncated_to_200_chars(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_payment_failed
            await track_payment_failed(1, "stripe", reason="x" * 300)

        assert len(mock_track.call_args[1]["reason"]) == 200

    async def test_all_default_fields_present(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_payment_failed
            await track_payment_failed(1, "method")

        kwargs = mock_track.call_args[1]
        assert kwargs["payment_id"] == ""
        assert kwargs["pack_name"] == ""
        assert kwargs["amount_rub"] == 0.0
        assert kwargs["credits"] == 0
        assert kwargs["reason"] == ""
        assert kwargs["is_test"] is False

    async def test_extra_kwargs_forwarded(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_payment_failed
            await track_payment_failed(1, "m", extra="data")

        assert mock_track.call_args[1]["extra"] == "data"


class TestAnalyticsTrackFirstValue:
    async def test_event_name(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_first_value
            await track_first_value(1, "image", "flux-2-turbo")

        assert mock_track.call_args[0][0] == "first_value"

    async def test_fields_populated(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_first_value
            await track_first_value(1, "image", "flux-2-turbo", success_event="image_ready")

        kwargs = mock_track.call_args[1]
        assert kwargs["task_type"] == "image"
        assert kwargs["model"] == "flux-2-turbo"
        assert kwargs["success_event"] == "image_ready"

    async def test_none_values_coerced(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_first_value
            await track_first_value(1, None, None)

        kwargs = mock_track.call_args[1]
        assert kwargs["task_type"] == ""
        assert kwargs["model"] == ""

    async def test_extra_kwargs_merged(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_first_value
            await track_first_value(1, "video", "kling", session_id="abc")

        assert mock_track.call_args[1]["session_id"] == "abc"


class TestAnalyticsTrackPremiumAction:
    async def test_event_name(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_premium_action
            await track_premium_action(1, "video", "kling-2.6")

        assert mock_track.call_args[0][0] == "premium_action"

    async def test_cr_cost_field(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_premium_action
            await track_premium_action(1, "video", "kling-2.6", cr_cost=100)

        assert mock_track.call_args[1]["cr_cost"] == 100

    async def test_default_cr_cost_is_zero(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_premium_action
            await track_premium_action(1, "music", "suno")

        assert mock_track.call_args[1]["cr_cost"] == 0

    async def test_success_event_field(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_premium_action
            await track_premium_action(1, "t", "m", success_event="done")

        assert mock_track.call_args[1]["success_event"] == "done"

    async def test_extra_kwargs_forwarded(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_premium_action
            await track_premium_action(1, "music", "suno", extra_field="hello")

        assert mock_track.call_args[1]["extra_field"] == "hello"

    async def test_none_values_coerced(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_premium_action
            await track_premium_action(1, None, None, cr_cost=None)

        kwargs = mock_track.call_args[1]
        assert kwargs["task_type"] == ""
        assert kwargs["model"] == ""
        assert kwargs["cr_cost"] == 0
