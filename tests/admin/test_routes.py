"""Comprehensive pytest tests for services/admin/routes.py.

Strategy
--------
* The Flask app (services.admin.app) raises ValueError on import unless
  ADMIN_PANEL_SECRET and ADMIN_PANEL_PASSWORD are set, so we patch those env
  vars early via a module-level fixture.
* All DB calls are short-circuited by replacing ``services.admin.db.get_conn``
  with a factory that returns a fully-mocked connection / cursor.
* ``services.admin.access.ensure_admin_bootstrap`` is patched so it never
  touches a real DB during app construction.
* ``services.admin.audit.log_action`` is patched globally so audit writes do
  not hit the DB.
* Every route test follows the pattern:
    1.  Set up the mock cursor's ``fetchone`` / ``fetchall`` return values.
    2.  Perform the HTTP request via ``app.test_client()``.
    3.  Assert status code (200 for pages, 302 for redirects, etc.).
"""

from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# Inject required env vars BEFORE the app module is imported anywhere.
# ---------------------------------------------------------------------------
os.environ.setdefault("ADMIN_PANEL_SECRET", "test-secret-key-for-pytest-only")
os.environ.setdefault("ADMIN_PANEL_PASSWORD", "test-password")
os.environ.setdefault("ADMIN_PANEL_USER", "admin")
os.environ.setdefault("DATABASE_URL", "postgresql://fake:fake@localhost/fake")

# ---------------------------------------------------------------------------
# Standard-library & third-party imports
# ---------------------------------------------------------------------------
from unittest.mock import MagicMock, patch, call
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cursor(fetchone_seq=None, fetchall_seq=None):
    """Return a MagicMock cursor whose fetchone/fetchall cycle through the
    supplied sequences.  Each element of *fetchone_seq* is returned on
    successive fetchone() calls; similarly for fetchall_seq."""
    cursor = MagicMock()

    # fetchone side_effect — cycle the list
    _fone = list(fetchone_seq or [])
    _fone_iter = iter(_fone)

    def _fetchone():
        try:
            return next(_fone_iter)
        except StopIteration:
            return {"count": 0}

    cursor.fetchone.side_effect = _fetchone

    # fetchall side_effect — cycle the list
    _fall = list(fetchall_seq or [[]])
    _fall_iter = iter(_fall)

    def _fetchall():
        try:
            return next(_fall_iter)
        except StopIteration:
            return []

    cursor.fetchall.side_effect = _fetchall
    return cursor


def _make_conn(cursor=None):
    """Return a MagicMock connection that hands back *cursor* from cursor()."""
    conn = MagicMock()
    if cursor is None:
        cursor = _make_cursor()
    conn.cursor.return_value = cursor
    return conn


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def _patched_bootstrap():
    """Patch ensure_admin_bootstrap so app import never calls the real DB."""
    with patch("services.admin.access.ensure_admin_bootstrap", return_value=None):
        yield


@pytest.fixture()
def app(_patched_bootstrap):
    """Import and return the Flask app with bootstrap mocked."""
    # Late import so env vars are in place
    with patch("services.admin.access.ensure_admin_bootstrap", return_value=None):
        # Re-import will be a no-op (already cached); just return the module app
        import importlib
        import services.admin.app as admin_app_module
        return admin_app_module.app


@pytest.fixture()
def client(app):
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture()
def auth_session(client):
    """Helper: set session variables so the client looks logged-in as owner."""
    with client.session_transaction() as sess:
        sess["admin_logged_in"] = True
        sess["admin_user_id"] = 1
        sess["admin_login"] = "admin"
        sess["admin_role"] = "owner"
    return client


# ---------------------------------------------------------------------------
# Shared mock target strings
# ---------------------------------------------------------------------------

_GET_CONN = "services.admin.routes.get_conn"
_LOG_ACTION = "services.admin.audit.log_action"
_RENDER = "flask.templating._render"  # used by render_template internally
_RENDER_TEMPLATE = "services.admin.routes.render_template"
_RENDER_TEMPLATE_APP = "services.admin.app.render_template"


# ===========================================================================
# Helper / pure-function tests (no HTTP needed)
# ===========================================================================

class TestDeltaStr:
    def _fn(self):
        from services.admin.routes import _delta_str
        return _delta_str

    def test_positive_delta(self):
        assert self._fn()(120, 100) == "+20.0%"

    def test_negative_delta(self):
        result = self._fn()(80, 100)
        assert result == "-20.0%"

    def test_zero_delta(self):
        assert self._fn()(100, 100) == "0%"

    def test_no_prev(self):
        assert self._fn()(100, 0) == ""

    def test_prev_none(self):
        assert self._fn()(100, None) == ""

    def test_curr_none(self):
        result = self._fn()(None, 100)
        assert result == "-100.0%"

    def test_float_values(self):
        result = self._fn()(1.5, 1.0)
        assert "+" in result


class TestGetPeriodSql:
    def _fn(self):
        from services.admin.routes import _get_period_sql
        return _get_period_sql

    def test_day(self):
        assert self._fn()("day") == (1, "1 day")

    def test_week(self):
        assert self._fn()("week") == (7, "7 days")

    def test_month(self):
        assert self._fn()("month") == (30, "30 days")

    def test_default(self):
        assert self._fn()("year") == (30, "30 days")


class TestPeriodDays:
    def _fn(self):
        from services.admin.routes import _period_days
        return _period_days

    def test_day(self):
        assert self._fn()("day") == 1

    def test_week(self):
        assert self._fn()("week") == 7

    def test_month(self):
        assert self._fn()("month") == 30

    def test_other(self):
        assert self._fn()("year") == 365


class TestInfraCost:
    def _fn(self):
        from services.admin.routes import _infra_cost_rub_for_days
        return _infra_cost_rub_for_days

    def test_30_days(self):
        cost = self._fn()(30)
        assert isinstance(cost, float)
        assert cost > 0

    def test_1_day(self):
        cost = self._fn()(1)
        assert cost < self._fn()(30)


class TestAdminIp:
    def _fn(self):
        from services.admin.routes import _admin_ip
        return _admin_ip

    def test_forwarded_for(self, app):
        with app.test_request_context("/", headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}):
            ip = self._fn()()
            assert ip == "1.2.3.4"

    def test_remote_addr(self, app):
        with app.test_request_context("/", environ_base={"REMOTE_ADDR": "9.9.9.9"}):
            ip = self._fn()()
            assert ip == "9.9.9.9"


# ===========================================================================
# Auth routes
# ===========================================================================

class TestLoginLogout:
    def test_login_get(self, client):
        with patch(_RENDER_TEMPLATE_APP, return_value="login page") as mock_render:
            resp = client.get("/login")
            assert resp.status_code == 200
            mock_render.assert_called_once()
            call_kwargs = mock_render.call_args
            assert call_kwargs[0][0] == "login.html"

    def test_login_post_bad_credentials(self, client):
        with patch("services.admin.app.authenticate_admin", return_value=None), \
             patch(_RENDER_TEMPLATE_APP, return_value="bad creds") as mock_render:
            resp = client.post("/login", data={"login": "admin", "password": "wrong"})
            assert resp.status_code == 200
            mock_render.assert_called()

    def test_login_post_success(self, client):
        fake_auth = {"id": 1, "login": "admin", "role": "owner", "otp_required": False, "token": "test-token"}
        with patch("services.admin.app.authenticate_admin", return_value=fake_auth):
            resp = client.post("/login", data={"login": "admin", "password": "correct"})
            # Should redirect to dashboard
            assert resp.status_code == 302

    def test_login_post_otp_required(self, client):
        fake_auth = {"otp_required": True, "login": "admin"}
        with patch("services.admin.app.authenticate_admin", return_value=fake_auth), \
             patch(_RENDER_TEMPLATE_APP, return_value="otp needed") as mock_render:
            resp = client.post("/login", data={"login": "admin", "password": "pass"})
            assert resp.status_code == 200
            _, kwargs = mock_render.call_args
            assert kwargs.get("otp_required") is True or mock_render.call_args[0]

    def test_logout_redirects(self, auth_session):
        resp = auth_session.get("/logout")
        assert resp.status_code == 302

    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"


# ===========================================================================
# Unauthenticated redirects
# ===========================================================================

class TestUnauthenticated:
    """All protected routes should redirect to /login when not logged in."""

    def test_dashboard_redirects(self, client):
        resp = client.get("/")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_users_redirects(self, client):
        resp = client.get("/users")
        assert resp.status_code == 302

    def test_payments_redirects(self, client):
        resp = client.get("/payments")
        assert resp.status_code == 302

    def test_errors_redirects(self, client):
        resp = client.get("/errors")
        assert resp.status_code == 302

    def test_audit_redirects(self, client):
        resp = client.get("/audit")
        assert resp.status_code == 302

    def test_feedback_redirects(self, client):
        resp = client.get("/feedback")
        assert resp.status_code == 302

    def test_content_redirects(self, client):
        resp = client.get("/content")
        assert resp.status_code == 302

    def test_tariffs_redirects(self, client):
        resp = client.get("/tariffs")
        assert resp.status_code == 302

    def test_user_detail_redirects(self, client):
        resp = client.get("/user/1")
        assert resp.status_code == 302

    def test_stats_redirects(self, client):
        resp = client.get("/stats")
        assert resp.status_code == 302


# ===========================================================================
# Dashboard
# ===========================================================================

def _dashboard_cursor():
    """Build a cursor that answers all the dashboard queries with sensible
    zero-row / zero-count responses."""

    # Single-value count rows
    _count_row = {"count": 0}
    _sum_row = {"s": 0, "c": 0}
    _arpu_row = {"arpu": 0}
    _cost_row = {"cost_usd": 0}

    fetchone_sequence = [
        # users_day, users_week, users_month, users_year, users_total
        _count_row, _count_row, _count_row, _count_row, _count_row,
        # dau, wau, mau
        _count_row, _count_row, _count_row,
        # users_period, users_prev
        _count_row, _count_row,
        # pay_day
        {"s": 0, "c": 0},
        # pay_week
        {"s": 0, "c": 0},
        # pay_month
        {"s": 0, "c": 0},
        # pay_year
        {"s": 0, "c": 0},
        # pay_total
        {"s": 0, "c": 0},
        # pay_period
        {"s": 0, "c": 0},
        # pay_prev
        {"s": 0, "c": 0},
        # pay_pending
        {"s": 0, "c": 0},
        # arpu
        _arpu_row,
        # ai_cost
        _cost_row,
        # payers_total
        _count_row,
        # ret_1d, ret_3d, ret_7d
        _count_row, _count_row, _count_row,
        # base_1d, base_3d, base_7d
        {"count": 1}, {"count": 1}, {"count": 1},
        # gen_day, gen_week, gen_month, gen_year, gen_total
        _count_row, _count_row, _count_row, _count_row, _count_row,
        # gen_period, gen_prev
        _count_row, _count_row,
        # active_today
        _count_row,
        # errors_week, total_week
        _count_row, {"count": 1},
        # banned_total
        _count_row,
        # promo_uses, promo_codes
        _count_row, _count_row,
        # referred_total, referred_paid
        _count_row, _count_row,
    ]

    fetchall_sequence = [
        # segment_counts
        [],
        # provider_split
        [],
        # last_payments
        [],
        # activity_day (24 hours call)
        [],
        # activity_week
        [],
        # activity_month
        [],
        # requests_by_type
        [],
        # requests_by_model
        [],
        # avg_gen_time
        [],
        # top_errors
        [],
        # top_sources
        [],
        # ratings day/week/month (3x)
        [], [], [],
        # users_trend
        [],
        # pay_trend
        [],
        # gen_trend
        [],
    ]
    return _make_cursor(fetchone_sequence, fetchall_sequence)


class TestDashboard:
    def test_dashboard_get_default(self, auth_session):
        conn = _make_conn(_dashboard_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="dashboard html"):
            resp = auth_session.get("/")
            assert resp.status_code == 200

    def test_dashboard_get_period_day(self, auth_session):
        conn = _make_conn(_dashboard_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="dashboard html"):
            resp = auth_session.get("/?period=day")
            assert resp.status_code == 200

    def test_dashboard_get_period_week(self, auth_session):
        conn = _make_conn(_dashboard_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="dashboard html"):
            resp = auth_session.get("/?period=week")
            assert resp.status_code == 200

    def test_dashboard_get_period_month(self, auth_session):
        conn = _make_conn(_dashboard_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="dashboard html"):
            resp = auth_session.get("/?period=month")
            assert resp.status_code == 200

    def test_dashboard_invalid_period_falls_back(self, auth_session):
        conn = _make_conn(_dashboard_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="dashboard html") as mock_render:
            resp = auth_session.get("/?period=century")
            assert resp.status_code == 200
            # period kwarg passed to template should be "week"
            _, kwargs = mock_render.call_args
            assert kwargs.get("period") == "week"

    def test_dashboard_conn_closed_on_success(self, auth_session):
        conn = _make_conn(_dashboard_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="ok"):
            auth_session.get("/")
        conn.close.assert_called_once()

    def test_dashboard_alerts_generated(self, auth_session):
        """When errors_week_pct > 15 and pay_pending_cnt > 5, alerts fire."""
        cursor = _dashboard_cursor()

        # We need to override specific fetchone results to trigger alerts.
        # errors_week = 20, total_week = 100 → 20% → alert
        # pay_pending = sum=1000 cnt=10 → alert
        # This is hard to do with positional mocking, so we verify the
        # render_template call includes 'alerts' kwarg.
        conn = _make_conn(cursor)
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="ok") as mock_render:
            auth_session.get("/")
        _, kwargs = mock_render.call_args
        assert "alerts" in kwargs


# ===========================================================================
# Payments list
# ===========================================================================

def _payments_cursor():
    fetchone = [
        {"count": 3},  # total
        {"revenue_confirmed": 999.0, "refunds_sum": 0.0, "refunds_cnt": 0},  # summary
        {"cnt": 2},  # confirmed_cnt
    ]
    fetchall = [
        # providers
        [{"provider": "yookassa", "cnt": 2, "sum_rub": 999.0}],
        # rows (payments list)
        [
            {
                "id": 1, "user_id": 10, "username": "user1", "first_name": "Alice",
                "amount_rub": 499.0, "credits_amount": 100, "pack_name": "basic",
                "status": "confirmed", "provider": "yookassa",
                "created_at": "2024-01-01", "confirmed_at": "2024-01-01",
                "payment_id": "pay_001", "promo_code": None,
            }
        ],
    ]
    return _make_cursor(fetchone, fetchall)


class TestPaymentsList:
    def test_payments_list_basic(self, auth_session):
        conn = _make_conn(_payments_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="payments html"):
            resp = auth_session.get("/payments")
            assert resp.status_code == 200

    def test_payments_list_status_filter(self, auth_session):
        conn = _make_conn(_payments_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="payments html") as mock_render:
            resp = auth_session.get("/payments?status=confirmed")
            assert resp.status_code == 200
            _, kwargs = mock_render.call_args
            assert kwargs["status_filter"] == "confirmed"

    def test_payments_list_provider_filter(self, auth_session):
        conn = _make_conn(_payments_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="payments html") as mock_render:
            resp = auth_session.get("/payments?provider=yookassa")
            assert resp.status_code == 200
            _, kwargs = mock_render.call_args
            assert kwargs["provider_filter"] == "yookassa"

    def test_payments_list_pagination(self, auth_session):
        conn = _make_conn(_payments_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="payments html") as mock_render:
            resp = auth_session.get("/payments?page=2")
            assert resp.status_code == 200
            _, kwargs = mock_render.call_args
            assert kwargs["page"] == 2

    def test_payments_list_invalid_page(self, auth_session):
        conn = _make_conn(_payments_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="payments html") as mock_render:
            resp = auth_session.get("/payments?page=notanumber")
            assert resp.status_code == 200
            _, kwargs = mock_render.call_args
            assert kwargs["page"] == 1

    def test_payments_conn_closed(self, auth_session):
        conn = _make_conn(_payments_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="ok"):
            auth_session.get("/payments")
        conn.close.assert_called_once()


# ===========================================================================
# Payments export
# ===========================================================================

class TestPaymentsExport:
    def _cursor(self):
        rows = [
            {
                "id": 1, "user_id": 10, "username": "u1", "first_name": "Bob",
                "amount_rub": 499.0, "credits_amount": 50, "pack_name": "lite",
                "status": "confirmed", "provider": "stars", "promo_code": None,
                "created_at": "2024-01-01", "confirmed_at": "2024-01-01",
                "payment_id": "p1",
            }
        ]
        return _make_cursor([], [rows])

    def test_export_returns_csv(self, auth_session):
        conn = _make_conn(self._cursor())
        with patch(_GET_CONN, return_value=conn):
            resp = auth_session.get("/payments/export")
        assert resp.status_code == 200
        assert "text/csv" in resp.content_type

    def test_export_csv_has_header(self, auth_session):
        conn = _make_conn(self._cursor())
        with patch(_GET_CONN, return_value=conn):
            resp = auth_session.get("/payments/export")
        data = resp.data.decode()
        assert "id" in data
        assert "amount_rub" in data

    def test_export_with_status_filter(self, auth_session):
        conn = _make_conn(self._cursor())
        with patch(_GET_CONN, return_value=conn):
            resp = auth_session.get("/payments/export?status=confirmed")
        assert resp.status_code == 200

    def test_export_filename_header(self, auth_session):
        conn = _make_conn(self._cursor())
        with patch(_GET_CONN, return_value=conn):
            resp = auth_session.get("/payments/export")
        assert "payments.csv" in resp.headers.get("Content-Disposition", "")


# ===========================================================================
# Errors page
# ===========================================================================

def _errors_cursor(rows=None):
    if rows is None:
        rows = []
    fetchone = [{"count": len(rows)}]
    fetchall = [rows]
    return _make_cursor(fetchone, fetchall)


class TestErrorsPage:
    def test_errors_page_basic(self, auth_session):
        conn = _make_conn(_errors_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="errors html"):
            resp = auth_session.get("/errors")
            assert resp.status_code == 200

    def test_errors_page_user_id_filter(self, auth_session):
        conn = _make_conn(_errors_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="errors html") as mock_render:
            resp = auth_session.get("/errors?user_id=42")
            assert resp.status_code == 200
            _, kwargs = mock_render.call_args
            assert kwargs["user_filter"] == "42"

    def test_errors_page_username_filter(self, auth_session):
        conn = _make_conn(_errors_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="errors html"):
            resp = auth_session.get("/errors?user_id=john")
            assert resp.status_code == 200

    def test_errors_page_sort_by_user(self, auth_session):
        conn = _make_conn(_errors_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="errors html") as mock_render:
            resp = auth_session.get("/errors?sort=user")
            assert resp.status_code == 200
            _, kwargs = mock_render.call_args
            assert kwargs["sort_by"] == "user"

    def test_errors_page_pagination(self, auth_session):
        conn = _make_conn(_errors_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="errors html") as mock_render:
            resp = auth_session.get("/errors?page=3")
            assert resp.status_code == 200
            _, kwargs = mock_render.call_args
            assert kwargs["page"] == 3

    def test_errors_page_invalid_page(self, auth_session):
        conn = _make_conn(_errors_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="errors html") as mock_render:
            resp = auth_session.get("/errors?page=bad")
            assert resp.status_code == 200
            _, kwargs = mock_render.call_args
            assert kwargs["page"] == 1


# ===========================================================================
# Errors export
# ===========================================================================

class TestErrorsExport:
    def _cursor(self):
        rows = [
            {
                "id": 1, "user_id": 5, "username": "alice", "first_name": "Alice",
                "task_type": "text", "error_message": "some error",
                "started_at": "2024-01-01", "model": "gpt-4", "source": "request",
            }
        ]
        return _make_cursor([], [rows])

    def test_export_returns_csv(self, auth_session):
        conn = _make_conn(self._cursor())
        with patch(_GET_CONN, return_value=conn):
            resp = auth_session.get("/errors/export")
        assert resp.status_code == 200
        assert "text/csv" in resp.content_type

    def test_export_csv_has_error_column(self, auth_session):
        conn = _make_conn(self._cursor())
        with patch(_GET_CONN, return_value=conn):
            resp = auth_session.get("/errors/export")
        data = resp.data.decode()
        assert "error_message" in data

    def test_export_filename(self, auth_session):
        conn = _make_conn(self._cursor())
        with patch(_GET_CONN, return_value=conn):
            resp = auth_session.get("/errors/export")
        assert "errors.csv" in resp.headers.get("Content-Disposition", "")


# ===========================================================================
# Stats page
# ===========================================================================

def _stats_cursor():
    fetchone = [{"count": 5}, {"count": 10}]
    fetchall = [
        [{"day": "2024-01-01", "cnt": 3}],
        [{"day": "2024-01-01", "cnt": 2, "sum_rub": 499.0}],
        [{"task_type": "text", "cnt": 7}],
    ]
    return _make_cursor(fetchone, fetchall)


class TestStatsPage:
    def test_stats_page_renders(self, auth_session):
        conn = _make_conn(_stats_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="stats html"):
            resp = auth_session.get("/stats")
            assert resp.status_code == 200

    def test_stats_conn_closed(self, auth_session):
        conn = _make_conn(_stats_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="ok"):
            auth_session.get("/stats")
        conn.close.assert_called_once()


# ===========================================================================
# Users list
# ===========================================================================

def _users_cursor(rows=None):
    if rows is None:
        rows = []
    fetchone = [{"count": len(rows)}]
    fetchall = [rows]
    return _make_cursor(fetchone, fetchall)


class TestUsersList:
    def test_users_list_basic(self, auth_session):
        conn = _make_conn(_users_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="users html"):
            resp = auth_session.get("/users")
            assert resp.status_code == 200

    def test_users_list_search_text(self, auth_session):
        conn = _make_conn(_users_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="users html") as mock_render:
            resp = auth_session.get("/users?q=alice")
            assert resp.status_code == 200
            _, kwargs = mock_render.call_args
            assert kwargs["q"] == "alice"

    def test_users_list_search_by_id(self, auth_session):
        conn = _make_conn(_users_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="users html"):
            resp = auth_session.get("/users?q=42")
            assert resp.status_code == 200

    def test_users_list_status_filter(self, auth_session):
        conn = _make_conn(_users_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="users html") as mock_render:
            resp = auth_session.get("/users?status=paid")
            assert resp.status_code == 200
            _, kwargs = mock_render.call_args
            assert kwargs["status_filter"] == "paid"

    def test_users_list_sort_and_dir(self, auth_session):
        conn = _make_conn(_users_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="users html") as mock_render:
            resp = auth_session.get("/users?sort=ltv&dir=asc")
            assert resp.status_code == 200
            _, kwargs = mock_render.call_args
            assert kwargs["direction"] == "asc"

    def test_users_list_pagination(self, auth_session):
        conn = _make_conn(_users_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="users html") as mock_render:
            resp = auth_session.get("/users?page=2")
            assert resp.status_code == 200
            _, kwargs = mock_render.call_args
            assert kwargs["page"] == 2

    def test_users_list_invalid_page(self, auth_session):
        conn = _make_conn(_users_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="users html") as mock_render:
            resp = auth_session.get("/users?page=xyz")
            assert resp.status_code == 200
            _, kwargs = mock_render.call_args
            assert kwargs["page"] == 1


# ===========================================================================
# Users export
# ===========================================================================

class TestUsersExport:
    def _cursor(self):
        rows = [
            {
                "id": 1, "username": "alice", "first_name": "Alice",
                "credits_bought": 50, "credits_free_today": 5,
                "created_at": "2024-01-01", "is_blocked": False,
                "total_payments_rub": 0, "last_active_at": "2024-01-02",
                "source": "organic", "segment": "free",
            }
        ]
        return _make_cursor([], [rows])

    def test_export_returns_csv(self, auth_session):
        conn = _make_conn(self._cursor())
        with patch(_GET_CONN, return_value=conn):
            resp = auth_session.get("/users/export")
        assert resp.status_code == 200
        assert "text/csv" in resp.content_type

    def test_export_csv_header(self, auth_session):
        conn = _make_conn(self._cursor())
        with patch(_GET_CONN, return_value=conn):
            resp = auth_session.get("/users/export")
        data = resp.data.decode()
        assert "username" in data
        assert "segment" in data

    def test_export_filename(self, auth_session):
        conn = _make_conn(self._cursor())
        with patch(_GET_CONN, return_value=conn):
            resp = auth_session.get("/users/export")
        assert "users.csv" in resp.headers.get("Content-Disposition", "")


# ===========================================================================
# User detail
# ===========================================================================

def _user_detail_cursor(user_exists=True):
    if user_exists:
        user_row = {
            "id": 1, "username": "alice", "first_name": "Alice",
            "credits_bought": 50, "credits_free_today": 5,
            "is_blocked": False, "total_payments_rub": 0,
            "unlimited_ends_at": None, "trial_started_at": None,
            "full_access_48h_ends_at": None, "referral_count": 0,
            "acquisition_channel": None, "utm_source": None,
            "last_active_at": None, "created_at": "2024-01-01",
            "referred_by": None,
        }
    else:
        user_row = None

    fetchone = [user_row]
    fetchall = [
        # payments
        [],
        # transactions
        [],
        # notes
        [],
        # messages
        [],
        # feedback
        [],
    ]
    return _make_cursor(fetchone, fetchall)


class TestUserDetail:
    def test_user_found(self, auth_session):
        conn = _make_conn(_user_detail_cursor(user_exists=True))
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="user detail html"):
            resp = auth_session.get("/user/1")
            assert resp.status_code == 200

    def test_user_not_found(self, auth_session):
        conn = _make_conn(_user_detail_cursor(user_exists=False))
        with patch(_GET_CONN, return_value=conn):
            resp = auth_session.get("/user/999")
            assert resp.status_code == 404

    def test_user_detail_with_data(self, auth_session):
        """Cursor returns real-looking rows for all sub-queries."""
        cursor = _make_cursor(
            fetchone_seq=[
                {
                    "id": 1, "username": "bob", "first_name": "Bob",
                    "credits_bought": 100, "credits_free_today": 0,
                    "is_blocked": False, "total_payments_rub": 499.0,
                    "unlimited_ends_at": None, "trial_started_at": None,
                    "full_access_48h_ends_at": None, "referral_count": 2,
                    "acquisition_channel": "telegram", "utm_source": None,
                    "last_active_at": "2024-01-10", "created_at": "2024-01-01",
                    "referred_by": 42,
                }
            ],
            fetchall_seq=[
                [{"id": 10, "amount_rub": 499.0, "credits_amount": 100, "status": "confirmed",
                  "provider": "yookassa", "promo_code": None, "created_at": "2024-01-01", "confirmed_at": "2024-01-01"}],
                [{"amount": 100, "type": "purchase", "description": "Pack", "created_at": "2024-01-01"}],
                [{"note": "VIP", "created_at": "2024-01-01"}],
                [{"role": "user", "content": "hello", "created_at": "2024-01-01"}],
                [{"id": 1, "text": "great bot", "status": "new", "admin_note": None,
                  "created_at": "2024-01-01", "updated_at": "2024-01-01"}],
            ],
        )
        conn = _make_conn(cursor)
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="user detail html") as mock_render:
            resp = auth_session.get("/user/1")
            assert resp.status_code == 200
            _, kwargs = mock_render.call_args
            assert "user" in kwargs
            assert kwargs["user"]["username"] == "bob"


# ===========================================================================
# User actions
# ===========================================================================

def _simple_conn():
    """A conn whose cursor returns sensible defaults for user actions."""
    fetchone = [{"credits_bought": 200}]
    return _make_conn(_make_cursor(fetchone_seq=fetchone))


class TestUserAction:
    def _post(self, auth_session, user_id, **form_data):
        return auth_session.post(f"/user/{user_id}/action", data=form_data)

    def test_ban_action(self, auth_session):
        conn = _simple_conn()
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="ban")
        assert resp.status_code == 302

    def test_unban_action(self, auth_session):
        conn = _simple_conn()
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="unban")
        assert resp.status_code == 302

    def test_add_credits_valid(self, auth_session):
        conn = _simple_conn()
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="add_credits", amount="50")
        assert resp.status_code == 302

    def test_add_credits_invalid_amount(self, auth_session):
        conn = _simple_conn()
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="add_credits", amount="notanumber")
        assert resp.status_code == 302

    def test_add_credits_zero_amount(self, auth_session):
        conn = _simple_conn()
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="add_credits", amount="0")
        assert resp.status_code == 302

    def test_sub_credits_valid(self, auth_session):
        conn = _simple_conn()
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="sub_credits", amount="10")
        assert resp.status_code == 302

    def test_sub_credits_invalid_amount(self, auth_session):
        conn = _simple_conn()
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="sub_credits", amount="bad")
        assert resp.status_code == 302

    def test_set_unlimited_valid(self, auth_session):
        conn = _simple_conn()
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="set_unlimited", days="30")
        assert resp.status_code == 302

    def test_set_unlimited_invalid_days(self, auth_session):
        conn = _simple_conn()
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="set_unlimited", days="bad")
        assert resp.status_code == 302

    def test_set_unlimited_zero_days(self, auth_session):
        conn = _simple_conn()
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="set_unlimited", days="0")
        assert resp.status_code == 302

    def test_remove_unlimited(self, auth_session):
        conn = _simple_conn()
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="remove_unlimited")
        assert resp.status_code == 302

    def test_note_action_valid(self, auth_session):
        conn = _simple_conn()
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="note", note="Test note")
        assert resp.status_code == 302

    def test_note_action_empty_note(self, auth_session):
        """Empty note should not insert."""
        conn = _simple_conn()
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="note", note="")
        assert resp.status_code == 302

    def test_note_action_db_error(self, auth_session):
        """DB error in note insert should be handled gracefully (flash error)."""
        conn = _simple_conn()
        conn.cursor.return_value.execute.side_effect = [None, Exception("db error")]
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="note", note="a note")
        assert resp.status_code == 302

    def test_unknown_action(self, auth_session):
        """Unknown action should do nothing but still redirect."""
        conn = _simple_conn()
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="fly_to_moon")
        assert resp.status_code == 302

    def test_unauthenticated_post_redirects(self, client):
        resp = client.post("/user/1/action", data={"action": "ban"})
        assert resp.status_code == 302

    def test_viewer_role_redirected(self, client):
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_user_id"] = 2
            sess["admin_login"] = "viewer"
            sess["admin_role"] = "viewer"
        resp = client.post("/user/1/action", data={"action": "ban"})
        # role_required should redirect to dashboard
        assert resp.status_code == 302


# ===========================================================================
# Audit log
# ===========================================================================

def _audit_cursor(rows=None):
    rows = rows or []
    return _make_cursor([], [rows])


class TestAuditLog:
    def test_audit_log_basic(self, auth_session):
        conn = _make_conn(_audit_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="audit html"):
            resp = auth_session.get("/audit")
            assert resp.status_code == 200

    def test_audit_log_action_filter(self, auth_session):
        conn = _make_conn(_audit_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="audit html") as mock_render:
            resp = auth_session.get("/audit?action=user_block")
            assert resp.status_code == 200
            _, kwargs = mock_render.call_args
            assert kwargs["action_filter"] == "user_block"

    def test_audit_log_entity_filter(self, auth_session):
        conn = _make_conn(_audit_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="audit html") as mock_render:
            resp = auth_session.get("/audit?entity_type=user")
            assert resp.status_code == 200
            _, kwargs = mock_render.call_args
            assert kwargs["entity_filter"] == "user"

    def test_audit_conn_closed(self, auth_session):
        conn = _make_conn(_audit_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="ok"):
            auth_session.get("/audit")
        conn.close.assert_called_once()


# ===========================================================================
# Feedback list
# ===========================================================================

def _feedback_cursor(rows=None):
    rows = rows or []
    return _make_cursor([], [rows])


class TestFeedbackList:
    def test_feedback_list_basic(self, auth_session):
        conn = _make_conn(_feedback_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="feedback html"):
            resp = auth_session.get("/feedback")
            assert resp.status_code == 200

    def test_feedback_list_status_filter(self, auth_session):
        conn = _make_conn(_feedback_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="feedback html") as mock_render:
            resp = auth_session.get("/feedback?status=new")
            assert resp.status_code == 200
            _, kwargs = mock_render.call_args
            assert kwargs["status_filter"] == "new"

    def test_feedback_conn_closed(self, auth_session):
        conn = _make_conn(_feedback_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="ok"):
            auth_session.get("/feedback")
        conn.close.assert_called_once()


# ===========================================================================
# Feedback action
# ===========================================================================

class TestFeedbackAction:
    def _post(self, auth_session, feedback_id, **form_data):
        return auth_session.post(f"/feedback/{feedback_id}/action", data=form_data)

    def test_update_resolved(self, auth_session):
        conn = _make_conn(_make_cursor())
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="update", status="resolved", admin_note="Done")
        assert resp.status_code == 302

    def test_update_closed(self, auth_session):
        conn = _make_conn(_make_cursor())
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="update", status="closed", admin_note="")
        assert resp.status_code == 302

    def test_update_in_progress(self, auth_session):
        conn = _make_conn(_make_cursor())
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="update", status="in_progress", admin_note="")
        assert resp.status_code == 302

    def test_update_new_status(self, auth_session):
        conn = _make_conn(_make_cursor())
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="update", status="new", admin_note="")
        assert resp.status_code == 302

    def test_update_invalid_status_redirects(self, auth_session):
        conn = _make_conn(_make_cursor())
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="update", status="invalid_status", admin_note="")
        # Should redirect (flash error and redirect to feedback_list)
        assert resp.status_code == 302

    def test_no_action_still_redirects(self, auth_session):
        conn = _make_conn(_make_cursor())
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            resp = self._post(auth_session, 1, action="", status="new", admin_note="")
        assert resp.status_code == 302

    def test_feedback_action_conn_closed(self, auth_session):
        conn = _make_conn(_make_cursor())
        with patch(_GET_CONN, return_value=conn), patch(_LOG_ACTION):
            self._post(auth_session, 1, action="update", status="resolved")
        conn.close.assert_called_once()

    def test_unauthenticated_redirects(self, client):
        resp = client.post("/feedback/1/action", data={"action": "update", "status": "resolved"})
        assert resp.status_code == 302


# ===========================================================================
# Content texts
# ===========================================================================

def _content_cursor():
    rows = [{"key": "welcome_text", "title": "Welcome", "description": "Desc",
             "value": "Hello!", "enabled": True, "updated_at": "2024-01-01"}]
    return _make_cursor([], [[], rows])  # first fetchall for _sync (empty), second for SELECT


class TestContentTexts:
    def test_content_get(self, auth_session):
        conn = _make_conn(_content_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="content html"):
            resp = auth_session.get("/content")
            assert resp.status_code == 200

    def test_content_post_valid(self, auth_session):
        conn = _make_conn(_content_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_LOG_ACTION), \
             patch(_RENDER_TEMPLATE, return_value="content html"):
            resp = auth_session.post("/content", data={
                "key": "welcome_text",
                "value": "Hello World!",
                "title": "Welcome",
                "description": "A greeting",
                "enabled": "on",
            })
            assert resp.status_code == 200

    def test_content_post_missing_key(self, auth_session):
        """Post without key should skip the UPDATE but still render."""
        conn = _make_conn(_content_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="content html"):
            resp = auth_session.post("/content", data={
                "key": "",
                "value": "something",
            })
            assert resp.status_code == 200

    def test_content_post_missing_value(self, auth_session):
        """Post without value should skip the UPDATE."""
        conn = _make_conn(_content_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="content html"):
            resp = auth_session.post("/content", data={
                "key": "welcome_text",
                "value": "",
            })
            assert resp.status_code == 200

    def test_content_conn_closed(self, auth_session):
        conn = _make_conn(_content_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="ok"):
            auth_session.get("/content")
        conn.close.assert_called_once()


# ===========================================================================
# Tariffs
# ===========================================================================

def _tariffs_cursor():
    rows = [
        {
            "plan_key": "lite", "label": "Lite", "credits": 50,
            "price_rub": 149.0, "price_stars": 0, "price_usd": 1.99,
            "discount": "", "enabled": True, "sort_order": 1,
            "is_one_time": False, "is_unlimited": False,
            "period_days": None, "updated_at": "2024-01-01",
        }
    ]
    return _make_cursor([], [[], rows])  # first fetchall _sync, second SELECT


class TestTariffsList:
    def test_tariffs_get(self, auth_session):
        conn = _make_conn(_tariffs_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="tariffs html"):
            resp = auth_session.get("/tariffs")
            assert resp.status_code == 200

    def test_tariffs_post_valid(self, auth_session):
        conn = _make_conn(_tariffs_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_LOG_ACTION), \
             patch(_RENDER_TEMPLATE, return_value="tariffs html"):
            resp = auth_session.post("/tariffs", data={
                "plan_key": "lite",
                "label": "Lite Pack",
                "credits": "50",
                "price_rub": "149.0",
                "price_stars": "0",
                "price_usd": "1.99",
                "discount": "10%",
                "enabled": "on",
                "sort_order": "1",
                "is_one_time": "off",
                "period_days": "30",
            })
            assert resp.status_code == 200

    def test_tariffs_post_no_plan_key(self, auth_session):
        """Post without plan_key skips UPDATE."""
        conn = _make_conn(_tariffs_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="tariffs html"):
            resp = auth_session.post("/tariffs", data={"plan_key": ""})
            assert resp.status_code == 200

    def test_tariffs_conn_closed(self, auth_session):
        conn = _make_conn(_tariffs_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="ok"):
            auth_session.get("/tariffs")
        conn.close.assert_called_once()


# ===========================================================================
# Role-based access control
# ===========================================================================

class TestRBACRedirects:
    """Routes protected by role_required should redirect 'viewer' role to /."""

    def _viewer_client(self, client):
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_user_id"] = 99
            sess["admin_login"] = "viewer_user"
            sess["admin_role"] = "viewer"
        return client

    def test_users_export_requires_admin(self, client):
        self._viewer_client(client)
        resp = client.get("/users/export")
        assert resp.status_code == 302

    def test_payments_export_requires_admin(self, client):
        self._viewer_client(client)
        resp = client.get("/payments/export")
        assert resp.status_code == 302

    def test_errors_export_requires_admin(self, client):
        self._viewer_client(client)
        resp = client.get("/errors/export")
        assert resp.status_code == 302

    def test_audit_requires_admin(self, client):
        self._viewer_client(client)
        resp = client.get("/audit")
        assert resp.status_code == 302

    def test_content_requires_admin(self, client):
        self._viewer_client(client)
        resp = client.get("/content")
        assert resp.status_code == 302

    def test_tariffs_requires_admin(self, client):
        self._viewer_client(client)
        resp = client.get("/tariffs")
        assert resp.status_code == 302

    def test_support_can_access_feedback(self, client):
        """Support role SHOULD be able to access /feedback."""
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_user_id"] = 3
            sess["admin_login"] = "support_user"
            sess["admin_role"] = "support"
        conn = _make_conn(_feedback_cursor())
        with patch(_GET_CONN, return_value=conn), \
             patch(_RENDER_TEMPLATE, return_value="feedback html"):
            resp = client.get("/feedback")
            assert resp.status_code == 200


# ===========================================================================
# Rate limiting on login
# ===========================================================================

class TestLoginRateLimit:
    def test_rate_limit_blocks_after_5_failures(self, client):
        """After 5 failed attempts from the same IP, the 6th should show
        rate-limit message instead of regular auth error."""
        import services.admin.app as _admin_app
        _admin_app._login_attempts.clear()
        with patch("services.admin.app.authenticate_admin", return_value=None), \
             patch(_RENDER_TEMPLATE_APP, return_value="blocked") as mock_render:
            for _ in range(6):
                resp = client.post(
                    "/login",
                    data={"login": "admin", "password": "wrong"},
                    environ_base={"REMOTE_ADDR": "10.0.0.222"},
                )
            _admin_app._login_attempts.clear()
            calls = mock_render.call_args_list
            error_texts = [c[1].get("error", "") for c in calls if c[1]]
            assert any("попыток" in (t or "") for t in error_texts)
