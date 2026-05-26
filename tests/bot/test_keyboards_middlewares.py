"""Tests for keyboards (main, admin, modes) and middlewares (ban_check, rate_limit, log_context)."""
import time
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(user_id: int = 111):
    u = MagicMock()
    u.id = user_id
    u.username = "testuser"
    u.first_name = "Test"
    return u


def _make_message(user_id: int = 111):
    msg = AsyncMock(spec=types.Message)
    msg.from_user = _make_user(user_id)
    msg.answer = AsyncMock()
    msg.chat = MagicMock()
    msg.chat.id = user_id
    return msg


def _make_callback(user_id: int = 111):
    cb = AsyncMock(spec=types.CallbackQuery)
    cb.from_user = _make_user(user_id)
    cb.answer = AsyncMock()
    return cb


async def _noop_handler(event, data):
    return "ok"


# ---------------------------------------------------------------------------
# keyboards/main.py
# ---------------------------------------------------------------------------

class TestPersistentMenuKb:
    def test_default(self):
        from services.bot.keyboards.main import persistent_menu_kb
        kb = persistent_menu_kb()
        assert isinstance(kb, ReplyKeyboardMarkup)

    def test_with_trial(self):
        from services.bot.keyboards.main import persistent_menu_kb
        kb = persistent_menu_kb(credits=100, add_trial=True)
        assert isinstance(kb, ReplyKeyboardMarkup)
        # Verify the trial button text appears
        all_texts = [btn.text for row in kb.keyboard for btn in row]
        assert any("безлимита" in t for t in all_texts)

    def test_without_trial(self):
        from services.bot.keyboards.main import persistent_menu_kb
        kb = persistent_menu_kb(credits=0, add_trial=False)
        assert isinstance(kb, ReplyKeyboardMarkup)
        all_texts = [btn.text for row in kb.keyboard for btn in row]
        assert not any("безлимита" in t for t in all_texts)

    def test_zero_credits(self):
        from services.bot.keyboards.main import persistent_menu_kb
        kb = persistent_menu_kb(credits=0)
        assert kb is not None

    def test_negative_credits(self):
        from services.bot.keyboards.main import persistent_menu_kb
        kb = persistent_menu_kb(credits=-5)
        assert kb is not None

    def test_enable_video_flag(self):
        from services.bot.keyboards.main import persistent_menu_kb
        from shared.config import settings
        with patch.object(settings, "enable_video", True):
            kb = persistent_menu_kb()
            all_texts = [btn.text for row in kb.keyboard for btn in row]
            assert any("Видео" in t for t in all_texts)

    def test_enable_tts_flag(self):
        from services.bot.keyboards.main import persistent_menu_kb
        from shared.config import settings
        with patch.object(settings, "enable_tts", True):
            kb = persistent_menu_kb()
            assert kb is not None

    def test_enable_music_flag(self):
        from services.bot.keyboards.main import persistent_menu_kb
        from shared.config import settings
        with patch.object(settings, "enable_music", True):
            kb = persistent_menu_kb()
            all_texts = [btn.text for row in kb.keyboard for btn in row]
            assert any("Аудио" in t for t in all_texts)


class TestGetMainMenuKb:
    def test_basic(self):
        from services.bot.keyboards.main import get_main_menu_kb
        kb = get_main_menu_kb(credits=100)
        assert isinstance(kb, InlineKeyboardMarkup)

    def test_with_trial_button(self):
        from services.bot.keyboards.main import get_main_menu_kb
        kb = get_main_menu_kb(credits=50, add_trial_button=True)
        assert isinstance(kb, InlineKeyboardMarkup)
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("безлимита" in t for t in all_texts)

    def test_with_48h_button(self):
        from services.bot.keyboards.main import get_main_menu_kb
        kb = get_main_menu_kb(credits=50, add_48h_button=True)
        assert isinstance(kb, InlineKeyboardMarkup)
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("48" in t for t in all_texts)

    def test_both_bonus_buttons(self):
        from services.bot.keyboards.main import get_main_menu_kb
        kb = get_main_menu_kb(credits=0, add_trial_button=True, add_48h_button=True)
        assert isinstance(kb, InlineKeyboardMarkup)

    def test_admin_button_shown(self):
        from services.bot.keyboards.main import get_main_menu_kb
        from shared.config import settings
        admin_uid = 999999
        with patch.object(settings, "admin_ids", str(admin_uid)):
            kb = get_main_menu_kb(credits=0, user_id=admin_uid)
            all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
            assert any("Админ" in t for t in all_texts)

    def test_admin_button_not_shown_for_regular(self):
        from services.bot.keyboards.main import get_main_menu_kb
        kb = get_main_menu_kb(credits=0, user_id=12345)
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert not any("Админ" in t for t in all_texts)

    def test_user_id_zero(self):
        from services.bot.keyboards.main import get_main_menu_kb
        kb = get_main_menu_kb(credits=0, user_id=0)
        assert isinstance(kb, InlineKeyboardMarkup)

    def test_enable_video(self):
        from services.bot.keyboards.main import get_main_menu_kb
        from shared.config import settings
        with patch.object(settings, "enable_video", True):
            kb = get_main_menu_kb(credits=0)
            all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
            assert any("Видео" in t for t in all_texts)

    def test_kwargs_ignored(self):
        from services.bot.keyboards.main import get_main_menu_kb
        kb = get_main_menu_kb(credits=100, some_extra_kwarg="ignored")
        assert isinstance(kb, InlineKeyboardMarkup)


class TestGetMoreMenuKb:
    def test_returns_markup(self):
        from services.bot.keyboards.main import get_more_menu_kb
        kb = get_more_menu_kb()
        assert isinstance(kb, InlineKeyboardMarkup)

    def test_enable_music_adds_button(self):
        from services.bot.keyboards.main import get_more_menu_kb
        from shared.config import settings
        with patch.object(settings, "enable_music", True):
            kb = get_more_menu_kb()
            all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
            assert any("Музыка" in t for t in all_texts)

    def test_enable_tts_shows_audio(self):
        from services.bot.keyboards.main import get_more_menu_kb
        from shared.config import settings
        with patch.object(settings, "enable_tts", True):
            kb = get_more_menu_kb()
            all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
            assert any("Аудио" in t for t in all_texts)

    def test_tts_false_music_false_no_audio(self):
        from services.bot.keyboards.main import get_more_menu_kb
        from shared.config import settings
        with patch.object(settings, "enable_tts", False), patch.object(settings, "enable_music", False):
            kb = get_more_menu_kb()
            all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
            # The Аудио button should not appear when both disabled
            assert not any(t == "🎵 Аудио" for t in all_texts)


class TestSimpleKeyboards:
    def test_back_to_main_kb(self):
        from services.bot.keyboards.main import back_to_main_kb
        kb = back_to_main_kb()
        assert isinstance(kb, InlineKeyboardMarkup)

    def test_buy_credits_kb(self):
        from services.bot.keyboards.main import buy_credits_kb
        kb = buy_credits_kb()
        assert isinstance(kb, InlineKeyboardMarkup)
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("купить" in t.lower() or "кредит" in t.lower() for t in all_texts)

    def test_promo_credits_kb(self):
        from services.bot.keyboards.main import promo_credits_kb
        kb = promo_credits_kb()
        assert isinstance(kb, InlineKeyboardMarkup)

    def test_change_model_kb(self):
        from services.bot.keyboards.main import change_model_kb
        kb = change_model_kb("select_text_model")
        assert isinstance(kb, InlineKeyboardMarkup)

    def test_change_model_kb_different_callback(self):
        from services.bot.keyboards.main import change_model_kb
        kb = change_model_kb("select_image_model")
        all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "select_image_model" in all_cbs


class TestShortName:
    def test_known_model(self):
        from services.bot.keyboards.main import _short
        assert _short("gpt-4.1-nano") == "GPT-4.1 nano"

    def test_unknown_model_returns_id(self):
        from services.bot.keyboards.main import _short
        assert _short("some-unknown-model") == "some-unknown-model"

    def test_various_known_models(self):
        from services.bot.keyboards.main import _short, _SHORT_NAMES
        for model_id, expected in _SHORT_NAMES.items():
            assert _short(model_id) == expected


# ---------------------------------------------------------------------------
# keyboards/admin.py
# ---------------------------------------------------------------------------

class TestAdminDashboardKb:
    def test_returns_markup(self):
        from services.bot.keyboards.admin import admin_dashboard_kb
        kb = admin_dashboard_kb()
        assert isinstance(kb, InlineKeyboardMarkup)

    def test_contains_stats_button(self):
        from services.bot.keyboards.admin import admin_dashboard_kb
        kb = admin_dashboard_kb()
        all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
        assert "admin:stats" in all_cbs

    def test_no_web_button_without_url(self):
        from services.bot.keyboards.admin import admin_dashboard_kb
        from shared.config import settings
        with patch.object(settings, "admin_panel_url", ""):
            kb = admin_dashboard_kb()
            all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
            assert not any("Веб" in t for t in all_texts)

    def test_web_button_with_https_url(self):
        from services.bot.keyboards.admin import admin_dashboard_kb
        from shared.config import settings
        with patch.object(settings, "admin_panel_url", "https://admin.example.com"):
            kb = admin_dashboard_kb()
            all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
            assert any("Веб" in t for t in all_texts)

    def test_web_button_with_http_url(self):
        from services.bot.keyboards.admin import admin_dashboard_kb
        from shared.config import settings
        with patch.object(settings, "admin_panel_url", "http://localhost:8080"):
            kb = admin_dashboard_kb()
            all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
            assert any("Веб" in t for t in all_texts)

    def test_no_web_button_with_invalid_url(self):
        from services.bot.keyboards.admin import admin_dashboard_kb
        from shared.config import settings
        with patch.object(settings, "admin_panel_url", "not-a-url"):
            kb = admin_dashboard_kb()
            all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
            assert not any("Веб" in t for t in all_texts)

    def test_no_web_button_with_whitespace_url(self):
        from services.bot.keyboards.admin import admin_dashboard_kb
        from shared.config import settings
        with patch.object(settings, "admin_panel_url", "   "):
            kb = admin_dashboard_kb()
            all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
            assert not any("Веб" in t for t in all_texts)


class TestAdminBackKb:
    def test_returns_markup(self):
        from services.bot.keyboards.admin import admin_back_kb
        kb = admin_back_kb()
        assert isinstance(kb, InlineKeyboardMarkup)
        all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "admin:back" in all_cbs


class TestUserCardKb:
    def test_returns_markup(self):
        from services.bot.keyboards.admin import user_card_kb
        kb = user_card_kb(12345)
        assert isinstance(kb, InlineKeyboardMarkup)

    def test_contains_user_specific_callbacks(self):
        from services.bot.keyboards.admin import user_card_kb
        uid = 42
        kb = user_card_kb(uid)
        all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
        assert f"admin:user:ban:{uid}" in all_cbs
        assert f"admin:user:unban:{uid}" in all_cbs
        assert f"admin:user:add:{uid}" in all_cbs
        assert f"admin:user:sub:{uid}" in all_cbs

    def test_different_user_ids(self):
        from services.bot.keyboards.admin import user_card_kb
        for uid in [1, 100, 999999]:
            kb = user_card_kb(uid)
            assert isinstance(kb, InlineKeyboardMarkup)


class TestUsersPaginationKb:
    def test_first_page_no_prev(self):
        from services.bot.keyboards.admin import users_list_pagination_kb
        kb = users_list_pagination_kb(offset=0, page_size=10, total=50)
        all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
        assert not any("page:0" in cb and "◀️" in cb for cb in all_cbs)
        # Has next page
        assert any("page:10" in cb for cb in all_cbs)

    def test_middle_page_has_both(self):
        from services.bot.keyboards.admin import users_list_pagination_kb
        kb = users_list_pagination_kb(offset=10, page_size=10, total=50)
        all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
        assert any("page:0" in cb for cb in all_cbs)  # prev
        assert any("page:20" in cb for cb in all_cbs)  # next

    def test_last_page_no_next(self):
        from services.bot.keyboards.admin import users_list_pagination_kb
        kb = users_list_pagination_kb(offset=40, page_size=10, total=50)
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        # Should not have a forward arrow
        assert not any("▶️" == t for t in all_texts)

    def test_single_page(self):
        from services.bot.keyboards.admin import users_list_pagination_kb
        kb = users_list_pagination_kb(offset=0, page_size=10, total=5)
        assert isinstance(kb, InlineKeyboardMarkup)


class TestFinancePaginationKb:
    def test_first_page(self):
        from services.bot.keyboards.admin import finance_pagination_kb
        kb = finance_pagination_kb(offset=0, page_size=20, total=100)
        all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
        assert any("finance:page:20" in cb for cb in all_cbs)

    def test_middle_page(self):
        from services.bot.keyboards.admin import finance_pagination_kb
        kb = finance_pagination_kb(offset=20, page_size=20, total=100)
        all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
        assert any("finance:page:0" in cb for cb in all_cbs)
        assert any("finance:page:40" in cb for cb in all_cbs)

    def test_always_has_revenue_and_csv(self):
        from services.bot.keyboards.admin import finance_pagination_kb
        kb = finance_pagination_kb(offset=0, page_size=20, total=10)
        all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
        assert "admin:finance:revenue" in all_cbs
        assert "admin:finance:csv" in all_cbs


class TestPromoListKb:
    def test_returns_markup(self):
        from services.bot.keyboards.admin import promo_list_kb
        kb = promo_list_kb()
        assert isinstance(kb, InlineKeyboardMarkup)
        all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
        assert "admin:promo:create" in all_cbs


class TestModerationBoardKb:
    def test_returns_markup(self):
        from services.bot.keyboards.admin import moderation_board_kb
        kb = moderation_board_kb()
        assert isinstance(kb, InlineKeyboardMarkup)
        all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
        assert "admin:mod:complaints" in all_cbs
        assert "admin:mod:banned" in all_cbs
        assert "admin:mod:stopwords" in all_cbs


class TestSystemKb:
    def test_returns_markup(self):
        from services.bot.keyboards.admin import system_kb
        kb = system_kb()
        assert isinstance(kb, InlineKeyboardMarkup)
        all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
        assert "admin:sys:clear_cache" in all_cbs
        assert "admin:sys:download_log" in all_cbs


# ---------------------------------------------------------------------------
# keyboards/modes.py
# ---------------------------------------------------------------------------

class TestCategoriesKb:
    def test_returns_markup(self):
        from services.bot.keyboards.modes import categories_kb
        kb = categories_kb()
        assert isinstance(kb, InlineKeyboardMarkup)

    def test_all_categories_present(self):
        from services.bot.keyboards.modes import categories_kb, CATEGORIES
        kb = categories_kb()
        all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
        for _, cat_id in CATEGORIES:
            assert f"mode_cat:{cat_id}" in all_cbs

    def test_correct_number_of_buttons(self):
        from services.bot.keyboards.modes import categories_kb, CATEGORIES
        kb = categories_kb()
        total_buttons = sum(len(row) for row in kb.inline_keyboard)
        assert total_buttons == len(CATEGORIES)


class TestModesInCategoryKb:
    def test_with_back(self):
        from services.bot.keyboards.modes import modes_in_category_kb
        modes = [(1, "Mode One", "🔥"), (2, "Mode Two", "💡")]
        kb = modes_in_category_kb(modes, back_to_categories=True)
        assert isinstance(kb, InlineKeyboardMarkup)
        all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
        assert "mode_select:1" in all_cbs
        assert "mode_select:2" in all_cbs
        assert "mode_open" in all_cbs

    def test_without_back(self):
        from services.bot.keyboards.modes import modes_in_category_kb
        modes = [(3, "Mode Three", "⚡")]
        kb = modes_in_category_kb(modes, back_to_categories=False)
        all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
        assert "mode_open" not in all_cbs
        assert "main_menu" in all_cbs

    def test_empty_modes(self):
        from services.bot.keyboards.modes import modes_in_category_kb
        kb = modes_in_category_kb([], back_to_categories=True)
        assert isinstance(kb, InlineKeyboardMarkup)

    def test_button_text_includes_emoji_and_name(self):
        from services.bot.keyboards.modes import modes_in_category_kb
        modes = [(10, "TestMode", "🎯")]
        kb = modes_in_category_kb(modes)
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("TestMode" in t for t in all_texts)
        assert any("🎯" in t for t in all_texts)


class TestCustomModeKb:
    def test_has_custom_true(self):
        from services.bot.keyboards.modes import custom_mode_kb
        kb = custom_mode_kb(has_custom=True)
        assert isinstance(kb, InlineKeyboardMarkup)
        all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
        assert "mode_custom_edit" in all_cbs
        assert "mode_custom_delete" in all_cbs

    def test_has_custom_false(self):
        from services.bot.keyboards.modes import custom_mode_kb
        kb = custom_mode_kb(has_custom=False)
        assert isinstance(kb, InlineKeyboardMarkup)
        all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
        assert "mode_custom_edit" in all_cbs
        assert "mode_custom_delete" not in all_cbs

    def test_both_have_main_menu_back(self):
        from services.bot.keyboards.modes import custom_mode_kb
        for has_custom in [True, False]:
            kb = custom_mode_kb(has_custom=has_custom)
            all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
            assert "main_menu" in all_cbs


# ---------------------------------------------------------------------------
# middlewares/log_context.py
# ---------------------------------------------------------------------------

class TestLogContextMiddleware:
    async def test_passes_through_message(self):
        from services.bot.middlewares.log_context import LogContextMiddleware
        mw = LogContextMiddleware()
        msg = _make_message(user_id=123)
        data = {"event_from_user": msg.from_user}
        result = await mw(handler=_noop_handler, event=msg, data=data)
        assert result == "ok"

    async def test_passes_through_callback(self):
        from services.bot.middlewares.log_context import LogContextMiddleware
        mw = LogContextMiddleware()
        cb = _make_callback(user_id=456)
        data = {"event_from_user": cb.from_user}
        result = await mw(handler=_noop_handler, event=cb, data=data)
        assert result == "ok"

    async def test_unknown_event_type(self):
        from services.bot.middlewares.log_context import LogContextMiddleware
        mw = LogContextMiddleware()
        event = MagicMock()
        event.from_user = None
        # Not a Message or CallbackQuery
        data = {}
        result = await mw(handler=_noop_handler, event=event, data=data)
        assert result == "ok"

    async def test_handler_receives_same_data(self):
        from services.bot.middlewares.log_context import LogContextMiddleware
        mw = LogContextMiddleware()
        captured = {}

        async def capture_handler(event, data):
            captured.update(data)
            return "captured"

        msg = _make_message()
        data = {"some_key": "some_value"}
        result = await mw(handler=capture_handler, event=msg, data=data)
        assert result == "captured"
        assert captured.get("some_key") == "some_value"


class TestUserIdFromEvent:
    def test_message_with_user(self):
        from services.bot.middlewares.log_context import _user_id_from_event
        msg = _make_message(user_id=789)
        assert _user_id_from_event(msg) == 789

    def test_callback_with_user(self):
        from services.bot.middlewares.log_context import _user_id_from_event
        cb = _make_callback(user_id=321)
        assert _user_id_from_event(cb) == 321

    def test_unknown_event_returns_none(self):
        from services.bot.middlewares.log_context import _user_id_from_event
        event = MagicMock()
        # Not a Message or CallbackQuery
        assert _user_id_from_event(event) is None

    def test_message_without_user(self):
        from services.bot.middlewares.log_context import _user_id_from_event
        msg = AsyncMock(spec=types.Message)
        msg.from_user = None
        assert _user_id_from_event(msg) is None

    def test_callback_without_user(self):
        from services.bot.middlewares.log_context import _user_id_from_event
        cb = AsyncMock(spec=types.CallbackQuery)
        cb.from_user = None
        assert _user_id_from_event(cb) is None


# ---------------------------------------------------------------------------
# middlewares/ban_check.py
# ---------------------------------------------------------------------------

class TestBanCheckMiddleware:
    async def test_no_user_id_passes_through(self):
        """Events without from_user are passed through."""
        from services.bot.middlewares.ban_check import BanCheckMiddleware
        mw = BanCheckMiddleware()
        event = MagicMock(spec=[])  # Not a Message or CallbackQuery
        data = {}
        result = await mw(handler=_noop_handler, event=event, data=data)
        assert result == "ok"

    async def test_cached_banned_message_blocks(self):
        from services.bot.middlewares.ban_check import BanCheckMiddleware
        mw = BanCheckMiddleware()
        msg = _make_message(user_id=200)

        with patch("services.bot.middlewares.ban_check._get_ban_cached", AsyncMock(return_value=True)):
            result = await mw(handler=_noop_handler, event=msg, data={})
        assert result is None
        msg.answer.assert_called_once()

    async def test_cached_banned_callback_blocks(self):
        from services.bot.middlewares.ban_check import BanCheckMiddleware
        mw = BanCheckMiddleware()
        cb = _make_callback(user_id=201)

        with patch("services.bot.middlewares.ban_check._get_ban_cached", AsyncMock(return_value=True)):
            result = await mw(handler=_noop_handler, event=cb, data={})
        assert result is None
        cb.answer.assert_called_once()

    async def test_cached_not_banned_passes_through(self):
        from services.bot.middlewares.ban_check import BanCheckMiddleware
        mw = BanCheckMiddleware()
        msg = _make_message(user_id=202)

        with patch("services.bot.middlewares.ban_check._get_ban_cached", AsyncMock(return_value=False)):
            result = await mw(handler=_noop_handler, event=msg, data={})
        assert result == "ok"

    async def test_db_user_not_found_passes_through(self):
        """New user not in DB — should be let through and cached as not-banned."""
        from services.bot.middlewares.ban_check import BanCheckMiddleware
        mw = BanCheckMiddleware()
        msg = _make_message(user_id=300)

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("services.bot.middlewares.ban_check._get_ban_cached", AsyncMock(return_value=None)), \
             patch("services.bot.middlewares.ban_check.get_pool", AsyncMock(return_value=mock_pool)), \
             patch("services.bot.middlewares.ban_check._set_ban_cached", AsyncMock()):
            result = await mw(handler=_noop_handler, event=msg, data={})
        assert result == "ok"

    async def test_db_user_not_banned_passes_through(self):
        from services.bot.middlewares.ban_check import BanCheckMiddleware
        mw = BanCheckMiddleware()
        msg = _make_message(user_id=301)

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"is_blocked": False})
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("services.bot.middlewares.ban_check._get_ban_cached", AsyncMock(return_value=None)), \
             patch("services.bot.middlewares.ban_check.get_pool", AsyncMock(return_value=mock_pool)), \
             patch("services.bot.middlewares.ban_check._set_ban_cached", AsyncMock()):
            result = await mw(handler=_noop_handler, event=msg, data={})
        assert result == "ok"

    async def test_db_user_banned_message_blocked(self):
        from services.bot.middlewares.ban_check import BanCheckMiddleware
        mw = BanCheckMiddleware()
        msg = _make_message(user_id=302)

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"is_blocked": True})
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("services.bot.middlewares.ban_check._get_ban_cached", AsyncMock(return_value=None)), \
             patch("services.bot.middlewares.ban_check.get_pool", AsyncMock(return_value=mock_pool)), \
             patch("services.bot.middlewares.ban_check._set_ban_cached", AsyncMock()):
            result = await mw(handler=_noop_handler, event=msg, data={})
        assert result is None
        msg.answer.assert_called_once()

    async def test_db_user_banned_callback_blocked(self):
        from services.bot.middlewares.ban_check import BanCheckMiddleware
        mw = BanCheckMiddleware()
        cb = _make_callback(user_id=303)

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"is_blocked": True})
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("services.bot.middlewares.ban_check._get_ban_cached", AsyncMock(return_value=None)), \
             patch("services.bot.middlewares.ban_check.get_pool", AsyncMock(return_value=mock_pool)), \
             patch("services.bot.middlewares.ban_check._set_ban_cached", AsyncMock()):
            result = await mw(handler=_noop_handler, event=cb, data={})
        assert result is None
        cb.answer.assert_called_once()

    async def test_exception_allows_through(self):
        """When an exception occurs during ban check, allow the event through."""
        from services.bot.middlewares.ban_check import BanCheckMiddleware
        mw = BanCheckMiddleware()
        msg = _make_message(user_id=400)

        with patch("services.bot.middlewares.ban_check._get_ban_cached", AsyncMock(side_effect=Exception("Redis down"))):
            result = await mw(handler=_noop_handler, event=msg, data={})
        assert result == "ok"

    async def test_callback_query_no_user_passes_through(self):
        from services.bot.middlewares.ban_check import BanCheckMiddleware
        mw = BanCheckMiddleware()
        cb = AsyncMock(spec=types.CallbackQuery)
        cb.from_user = None
        result = await mw(handler=_noop_handler, event=cb, data={})
        assert result == "ok"

    async def test_cached_banned_message_answer_raises_silenced(self):
        """Exception in event.answer() when cached=True+Message is silenced."""
        from services.bot.middlewares.ban_check import BanCheckMiddleware
        mw = BanCheckMiddleware()
        msg = _make_message(user_id=210)
        msg.answer.side_effect = Exception("Telegram error")
        with patch("services.bot.middlewares.ban_check._get_ban_cached", AsyncMock(return_value=True)):
            result = await mw(handler=_noop_handler, event=msg, data={})
        assert result is None  # Still blocked, exception silenced

    async def test_db_banned_callback_answer_raises_silenced(self):
        """Exception in cb.answer() when DB says banned is silenced."""
        from services.bot.middlewares.ban_check import BanCheckMiddleware
        mw = BanCheckMiddleware()
        cb = _make_callback(user_id=304)
        cb.answer.side_effect = Exception("Telegram error")

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"is_blocked": True})
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("services.bot.middlewares.ban_check._get_ban_cached", AsyncMock(return_value=None)), \
             patch("services.bot.middlewares.ban_check.get_pool", AsyncMock(return_value=mock_pool)), \
             patch("services.bot.middlewares.ban_check._set_ban_cached", AsyncMock()):
            result = await mw(handler=_noop_handler, event=cb, data={})
        assert result is None  # Still blocked, exception silenced


class TestBanCacheHelpers:
    async def test_get_ban_cached_no_redis(self):
        from services.bot.middlewares.ban_check import _get_ban_cached
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=None)):
            result = await _get_ban_cached(999)
        assert result is None

    async def test_get_ban_cached_redis_has_ban(self):
        from services.bot.middlewares.ban_check import _get_ban_cached
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"1")
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_redis)):
            result = await _get_ban_cached(111)
        assert result is True

    async def test_get_ban_cached_redis_not_banned(self):
        from services.bot.middlewares.ban_check import _get_ban_cached
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"0")
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_redis)):
            result = await _get_ban_cached(222)
        assert result is False

    async def test_get_ban_cached_redis_key_missing(self):
        from services.bot.middlewares.ban_check import _get_ban_cached
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_redis)):
            result = await _get_ban_cached(333)
        assert result is None

    async def test_get_ban_cached_exception_returns_none(self):
        from services.bot.middlewares.ban_check import _get_ban_cached
        with patch("shared.redis.store._get_redis", AsyncMock(side_effect=Exception("fail"))):
            result = await _get_ban_cached(444)
        assert result is None

    async def test_set_ban_cached_banned(self):
        from services.bot.middlewares.ban_check import _set_ban_cached
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_redis)):
            await _set_ban_cached(555, True)
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][1] == "1"

    async def test_set_ban_cached_not_banned(self):
        from services.bot.middlewares.ban_check import _set_ban_cached
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_redis)):
            await _set_ban_cached(666, False)
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][1] == "0"

    async def test_set_ban_cached_no_redis(self):
        from services.bot.middlewares.ban_check import _set_ban_cached
        # Should not raise even when redis is None
        with patch("shared.redis.store._get_redis", AsyncMock(return_value=None)):
            await _set_ban_cached(777, True)  # Should not raise

    async def test_set_ban_cached_exception_silenced(self):
        from services.bot.middlewares.ban_check import _set_ban_cached
        with patch("shared.redis.store._get_redis", AsyncMock(side_effect=Exception("fail"))):
            await _set_ban_cached(888, True)  # Should not raise


# ---------------------------------------------------------------------------
# middlewares/rate_limit.py
# ---------------------------------------------------------------------------

class TestCheckAndRecordMemory:
    def setup_method(self):
        """Clear in-memory rate state before each test."""
        from services.bot.middlewares import rate_limit
        rate_limit._rate.clear()
        rate_limit._last_full_cleanup = 0.0

    def test_under_limit_returns_false(self):
        from services.bot.middlewares.rate_limit import _check_and_record_memory, MAX_PER_WINDOW
        uid = 10001
        for _ in range(MAX_PER_WINDOW - 1):
            over = _check_and_record_memory(uid)
            assert over is False

    def test_at_limit_returns_true(self):
        from services.bot.middlewares.rate_limit import _check_and_record_memory, MAX_PER_WINDOW
        uid = 10002
        for _ in range(MAX_PER_WINDOW):
            _check_and_record_memory(uid)
        assert _check_and_record_memory(uid) is True

    def test_old_timestamps_cleaned(self):
        from services.bot.middlewares import rate_limit
        from services.bot.middlewares.rate_limit import _check_and_record_memory, MAX_PER_WINDOW, WINDOW_SEC
        uid = 10003
        old_time = time.monotonic() - WINDOW_SEC - 1
        rate_limit._rate[uid] = deque([old_time] * MAX_PER_WINDOW, maxlen=MAX_PER_WINDOW + 10)
        # Prevent full cleanup from running so the per-user popleft path (line 37) executes
        rate_limit._last_full_cleanup = time.monotonic()
        # Old timestamps should be expired via popleft, so not over limit
        over = _check_and_record_memory(uid)
        assert over is False

    def test_cleanup_removes_stale_users(self):
        from services.bot.middlewares import rate_limit
        from services.bot.middlewares.rate_limit import WINDOW_SEC, _CLEANUP_INTERVAL
        old_time = time.monotonic() - WINDOW_SEC - 10
        rate_limit._rate[99901] = deque([old_time])
        rate_limit._last_full_cleanup = time.monotonic() - _CLEANUP_INTERVAL - 1
        # Trigger cleanup via any call
        rate_limit._check_and_record_memory(99902)
        assert 99901 not in rate_limit._rate

    def test_different_users_independent(self):
        from services.bot.middlewares.rate_limit import _check_and_record_memory
        assert _check_and_record_memory(20001) is False
        assert _check_and_record_memory(20002) is False


class TestSendRateLimitWarning:
    async def test_message_gets_answer(self):
        from services.bot.middlewares.rate_limit import _send_rate_limit_warning
        msg = _make_message()
        await _send_rate_limit_warning(msg)
        msg.answer.assert_called_once()

    async def test_callback_gets_answer(self):
        from services.bot.middlewares.rate_limit import _send_rate_limit_warning
        cb = _make_callback()
        await _send_rate_limit_warning(cb)
        cb.answer.assert_called_once()

    async def test_exception_silenced(self):
        from services.bot.middlewares.rate_limit import _send_rate_limit_warning
        msg = _make_message()
        msg.answer.side_effect = Exception("TG error")
        await _send_rate_limit_warning(msg)  # Should not raise


class TestRateLimitMiddleware:
    def setup_method(self):
        from services.bot.middlewares import rate_limit
        rate_limit._rate.clear()
        rate_limit._last_full_cleanup = 0.0

    async def test_no_user_passes_through(self):
        from services.bot.middlewares.rate_limit import RateLimitMiddleware
        mw = RateLimitMiddleware()
        event = MagicMock(spec=[])
        result = await mw(handler=_noop_handler, event=event, data={})
        assert result == "ok"

    async def test_admin_always_passes(self):
        from services.bot.middlewares.rate_limit import RateLimitMiddleware
        mw = RateLimitMiddleware()
        msg = _make_message(user_id=500)
        with patch("shared.domain.credits._is_admin_user", return_value=True):
            result = await mw(handler=_noop_handler, event=msg, data={})
        assert result == "ok"

    async def test_redis_under_limit_passes(self):
        from services.bot.middlewares.rate_limit import RateLimitMiddleware
        mw = RateLimitMiddleware()
        msg = _make_message(user_id=501)
        with patch("shared.domain.credits._is_admin_user", return_value=False), \
             patch("shared.redis.store.rate_limit_check_and_incr", AsyncMock(return_value=False)):
            result = await mw(handler=_noop_handler, event=msg, data={})
        assert result == "ok"

    async def test_redis_over_limit_blocks(self):
        from services.bot.middlewares.rate_limit import RateLimitMiddleware
        mw = RateLimitMiddleware()
        msg = _make_message(user_id=502)
        with patch("shared.domain.credits._is_admin_user", return_value=False), \
             patch("shared.redis.store.rate_limit_check_and_incr", AsyncMock(return_value=True)):
            result = await mw(handler=_noop_handler, event=msg, data={})
        assert result is None
        msg.answer.assert_called_once()

    async def test_redis_exception_falls_back_to_memory(self):
        """When Redis fails, fallback to in-memory rate limiting."""
        from services.bot.middlewares.rate_limit import RateLimitMiddleware
        mw = RateLimitMiddleware()
        msg = _make_message(user_id=503)
        with patch("shared.domain.credits._is_admin_user", return_value=False), \
             patch("shared.redis.store.rate_limit_check_and_incr", AsyncMock(side_effect=Exception("Redis down"))):
            result = await mw(handler=_noop_handler, event=msg, data={})
        assert result == "ok"  # under limit in memory

    async def test_memory_over_limit_blocks(self):
        from services.bot.middlewares.rate_limit import RateLimitMiddleware, MAX_PER_WINDOW, _rate
        mw = RateLimitMiddleware()
        uid = 504
        msg = _make_message(user_id=uid)
        # Pre-fill rate deque to be at limit
        now = time.monotonic()
        _rate[uid] = deque([now] * MAX_PER_WINDOW, maxlen=MAX_PER_WINDOW + 10)
        with patch("shared.domain.credits._is_admin_user", return_value=False), \
             patch("shared.redis.store.rate_limit_check_and_incr", AsyncMock(side_effect=Exception("Redis down"))):
            result = await mw(handler=_noop_handler, event=msg, data={})
        assert result is None
        msg.answer.assert_called_once()

    async def test_callback_under_limit_redis(self):
        from services.bot.middlewares.rate_limit import RateLimitMiddleware
        mw = RateLimitMiddleware()
        cb = _make_callback(user_id=505)
        with patch("shared.domain.credits._is_admin_user", return_value=False), \
             patch("shared.redis.store.rate_limit_check_and_incr", AsyncMock(return_value=False)):
            result = await mw(handler=_noop_handler, event=cb, data={})
        assert result == "ok"

    async def test_callback_over_limit_redis(self):
        from services.bot.middlewares.rate_limit import RateLimitMiddleware
        mw = RateLimitMiddleware()
        cb = _make_callback(user_id=506)
        with patch("shared.domain.credits._is_admin_user", return_value=False), \
             patch("shared.redis.store.rate_limit_check_and_incr", AsyncMock(return_value=True)):
            result = await mw(handler=_noop_handler, event=cb, data={})
        assert result is None
        cb.answer.assert_called_once()

    async def test_message_no_from_user_passes(self):
        from services.bot.middlewares.rate_limit import RateLimitMiddleware
        mw = RateLimitMiddleware()
        msg = AsyncMock(spec=types.Message)
        msg.from_user = None
        result = await mw(handler=_noop_handler, event=msg, data={})
        assert result == "ok"
