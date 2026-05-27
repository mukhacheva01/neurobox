"""Tests for the current backend-client based admin access layer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest


def _response(status_code: int, payload: dict | None = None):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = payload or {}
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "boom",
            request=MagicMock(),
            response=response,
        )
    else:
        response.raise_for_status.return_value = None
    return response


def test_ensure_admin_bootstrap_is_noop():
    from services.admin.access import ensure_admin_bootstrap

    assert ensure_admin_bootstrap() is None


class TestAuthenticateAdmin:
    def test_returns_none_on_http_error(self):
        with patch("services.admin.access.post_json", side_effect=httpx.ConnectError("down")):
            from services.admin.access import authenticate_admin

            assert authenticate_admin("admin", "pw") is None

    def test_returns_rate_limited_marker(self):
        with patch("services.admin.access.post_json", return_value=_response(429)):
            from services.admin.access import authenticate_admin

            assert authenticate_admin("admin", "pw") == {"rate_limited": True}

    def test_returns_none_on_unauthorized(self):
        with patch("services.admin.access.post_json", return_value=_response(401)):
            from services.admin.access import authenticate_admin

            assert authenticate_admin("admin", "pw") is None

    def test_returns_none_when_payload_has_no_token(self):
        with patch("services.admin.access.post_json", return_value=_response(200, {"admin_login": "admin"})):
            from services.admin.access import authenticate_admin

            assert authenticate_admin("admin", "pw") is None

    def test_returns_otp_required_marker(self):
        with patch("services.admin.access.post_json", return_value=_response(200, {"otp_required": True})):
            from services.admin.access import authenticate_admin

            assert authenticate_admin("admin", "pw") == {"otp_required": True, "login": "admin"}

    def test_normalizes_role_and_returns_auth_payload(self):
        payload = {
            "token": "jwt-token",
            "admin_user_id": 7,
            "admin_login": "boss",
            "admin_role": "superadmin",
            "admin_tg_id": 123,
        }
        with patch("services.admin.access.post_json", return_value=_response(200, payload)):
            from services.admin.access import authenticate_admin

            result = authenticate_admin("admin", "pw", otp="123456")

        assert result == {
            "id": 7,
            "login": "boss",
            "role": "owner",
            "tg_id": 123,
            "token": "jwt-token",
        }

    def test_unknown_role_falls_back_to_viewer(self):
        payload = {
            "token": "jwt-token",
            "admin_role": "mystery",
        }
        with patch("services.admin.access.post_json", return_value=_response(200, payload)):
            from services.admin.access import authenticate_admin

            result = authenticate_admin("admin", "pw")

        assert result["role"] == "viewer"


def test_current_admin_reads_session():
    from services.admin.access import current_admin
    from services.admin.app import app

    with app.test_request_context("/"):
        from flask import session

        session["admin_user_id"] = 5
        session["admin_login"] = "owner"
        session["admin_role"] = "owner"
        session["admin_api_token"] = "token"
        assert current_admin() == {
            "id": 5,
            "login": "owner",
            "role": "owner",
            "token": "token",
        }


class TestDecorators:
    def test_login_required_redirects_guest(self):
        from services.admin.access import login_required
        from services.admin.app import app

        @login_required
        def protected():
            return "ok"

        with app.test_request_context("/secret"):
            response = protected()
            assert response.status_code == 302
            assert "/login" in response.location

    def test_login_required_allows_logged_in_user(self):
        from services.admin.access import login_required
        from services.admin.app import app

        @login_required
        def protected():
            return "ok"

        with app.test_request_context("/secret"):
            from flask import session

            session["admin_logged_in"] = True
            assert protected() == "ok"

    def test_role_required_redirects_guest(self):
        from services.admin.access import role_required
        from services.admin.app import app

        @role_required("owner")
        def protected():
            return "ok"

        with app.test_request_context("/secret"):
            response = protected()
            assert response.status_code == 302
            assert "/login" in response.location

    def test_role_required_redirects_for_wrong_role(self):
        from services.admin.access import role_required
        from services.admin.app import app

        @role_required("owner")
        def protected():
            return "ok"

        with app.test_request_context("/secret"):
            from flask import session

            session["admin_logged_in"] = True
            session["admin_role"] = "support"
            response = protected()
            assert response.status_code == 302
            assert response.location.endswith("/")

    def test_role_required_allows_matching_role(self):
        from services.admin.access import role_required
        from services.admin.app import app

        @role_required("admin", "owner")
        def protected():
            return "ok"

        with app.test_request_context("/secret"):
            from flask import session

            session["admin_logged_in"] = True
            session["admin_role"] = "admin"
            assert protected() == "ok"
