"""Tests for small files to push coverage over 75%:
  services/admin/backend_client.py
  services/bot/i18n.py
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_message(user_id: int = 111):
    from aiogram import types
    msg = AsyncMock(spec=types.Message)
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.from_user.username = "admin_user"
    msg.answer = AsyncMock()
    return msg


def _make_pool(fetchval_values=None):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock()
    conn.execute = AsyncMock()
    if fetchval_values:
        conn.fetchval = AsyncMock(side_effect=list(fetchval_values))
    else:
        conn.fetchval = AsyncMock(return_value=0)

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool = MagicMock()
    pool.acquire = _acquire
    return pool, conn


# ===========================================================================
# services/admin/backend_client.py
# ===========================================================================

class TestAdminBackendClient:
    def setup_method(self):
        import services.admin.backend_client as m
        m._client = None

    def test_get_client_creates_instance(self):
        import services.admin.backend_client as m
        with patch.dict("os.environ", {"BACKEND_URL": "http://test-backend:9999"}):
            client = m._get_client()
        assert client is not None
        assert str(client.base_url).rstrip("/") == "http://test-backend:9999"

    def test_get_client_returns_same_instance(self):
        import services.admin.backend_client as m
        with patch.dict("os.environ", {"BACKEND_URL": "http://test-backend:9999"}):
            c1 = m._get_client()
            c2 = m._get_client()
        assert c1 is c2

    async def test_close_client_clears_instance(self):
        import services.admin.backend_client as m
        with patch.dict("os.environ", {"BACKEND_URL": "http://test:9999"}):
            m._get_client()
        await m.close_client()
        assert m._client is None

    async def test_close_client_noop_when_none(self):
        import services.admin.backend_client as m
        m._client = None
        await m.close_client()
        assert m._client is None


# ===========================================================================
# services/bot/i18n.py — t(), get_user_lang, set_user_lang
# ===========================================================================

class TestI18n:
    def test_t_ru_key(self):
        from services.bot.i18n import t
        result = t("btn_text", "ru")
        assert result == "💬 Текст"

    def test_t_en_key(self):
        from services.bot.i18n import t
        result = t("btn_text", "en")
        assert result == "💬 Text"

    def test_t_fallback_to_ru_for_unknown_lang(self):
        from services.bot.i18n import t
        result = t("btn_text", "de")
        assert result == "💬 Текст"

    def test_t_missing_key_returns_key(self):
        from services.bot.i18n import t
        result = t("nonexistent_key_xyz")
        assert result == "nonexistent_key_xyz"

    def test_t_with_kwargs(self):
        from services.bot.i18n import t
        result = t("daily_bonus", "ru", amount=5)
        assert "5" in result

    def test_t_with_bad_kwargs_returns_text(self):
        from services.bot.i18n import t
        result = t("btn_text", "ru", nonexistent=123)
        assert result == "💬 Текст"

    def test_t_en_welcome(self):
        from services.bot.i18n import t
        result = t("welcome", "en", credits=100)
        assert "100" in result

    async def test_get_user_lang_redis_hit(self):
        from services.bot.i18n import get_user_lang
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"en")
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_redis)):
            result = await get_user_lang(42)
        assert result == "en"

    async def test_get_user_lang_redis_miss_db_hit(self):
        from services.bot.i18n import get_user_lang
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value="en")

        @asynccontextmanager
        async def _acquire():
            yield conn

        pool = MagicMock()
        pool.acquire = _acquire

        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_redis)), \
             patch("shared.db.database.get_pool", AsyncMock(return_value=pool)):
            result = await get_user_lang(42)
        assert result == "en"

    async def test_get_user_lang_all_fail_returns_ru(self):
        from services.bot.i18n import get_user_lang
        with patch("shared.redis.store._get_redis", AsyncMock(side_effect=Exception("redis down"))), \
             patch("shared.db.database.get_pool", AsyncMock(side_effect=Exception("db down"))):
            result = await get_user_lang(42)
        assert result == "ru"

    async def test_set_user_lang(self):
        from services.bot.i18n import set_user_lang
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        conn = AsyncMock()
        conn.execute = AsyncMock()

        @asynccontextmanager
        async def _acquire():
            yield conn

        pool = MagicMock()
        pool.acquire = _acquire

        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_redis)), \
             patch("shared.db.database.get_pool", AsyncMock(return_value=pool)):
            await set_user_lang(42, "en")

        conn.execute.assert_awaited_once()

    async def test_set_user_lang_exception_swallowed(self):
        from services.bot.i18n import set_user_lang
        with patch("shared.db.database.get_pool", AsyncMock(side_effect=Exception("db down"))):
            await set_user_lang(42, "en")  # must not raise
