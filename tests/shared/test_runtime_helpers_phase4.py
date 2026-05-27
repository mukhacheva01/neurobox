"""Additional phase 4 coverage tests for helper modules."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_build_async_database_url_custom_values():
    from shared.config.runtime_urls import build_async_database_url

    assert (
        build_async_database_url(
            host="db",
            port=6543,
            database="nb",
            user="alice",
            password="secret",
        )
        == "postgresql+asyncpg://alice:secret@db:6543/nb"
    )


def test_build_sync_database_url_custom_values():
    from shared.config.runtime_urls import build_sync_database_url

    assert (
        build_sync_database_url(
            host="db",
            port=6543,
            database="nb",
            user="alice",
            password="secret",
        )
        == "postgresql://alice:secret@db:6543/nb"
    )


def test_normalize_sync_database_url_converts_asyncpg_prefix():
    from shared.config.runtime_urls import normalize_sync_database_url

    assert (
        normalize_sync_database_url("postgresql+asyncpg://u:p@host:5432/db")
        == "postgresql://u:p@host:5432/db"
    )


def test_database_url_from_env_uses_raw_database_url():
    from shared.config.runtime_urls import database_url_from_env

    with patch.dict("os.environ", {"DATABASE_URL": "postgresql+asyncpg://raw"}, clear=True):
        assert database_url_from_env() == "postgresql+asyncpg://raw"
        assert database_url_from_env(async_driver=False) == "postgresql://raw"


def test_database_url_from_env_builds_from_parts():
    from shared.config.runtime_urls import database_url_from_env

    with patch.dict(
        "os.environ",
        {
            "POSTGRES_HOST": "db",
            "POSTGRES_PORT": "6543",
            "POSTGRES_DB": "nb",
            "POSTGRES_USER": "alice",
            "POSTGRES_PASSWORD": "secret",
        },
        clear=True,
    ):
        assert database_url_from_env() == "postgresql+asyncpg://alice:secret@db:6543/nb"


def test_redis_url_from_env_prefers_raw_value():
    from shared.config.runtime_urls import redis_url_from_env

    with patch.dict("os.environ", {"REDIS_URL": "redis://custom"}, clear=True):
        assert redis_url_from_env(db=5) == "redis://custom"


def test_redis_url_from_env_builds_from_parts():
    from shared.config.runtime_urls import redis_url_from_env

    with patch.dict(
        "os.environ",
        {
            "REDIS_HOST": "cache",
            "REDIS_PORT": "6380",
            "REDIS_PASSWORD": "pw",
        },
        clear=True,
    ):
        assert redis_url_from_env(db=2) == "redis://:pw@cache:6380/2"


def test_routes_shared_admin_helpers_and_sync_defaults():
    from services.admin import routes_shared as m

    with patch("services.admin.routes_shared.current_admin", return_value={"id": "42"}):
        assert m.admin_user_id() == 42

    with patch("services.admin.routes_shared.current_admin", return_value={"id": "oops"}):
        assert m.admin_user_id() is None

    with patch("services.admin.routes_shared.settings") as mock_settings:
        mock_settings.infra_monthly_cost_usd = 30.0
        mock_settings.usd_to_rub = 100.0
        assert m.infra_cost_rub_for_days(15) == 1500.0

    fake_cursor = MagicMock()
    m.sync_default_content_and_plans(fake_cursor, admin_id=7)
    assert fake_cursor.execute.call_count >= len(m.DEFAULT_ADMIN_TEXTS) + len(m.DEFAULT_CREDIT_PACKS)


def test_routes_shared_request_helpers():
    from services.admin.app import app
    from services.admin import routes_shared as m

    assert m.delta_str(120, 100) == "+20.0%"
    assert m.get_period_sql("week") == (7, "7 days")
    assert m.period_days("month") == 30

    with app.test_request_context("/", headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}):
        assert m.admin_ip() == "1.2.3.4"
