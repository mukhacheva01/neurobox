"""Pytest tests for admin bot handlers.

Covers:
  services/bot/handlers/admin/users.py
  services/bot/handlers/admin/broadcast.py
  services/bot/handlers/admin/stats.py
  services/bot/handlers/admin/finance.py
  services/bot/handlers/admin/moderation.py
  services/bot/handlers/admin/promo.py
  services/bot/handlers/admin/system.py
  services/bot/handlers/admin/subscriptions.py
  services/bot/handlers/admin/dashboard.py
  services/bot/handlers/admin_cmd.py
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import types
from aiogram.fsm.context import FSMContext

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

ADMIN_ID = 777
NON_ADMIN_ID = 999


def _make_user(user_id: int = ADMIN_ID, username: str = "admin_user", first_name: str = "Admin"):
    u = MagicMock()
    u.id = user_id
    u.username = username
    u.first_name = first_name
    return u


def _make_message(text: str = "hi", user_id: int = ADMIN_ID):
    msg = AsyncMock(spec=types.Message)
    msg.from_user = _make_user(user_id)
    msg.text = text
    msg.answer = AsyncMock()
    msg.answer_document = AsyncMock()
    msg.answer_photo = AsyncMock()
    msg.edit_text = AsyncMock()
    msg.chat = MagicMock()
    msg.chat.id = user_id
    msg.reply_to_message = None
    msg.bot = AsyncMock()
    msg.photo = None
    return msg


def _make_callback(data: str = "test", user_id: int = ADMIN_ID):
    cb = AsyncMock(spec=types.CallbackQuery)
    cb.from_user = _make_user(user_id)
    cb.data = data
    cb.message = _make_message(user_id=user_id)
    cb.answer = AsyncMock()
    cb.bot = AsyncMock()
    return cb


def _make_state():
    state = AsyncMock(spec=FSMContext)
    state.set_state = AsyncMock()
    state.get_state = AsyncMock(return_value=None)
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    state.clear = AsyncMock()
    return state


def _make_pool():
    """Build a mock asyncpg pool using asynccontextmanager (as required)."""
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=0)
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock()

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool = MagicMock()
    pool.acquire = _acquire
    return pool, conn


# ---------------------------------------------------------------------------
# Reusable patch contexts
# ---------------------------------------------------------------------------

def _patch_admin_log():
    return patch("shared.domain.admin_log.log_admin", new=AsyncMock())


# ===========================================================================
# admin/dashboard.py
# ===========================================================================

class TestDashboardCbAdminBack:
    async def test_allowed(self):
        cb = _make_callback("admin:back")
        state = _make_state()
        with patch("services.bot.handlers.admin.dashboard._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.dashboard._admin_denied", new=AsyncMock()) as denied, \
             patch("services.bot.handlers.admin.dashboard.admin_dashboard_kb", return_value=MagicMock()):
            from services.bot.handlers.admin.dashboard import cb_admin_back
            await cb_admin_back(cb, state)
        cb.answer.assert_awaited_once()
        state.clear.assert_awaited_once()
        cb.message.answer.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:back", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.dashboard._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.dashboard._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.dashboard import cb_admin_back
            await cb_admin_back(cb, state)
        denied_mock.assert_awaited_once()
        cb.answer.assert_not_awaited()


class TestDashboardCbAdminWebPanel:
    async def test_allowed(self):
        cb = _make_callback("admin:web_panel")
        with patch("services.bot.handlers.admin.dashboard._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.dashboard._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.dashboard import cb_admin_web_panel
            await cb_admin_web_panel(cb)
        cb.answer.assert_awaited_once()
        cb.message.answer.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:web_panel", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.dashboard._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.dashboard._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.dashboard import cb_admin_web_panel
            await cb_admin_web_panel(cb)
        denied_mock.assert_awaited_once()
        cb.answer.assert_not_awaited()


# ===========================================================================
# admin_cmd.py
# ===========================================================================

class TestAdminCmd:
    async def test_cmd_admin_allowed(self):
        msg = _make_message("/admin")
        pool, conn = _make_pool()
        conn.fetchval = AsyncMock(side_effect=[10, 5000, 3, 42])
        with patch("services.bot.handlers.admin_cmd.is_admin", return_value=True), \
             patch("services.bot.handlers.admin_cmd._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin_cmd.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin_cmd.admin_dashboard_kb", return_value=MagicMock()):
            from services.bot.handlers.admin_cmd import cmd_admin
            await cmd_admin(msg)
        msg.answer.assert_awaited()

    async def test_cmd_admin_denied(self):
        msg = _make_message("/admin", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin_cmd.is_admin", return_value=False), \
             patch("services.bot.handlers.admin_cmd._admin_denied", new=denied_mock):
            from services.bot.handlers.admin_cmd import cmd_admin
            await cmd_admin(msg)
        denied_mock.assert_awaited_once()

    async def test_cb_open_admin_allowed(self):
        cb = _make_callback("open_admin")
        pool, conn = _make_pool()
        conn.fetchval = AsyncMock(side_effect=[10, 5000, 3, 42])
        with patch("services.bot.handlers.admin_cmd.is_admin", return_value=True), \
             patch("services.bot.handlers.admin_cmd._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin_cmd.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin_cmd.admin_dashboard_kb", return_value=MagicMock()):
            from services.bot.handlers.admin_cmd import cb_open_admin
            await cb_open_admin(cb)
        cb.answer.assert_awaited()

    async def test_cb_open_admin_denied(self):
        cb = _make_callback("open_admin", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin_cmd.is_admin", return_value=False), \
             patch("services.bot.handlers.admin_cmd._admin_denied", new=denied_mock):
            from services.bot.handlers.admin_cmd import cb_open_admin
            await cb_open_admin(cb)
        denied_mock.assert_awaited_once()
        cb.answer.assert_not_awaited()

    def test_is_admin_helper(self):
        from services.bot.handlers.admin_cmd import is_admin
        with patch("services.bot.handlers.admin_cmd.settings") as mock_settings:
            mock_settings.admin_id_list = [ADMIN_ID]
            assert is_admin(ADMIN_ID) is True
            assert is_admin(NON_ADMIN_ID) is False


# ===========================================================================
# admin/users.py
# ===========================================================================

class TestCbAdminUsers:
    async def test_allowed(self):
        cb = _make_callback("admin:users")
        pool, conn = _make_pool()
        conn.fetchval = AsyncMock(return_value=5)
        conn.fetch = AsyncMock(return_value=[])
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.users.get_pool", return_value=pool):
            from services.bot.handlers.admin.users import cb_admin_users
            await cb_admin_users(cb)
        cb.answer.assert_awaited_once()
        cb.message.answer.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:users", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.users._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.users import cb_admin_users
            await cb_admin_users(cb)
        denied_mock.assert_awaited_once()


class TestCbUsersPage:
    async def test_allowed_valid_offset(self):
        cb = _make_callback("admin:users:page:20")
        pool, conn = _make_pool()
        conn.fetchval = AsyncMock(return_value=100)
        conn.fetch = AsyncMock(return_value=[])
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.users.get_pool", return_value=pool):
            from services.bot.handlers.admin.users import cb_users_page
            await cb_users_page(cb)
        cb.answer.assert_awaited_once()
        cb.message.answer.assert_awaited_once()

    async def test_invalid_offset(self):
        cb = _make_callback("admin:users:page:notanumber")
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.users import cb_users_page
            await cb_users_page(cb)
        cb.message.answer.assert_not_awaited()

    async def test_denied(self):
        cb = _make_callback("admin:users:page:0", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.users._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.users import cb_users_page
            await cb_users_page(cb)
        denied_mock.assert_awaited_once()


class TestCbFindUserStart:
    async def test_allowed(self):
        cb = _make_callback("admin:find_user")
        state = _make_state()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.users import cb_find_user_start
            await cb_find_user_start(cb, state)
        state.set_state.assert_awaited_once()
        cb.message.answer.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:find_user", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.users._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.users import cb_find_user_start
            await cb_find_user_start(cb, state)
        denied_mock.assert_awaited_once()


class TestFindUserEnter:
    async def test_allowed_user_found_by_id(self):
        msg = _make_message("12345")
        state = _make_state()
        pool, conn = _make_pool()
        fake_user = {
            "id": 12345, "username": "alice", "first_name": "Alice",
            "credits_bought": 10, "credits_free_today": 5,
            "created_at": MagicMock(strftime=lambda f: "01.01.2024"),
            "is_blocked": False,
        }
        conn.fetchrow = AsyncMock(return_value=fake_user)
        conn.fetchval = AsyncMock(return_value=0)
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.users.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.users.user_card_kb", return_value=MagicMock()), \
             patch("services.bot.services.mode_service.get_current_mode_display",
                   new=AsyncMock(return_value="Text")):
            from services.bot.handlers.admin.users import find_user_enter
            await find_user_enter(msg, state)
        msg.answer.assert_awaited()

    async def test_user_not_found(self):
        msg = _make_message("99999")
        state = _make_state()
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.users.get_pool", return_value=pool):
            from services.bot.handlers.admin.users import find_user_enter
            await find_user_enter(msg, state)
        msg.answer.assert_awaited()
        state.clear.assert_awaited()

    async def test_empty_query(self):
        msg = _make_message("  ")
        state = _make_state()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.users import find_user_enter
            await find_user_enter(msg, state)
        msg.answer.assert_awaited_once()

    async def test_denied(self):
        msg = _make_message("123", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.users._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.users import find_user_enter
            await find_user_enter(msg, state)
        denied_mock.assert_awaited_once()
        state.clear.assert_awaited()


class TestCbUserBan:
    async def test_allowed(self):
        cb = _make_callback("admin:user:ban:42")
        pool, conn = _make_pool()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.users.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.users.log_admin", new=AsyncMock()):
            from services.bot.handlers.admin.users import cb_user_ban
            await cb_user_ban(cb)
        conn.execute.assert_awaited()
        cb.answer.assert_awaited()

    async def test_invalid_uid(self):
        cb = _make_callback("admin:user:ban:notanumber")
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.users import cb_user_ban
            await cb_user_ban(cb)
        cb.answer.assert_not_awaited()

    async def test_denied(self):
        cb = _make_callback("admin:user:ban:42", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.users._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.users import cb_user_ban
            await cb_user_ban(cb)
        denied_mock.assert_awaited_once()


class TestCbUserUnban:
    async def test_allowed(self):
        cb = _make_callback("admin:user:unban:42")
        pool, conn = _make_pool()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.users.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.users.log_admin", new=AsyncMock()):
            from services.bot.handlers.admin.users import cb_user_unban
            await cb_user_unban(cb)
        conn.execute.assert_awaited()

    async def test_denied(self):
        cb = _make_callback("admin:user:unban:42", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.users._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.users import cb_user_unban
            await cb_user_unban(cb)
        denied_mock.assert_awaited_once()


class TestCbUserAdd:
    async def test_allowed(self):
        cb = _make_callback("admin:user:add:42")
        state = _make_state()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.users import cb_user_add
            await cb_user_add(cb, state)
        state.update_data.assert_awaited()
        state.set_state.assert_awaited()
        cb.message.answer.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:user:add:42", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.users._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.users import cb_user_add
            await cb_user_add(cb, state)
        denied_mock.assert_awaited_once()


class TestCbUserSub:
    async def test_allowed(self):
        cb = _make_callback("admin:user:sub:42")
        state = _make_state()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.users import cb_user_sub
            await cb_user_sub(cb, state)
        state.update_data.assert_awaited()
        state.set_state.assert_awaited()

    async def test_denied(self):
        cb = _make_callback("admin:user:sub:42", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.users._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.users import cb_user_sub
            await cb_user_sub(cb, state)
        denied_mock.assert_awaited_once()


class TestCreditAmount:
    async def test_allowed_add(self):
        msg = _make_message("50")
        state = _make_state()
        state.get_data = AsyncMock(return_value={"credit_user_id": 42, "credit_action": "add"})
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.users.log_admin", new=AsyncMock()), \
             patch("shared.domain.credits.add_credits", new=AsyncMock()):
            from services.bot.handlers.admin.users import credit_amount
            await credit_amount(msg, state)
        msg.answer.assert_awaited()
        state.clear.assert_awaited()

    async def test_allowed_sub(self):
        msg = _make_message("20")
        state = _make_state()
        state.get_data = AsyncMock(return_value={"credit_user_id": 42, "credit_action": "sub"})
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={"credits_bought": 100})
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.users.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.users.log_admin", new=AsyncMock()):
            from services.bot.handlers.admin.users import credit_amount
            await credit_amount(msg, state)
        msg.answer.assert_awaited()

    async def test_invalid_amount(self):
        msg = _make_message("abc")
        state = _make_state()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.users import credit_amount
            await credit_amount(msg, state)
        msg.answer.assert_awaited_once()

    async def test_zero_amount(self):
        msg = _make_message("0")
        state = _make_state()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.users import credit_amount
            await credit_amount(msg, state)
        msg.answer.assert_awaited_once()

    async def test_denied(self):
        msg = _make_message("50", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.users._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.users import credit_amount
            await credit_amount(msg, state)
        denied_mock.assert_awaited_once()
        state.clear.assert_awaited()


class TestCbUserMsg:
    async def test_allowed(self):
        cb = _make_callback("admin:user:msg:42")
        state = _make_state()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.users import cb_user_msg
            await cb_user_msg(cb, state)
        state.update_data.assert_awaited()
        state.set_state.assert_awaited()

    async def test_denied(self):
        cb = _make_callback("admin:user:msg:42", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.users._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.users import cb_user_msg
            await cb_user_msg(cb, state)
        denied_mock.assert_awaited_once()


class TestAdminSendMsgToUser:
    async def test_allowed_send(self):
        msg = _make_message("Hello user!")
        state = _make_state()
        state.get_data = AsyncMock(return_value={"admin_msg_target": 42})
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.users import admin_send_msg_to_user
            await admin_send_msg_to_user(msg, state)
        msg.bot.send_message.assert_awaited()
        msg.answer.assert_awaited()

    async def test_cancel(self):
        msg = _make_message("/cancel")
        state = _make_state()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.users import admin_send_msg_to_user
            await admin_send_msg_to_user(msg, state)
        state.clear.assert_awaited()
        msg.answer.assert_awaited_once()

    async def test_denied(self):
        msg = _make_message("hi", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.users._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.users import admin_send_msg_to_user
            await admin_send_msg_to_user(msg, state)
        denied_mock.assert_awaited_once()


class TestCbUserNote:
    async def test_allowed(self):
        cb = _make_callback("admin:user:note:42")
        state = _make_state()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.users import cb_user_note
            await cb_user_note(cb, state)
        state.update_data.assert_awaited()
        state.set_state.assert_awaited()

    async def test_denied(self):
        cb = _make_callback("admin:user:note:42", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.users._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.users import cb_user_note
            await cb_user_note(cb, state)
        denied_mock.assert_awaited_once()


class TestUserNoteEnter:
    async def test_allowed(self):
        msg = _make_message("Some note about user")
        state = _make_state()
        state.get_data = AsyncMock(return_value={"note_user_id": 42})
        pool, conn = _make_pool()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.users.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.users.log_admin", new=AsyncMock()):
            from services.bot.handlers.admin.users import user_note_enter
            await user_note_enter(msg, state)
        conn.execute.assert_awaited()
        msg.answer.assert_awaited_once()

    async def test_no_uid(self):
        msg = _make_message("Note text")
        state = _make_state()
        state.get_data = AsyncMock(return_value={})
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.users import user_note_enter
            await user_note_enter(msg, state)
        state.clear.assert_awaited()

    async def test_denied(self):
        msg = _make_message("note", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.users._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.users import user_note_enter
            await user_note_enter(msg, state)
        denied_mock.assert_awaited_once()


class TestCbUserHistory:
    async def test_allowed_no_transactions(self):
        cb = _make_callback("admin:user:history:42")
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])
        with patch("services.bot.handlers.admin.users._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.users._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.users.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.users.admin_back_kb", return_value=MagicMock()):
            from services.bot.handlers.admin.users import cb_user_history
            await cb_user_history(cb)
        cb.answer.assert_awaited_once()
        cb.message.answer.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:user:history:42", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.users._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.users._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.users import cb_user_history
            await cb_user_history(cb)
        denied_mock.assert_awaited_once()


# ===========================================================================
# admin/broadcast.py
# ===========================================================================

class TestCbBroadcastStart:
    async def test_allowed(self):
        cb = _make_callback("admin:broadcast")
        state = _make_state()
        with patch("services.bot.handlers.admin.broadcast._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.broadcast._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.broadcast import cb_broadcast_start
            await cb_broadcast_start(cb, state)
        cb.answer.assert_awaited_once()
        state.set_state.assert_awaited_once()
        cb.message.answer.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:broadcast", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.broadcast._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.broadcast._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.broadcast import cb_broadcast_start
            await cb_broadcast_start(cb, state)
        denied_mock.assert_awaited_once()


class TestBroadcastText:
    async def test_allowed(self):
        msg = _make_message("Hello broadcast!")
        state = _make_state()
        with patch("services.bot.handlers.admin.broadcast._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.broadcast._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.broadcast import broadcast_text
            await broadcast_text(msg, state)
        state.update_data.assert_awaited()
        state.set_state.assert_awaited()
        msg.answer.assert_awaited_once()

    async def test_empty_text(self):
        msg = _make_message("   ")
        state = _make_state()
        with patch("services.bot.handlers.admin.broadcast._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.broadcast._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.broadcast import broadcast_text
            await broadcast_text(msg, state)
        msg.answer.assert_awaited_once()

    async def test_denied(self):
        msg = _make_message("text", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.broadcast._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.broadcast._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.broadcast import broadcast_text
            await broadcast_text(msg, state)
        denied_mock.assert_awaited_once()
        state.clear.assert_awaited()


class TestBroadcastPhoto:
    async def test_allowed(self):
        msg = _make_message()
        photo_mock = MagicMock()
        photo_mock.file_id = "file123"
        msg.photo = [photo_mock]
        state = _make_state()
        with patch("services.bot.handlers.admin.broadcast._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.broadcast._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.broadcast import broadcast_photo
            await broadcast_photo(msg, state)
        state.update_data.assert_awaited()
        state.set_state.assert_awaited()

    async def test_denied(self):
        msg = _make_message(user_id=NON_ADMIN_ID)
        photo_mock = MagicMock()
        photo_mock.file_id = "file123"
        msg.photo = [photo_mock]
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.broadcast._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.broadcast._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.broadcast import broadcast_photo
            await broadcast_photo(msg, state)
        denied_mock.assert_awaited_once()


class TestBroadcastSkipPhoto:
    async def test_skip(self):
        msg = _make_message("/skip")
        state = _make_state()
        with patch("services.bot.handlers.admin.broadcast._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.broadcast._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.broadcast import broadcast_skip_photo
            await broadcast_skip_photo(msg, state)
        state.set_state.assert_awaited()

    async def test_non_skip_text(self):
        msg = _make_message("not a photo or skip")
        state = _make_state()
        with patch("services.bot.handlers.admin.broadcast._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.broadcast._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.broadcast import broadcast_skip_photo
            await broadcast_skip_photo(msg, state)
        msg.answer.assert_awaited_once()

    async def test_denied(self):
        msg = _make_message("/skip", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.broadcast._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.broadcast._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.broadcast import broadcast_skip_photo
            await broadcast_skip_photo(msg, state)
        denied_mock.assert_awaited_once()


class TestBroadcastButton:
    async def test_with_url_and_label(self):
        msg = _make_message("https://example.com|Click me")
        state = _make_state()
        with patch("services.bot.handlers.admin.broadcast._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.broadcast._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.broadcast import broadcast_button
            await broadcast_button(msg, state)
        state.update_data.assert_awaited()
        state.set_state.assert_awaited()

    async def test_url_only(self):
        msg = _make_message("https://example.com")
        state = _make_state()
        with patch("services.bot.handlers.admin.broadcast._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.broadcast._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.broadcast import broadcast_button
            await broadcast_button(msg, state)
        state.set_state.assert_awaited()

    async def test_denied(self):
        msg = _make_message("https://example.com", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.broadcast._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.broadcast._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.broadcast import broadcast_button
            await broadcast_button(msg, state)
        denied_mock.assert_awaited_once()


class TestBroadcastAudience:
    async def test_allowed_all(self):
        cb = _make_callback("admin:broadcast:aud:all")
        state = _make_state()
        state.get_data = AsyncMock(return_value={"broadcast_text": "Hello"})
        pool, conn = _make_pool()
        conn.fetchval = AsyncMock(return_value=100)
        with patch("services.bot.handlers.admin.broadcast._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.broadcast._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.broadcast.get_pool", return_value=pool):
            from services.bot.handlers.admin.broadcast import broadcast_audience
            await broadcast_audience(cb, state)
        state.update_data.assert_awaited()
        state.set_state.assert_awaited()

    async def test_invalid_audience(self):
        cb = _make_callback("admin:broadcast:aud:invalid")
        state = _make_state()
        with patch("services.bot.handlers.admin.broadcast._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.broadcast._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.broadcast import broadcast_audience
            await broadcast_audience(cb, state)
        cb.answer.assert_awaited()
        # Should return early without setting state
        state.set_state.assert_not_awaited()

    async def test_denied(self):
        cb = _make_callback("admin:broadcast:aud:all", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.broadcast._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.broadcast._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.broadcast import broadcast_audience
            await broadcast_audience(cb, state)
        denied_mock.assert_awaited_once()


class TestCbBroadcastConfirm:
    async def test_allowed_text_only(self):
        cb = _make_callback("admin:broadcast:confirm")
        state = _make_state()
        state.get_data = AsyncMock(return_value={
            "broadcast_text": "Hello everyone!",
            "broadcast_audience": "all",
        })
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[{"id": 100}, {"id": 101}])
        with patch("services.bot.handlers.admin.broadcast._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.broadcast._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.broadcast.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.broadcast.admin_back_kb", return_value=MagicMock()), \
             patch("services.bot.handlers.admin.broadcast.asyncio.sleep", new=AsyncMock()):
            from services.bot.handlers.admin.broadcast import cb_broadcast_confirm
            await cb_broadcast_confirm(cb, state)
        cb.message.answer.assert_awaited()

    async def test_denied(self):
        cb = _make_callback("admin:broadcast:confirm", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.broadcast._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.broadcast._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.broadcast import cb_broadcast_confirm
            await cb_broadcast_confirm(cb, state)
        denied_mock.assert_awaited_once()


# ===========================================================================
# admin/stats.py
# ===========================================================================

class TestCbAdminStats:
    async def test_allowed(self):
        cb = _make_callback("admin:stats")
        pool, conn = _make_pool()
        conn.fetchval = AsyncMock(return_value=0)
        conn.fetch = AsyncMock(return_value=[])
        with patch("services.bot.handlers.admin.stats._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.stats._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.stats.get_pool", return_value=pool):
            from services.bot.handlers.admin.stats import cb_admin_stats
            await cb_admin_stats(cb)
        cb.answer.assert_awaited_once()
        cb.message.answer.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:stats", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.stats._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.stats._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.stats import cb_admin_stats
            await cb_admin_stats(cb)
        denied_mock.assert_awaited_once()


class TestCbAdminRatings:
    async def test_allowed(self):
        cb = _make_callback("admin:ratings")
        pool, conn = _make_pool()
        conn.fetchval = AsyncMock(return_value=0)
        with patch("services.bot.handlers.admin.stats._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.stats._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.stats.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.stats.admin_back_kb", return_value=MagicMock()):
            from services.bot.handlers.admin.stats import cb_admin_ratings
            await cb_admin_ratings(cb)
        cb.answer.assert_awaited_once()
        cb.message.answer.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:ratings", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.stats._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.stats._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.stats import cb_admin_ratings
            await cb_admin_ratings(cb)
        denied_mock.assert_awaited_once()


class TestCbAdminStatsCsv:
    async def test_allowed(self):
        cb = _make_callback("admin:stats:csv")
        cb.message.answer_document = AsyncMock()
        pool, conn = _make_pool()
        fake_row = MagicMock()
        fake_row.__getitem__ = lambda self, key: {"day": MagicMock(strftime=lambda f: "2024-01-01"), "users": 5}[key]
        conn.fetch = AsyncMock(return_value=[fake_row])
        with patch("services.bot.handlers.admin.stats._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.stats._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.stats.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.stats.admin_back_kb", return_value=MagicMock()):
            from services.bot.handlers.admin.stats import cb_admin_stats_csv
            await cb_admin_stats_csv(cb)
        cb.answer.assert_awaited_once()
        cb.message.answer_document.assert_awaited_once()

    async def test_allowed_empty_rows(self):
        cb = _make_callback("admin:stats:csv")
        cb.message.answer_document = AsyncMock()
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])
        with patch("services.bot.handlers.admin.stats._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.stats._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.stats.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.stats.admin_back_kb", return_value=MagicMock()):
            from services.bot.handlers.admin.stats import cb_admin_stats_csv
            await cb_admin_stats_csv(cb)
        cb.message.answer_document.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:stats:csv", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.stats._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.stats._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.stats import cb_admin_stats_csv
            await cb_admin_stats_csv(cb)
        denied_mock.assert_awaited_once()


# ===========================================================================
# admin/finance.py
# ===========================================================================

class TestCbAdminFinance:
    async def test_allowed(self):
        cb = _make_callback("admin:finance")
        pool, conn = _make_pool()
        conn.fetchval = AsyncMock(return_value=0)
        conn.fetch = AsyncMock(return_value=[])
        with patch("services.bot.handlers.admin.finance._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.finance._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.finance.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.finance.finance_pagination_kb", return_value=MagicMock()):
            from services.bot.handlers.admin.finance import cb_admin_finance
            await cb_admin_finance(cb)
        cb.answer.assert_awaited_once()
        cb.message.answer.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:finance", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.finance._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.finance._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.finance import cb_admin_finance
            await cb_admin_finance(cb)
        denied_mock.assert_awaited_once()


class TestCbFinancePage:
    async def test_allowed(self):
        cb = _make_callback("admin:finance:page:50")
        pool, conn = _make_pool()
        conn.fetchval = AsyncMock(return_value=100)
        conn.fetch = AsyncMock(return_value=[])
        with patch("services.bot.handlers.admin.finance._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.finance._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.finance.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.finance.finance_pagination_kb", return_value=MagicMock()):
            from services.bot.handlers.admin.finance import cb_finance_page
            await cb_finance_page(cb)
        cb.answer.assert_awaited_once()

    async def test_invalid_offset(self):
        cb = _make_callback("admin:finance:page:bad")
        with patch("services.bot.handlers.admin.finance._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.finance._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.finance import cb_finance_page
            await cb_finance_page(cb)
        cb.message.answer.assert_not_awaited()

    async def test_denied(self):
        cb = _make_callback("admin:finance:page:0", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.finance._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.finance._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.finance import cb_finance_page
            await cb_finance_page(cb)
        denied_mock.assert_awaited_once()


class TestCbFinanceRevenue:
    async def test_allowed(self):
        cb = _make_callback("admin:finance:revenue")
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])
        with patch("services.bot.handlers.admin.finance._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.finance._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.finance.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.finance.admin_back_kb", return_value=MagicMock()):
            from services.bot.handlers.admin.finance import cb_finance_revenue
            await cb_finance_revenue(cb)
        cb.answer.assert_awaited_once()
        cb.message.answer.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:finance:revenue", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.finance._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.finance._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.finance import cb_finance_revenue
            await cb_finance_revenue(cb)
        denied_mock.assert_awaited_once()


class TestCbFinanceCsv:
    async def test_allowed(self):
        cb = _make_callback("admin:finance:csv")
        cb.message.answer_document = AsyncMock()
        pool, conn = _make_pool()
        fake_row = MagicMock()

        def row_getitem(key):
            data = {
                "created_at": MagicMock(isoformat=lambda: "2024-01-01T00:00:00"),
                "user_id": 42,
                "username": "user",
                "amount_rub": 100.0,
                "credits_amount": 50,
                "pack_name": "basic",
                "status": "confirmed",
            }
            return data[key]

        fake_row.__getitem__ = lambda self, key: row_getitem(key)
        conn.fetch = AsyncMock(return_value=[fake_row])
        with patch("services.bot.handlers.admin.finance._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.finance._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.finance.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.finance.admin_back_kb", return_value=MagicMock()):
            from services.bot.handlers.admin.finance import cb_finance_csv
            await cb_finance_csv(cb)
        cb.message.answer_document.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:finance:csv", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.finance._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.finance._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.finance import cb_finance_csv
            await cb_finance_csv(cb)
        denied_mock.assert_awaited_once()


# ===========================================================================
# admin/moderation.py
# ===========================================================================

class TestCbAdminModeration:
    async def test_allowed(self):
        cb = _make_callback("admin:moderation")
        with patch("services.bot.handlers.admin.moderation._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.moderation._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.moderation.moderation_board_kb", return_value=MagicMock()):
            from services.bot.handlers.admin.moderation import cb_admin_moderation
            await cb_admin_moderation(cb)
        cb.answer.assert_awaited_once()
        cb.message.answer.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:moderation", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.moderation._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.moderation._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.moderation import cb_admin_moderation
            await cb_admin_moderation(cb)
        denied_mock.assert_awaited_once()


class TestCbComplaints:
    async def test_allowed_no_complaints(self):
        cb = _make_callback("admin:mod:complaints")
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])
        with patch("services.bot.handlers.admin.moderation._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.moderation._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.moderation.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.moderation.admin_back_kb", return_value=MagicMock()):
            from services.bot.handlers.admin.moderation import cb_complaints
            await cb_complaints(cb)
        cb.message.answer.assert_awaited_once()

    async def test_allowed_with_complaints(self):
        cb = _make_callback("admin:mod:complaints")
        pool, conn = _make_pool()
        fake_row = {"post_id": 1, "user_id": 42, "reason": "spam"}
        conn.fetch = AsyncMock(return_value=[fake_row])
        with patch("services.bot.handlers.admin.moderation._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.moderation._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.moderation.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.moderation.admin_back_kb", return_value=MagicMock()):
            from services.bot.handlers.admin.moderation import cb_complaints
            await cb_complaints(cb)
        cb.message.answer.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:mod:complaints", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.moderation._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.moderation._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.moderation import cb_complaints
            await cb_complaints(cb)
        denied_mock.assert_awaited_once()


class TestCbBanned:
    async def test_allowed_no_bans(self):
        cb = _make_callback("admin:mod:banned")
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])
        with patch("services.bot.handlers.admin.moderation._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.moderation._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.moderation.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.moderation.admin_back_kb", return_value=MagicMock()):
            from services.bot.handlers.admin.moderation import cb_banned
            await cb_banned(cb)
        cb.message.answer.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:mod:banned", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.moderation._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.moderation._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.moderation import cb_banned
            await cb_banned(cb)
        denied_mock.assert_awaited_once()


class TestCbStopwords:
    async def test_allowed(self):
        cb = _make_callback("admin:mod:stopwords")
        state = _make_state()
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[{"word": "spam"}])
        with patch("services.bot.handlers.admin.moderation._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.moderation._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.moderation.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.moderation.admin_back_kb", return_value=MagicMock()):
            from services.bot.handlers.admin.moderation import cb_stopwords
            await cb_stopwords(cb, state)
        cb.message.answer.assert_awaited_once()
        state.set_state.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:mod:stopwords", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.moderation._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.moderation._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.moderation import cb_stopwords
            await cb_stopwords(cb, state)
        denied_mock.assert_awaited_once()


class TestStopwordAdd:
    async def test_allowed(self):
        msg = _make_message("badword")
        state = _make_state()
        pool, conn = _make_pool()
        with patch("services.bot.handlers.admin.moderation._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.moderation._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.moderation.get_pool", return_value=pool):
            from services.bot.handlers.admin.moderation import stopword_add
            await stopword_add(msg, state)
        conn.execute.assert_awaited()
        msg.answer.assert_awaited_once()
        state.clear.assert_awaited()

    async def test_empty_word(self):
        msg = _make_message("   ")
        state = _make_state()
        with patch("services.bot.handlers.admin.moderation._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.moderation._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.moderation import stopword_add
            await stopword_add(msg, state)
        state.clear.assert_awaited()
        msg.answer.assert_not_awaited()

    async def test_command_word_ignored(self):
        msg = _make_message("/cancel")
        state = _make_state()
        with patch("services.bot.handlers.admin.moderation._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.moderation._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.moderation import stopword_add
            await stopword_add(msg, state)
        state.clear.assert_awaited()
        msg.answer.assert_not_awaited()

    async def test_denied(self):
        msg = _make_message("spam", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.moderation._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.moderation._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.moderation import stopword_add
            await stopword_add(msg, state)
        denied_mock.assert_awaited_once()
        state.clear.assert_awaited()


# ===========================================================================
# admin/promo.py
# ===========================================================================

class TestCbAdminPromo:
    async def test_allowed(self):
        cb = _make_callback("admin:promo")
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])
        with patch("services.bot.handlers.admin.promo._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.promo._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.promo.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.promo.promo_list_kb", return_value=MagicMock()):
            from services.bot.handlers.admin.promo import cb_admin_promo
            await cb_admin_promo(cb)
        cb.answer.assert_awaited_once()
        cb.message.answer.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:promo", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.promo._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.promo._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.promo import cb_admin_promo
            await cb_admin_promo(cb)
        denied_mock.assert_awaited_once()


class TestCbPromoCreate:
    async def test_allowed(self):
        cb = _make_callback("admin:promo:create")
        state = _make_state()
        with patch("services.bot.handlers.admin.promo._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.promo._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.promo import cb_promo_create
            await cb_promo_create(cb, state)
        state.set_state.assert_awaited_once()
        cb.message.answer.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:promo:create", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.promo._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.promo._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.promo import cb_promo_create
            await cb_promo_create(cb, state)
        denied_mock.assert_awaited_once()


class TestPromoCode:
    async def test_allowed_valid_code(self):
        msg = _make_message("SAVE20")
        state = _make_state()
        with patch("services.bot.handlers.admin.promo._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.promo._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.promo import promo_code
            await promo_code(msg, state)
        state.update_data.assert_awaited()
        state.set_state.assert_awaited()
        msg.answer.assert_awaited_once()

    async def test_empty_code(self):
        msg = _make_message("   ")
        state = _make_state()
        with patch("services.bot.handlers.admin.promo._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.promo._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.promo import promo_code
            await promo_code(msg, state)
        msg.answer.assert_awaited_once()

    async def test_denied(self):
        msg = _make_message("CODE", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.promo._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.promo._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.promo import promo_code
            await promo_code(msg, state)
        denied_mock.assert_awaited_once()
        state.clear.assert_awaited()


class TestPromoCredits:
    async def test_allowed_valid(self):
        msg = _make_message("100")
        state = _make_state()
        with patch("services.bot.handlers.admin.promo._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.promo._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.promo import promo_credits
            await promo_credits(msg, state)
        state.update_data.assert_awaited()
        state.set_state.assert_awaited()

    async def test_invalid_credits(self):
        msg = _make_message("notanumber")
        state = _make_state()
        with patch("services.bot.handlers.admin.promo._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.promo._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.promo import promo_credits
            await promo_credits(msg, state)
        msg.answer.assert_awaited_once()

    async def test_zero_credits(self):
        msg = _make_message("0")
        state = _make_state()
        with patch("services.bot.handlers.admin.promo._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.promo._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.promo import promo_credits
            await promo_credits(msg, state)
        msg.answer.assert_awaited_once()

    async def test_denied(self):
        msg = _make_message("100", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.promo._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.promo._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.promo import promo_credits
            await promo_credits(msg, state)
        denied_mock.assert_awaited_once()
        state.clear.assert_awaited()


class TestPromoMaxUses:
    async def test_allowed_valid(self):
        msg = _make_message("50")
        state = _make_state()
        state.get_data = AsyncMock(return_value={"promo_code": "CODE", "promo_credits": 100})
        pool, conn = _make_pool()
        with patch("services.bot.handlers.admin.promo._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.promo._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.promo.get_pool", return_value=pool):
            from services.bot.handlers.admin.promo import promo_max_uses
            await promo_max_uses(msg, state)
        conn.execute.assert_awaited()
        msg.answer.assert_awaited_once()
        state.clear.assert_awaited()

    async def test_invalid_max_uses(self):
        msg = _make_message("bad")
        state = _make_state()
        with patch("services.bot.handlers.admin.promo._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.promo._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.promo import promo_max_uses
            await promo_max_uses(msg, state)
        msg.answer.assert_awaited_once()

    async def test_zero_max_uses(self):
        msg = _make_message("0")
        state = _make_state()
        with patch("services.bot.handlers.admin.promo._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.promo._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.promo import promo_max_uses
            await promo_max_uses(msg, state)
        msg.answer.assert_awaited_once()

    async def test_denied(self):
        msg = _make_message("10", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.promo._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.promo._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.promo import promo_max_uses
            await promo_max_uses(msg, state)
        denied_mock.assert_awaited_once()
        state.clear.assert_awaited()


# ===========================================================================
# admin/system.py
# ===========================================================================

class TestCbAdminSystem:
    async def test_allowed(self):
        cb = _make_callback("admin:system")
        pool, conn = _make_pool()
        conn.fetchval = AsyncMock(return_value=1)
        conn.fetchrow = AsyncMock(return_value=None)
        with patch("services.bot.handlers.admin.system._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.system._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.system.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.system._redis_ok", return_value=True), \
             patch("services.bot.handlers.admin.system.system_kb", return_value=MagicMock()):
            from services.bot.handlers.admin.system import cb_admin_system
            await cb_admin_system(cb)
        cb.answer.assert_awaited_once()
        cb.message.answer.assert_awaited_once()

    async def test_allowed_redis_down(self):
        cb = _make_callback("admin:system")
        pool, conn = _make_pool()
        conn.fetchval = AsyncMock(return_value=1)
        conn.fetchrow = AsyncMock(return_value=None)
        with patch("services.bot.handlers.admin.system._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.system._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.system.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.system._redis_ok", return_value=False), \
             patch("services.bot.handlers.admin.system.system_kb", return_value=MagicMock()):
            from services.bot.handlers.admin.system import cb_admin_system
            await cb_admin_system(cb)
        cb.message.answer.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:system", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.system._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.system._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.system import cb_admin_system
            await cb_admin_system(cb)
        denied_mock.assert_awaited_once()


class TestCbClearCache:
    async def test_allowed(self):
        cb = _make_callback("admin:sys:clear_cache")
        with patch("services.bot.handlers.admin.system._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.system._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.system import cb_clear_cache
            await cb_clear_cache(cb)
        cb.answer.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:sys:clear_cache", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.system._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.system._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.system import cb_clear_cache
            await cb_clear_cache(cb)
        denied_mock.assert_awaited_once()


class TestCbDownloadLog:
    async def test_allowed(self):
        cb = _make_callback("admin:sys:download_log")
        cb.message.answer_document = AsyncMock()
        pool, conn = _make_pool()
        fake_row = {
            "admin_id": ADMIN_ID,
            "action": "ban_user",
            "details": "{}",
            "created_at": MagicMock(strftime=lambda f: "2024-01-01 12:00"),
        }
        conn.fetch = AsyncMock(return_value=[fake_row])
        with patch("services.bot.handlers.admin.system._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.system._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.system.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.system.admin_back_kb", return_value=MagicMock()):
            from services.bot.handlers.admin.system import cb_download_log
            await cb_download_log(cb)
        cb.message.answer_document.assert_awaited_once()

    async def test_allowed_empty_log(self):
        cb = _make_callback("admin:sys:download_log")
        cb.message.answer_document = AsyncMock()
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])
        with patch("services.bot.handlers.admin.system._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.system._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.system.get_pool", return_value=pool), \
             patch("services.bot.handlers.admin.system.admin_back_kb", return_value=MagicMock()):
            from services.bot.handlers.admin.system import cb_download_log
            await cb_download_log(cb)
        cb.message.answer_document.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:sys:download_log", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.system._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.system._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.system import cb_download_log
            await cb_download_log(cb)
        denied_mock.assert_awaited_once()


# ===========================================================================
# admin/subscriptions.py
# ===========================================================================

class TestCbAdminSubs:
    async def test_allowed(self):
        cb = _make_callback("admin:subs")
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])
        with patch("services.bot.handlers.admin.subscriptions._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.subscriptions._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.subscriptions.get_pool", return_value=pool):
            from services.bot.handlers.admin.subscriptions import cb_admin_subs
            await cb_admin_subs(cb)
        cb.answer.assert_awaited_once()
        cb.message.answer.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:subs", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.subscriptions._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.subscriptions._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.subscriptions import cb_admin_subs
            await cb_admin_subs(cb)
        denied_mock.assert_awaited_once()


class TestCbUnlimitedByUsername:
    async def test_allowed(self):
        cb = _make_callback("admin:unlimited_by_username")
        state = _make_state()
        with patch("services.bot.handlers.admin.subscriptions._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.subscriptions._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.subscriptions import cb_unlimited_by_username
            await cb_unlimited_by_username(cb, state)
        state.set_state.assert_awaited_once()
        cb.message.answer.assert_awaited_once()

    async def test_denied(self):
        cb = _make_callback("admin:unlimited_by_username", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.subscriptions._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.subscriptions._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.subscriptions import cb_unlimited_by_username
            await cb_unlimited_by_username(cb, state)
        denied_mock.assert_awaited_once()


class TestMsgUnlimitedUsername:
    async def test_allowed_user_not_found(self):
        msg = _make_message("vasya")
        state = _make_state()
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)
        with patch("services.bot.handlers.admin.subscriptions._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.subscriptions._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.subscriptions.get_pool", return_value=pool):
            from services.bot.handlers.admin.subscriptions import msg_unlimited_username
            await msg_unlimited_username(msg, state)
        msg.answer.assert_awaited_once()
        state.clear.assert_awaited()

    async def test_allowed_user_found(self):
        msg = _make_message("vasya")
        state = _make_state()
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={
            "id": 42, "username": "vasya", "unlimited_ends_at": None
        })
        with patch("services.bot.handlers.admin.subscriptions._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.subscriptions._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.subscriptions.get_pool", return_value=pool), \
             patch("shared.domain.credits.get_unlimited_ends_at", new=AsyncMock(return_value=None)):
            from services.bot.handlers.admin.subscriptions import msg_unlimited_username
            await msg_unlimited_username(msg, state)
        msg.answer.assert_awaited_once()

    async def test_empty_username(self):
        msg = _make_message("   ")
        state = _make_state()
        with patch("services.bot.handlers.admin.subscriptions._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.subscriptions._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.subscriptions import msg_unlimited_username
            await msg_unlimited_username(msg, state)
        msg.answer.assert_awaited_once()

    async def test_denied(self):
        msg = _make_message("vasya", user_id=NON_ADMIN_ID)
        state = _make_state()
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.subscriptions._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.subscriptions._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.subscriptions import msg_unlimited_username
            await msg_unlimited_username(msg, state)
        denied_mock.assert_awaited_once()
        state.clear.assert_awaited()


class TestCbUserUnlimited:
    async def test_allowed(self):
        cb = _make_callback("admin:user:unlimited:42")
        with patch("services.bot.handlers.admin.subscriptions._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.subscriptions._admin_denied", new=AsyncMock()), \
             patch("shared.domain.credits.get_unlimited_ends_at", new=AsyncMock(return_value=None)):
            from services.bot.handlers.admin.subscriptions import cb_user_unlimited
            await cb_user_unlimited(cb)
        cb.answer.assert_awaited_once()
        cb.message.answer.assert_awaited_once()

    async def test_invalid_uid(self):
        cb = _make_callback("admin:user:unlimited:notanumber")
        with patch("services.bot.handlers.admin.subscriptions._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.subscriptions._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.subscriptions import cb_user_unlimited
            await cb_user_unlimited(cb)
        cb.answer.assert_not_awaited()

    async def test_denied(self):
        cb = _make_callback("admin:user:unlimited:42", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.subscriptions._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.subscriptions._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.subscriptions import cb_user_unlimited
            await cb_user_unlimited(cb)
        denied_mock.assert_awaited_once()


class TestCbSetUnlimited:
    async def test_allowed_set_days(self):
        cb = _make_callback("admin:user:setunl:42:30")
        with patch("services.bot.handlers.admin.subscriptions._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.subscriptions._admin_denied", new=AsyncMock()), \
             patch("shared.domain.credits.set_unlimited_until", new=AsyncMock()), \
             patch("shared.domain.credits.get_unlimited_ends_at", new=AsyncMock(return_value=None)), \
             patch("shared.domain.admin_log.log_admin", new=AsyncMock()):
            from services.bot.handlers.admin.subscriptions import cb_set_unlimited
            await cb_set_unlimited(cb)
        cb.answer.assert_awaited_once()
        cb.message.answer.assert_awaited_once()

    async def test_allowed_remove_unlimited(self):
        cb = _make_callback("admin:user:setunl:42:0")
        pool, conn = _make_pool()
        with patch("services.bot.handlers.admin.subscriptions._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.subscriptions._admin_denied", new=AsyncMock()), \
             patch("services.bot.handlers.admin.subscriptions.get_pool", return_value=pool), \
             patch("shared.domain.credits._balance_cache_invalidate", new=AsyncMock()), \
             patch("shared.domain.admin_log.log_admin", new=AsyncMock()):
            from services.bot.handlers.admin.subscriptions import cb_set_unlimited
            await cb_set_unlimited(cb)
        conn.execute.assert_awaited()
        cb.message.answer.assert_awaited_once()

    async def test_invalid_parts(self):
        cb = _make_callback("admin:user:setunl:bad:parts")
        with patch("services.bot.handlers.admin.subscriptions._is_admin", return_value=True), \
             patch("services.bot.handlers.admin.subscriptions._admin_denied", new=AsyncMock()):
            from services.bot.handlers.admin.subscriptions import cb_set_unlimited
            await cb_set_unlimited(cb)
        cb.answer.assert_not_awaited()

    async def test_denied(self):
        cb = _make_callback("admin:user:setunl:42:30", user_id=NON_ADMIN_ID)
        denied_mock = AsyncMock()
        with patch("services.bot.handlers.admin.subscriptions._is_admin", return_value=False), \
             patch("services.bot.handlers.admin.subscriptions._admin_denied", new=denied_mock):
            from services.bot.handlers.admin.subscriptions import cb_set_unlimited
            await cb_set_unlimited(cb)
        denied_mock.assert_awaited_once()
