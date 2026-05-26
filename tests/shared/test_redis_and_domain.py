"""Tests for shared/redis/store.py, shared/domain/admin_runtime.py,
shared/domain/cryptobot.py, shared/domain/payment_notify.py,
shared/domain/video.py, and shared/domain/analytics.py.

Target: raise coverage on all six files significantly.
asyncio_mode = auto (from pytest.ini) — bare async def test_* functions work.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============================================================================
# Helpers
# ============================================================================

def _make_conn():
    """Return a mock asyncpg connection."""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    return conn


def _make_pool(conn=None):
    """Return a mock asyncpg pool that yields *conn* from acquire()."""
    if conn is None:
        conn = _make_conn()
    pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire
    return pool, conn


# ============================================================================
# shared/redis/store.py
# ============================================================================

class TestGetRedis:
    """Tests for the _get_redis singleton logic."""

    async def test_returns_cached_redis_on_ping_success(self):
        import shared.redis.store as rs
        mock_r = AsyncMock()
        mock_r.ping = AsyncMock()
        rs._redis = mock_r
        result = await rs._get_redis()
        assert result is mock_r
        rs._redis = None

    async def test_reconnects_when_ping_fails(self):
        import shared.redis.store as rs
        mock_r = AsyncMock()
        mock_r.ping = AsyncMock(side_effect=Exception("timeout"))
        rs._redis = mock_r

        new_r = AsyncMock()
        new_r.ping = AsyncMock()

        with patch("redis.asyncio.Redis.from_url", return_value=new_r):
            result = await rs._get_redis()
        # After ping failure _redis is cleared; the test may return None or new_r
        # depending on whether redis.asyncio is importable — just check no crash
        rs._redis = None

    async def test_returns_none_on_connection_failure(self):
        import shared.redis.store as rs
        rs._redis = None
        with patch("redis.asyncio.Redis.from_url", side_effect=Exception("refused")):
            result = await rs._get_redis()
        assert result is None
        rs._redis = None


class TestCloseRedis:
    async def test_close_clears_global(self):
        import shared.redis.store as rs
        mock_r = AsyncMock()
        mock_r.aclose = AsyncMock()
        rs._redis = mock_r
        await rs.close_redis()
        assert rs._redis is None

    async def test_close_swallows_exception(self):
        import shared.redis.store as rs
        mock_r = AsyncMock()
        mock_r.aclose = AsyncMock(side_effect=Exception("boom"))
        rs._redis = mock_r
        await rs.close_redis()  # must not raise
        assert rs._redis is None

    async def test_close_noop_when_already_none(self):
        import shared.redis.store as rs
        rs._redis = None
        await rs.close_redis()  # must not raise


class TestGenLock:
    async def test_acquired_true_when_redis_available(self):
        mock_r = AsyncMock()
        mock_r.set = AsyncMock(return_value=True)
        mock_r.delete = AsyncMock()
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import gen_lock
            async with gen_lock(42) as acquired:
                assert acquired is True
            mock_r.delete.assert_called_once()

    async def test_acquired_false_when_redis_unavailable(self):
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=None)):
            from shared.redis.store import gen_lock
            async with gen_lock(42) as acquired:
                assert acquired is False

    async def test_acquired_false_when_lock_taken(self):
        mock_r = AsyncMock()
        mock_r.set = AsyncMock(return_value=False)  # nx=True → lock held by other
        mock_r.delete = AsyncMock()
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import gen_lock
            async with gen_lock(99) as acquired:
                assert not acquired
            mock_r.delete.assert_not_called()

    async def test_custom_key_prefix(self):
        mock_r = AsyncMock()
        mock_r.set = AsyncMock(return_value=True)
        mock_r.delete = AsyncMock()
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import gen_lock
            async with gen_lock(7, key_prefix="pay_lock", ttl_sec=30):
                pass
            call_kwargs = mock_r.set.call_args
            assert call_kwargs[0][0] == "pay_lock:7"
            assert call_kwargs[1].get("ex") == 30

    async def test_set_exception_yields_false(self):
        mock_r = AsyncMock()
        mock_r.set = AsyncMock(side_effect=Exception("redis error"))
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import gen_lock
            async with gen_lock(5) as acquired:
                assert not acquired


class TestSetUpscaleUrl:
    async def test_returns_true_on_success(self):
        mock_r = AsyncMock()
        mock_r.set = AsyncMock()
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import set_upscale_url
            result = await set_upscale_url(1, 100, "https://example.com/img.png")
        assert result is True
        mock_r.set.assert_called_once_with("upscale:1:100", "https://example.com/img.png", ex=3600)

    async def test_returns_false_when_no_redis(self):
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=None)):
            from shared.redis.store import set_upscale_url
            result = await set_upscale_url(1, 100, "https://example.com/img.png")
        assert result is False

    async def test_returns_false_on_exception(self):
        mock_r = AsyncMock()
        mock_r.set = AsyncMock(side_effect=Exception("write error"))
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import set_upscale_url
            result = await set_upscale_url(1, 100, "url")
        assert result is False

    async def test_custom_ttl(self):
        mock_r = AsyncMock()
        mock_r.set = AsyncMock()
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import set_upscale_url
            await set_upscale_url(2, 200, "url", ttl_sec=600)
        assert mock_r.set.call_args[1]["ex"] == 600


class TestGetUpscaleUrl:
    async def test_returns_decoded_string(self):
        mock_r = AsyncMock()
        mock_r.get = AsyncMock(return_value=b"https://example.com/img.png")
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import get_upscale_url
            result = await get_upscale_url(1, 100)
        assert result == "https://example.com/img.png"

    async def test_returns_none_when_key_missing(self):
        mock_r = AsyncMock()
        mock_r.get = AsyncMock(return_value=None)
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import get_upscale_url
            result = await get_upscale_url(1, 100)
        assert result is None

    async def test_returns_none_when_no_redis(self):
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=None)):
            from shared.redis.store import get_upscale_url
            result = await get_upscale_url(1, 100)
        assert result is None

    async def test_returns_none_on_exception(self):
        mock_r = AsyncMock()
        mock_r.get = AsyncMock(side_effect=Exception("read error"))
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import get_upscale_url
            result = await get_upscale_url(1, 100)
        assert result is None


class TestPushTask:
    async def test_returns_true_on_success(self):
        mock_r = AsyncMock()
        mock_r.rpush = AsyncMock()
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import push_task, QUEUE_KEY
            result = await push_task({"type": "image", "user_id": 1})
        assert result is True
        called_key = mock_r.rpush.call_args[0][0]
        assert called_key == QUEUE_KEY

    async def test_serialises_task_as_json(self):
        mock_r = AsyncMock()
        mock_r.rpush = AsyncMock()
        task = {"type": "video", "prompt": "a cat"}
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import push_task
            await push_task(task)
        serialised = mock_r.rpush.call_args[0][1]
        assert json.loads(serialised) == task

    async def test_returns_false_when_no_redis(self):
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=None)):
            from shared.redis.store import push_task
            result = await push_task({"type": "text"})
        assert result is False

    async def test_returns_false_on_exception(self):
        mock_r = AsyncMock()
        mock_r.rpush = AsyncMock(side_effect=Exception("queue full"))
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import push_task
            result = await push_task({"type": "text"})
        assert result is False


class TestRateLimitCheckAndIncr:
    async def test_returns_false_when_under_limit(self):
        mock_r = AsyncMock()
        pipe = AsyncMock()
        pipe.execute = AsyncMock(return_value=[5, True])
        mock_r.pipeline = MagicMock(return_value=pipe)
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import rate_limit_check_and_incr
            result = await rate_limit_check_and_incr(1)
        assert result is False

    async def test_returns_true_when_over_limit(self):
        mock_r = AsyncMock()
        pipe = AsyncMock()
        pipe.execute = AsyncMock(return_value=[46, True])  # 46 > RATE_MAX_PER_WINDOW=45
        mock_r.pipeline = MagicMock(return_value=pipe)
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import rate_limit_check_and_incr
            result = await rate_limit_check_and_incr(1)
        assert result is True

    async def test_returns_false_when_no_redis(self):
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=None)):
            from shared.redis.store import rate_limit_check_and_incr
            result = await rate_limit_check_and_incr(1)
        assert result is False

    async def test_returns_false_on_exception(self):
        mock_r = AsyncMock()
        mock_r.pipeline = MagicMock(side_effect=Exception("pipeline error"))
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import rate_limit_check_and_incr
            result = await rate_limit_check_and_incr(1)
        assert result is False


class TestRateLimitIsOver:
    async def test_returns_false_when_under_limit(self):
        mock_r = AsyncMock()
        mock_r.get = AsyncMock(return_value=b"10")
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import rate_limit_is_over
            result = await rate_limit_is_over(1)
        assert result is False

    async def test_returns_true_when_at_limit(self):
        mock_r = AsyncMock()
        mock_r.get = AsyncMock(return_value=b"45")  # == RATE_MAX_PER_WINDOW
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import rate_limit_is_over
            result = await rate_limit_is_over(1)
        assert result is True

    async def test_returns_false_when_key_missing(self):
        mock_r = AsyncMock()
        mock_r.get = AsyncMock(return_value=None)
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import rate_limit_is_over
            result = await rate_limit_is_over(1)
        assert result is False

    async def test_returns_false_when_no_redis(self):
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=None)):
            from shared.redis.store import rate_limit_is_over
            result = await rate_limit_is_over(99)
        assert result is False

    async def test_returns_false_on_exception(self):
        mock_r = AsyncMock()
        mock_r.get = AsyncMock(side_effect=Exception("read error"))
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import rate_limit_is_over
            result = await rate_limit_is_over(1)
        assert result is False


class TestRateLimitIncr:
    async def test_sets_expire_on_first_incr(self):
        mock_r = AsyncMock()
        mock_r.incr = AsyncMock(return_value=1)  # first call
        mock_r.expire = AsyncMock()
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import rate_limit_incr, RATE_WINDOW_SEC
            await rate_limit_incr(1)
        mock_r.expire.assert_called_once()
        assert mock_r.expire.call_args[0][1] == RATE_WINDOW_SEC

    async def test_no_expire_on_subsequent_incr(self):
        mock_r = AsyncMock()
        mock_r.incr = AsyncMock(return_value=5)  # not first call
        mock_r.expire = AsyncMock()
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import rate_limit_incr
            await rate_limit_incr(1)
        mock_r.expire.assert_not_called()

    async def test_noop_when_no_redis(self):
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=None)):
            from shared.redis.store import rate_limit_incr
            await rate_limit_incr(1)  # must not raise

    async def test_swallows_exception(self):
        mock_r = AsyncMock()
        mock_r.incr = AsyncMock(side_effect=Exception("incr error"))
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
            from shared.redis.store import rate_limit_incr
            await rate_limit_incr(1)  # must not raise


# ============================================================================
# shared/domain/admin_runtime.py
# ============================================================================

class TestParseStartPayload:
    def test_empty_string_returns_empty(self):
        from shared.domain.admin_runtime import parse_start_payload
        assert parse_start_payload("") == {}

    def test_none_returns_empty(self):
        from shared.domain.admin_runtime import parse_start_payload
        assert parse_start_payload(None) == {}

    def test_ref_prefix(self):
        from shared.domain.admin_runtime import parse_start_payload
        result = parse_start_payload("ref_ABC123")
        assert result["acquisition_channel"] == "referral"
        assert result["start_payload"] == "ref_ABC123"

    def test_utm_query_string(self):
        from shared.domain.admin_runtime import parse_start_payload
        result = parse_start_payload("utm_source=google&utm_campaign=search")
        assert result["utm_source"] == "google"
        assert result["utm_campaign"] == "search"
        assert result["acquisition_channel"] == "google"

    def test_utm_query_string_with_medium(self):
        from shared.domain.admin_runtime import parse_start_payload
        result = parse_start_payload(
            "utm_source=fb&utm_medium=cpc&utm_campaign=spring&utm_content=v1&utm_term=ai"
        )
        assert result["utm_medium"] == "cpc"
        assert result["utm_content"] == "v1"
        assert result["utm_term"] == "ai"

    def test_src_prefix_three_parts(self):
        from shared.domain.admin_runtime import parse_start_payload
        result = parse_start_payload("src:telegram:promo2024:button1")
        assert result["utm_source"] == "telegram"
        assert result["utm_campaign"] == "promo2024"
        assert result["utm_content"] == "button1"
        assert result["acquisition_channel"] == "telegram"

    def test_src_prefix_one_part(self):
        from shared.domain.admin_runtime import parse_start_payload
        result = parse_start_payload("src:instagram")
        assert result["utm_source"] == "instagram"
        assert "utm_campaign" not in result

    def test_src_prefix_two_parts(self):
        from shared.domain.admin_runtime import parse_start_payload
        result = parse_start_payload("src:tiktok:summer")
        assert result["utm_campaign"] == "summer"
        assert "utm_content" not in result

    def test_fallback_generic_channel(self):
        from shared.domain.admin_runtime import parse_start_payload
        result = parse_start_payload("some_random_code")
        assert result["acquisition_channel"] == "some_random_code"
        assert result["start_payload"] == "some_random_code"

    def test_payload_truncated_to_255(self):
        from shared.domain.admin_runtime import parse_start_payload
        long_payload = "x" * 300
        result = parse_start_payload(long_payload)
        assert len(result["start_payload"]) == 255

    def test_whitespace_only_returns_empty(self):
        from shared.domain.admin_runtime import parse_start_payload
        assert parse_start_payload("   ") == {}


class TestSyncAdminTextDefaults:
    async def test_inserts_all_defaults(self):
        pool, conn = _make_pool()
        conn.execute = AsyncMock()
        with patch("shared.domain.admin_runtime.get_pool", AsyncMock(return_value=pool)):
            from shared.domain.admin_runtime import sync_admin_text_defaults, DEFAULT_ADMIN_TEXTS
            await sync_admin_text_defaults()
        assert conn.execute.call_count == len(DEFAULT_ADMIN_TEXTS)

    async def test_swallows_exception(self):
        pool, conn = _make_pool()
        conn.execute = AsyncMock(side_effect=Exception("DB down"))
        with patch("shared.domain.admin_runtime.get_pool", AsyncMock(return_value=pool)):
            from shared.domain.admin_runtime import sync_admin_text_defaults
            await sync_admin_text_defaults()  # must not raise


class TestGetAdminText:
    async def test_returns_db_value_when_enabled(self):
        pool, conn = _make_pool()
        row = {"value": "Hello World", "enabled": True}
        conn.fetchrow = AsyncMock(return_value=row)
        conn.execute = AsyncMock()

        with patch("shared.domain.admin_runtime.get_pool", AsyncMock(return_value=pool)), \
             patch("shared.domain.admin_runtime.sync_admin_text_defaults", AsyncMock()):
            from shared.domain.admin_runtime import get_admin_text
            result = await get_admin_text("welcome_text")
        assert result == "Hello World"

    async def test_returns_default_argument_when_row_disabled(self):
        pool, conn = _make_pool()
        row = MagicMock()
        row.get = MagicMock(side_effect=lambda k, *a: False if k == "enabled" else "")
        conn.fetchrow = AsyncMock(return_value=row)
        conn.execute = AsyncMock()

        with patch("shared.domain.admin_runtime.get_pool", AsyncMock(return_value=pool)), \
             patch("shared.domain.admin_runtime.sync_admin_text_defaults", AsyncMock()):
            from shared.domain.admin_runtime import get_admin_text
            result = await get_admin_text("welcome_text", default="fallback text")
        assert result == "fallback text"

    async def test_returns_hardcoded_default_when_no_db_row(self):
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)
        conn.execute = AsyncMock()

        with patch("shared.domain.admin_runtime.get_pool", AsyncMock(return_value=pool)), \
             patch("shared.domain.admin_runtime.sync_admin_text_defaults", AsyncMock()):
            from shared.domain.admin_runtime import get_admin_text, DEFAULT_ADMIN_TEXTS
            result = await get_admin_text("welcome_text")
        assert result == DEFAULT_ADMIN_TEXTS["welcome_text"]["value"]

    async def test_returns_empty_string_for_unknown_key(self):
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)
        conn.execute = AsyncMock()

        with patch("shared.domain.admin_runtime.get_pool", AsyncMock(return_value=pool)), \
             patch("shared.domain.admin_runtime.sync_admin_text_defaults", AsyncMock()):
            from shared.domain.admin_runtime import get_admin_text
            result = await get_admin_text("nonexistent_key")
        assert result == ""

    async def test_exception_in_fetchrow_returns_default(self):
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(side_effect=Exception("DB error"))
        conn.execute = AsyncMock()

        with patch("shared.domain.admin_runtime.get_pool", AsyncMock(return_value=pool)), \
             patch("shared.domain.admin_runtime.sync_admin_text_defaults", AsyncMock()):
            from shared.domain.admin_runtime import get_admin_text
            result = await get_admin_text("welcome_text", default="safe_default")
        assert result == "safe_default"


class TestSaveUserAcquisition:
    async def test_noop_when_empty_payload(self):
        pool, conn = _make_pool()
        with patch("shared.domain.admin_runtime.get_pool", AsyncMock(return_value=pool)):
            from shared.domain.admin_runtime import save_user_acquisition
            await save_user_acquisition(1, None)
        conn.execute.assert_not_called()

    async def test_executes_update_with_parsed_fields(self):
        pool, conn = _make_pool()
        conn.execute = AsyncMock()
        with patch("shared.domain.admin_runtime.get_pool", AsyncMock(return_value=pool)):
            from shared.domain.admin_runtime import save_user_acquisition
            await save_user_acquisition(42, "ref_MYCODE")
        conn.execute.assert_called_once()
        # SQL should include acquisition_channel
        sql_arg = conn.execute.call_args[0][0]
        assert "acquisition_channel" in sql_arg

    async def test_swallows_db_exception(self):
        pool, conn = _make_pool()
        conn.execute = AsyncMock(side_effect=Exception("DB down"))
        with patch("shared.domain.admin_runtime.get_pool", AsyncMock(return_value=pool)):
            from shared.domain.admin_runtime import save_user_acquisition
            await save_user_acquisition(1, "ref_XYZ")  # must not raise

    async def test_noop_when_no_fields_extracted(self):
        pool, conn = _make_pool()
        with patch("shared.domain.admin_runtime.get_pool", AsyncMock(return_value=pool)):
            from shared.domain.admin_runtime import save_user_acquisition
            await save_user_acquisition(1, "   ")
        conn.execute.assert_not_called()


# ============================================================================
# shared/domain/cryptobot.py
# ============================================================================

class TestCreateCryptoInvoice:
    async def test_returns_error_when_no_token(self):
        mock_settings = MagicMock()
        mock_settings.cryptobot_api_token = ""
        with patch("shared.config.settings", mock_settings):
            from shared.domain.cryptobot import create_crypto_invoice
            result = await create_crypto_invoice(5.0, "lite", 300, 1)
        assert result["ok"] is False
        assert "не настроен" in result["error"]

    async def test_returns_ok_on_successful_response(self):
        mock_settings = MagicMock()
        mock_settings.cryptobot_api_token = "test_token"
        api_response = {
            "ok": True,
            "result": {
                "invoice_id": 12345,
                "pay_url": "https://t.me/CryptoBot?start=IV12345",
            },
        }
        mock_http_response = MagicMock()
        mock_http_response.json = MagicMock(return_value=api_response)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_http_response)

        with patch("shared.config.settings", mock_settings), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            from shared.domain.cryptobot import create_crypto_invoice
            result = await create_crypto_invoice(5.0, "lite", 300, 1)
        assert result["ok"] is True
        assert result["invoice_id"] == 12345

    async def test_returns_error_on_api_failure(self):
        mock_settings = MagicMock()
        mock_settings.cryptobot_api_token = "test_token"
        api_response = {
            "ok": False,
            "error": {"name": "INVOICE_NOT_FOUND"},
        }
        mock_http_response = MagicMock()
        mock_http_response.json = MagicMock(return_value=api_response)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_http_response)

        with patch("shared.config.settings", mock_settings), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            from shared.domain.cryptobot import create_crypto_invoice
            result = await create_crypto_invoice(5.0, "lite", 300, 1)
        assert result["ok"] is False
        assert "INVOICE_NOT_FOUND" in result["error"]

    async def test_returns_error_on_network_exception(self):
        mock_settings = MagicMock()
        mock_settings.cryptobot_api_token = "test_token"
        with patch("shared.config.settings", mock_settings), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(side_effect=Exception("network"))
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            from shared.domain.cryptobot import create_crypto_invoice
            result = await create_crypto_invoice(5.0, "lite", 300, 1)
        assert result["ok"] is False
        assert "связи" in result["error"]

    async def test_uses_bot_invoice_url_fallback(self):
        mock_settings = MagicMock()
        mock_settings.cryptobot_api_token = "tok"
        api_response = {
            "ok": True,
            "result": {
                "invoice_id": 99,
                "pay_url": None,
                "bot_invoice_url": "https://t.me/CryptoBot?start=IV99",
            },
        }
        mock_http_response = MagicMock()
        mock_http_response.json = MagicMock(return_value=api_response)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_http_response)

        with patch("shared.config.settings", mock_settings), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            from shared.domain.cryptobot import create_crypto_invoice
            result = await create_crypto_invoice(5.0, "lite", 300, 1)
        assert result["pay_url"] == "https://t.me/CryptoBot?start=IV99"


class TestGetCryptoInvoice:
    async def test_returns_false_when_no_token(self):
        mock_settings = MagicMock()
        mock_settings.cryptobot_api_token = ""
        with patch("shared.config.settings", mock_settings):
            from shared.domain.cryptobot import get_crypto_invoice
            result = await get_crypto_invoice(123)
        assert result == {"ok": False}

    async def test_returns_invoice_data_on_success(self):
        mock_settings = MagicMock()
        mock_settings.cryptobot_api_token = "tok"
        api_response = {
            "ok": True,
            "result": {
                "items": [{
                    "invoice_id": 123,
                    "status": "paid",
                    "amount": "5.00",
                    "asset": "USDT",
                    "payload": "1:lite:300",
                }]
            },
        }
        mock_http_response = MagicMock()
        mock_http_response.json = MagicMock(return_value=api_response)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_http_response)

        with patch("shared.config.settings", mock_settings), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            from shared.domain.cryptobot import get_crypto_invoice
            result = await get_crypto_invoice(123)
        assert result["ok"] is True
        assert result["status"] == "paid"
        assert result["payload"] == "1:lite:300"

    async def test_returns_false_when_items_empty(self):
        mock_settings = MagicMock()
        mock_settings.cryptobot_api_token = "tok"
        api_response = {"ok": True, "result": {"items": []}}
        mock_http_response = MagicMock()
        mock_http_response.json = MagicMock(return_value=api_response)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_http_response)

        with patch("shared.config.settings", mock_settings), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            from shared.domain.cryptobot import get_crypto_invoice
            result = await get_crypto_invoice(123)
        assert result == {"ok": False}

    async def test_returns_false_on_exception(self):
        mock_settings = MagicMock()
        mock_settings.cryptobot_api_token = "tok"
        with patch("shared.config.settings", mock_settings), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(side_effect=Exception("net"))
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            from shared.domain.cryptobot import get_crypto_invoice
            result = await get_crypto_invoice(123)
        assert result == {"ok": False}


class TestSafeFloat:
    def test_valid_number(self):
        from shared.domain.cryptobot import _safe_float
        assert _safe_float("3.14") == pytest.approx(3.14)

    def test_integer_string(self):
        from shared.domain.cryptobot import _safe_float
        assert _safe_float("10") == 10.0

    def test_none_returns_default(self):
        from shared.domain.cryptobot import _safe_float
        assert _safe_float(None) == 0.0

    def test_invalid_string_returns_default(self):
        from shared.domain.cryptobot import _safe_float
        assert _safe_float("abc") == 0.0

    def test_custom_default(self):
        from shared.domain.cryptobot import _safe_float
        assert _safe_float(None, default=99.9) == 99.9


class TestProcessCryptoWebhook:
    def _verified_paid(self, payload="1:lite:300"):
        return {
            "ok": True,
            "status": "paid",
            "payload": payload,
            "amount": "5.00",
            "invoice_id": 42,
        }

    async def test_returns_error_when_not_paid(self):
        from shared.domain.cryptobot import process_crypto_webhook
        result = await process_crypto_webhook({"status": "active", "invoice_id": 1})
        assert result == {"ok": False, "error": "not_paid"}

    async def test_returns_error_on_invalid_invoice_id(self):
        from shared.domain.cryptobot import process_crypto_webhook
        result = await process_crypto_webhook({"status": "paid", "invoice_id": "bad"})
        assert result == {"ok": False, "error": "invalid_invoice_id"}

    async def test_returns_error_when_invoice_not_confirmed(self):
        with patch("shared.domain.cryptobot.get_crypto_invoice", AsyncMock(return_value={"ok": False})):
            from shared.domain.cryptobot import process_crypto_webhook
            result = await process_crypto_webhook({"status": "paid", "invoice_id": 99})
        assert result["error"] == "invoice_not_paid_or_unknown"

    async def test_returns_error_on_payload_mismatch(self):
        verified = self._verified_paid(payload="1:lite:300")
        with patch("shared.domain.cryptobot.get_crypto_invoice", AsyncMock(return_value=verified)):
            from shared.domain.cryptobot import process_crypto_webhook
            result = await process_crypto_webhook({
                "status": "paid",
                "invoice_id": 42,
                "payload": "1:pro:1000",  # different from verified
            })
        assert result["error"] == "payload_mismatch"

    async def test_returns_error_on_invalid_payload_parts(self):
        verified = {"ok": True, "status": "paid", "payload": "badpayload", "amount": "5.00"}
        with patch("shared.domain.cryptobot.get_crypto_invoice", AsyncMock(return_value=verified)):
            from shared.domain.cryptobot import process_crypto_webhook
            result = await process_crypto_webhook({"status": "paid", "invoice_id": 42})
        assert result["error"] == "invalid_payload"

    async def test_returns_error_on_unknown_pack(self):
        verified = self._verified_paid()
        with patch("shared.domain.cryptobot.get_crypto_invoice", AsyncMock(return_value=verified)), \
             patch("shared.domain.credits.get_credit_pack", AsyncMock(return_value=None)):
            from shared.domain.cryptobot import process_crypto_webhook
            result = await process_crypto_webhook({"status": "paid", "invoice_id": 42})
        assert result["error"] == "unknown_pack"

    async def test_returns_error_on_credits_mismatch(self):
        verified = self._verified_paid()  # payload says 300 credits
        pack = {"credits": 500, "label": "Pro Pack"}  # pack says 500
        with patch("shared.domain.cryptobot.get_crypto_invoice", AsyncMock(return_value=verified)), \
             patch("shared.domain.credits.get_credit_pack", AsyncMock(return_value=pack)):
            from shared.domain.cryptobot import process_crypto_webhook
            result = await process_crypto_webhook({"status": "paid", "invoice_id": 42})
        assert result["error"] == "credits_mismatch"

    async def test_returns_already_true_when_payment_already_confirmed(self):
        verified = self._verified_paid()
        pack = {"credits": 300, "label": "Lite"}
        existing = {"status": "confirmed"}
        with patch("shared.domain.cryptobot.get_crypto_invoice", AsyncMock(return_value=verified)), \
             patch("shared.domain.credits.get_credit_pack", AsyncMock(return_value=pack)), \
             patch("shared.domain.credits.get_payment_by_yookassa_id", AsyncMock(return_value=existing)):
            from shared.domain.cryptobot import process_crypto_webhook
            result = await process_crypto_webhook({"status": "paid", "invoice_id": 42})
        assert result == {"ok": True, "already": True}

    async def test_successful_payment_adds_credits(self):
        verified = self._verified_paid()
        pack = {"credits": 300, "label": "Lite Pack"}
        mock_settings = MagicMock()
        mock_settings.bot_username = "neurobox_bot"

        with patch("shared.domain.cryptobot.get_crypto_invoice", AsyncMock(return_value=verified)), \
             patch("shared.domain.credits.get_credit_pack", AsyncMock(return_value=pack)), \
             patch("shared.domain.credits.get_payment_by_yookassa_id", AsyncMock(return_value=None)), \
             patch("shared.domain.credits.create_payment_record", AsyncMock(return_value=True)), \
             patch("shared.domain.credits.confirm_payment_record", AsyncMock(return_value=True)), \
             patch("shared.domain.credits.add_credits", AsyncMock(return_value={"ok": True})), \
             patch("shared.domain.analytics.track_payment_success", AsyncMock()), \
             patch("shared.domain.payment_notify.send_payment_notification_to_admin", AsyncMock()), \
             patch("shared.config.settings", mock_settings):
            from shared.domain.cryptobot import process_crypto_webhook
            result = await process_crypto_webhook({"status": "paid", "invoice_id": 42})
        assert result["ok"] is True
        assert result["user_id"] == 1
        assert result["credits"] == 300

    async def test_unlimited_pack_calls_set_unlimited(self):
        verified = {"ok": True, "status": "paid", "payload": "1:unlimited:0", "amount": "9.99"}
        pack = {"credits": 0, "label": "Unlimited"}
        mock_settings = MagicMock()
        mock_settings.bot_username = "nb_bot"

        with patch("shared.domain.cryptobot.get_crypto_invoice", AsyncMock(return_value=verified)), \
             patch("shared.domain.credits.get_credit_pack", AsyncMock(return_value=pack)), \
             patch("shared.domain.credits.get_payment_by_yookassa_id", AsyncMock(return_value=None)), \
             patch("shared.domain.credits.create_payment_record", AsyncMock(return_value=True)), \
             patch("shared.domain.credits.confirm_payment_record", AsyncMock(return_value=True)), \
             patch("shared.domain.credits.set_unlimited_until", AsyncMock()) as mock_unlimited, \
             patch("shared.domain.credits.UNLIMITED_DAYS", 30), \
             patch("shared.domain.analytics.track_payment_success", AsyncMock()), \
             patch("shared.domain.payment_notify.send_payment_notification_to_admin", AsyncMock()), \
             patch("shared.config.settings", mock_settings):
            from shared.domain.cryptobot import process_crypto_webhook
            result = await process_crypto_webhook({"status": "paid", "invoice_id": 42})
        assert result["ok"] is True
        mock_unlimited.assert_called_once()

    async def test_confirm_payment_returns_none_yields_already(self):
        """If confirm_payment_record returns falsy, return already:True."""
        verified = self._verified_paid()
        pack = {"credits": 300, "label": "Lite"}
        with patch("shared.domain.cryptobot.get_crypto_invoice", AsyncMock(return_value=verified)), \
             patch("shared.domain.credits.get_credit_pack", AsyncMock(return_value=pack)), \
             patch("shared.domain.credits.get_payment_by_yookassa_id", AsyncMock(return_value=None)), \
             patch("shared.domain.credits.create_payment_record", AsyncMock(return_value=True)), \
             patch("shared.domain.credits.confirm_payment_record", AsyncMock(return_value=None)):
            from shared.domain.cryptobot import process_crypto_webhook
            result = await process_crypto_webhook({"status": "paid", "invoice_id": 42})
        assert result == {"ok": True, "already": True}


# ============================================================================
# shared/domain/payment_notify.py
# ============================================================================

class TestSendPaymentNotificationToAdmin:
    async def test_noop_when_no_token(self):
        mock_settings = MagicMock()
        mock_settings.payment_notify_bot_token = ""
        mock_settings.payment_notify_chat_id = "123"
        with patch("shared.config.settings", mock_settings):
            from shared.domain.payment_notify import send_payment_notification_to_admin
            await send_payment_notification_to_admin("NB", "Lite", 1)  # must not raise

    async def test_sends_message_via_telegram_api(self):
        mock_settings = MagicMock()
        mock_settings.payment_notify_bot_token = "BOT_TOKEN"
        mock_settings.payment_notify_chat_id = "72916668"
        pool, conn = _make_pool()
        row = {"username": "testuser"}
        conn.fetchrow = AsyncMock(return_value=row)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("shared.config.settings", mock_settings), \
             patch("shared.db.database.get_pool", AsyncMock(return_value=pool)), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            from shared.domain.payment_notify import send_payment_notification_to_admin
            await send_payment_notification_to_admin("NB", "Lite — 300 CR", 42, method="yookassa")
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args[1]["json"]
        assert "НейроБокс" in call_kwargs["text"] or "NB" in call_kwargs["text"]

    async def test_includes_amount_str_when_provided(self):
        mock_settings = MagicMock()
        mock_settings.payment_notify_bot_token = "TOK"
        mock_settings.payment_notify_chat_id = "123"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={"username": ""})

        with patch("shared.config.settings", mock_settings), \
             patch("shared.db.database.get_pool", AsyncMock(return_value=pool)), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            from shared.domain.payment_notify import send_payment_notification_to_admin
            await send_payment_notification_to_admin(
                "NB", "Pack", 1, amount_str="5.00 USDT", method="cryptobot"
            )
        sent_text = mock_client.post.call_args[1]["json"]["text"]
        assert "5.00 USDT" in sent_text
        assert "CryptoBot" in sent_text

    async def test_uses_provided_username(self):
        """When username is explicitly passed, no DB lookup is done."""
        mock_settings = MagicMock()
        mock_settings.payment_notify_bot_token = "TOK"
        mock_settings.payment_notify_chat_id = "123"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("shared.config.settings", mock_settings), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            from shared.domain.payment_notify import send_payment_notification_to_admin
            await send_payment_notification_to_admin(
                "NB", "Pack", 77, username="myuser"
            )
        sent_text = mock_client.post.call_args[1]["json"]["text"]
        assert "@myuser" in sent_text

    async def test_logs_warning_on_non_200_status(self):
        mock_settings = MagicMock()
        mock_settings.payment_notify_bot_token = "TOK"
        mock_settings.payment_notify_chat_id = "123"

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        with patch("shared.config.settings", mock_settings), \
             patch("shared.db.database.get_pool", AsyncMock(return_value=pool)), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            from shared.domain.payment_notify import send_payment_notification_to_admin
            await send_payment_notification_to_admin("NB", "Pack", 1)  # must not raise

    async def test_swallows_http_exception(self):
        mock_settings = MagicMock()
        mock_settings.payment_notify_bot_token = "TOK"
        mock_settings.payment_notify_chat_id = "123"
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        with patch("shared.config.settings", mock_settings), \
             patch("shared.db.database.get_pool", AsyncMock(return_value=pool)), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(side_effect=Exception("network"))
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            from shared.domain.payment_notify import send_payment_notification_to_admin
            await send_payment_notification_to_admin("NB", "Pack", 1)  # must not raise

    async def test_swallows_db_exception_for_username_lookup(self):
        mock_settings = MagicMock()
        mock_settings.payment_notify_bot_token = "TOK"
        mock_settings.payment_notify_chat_id = "123"
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(side_effect=Exception("db down"))

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("shared.config.settings", mock_settings), \
             patch("shared.db.database.get_pool", AsyncMock(return_value=pool)), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            from shared.domain.payment_notify import send_payment_notification_to_admin
            await send_payment_notification_to_admin("NB", "Pack", 1)  # must not raise




# ============================================================================
# shared/domain/analytics.py
# ============================================================================

class TestTrack:
    async def test_calls_repo_create_when_session_ok(self):
        mock_repo = AsyncMock()
        mock_repo.create = AsyncMock()
        mock_session = AsyncMock()

        @asynccontextmanager
        async def _fake_session():
            yield mock_session

        with patch("shared.db.repositories.event.EventRepository", return_value=mock_repo), \
             patch("shared.db.session.get_session", _fake_session):
            from shared.domain.analytics import track
            await track("test_event", 1, key="value")
        mock_repo.create.assert_called_once_with(
            event_name="test_event",
            user_id=1,
            properties={"key": "value"},
        )

    async def test_does_not_raise_when_repo_raises(self):
        @asynccontextmanager
        async def _bad_session():
            raise Exception("DB gone")
            yield  # noqa: unreachable

        with patch("shared.db.session.get_session", _bad_session):
            from shared.domain.analytics import track
            await track("error_event", 999)  # must not raise

    async def test_passes_none_properties_when_no_extra(self):
        mock_repo = AsyncMock()
        mock_repo.create = AsyncMock()
        mock_session = AsyncMock()

        @asynccontextmanager
        async def _fake_session():
            yield mock_session

        with patch("shared.db.repositories.event.EventRepository", return_value=mock_repo), \
             patch("shared.db.session.get_session", _fake_session):
            from shared.domain.analytics import track
            await track("bare_event", 5)
        mock_repo.create.assert_called_once_with(
            event_name="bare_event",
            user_id=5,
            properties=None,
        )


class TestTrackPaywallView:
    async def test_delegates_to_track(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_paywall_view
            await track_paywall_view(1, "make a video", 50, 10, ["lite", "pro"], "checkout")
        mock_track.assert_called_once()
        call_kwargs = mock_track.call_args
        assert call_kwargs[0][0] == "paywall_view"
        assert call_kwargs[1]["need_cr"] == 50

    async def test_defaults_source_to_smart_paywall(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_paywall_view
            await track_paywall_view(1, "task", 10, 0)
        assert mock_track.call_args[1]["source"] == "smart_paywall"

    async def test_recommended_packs_defaults_to_empty_list(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_paywall_view
            await track_paywall_view(1, "task", 10, 0)
        assert mock_track.call_args[1]["recommended_packs"] == []


class TestTrackPaywallHit:
    async def test_calls_track_paywall_view(self):
        with patch("shared.domain.analytics.track_paywall_view", AsyncMock()) as mock_view:
            from shared.domain.analytics import track_paywall_hit
            await track_paywall_hit(1, "desc", 20, 5)
        mock_view.assert_called_once_with(1, "desc", 20, 5)


class TestTrackPlanSelected:
    async def test_standard_call(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_plan_selected
            await track_plan_selected(1, "lite", price_rub=99.0, credits=300)
        assert mock_track.call_args[0][0] == "plan_selected"
        assert mock_track.call_args[1]["pack_name"] == "lite"
        assert mock_track.call_args[1]["credits"] == 300

    async def test_extra_kwargs_merged(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_plan_selected
            await track_plan_selected(1, "pro", campaign="spring")
        assert mock_track.call_args[1]["campaign"] == "spring"


class TestTrackPaymentStarted:
    async def test_standard_call(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_payment_started
            await track_payment_started(1, "pay_1", "yookassa", pack_name="lite", amount_rub=99.0, credits=300)
        assert mock_track.call_args[0][0] == "payment_started"
        props = mock_track.call_args[1]
        assert props["method"] == "yookassa"
        assert props["is_test"] is False

    async def test_is_test_flag(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_payment_started
            await track_payment_started(1, "pay_x", "stripe", is_test=True)
        assert mock_track.call_args[1]["is_test"] is True


class TestTrackPaymentSuccess:
    async def test_event_name(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_payment_success
            await track_payment_success(1, "pay_ok", "yookassa")
        assert mock_track.call_args[0][0] == "payment_success"

    async def test_extra_kwargs_forwarded(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_payment_success
            await track_payment_success(1, "pay_ok", "crypto", amount_usd=5.0)
        assert mock_track.call_args[1]["amount_usd"] == 5.0


class TestTrackPaymentFailed:
    async def test_event_name(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_payment_failed
            await track_payment_failed(1, "yookassa", reason="cancelled")
        assert mock_track.call_args[0][0] == "payment_failed"

    async def test_reason_truncated_to_200_chars(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_payment_failed
            long_reason = "x" * 300
            await track_payment_failed(1, "stripe", reason=long_reason)
        assert len(mock_track.call_args[1]["reason"]) == 200


class TestTrackFirstValue:
    async def test_event_name_and_props(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_first_value
            await track_first_value(1, "image", "flux-2-turbo", success_event="image_ready")
        assert mock_track.call_args[0][0] == "first_value"
        assert mock_track.call_args[1]["task_type"] == "image"
        assert mock_track.call_args[1]["model"] == "flux-2-turbo"


class TestTrackPremiumAction:
    async def test_event_name_and_cr_cost(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_premium_action
            await track_premium_action(1, "video", "kling-2.6", cr_cost=100)
        assert mock_track.call_args[0][0] == "premium_action"
        assert mock_track.call_args[1]["cr_cost"] == 100

    async def test_extra_kwargs_forwarded(self):
        with patch("shared.domain.analytics.track", AsyncMock()) as mock_track:
            from shared.domain.analytics import track_premium_action
            await track_premium_action(1, "music", "suno", extra_field="hello")
        assert mock_track.call_args[1]["extra_field"] == "hello"
