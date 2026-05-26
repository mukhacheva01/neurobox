"""Tests for services/bot/handlers/start.py and services/bot/handlers/balance.py"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import types


# ── Helper factories ──────────────────────────────────────────────────────────

def _make_user(user_id=111, username="user", first_name="Test"):
    u = MagicMock()
    u.id = user_id
    u.username = username
    u.first_name = first_name
    return u


def _make_message(text="hi", user_id=111):
    msg = AsyncMock(spec=types.Message)
    msg.from_user = _make_user(user_id)
    msg.text = text
    msg.answer = AsyncMock()
    msg.chat = MagicMock()
    msg.chat.id = user_id
    msg.answer_document = AsyncMock()
    msg.answer_photo = AsyncMock()
    msg.answer_invoice = AsyncMock()
    msg.successful_payment = None
    return msg


def _make_cb(data="test", user_id=111):
    cb = AsyncMock(spec=types.CallbackQuery)
    cb.from_user = _make_user(user_id)
    cb.data = data
    cb.answer = AsyncMock()
    cb.message = _make_message(user_id=user_id)
    return cb


def _make_state():
    st = AsyncMock()
    st.clear = AsyncMock()
    st.set_state = AsyncMock()
    st.update_data = AsyncMock()
    st.get_state = AsyncMock(return_value=None)
    st.get_data = AsyncMock(return_value={})
    return st


def _fake_pool(fetchrow=None, fetchval=None, fetch=None):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow)
    conn.fetchval = AsyncMock(return_value=fetchval)
    conn.fetch = AsyncMock(return_value=fetch or [])
    conn.execute = AsyncMock()
    pool = AsyncMock()
    pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False),
        )
    )
    return pool, conn


# Common patch targets for start.py
_START = "services.bot.handlers.start"
_BALANCE = "services.bot.handlers.balance"


def _start_patches(extra=None):
    """Return a dict of default patches for start.py module-level imports."""
    defaults = {
        f"{_START}.get_balance": AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
        f"{_START}.get_trial_status": AsyncMock(return_value={"is_active": False, "can_activate": True, "expires_at": None}),
        f"{_START}.get_or_create_user": AsyncMock(return_value={"id": 111, "created_at": None, "is_blocked": False, "credits_total_spent": 0, "credits_bought": 0}),
        f"{_START}.get_main_menu_kb": MagicMock(return_value=MagicMock()),
        f"{_START}.back_to_main_kb": MagicMock(return_value=MagicMock()),
        f"{_START}.persistent_menu_kb": MagicMock(return_value=MagicMock()),
        f"{_START}.get_admin_text": AsyncMock(return_value="Welcome {first_name} you have {free} CR"),
        f"{_START}.save_user_acquisition": AsyncMock(return_value=None),
        f"{_START}.get_onboarded": AsyncMock(return_value=True),
        f"{_START}.set_onboarded": AsyncMock(return_value=None),
        f"{_START}.start_trial": AsyncMock(return_value=True),
        f"{_START}.try_grant_daily_login_bonus": AsyncMock(return_value=None),
        f"{_START}.settings": MagicMock(
            admin_id_list=[999],
            admin_ids="",
            enable_full_access_48h=False,
            enable_video=True,
            enable_tts=False,
            enable_music=False,
            free_daily_credits=20,
            bot_username="neurobox_bot",
            legal_base_url="https://example.com",
        ),
    }
    if extra:
        defaults.update(extra)
    return defaults


def _balance_patches(extra=None):
    """Return a dict of default patches for balance.py module-level imports."""
    defaults = {
        f"{_BALANCE}.get_balance": AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
        f"{_BALANCE}.get_or_create_user": AsyncMock(return_value={"id": 111}),
        f"{_BALANCE}.get_unlimited_ends_at": AsyncMock(return_value=None),
        f"{_BALANCE}.get_credit_packs": AsyncMock(return_value={}),
        f"{_BALANCE}.get_credit_pack": AsyncMock(return_value={
            "id": "basic", "price_rub": 99, "credits": 100, "label": "Basic",
            "price_stars": 10, "price_usd": 2, "discount": None,
        }),
        f"{_BALANCE}.create_payment_record": AsyncMock(return_value="pay123"),
        f"{_BALANCE}.confirm_payment_record": AsyncMock(return_value={"pack_name": "basic", "credits_amount": 100, "amount_rub": 99}),
        f"{_BALANCE}.add_credits": AsyncMock(return_value=None),
        f"{_BALANCE}.set_unlimited_until": AsyncMock(return_value=None),
        f"{_BALANCE}.settings": MagicMock(
            enable_yookassa_payment=False,
            yookassa_shop_id="",
            yookassa_secret_key="",
            enable_cryptobot_payment=False,
            cryptobot_api_token="",
            enable_stars_payment=True,
            enable_test_payments=True,
            enable_video=True,
            enable_tts=False,
            enable_music=False,
            free_daily_credits=20,
        ),
        f"{_BALANCE}.CREDIT_PRICES": {"gpt-4o-mini": 1, "dall-e-3": 5, "musicgen": 15, "suno-v4": 50},
        f"{_BALANCE}.FREE_MODELS": set(),
        f"{_BALANCE}.UNLIMITED_DAYS": 30,
        f"{_BALANCE}.VIDEO_MODELS": {},
        f"{_BALANCE}.IMAGE_MODELS": [("DALL-E 3", "dall-e-3", "5 CR", False)],
    }
    if extra:
        defaults.update(extra)
    return defaults


# ═══════════════════════════════════════════════════════════════════════════════
# start.py tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsAdmin:
    def test_is_admin_in_list(self):
        from services.bot.handlers.start import _is_admin
        with patch(f"{_START}.settings") as s:
            s.admin_id_list = [111, 222]
            s.admin_ids = ""
            assert _is_admin(111) is True

    def test_is_admin_not_in_list(self):
        from services.bot.handlers.start import _is_admin
        with patch(f"{_START}.settings") as s:
            s.admin_id_list = [999]
            s.admin_ids = ""
            assert _is_admin(111) is False

    def test_is_admin_from_csv(self):
        from services.bot.handlers.start import _is_admin
        with patch(f"{_START}.settings") as s:
            s.admin_id_list = []
            s.admin_ids = "111,222"
            assert _is_admin(111) is True

    def test_is_admin_csv_not_found(self):
        from services.bot.handlers.start import _is_admin
        with patch(f"{_START}.settings") as s:
            s.admin_id_list = []
            s.admin_ids = "999,888"
            assert _is_admin(111) is False

    def test_is_admin_invalid_csv(self):
        from services.bot.handlers.start import _is_admin
        with patch(f"{_START}.settings") as s:
            s.admin_id_list = []
            s.admin_ids = "bad,data"
            assert _is_admin(111) is False


class TestAdminDenied:
    async def test_admin_denied_callback(self):
        from services.bot.handlers.start import _admin_denied
        cb = _make_cb()
        await _admin_denied(cb)
        cb.answer.assert_called_once()

    async def test_admin_denied_message(self):
        from services.bot.handlers.start import _admin_denied
        msg = _make_message()
        await _admin_denied(msg, context="test")
        # No answer call for message (not a CallbackQuery)
        msg.answer.assert_not_called()

    async def test_admin_denied_callback_exception(self):
        from services.bot.handlers.start import _admin_denied
        cb = _make_cb()
        cb.answer = AsyncMock(side_effect=Exception("boom"))
        # Should not raise
        await _admin_denied(cb)


class TestRefCodeFromStart:
    def test_ref_code_present(self):
        from services.bot.handlers.start import _ref_code_from_start
        assert _ref_code_from_start("/start ref_ABC123") == "ABC123"

    def test_ref_code_absent(self):
        from services.bot.handlers.start import _ref_code_from_start
        assert _ref_code_from_start("/start") is None

    def test_ref_code_empty(self):
        from services.bot.handlers.start import _ref_code_from_start
        assert _ref_code_from_start("") is None

    def test_ref_code_no_ref_prefix(self):
        from services.bot.handlers.start import _ref_code_from_start
        assert _ref_code_from_start("/start hello") is None


class TestSendOnboardingIfNew:
    async def test_new_user_sends_welcome(self):
        from services.bot.handlers.start import _send_onboarding_if_new
        msg = _make_message()
        user = {"created_at": datetime.now(timezone.utc) - timedelta(seconds=30)}
        with patch(f"{_START}.get_admin_text", AsyncMock(return_value="Hi {first_name} {free}")):
            with patch(f"{_START}.settings") as s:
                s.free_daily_credits = 20
                await _send_onboarding_if_new(msg, user)
        msg.answer.assert_called()

    async def test_old_user_no_welcome(self):
        from services.bot.handlers.start import _send_onboarding_if_new
        msg = _make_message()
        user = {"created_at": datetime.now(timezone.utc) - timedelta(hours=1)}
        await _send_onboarding_if_new(msg, user)
        msg.answer.assert_not_called()

    async def test_missing_created_at(self):
        from services.bot.handlers.start import _send_onboarding_if_new
        msg = _make_message()
        user = {"created_at": None}
        await _send_onboarding_if_new(msg, user)
        msg.answer.assert_not_called()

    async def test_naive_datetime_user(self):
        from services.bot.handlers.start import _send_onboarding_if_new
        msg = _make_message()
        # naive datetime (no tzinfo) — should be treated as UTC
        naive_dt = datetime.utcnow() - timedelta(seconds=10)
        user = {"created_at": naive_dt}
        with patch(f"{_START}.get_admin_text", AsyncMock(return_value="Hi {first_name} {free}")):
            with patch(f"{_START}.settings") as s:
                s.free_daily_credits = 20
                await _send_onboarding_if_new(msg, user)
        msg.answer.assert_called()


class TestMainMenuTextAndKb:
    async def test_trial_can_activate(self):
        from services.bot.handlers.start import _main_menu_text_and_kb
        with patch(f"{_START}.get_balance", AsyncMock(return_value={"total": 100, "free": 10, "bought": 90})):
            with patch(f"{_START}.get_trial_status", AsyncMock(return_value={"is_active": False, "can_activate": True, "expires_at": None})):
                with patch(f"{_START}.get_main_menu_kb", MagicMock(return_value=MagicMock())) as mkb:
                    with patch(f"{_START}.settings") as s:
                        s.enable_full_access_48h = False
                        text, kb = await _main_menu_text_and_kb(111)
        assert "100" in text

    async def test_trial_active_with_expiry(self):
        from services.bot.handlers.start import _main_menu_text_and_kb
        exp = datetime.now(timezone.utc) + timedelta(minutes=30)
        with patch(f"{_START}.get_balance", AsyncMock(return_value={"total": 100, "free": 10, "bought": 90})):
            with patch(f"{_START}.get_trial_status", AsyncMock(return_value={"is_active": True, "can_activate": False, "expires_at": exp})):
                with patch(f"{_START}.get_main_menu_kb", MagicMock(return_value=MagicMock())):
                    with patch(f"{_START}.settings") as s:
                        s.enable_full_access_48h = False
                        text, kb = await _main_menu_text_and_kb(111)
        assert "Безлимит" in text

    async def test_trial_active_expired(self):
        from services.bot.handlers.start import _main_menu_text_and_kb
        exp = datetime.now(timezone.utc) - timedelta(minutes=5)
        with patch(f"{_START}.get_balance", AsyncMock(return_value={"total": 50, "free": 10, "bought": 40})):
            with patch(f"{_START}.get_trial_status", AsyncMock(return_value={"is_active": True, "can_activate": False, "expires_at": exp})):
                with patch(f"{_START}.get_main_menu_kb", MagicMock(return_value=MagicMock())):
                    with patch(f"{_START}.settings") as s:
                        s.enable_full_access_48h = False
                        text, kb = await _main_menu_text_and_kb(111)
        assert "0 мин" in text

    async def test_trial_active_naive_expiry(self):
        from services.bot.handlers.start import _main_menu_text_and_kb
        exp = datetime.utcnow() + timedelta(minutes=10)  # naive
        with patch(f"{_START}.get_balance", AsyncMock(return_value={"total": 50, "free": 10, "bought": 40})):
            with patch(f"{_START}.get_trial_status", AsyncMock(return_value={"is_active": True, "can_activate": False, "expires_at": exp})):
                with patch(f"{_START}.get_main_menu_kb", MagicMock(return_value=MagicMock())):
                    with patch(f"{_START}.settings") as s:
                        s.enable_full_access_48h = False
                        text, kb = await _main_menu_text_and_kb(111)
        assert "мин" in text

    async def test_no_trial(self):
        from services.bot.handlers.start import _main_menu_text_and_kb
        with patch(f"{_START}.get_balance", AsyncMock(return_value={"total": 100, "free": 10, "bought": 90})):
            with patch(f"{_START}.get_trial_status", AsyncMock(return_value={"is_active": False, "can_activate": False, "expires_at": None})):
                with patch(f"{_START}.get_main_menu_kb", MagicMock(return_value=MagicMock())):
                    with patch(f"{_START}.settings") as s:
                        s.enable_full_access_48h = False
                        text, kb = await _main_menu_text_and_kb(111)
        assert "100" in text

    async def test_with_48h_feature(self):
        from services.bot.handlers.start import _main_menu_text_and_kb
        with patch(f"{_START}.get_balance", AsyncMock(return_value={"total": 100, "free": 10, "bought": 90})):
            with patch(f"{_START}.get_trial_status", AsyncMock(return_value={"is_active": False, "can_activate": False, "expires_at": None})):
                with patch(f"{_START}.get_main_menu_kb", MagicMock(return_value=MagicMock())):
                    with patch(f"{_START}.settings") as s:
                        s.enable_full_access_48h = True
                        with patch("shared.domain.credits.get_48h_status", AsyncMock(return_value={"can_activate": True})):
                            text, kb = await _main_menu_text_and_kb(111)
        assert "100" in text


class TestCmdCancel:
    async def test_cmd_cancel_clears_state(self):
        from services.bot.handlers.start import cmd_cancel
        msg = _make_message()
        state = _make_state()
        with patch(f"{_START}.get_balance", AsyncMock(return_value={"total": 100, "free": 10, "bought": 90})):
            with patch(f"{_START}.get_trial_status", AsyncMock(return_value={"is_active": False, "can_activate": False, "expires_at": None})):
                with patch(f"{_START}.get_main_menu_kb", MagicMock(return_value=MagicMock())):
                    with patch(f"{_START}.settings") as s:
                        s.enable_full_access_48h = False
                        await cmd_cancel(msg, state)
        state.clear.assert_called_once()
        msg.answer.assert_called()


class TestCmdStart:
    async def test_cmd_start_basic(self):
        from services.bot.handlers.start import cmd_start
        msg = _make_message(text="/start")
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111, "created_at": None, "credits_total_spent": 0, "credits_bought": 0}),
            save_user_acquisition=AsyncMock(return_value=None),
            get_onboarded=AsyncMock(return_value=True),
            set_onboarded=AsyncMock(),
            try_grant_daily_login_bonus=AsyncMock(return_value=None),
            get_balance=AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
            get_trial_status=AsyncMock(return_value={"is_active": False, "can_activate": True, "expires_at": None}),
            get_main_menu_kb=MagicMock(return_value=MagicMock()),
            persistent_menu_kb=MagicMock(return_value=MagicMock()),
            settings=MagicMock(enable_full_access_48h=False, free_daily_credits=20, bot_username="nb_bot"),
        ):
            await cmd_start(msg)
        msg.answer.assert_called()

    async def test_cmd_start_with_bonus_dict(self):
        from services.bot.handlers.start import cmd_start
        msg = _make_message(text="/start")
        bonus = {"amount": 10, "streak": 3, "streak_bonus": 2}
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111, "created_at": None, "credits_total_spent": 0, "credits_bought": 0}),
            save_user_acquisition=AsyncMock(return_value=None),
            get_onboarded=AsyncMock(return_value=True),
            set_onboarded=AsyncMock(),
            try_grant_daily_login_bonus=AsyncMock(return_value=bonus),
            get_balance=AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
            get_trial_status=AsyncMock(return_value={"is_active": False, "can_activate": True, "expires_at": None}),
            get_main_menu_kb=MagicMock(return_value=MagicMock()),
            persistent_menu_kb=MagicMock(return_value=MagicMock()),
            settings=MagicMock(enable_full_access_48h=False, free_daily_credits=20, bot_username="nb_bot"),
        ):
            await cmd_start(msg)
        assert msg.answer.call_count >= 2

    async def test_cmd_start_with_truthy_bonus(self):
        from services.bot.handlers.start import cmd_start
        msg = _make_message(text="/start")
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111, "created_at": None, "credits_total_spent": 0, "credits_bought": 0}),
            save_user_acquisition=AsyncMock(return_value=None),
            get_onboarded=AsyncMock(return_value=True),
            set_onboarded=AsyncMock(),
            try_grant_daily_login_bonus=AsyncMock(return_value=True),  # truthy but not dict
            get_balance=AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
            get_trial_status=AsyncMock(return_value={"is_active": False, "can_activate": True, "expires_at": None}),
            get_main_menu_kb=MagicMock(return_value=MagicMock()),
            persistent_menu_kb=MagicMock(return_value=MagicMock()),
            settings=MagicMock(enable_full_access_48h=False, free_daily_credits=20, bot_username="nb_bot"),
        ):
            await cmd_start(msg)
        assert msg.answer.call_count >= 2

    async def test_cmd_start_new_user_quickstart(self):
        from services.bot.handlers.start import cmd_start
        msg = _make_message(text="/start")
        new_user = {"id": 111, "created_at": datetime.now(timezone.utc) - timedelta(seconds=10), "credits_total_spent": 0, "credits_bought": 0}
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value=new_user),
            save_user_acquisition=AsyncMock(return_value=None),
            get_onboarded=AsyncMock(return_value=False),
            set_onboarded=AsyncMock(),
            try_grant_daily_login_bonus=AsyncMock(return_value=None),
            get_balance=AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
            get_trial_status=AsyncMock(return_value={"is_active": False, "can_activate": True, "expires_at": None}),
            get_main_menu_kb=MagicMock(return_value=MagicMock()),
            persistent_menu_kb=MagicMock(return_value=MagicMock()),
            get_admin_text=AsyncMock(return_value="Hi {first_name} {free}"),
            settings=MagicMock(enable_full_access_48h=False, free_daily_credits=20, bot_username="nb_bot"),
        ):
            await cmd_start(msg)
        msg.answer.assert_called()

    async def test_cmd_start_with_ref_code(self):
        from services.bot.handlers.start import cmd_start
        msg = _make_message(text="/start ref_TESTCODE")
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111, "created_at": None, "credits_total_spent": 0, "credits_bought": 0}),
            save_user_acquisition=AsyncMock(return_value=None),
            get_onboarded=AsyncMock(return_value=True),
            set_onboarded=AsyncMock(),
            try_grant_daily_login_bonus=AsyncMock(return_value=None),
            get_balance=AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
            get_trial_status=AsyncMock(return_value={"is_active": False, "can_activate": False, "expires_at": None}),
            get_main_menu_kb=MagicMock(return_value=MagicMock()),
            persistent_menu_kb=MagicMock(return_value=MagicMock()),
            settings=MagicMock(enable_full_access_48h=False, free_daily_credits=20, bot_username="nb_bot"),
        ):
            await cmd_start(msg)
        msg.answer.assert_called()


class TestBtnMainMenu:
    async def test_btn_main_menu(self):
        from services.bot.handlers.start import btn_main_menu
        msg = _make_message()
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111}),
            try_grant_daily_login_bonus=AsyncMock(return_value=None),
            get_balance=AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
            get_trial_status=AsyncMock(return_value={"is_active": False, "can_activate": True, "expires_at": None}),
            get_main_menu_kb=MagicMock(return_value=MagicMock()),
            persistent_menu_kb=MagicMock(return_value=MagicMock()),
            settings=MagicMock(enable_full_access_48h=False),
        ):
            await btn_main_menu(msg)
        msg.answer.assert_called()


class TestCmdRestart:
    async def test_cmd_restart(self):
        from services.bot.handlers.start import cmd_restart
        msg = _make_message()
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111}),
            try_grant_daily_login_bonus=AsyncMock(return_value=None),
            get_balance=AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
            get_trial_status=AsyncMock(return_value={"is_active": False, "can_activate": True, "expires_at": None}),
            get_main_menu_kb=MagicMock(return_value=MagicMock()),
            persistent_menu_kb=MagicMock(return_value=MagicMock()),
            settings=MagicMock(enable_full_access_48h=False),
        ):
            await cmd_restart(msg)
        msg.answer.assert_called()


class TestCbMainMenu:
    async def test_cb_main_menu(self):
        from services.bot.handlers.start import cb_main_menu
        cb = _make_cb(data="main_menu")
        with patch.multiple(
            _START,
            get_balance=AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
            get_trial_status=AsyncMock(return_value={"is_active": False, "can_activate": True, "expires_at": None}),
            get_main_menu_kb=MagicMock(return_value=MagicMock()),
            persistent_menu_kb=MagicMock(return_value=MagicMock()),
            settings=MagicMock(enable_full_access_48h=False),
        ):
            await cb_main_menu(cb)
        cb.answer.assert_called()
        cb.message.answer.assert_called()


class TestOnboardingCallbacks:
    async def test_cb_onboarding_step_1(self):
        from services.bot.handlers.start import cb_onboarding_step_1
        cb = _make_cb(data="onboarding_step_1")
        await cb_onboarding_step_1(cb)
        cb.answer.assert_called()
        cb.message.answer.assert_called()

    async def test_cb_onboarding_step_2(self):
        from services.bot.handlers.start import cb_onboarding_step_2
        cb = _make_cb(data="onboarding_step_2")
        await cb_onboarding_step_2(cb)
        cb.answer.assert_called()
        cb.message.answer.assert_called()

    async def test_cb_onboarding_step_3(self):
        from services.bot.handlers.start import cb_onboarding_step_3
        cb = _make_cb(data="onboarding_step_3")
        with patch(f"{_START}.settings") as s:
            s.free_daily_credits = 20
            await cb_onboarding_step_3(cb)
        cb.answer.assert_called()
        cb.message.answer.assert_called()

    async def test_cb_onboarding_done(self):
        from services.bot.handlers.start import cb_onboarding_done
        cb = _make_cb(data="onboarding_done")
        with patch.multiple(
            _START,
            set_onboarded=AsyncMock(),
            get_balance=AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
            get_trial_status=AsyncMock(return_value={"is_active": False, "can_activate": True, "expires_at": None}),
            get_main_menu_kb=MagicMock(return_value=MagicMock()),
            persistent_menu_kb=MagicMock(return_value=MagicMock()),
            settings=MagicMock(enable_full_access_48h=False),
        ):
            await cb_onboarding_done(cb)
        cb.answer.assert_called()
        cb.message.answer.assert_called()


class TestTrialActivate:
    async def test_cb_trial_activate_success(self):
        from services.bot.handlers.start import cb_trial_activate
        cb = _make_cb(data="trial_activate")
        with patch.multiple(
            _START,
            start_trial=AsyncMock(return_value=True),
            get_balance=AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
            get_trial_status=AsyncMock(return_value={"is_active": True, "can_activate": False, "expires_at": None}),
            get_main_menu_kb=MagicMock(return_value=MagicMock()),
            persistent_menu_kb=MagicMock(return_value=MagicMock()),
            settings=MagicMock(enable_full_access_48h=False),
        ):
            with patch("shared.domain.credits.TRIAL_DURATION_MINUTES", 45):
                await cb_trial_activate(cb)
        cb.answer.assert_called()
        cb.message.answer.assert_called()

    async def test_cb_trial_activate_already_used(self):
        from services.bot.handlers.start import cb_trial_activate
        cb = _make_cb(data="trial_activate")
        with patch(f"{_START}.start_trial", AsyncMock(return_value=False)):
            await cb_trial_activate(cb)
        cb.answer.assert_called()

    async def test_btn_trial_activate_success(self):
        from services.bot.handlers.start import btn_trial_activate
        msg = _make_message()
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111}),
            start_trial=AsyncMock(return_value=True),
            get_balance=AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
            get_trial_status=AsyncMock(return_value={"is_active": True, "can_activate": False, "expires_at": None}),
            get_main_menu_kb=MagicMock(return_value=MagicMock()),
            persistent_menu_kb=MagicMock(return_value=MagicMock()),
            settings=MagicMock(enable_full_access_48h=False),
        ):
            with patch("shared.domain.credits.TRIAL_DURATION_MINUTES", 45):
                await btn_trial_activate(msg)
        msg.answer.assert_called()

    async def test_btn_trial_activate_fail(self):
        from services.bot.handlers.start import btn_trial_activate
        msg = _make_message()
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111}),
            start_trial=AsyncMock(return_value=False),
            settings=MagicMock(enable_full_access_48h=False),
        ):
            await btn_trial_activate(msg)
        msg.answer.assert_called()


class TestFullAccess48h:
    async def test_cb_full_access_48h_disabled(self):
        from services.bot.handlers.start import cb_full_access_48h
        cb = _make_cb()
        with patch(f"{_START}.settings") as s:
            s.enable_full_access_48h = False
            await cb_full_access_48h(cb)
        cb.answer.assert_called()

    async def test_cb_full_access_48h_activated_now(self):
        from services.bot.handlers.start import cb_full_access_48h
        cb = _make_cb()
        end_dt = datetime.now(timezone.utc) + timedelta(hours=48)
        with patch(f"{_START}.settings") as s:
            s.enable_full_access_48h = True
            with patch("shared.domain.credits.activate_48h_full_access", AsyncMock(return_value=True)):
                with patch("shared.domain.credits.get_48h_status", AsyncMock(return_value={"is_active": True, "can_activate": False, "ends_at": end_dt})):
                    with patch("shared.domain.credits.FULL_ACCESS_48H_HOURS", 48):
                        with patch.multiple(
                            _START,
                            get_balance=AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
                            get_trial_status=AsyncMock(return_value={"is_active": False, "can_activate": False, "expires_at": None}),
                            get_main_menu_kb=MagicMock(return_value=MagicMock()),
                        ):
                            await cb_full_access_48h(cb)
        cb.message.answer.assert_called()

    async def test_cb_full_access_48h_already_activated(self):
        from services.bot.handlers.start import cb_full_access_48h
        cb = _make_cb()
        end_dt = datetime.now(timezone.utc) + timedelta(hours=24)
        with patch(f"{_START}.settings") as s:
            s.enable_full_access_48h = True
            with patch("shared.domain.credits.activate_48h_full_access", AsyncMock(return_value=False)):
                with patch("shared.domain.credits.get_48h_status", AsyncMock(return_value={"is_active": True, "can_activate": False, "ends_at": end_dt})):
                    with patch("shared.domain.credits.FULL_ACCESS_48H_HOURS", 48):
                        with patch.multiple(
                            _START,
                            get_balance=AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
                            get_trial_status=AsyncMock(return_value={"is_active": False, "can_activate": False, "expires_at": None}),
                            get_main_menu_kb=MagicMock(return_value=MagicMock()),
                        ):
                            await cb_full_access_48h(cb)
        cb.message.answer.assert_called()

    async def test_cb_full_access_48h_not_active(self):
        from services.bot.handlers.start import cb_full_access_48h
        cb = _make_cb()
        with patch(f"{_START}.settings") as s:
            s.enable_full_access_48h = True
            with patch("shared.domain.credits.activate_48h_full_access", AsyncMock(return_value=False)):
                with patch("shared.domain.credits.get_48h_status", AsyncMock(return_value={"is_active": False, "can_activate": False, "ends_at": None})):
                    with patch("shared.domain.credits.FULL_ACCESS_48H_HOURS", 48):
                        with patch.multiple(
                            _START,
                            get_balance=AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
                            get_trial_status=AsyncMock(return_value={"is_active": False, "can_activate": False, "expires_at": None}),
                            get_main_menu_kb=MagicMock(return_value=MagicMock()),
                        ):
                            await cb_full_access_48h(cb)
        cb.message.answer.assert_called()


class TestScreenText:
    async def test_btn_chat(self):
        from services.bot.handlers.start import btn_chat
        msg = _make_message()
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111}),
        ):
            with patch("shared.domain.credits.get_user_model", AsyncMock(return_value="gpt-4o-mini")):
                with patch("shared.domain.credits.CREDIT_PRICES", {"gpt-4o-mini": 1}):
                    with patch("services.bot.keyboards.main._short", return_value="GPT-4o"):
                        await btn_chat(msg)
        msg.answer.assert_called()

    async def test_cb_screen_text(self):
        from services.bot.handlers.start import cb_screen_text
        cb = _make_cb(data="screen_text")
        with patch("shared.domain.credits.get_user_model", AsyncMock(return_value="gpt-4o-mini")):
            with patch("shared.domain.credits.CREDIT_PRICES", {"gpt-4o-mini": 1}):
                with patch("services.bot.keyboards.main._short", return_value="GPT-4o"):
                    await cb_screen_text(cb)
        cb.answer.assert_called()
        cb.message.answer.assert_called()


class TestScreenImages:
    async def test_btn_images(self):
        from services.bot.handlers.start import btn_images
        msg = _make_message()
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111}),
        ):
            with patch("shared.domain.credits.get_user_model", AsyncMock(return_value="dall-e-3")):
                with patch("shared.domain.credits.CREDIT_PRICES", {"dall-e-3": 5}):
                    with patch("services.bot.keyboards.main._short", return_value="DALL-E"):
                        await btn_images(msg)
        msg.answer.assert_called()

    async def test_cb_screen_images(self):
        from services.bot.handlers.start import cb_screen_images
        cb = _make_cb(data="screen_images")
        with patch("shared.domain.credits.get_user_model", AsyncMock(return_value="dall-e-3")):
            with patch("shared.domain.credits.CREDIT_PRICES", {"dall-e-3": 5}):
                with patch("services.bot.keyboards.main._short", return_value="DALL-E"):
                    await cb_screen_images(cb)
        cb.message.answer.assert_called()


class TestScreenVideo:
    async def test_btn_video_disabled(self):
        from services.bot.handlers.start import btn_video
        msg = _make_message()
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111}),
            settings=MagicMock(enable_video=False),
        ):
            await btn_video(msg)
        msg.answer.assert_called()

    async def test_btn_video_enabled(self):
        from services.bot.handlers.start import btn_video
        msg = _make_message()
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111}),
            settings=MagicMock(enable_video=True),
        ):
            with patch("shared.domain.credits.get_user_model", AsyncMock(return_value="hailuo")):
                with patch("shared.domain.credits.CREDIT_PRICES", {"hailuo": 75}):
                    with patch("services.bot.keyboards.main._short", return_value="Hailuo"):
                        await btn_video(msg)
        msg.answer.assert_called()

    async def test_cb_screen_video_disabled(self):
        from services.bot.handlers.start import cb_screen_video
        cb = _make_cb(data="screen_video")
        with patch(f"{_START}.settings") as s:
            s.enable_video = False
            await cb_screen_video(cb)
        cb.message.answer.assert_called()

    async def test_cb_screen_video_enabled(self):
        from services.bot.handlers.start import cb_screen_video
        cb = _make_cb(data="screen_video")
        with patch(f"{_START}.settings") as s:
            s.enable_video = True
            with patch("shared.domain.credits.get_user_model", AsyncMock(return_value="hailuo")):
                with patch("shared.domain.credits.CREDIT_PRICES", {"hailuo": 75}):
                    with patch("services.bot.keyboards.main._short", return_value="Hailuo"):
                        await cb_screen_video(cb)
        cb.message.answer.assert_called()


class TestScreenVoice:
    async def test_btn_voice_tts_disabled(self):
        from services.bot.handlers.start import btn_voice
        msg = _make_message()
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111}),
            settings=MagicMock(enable_tts=False),
        ):
            await btn_voice(msg)
        msg.answer.assert_called()

    async def test_btn_voice_tts_enabled(self):
        from services.bot.handlers.start import btn_voice
        msg = _make_message()
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111}),
            settings=MagicMock(enable_tts=True),
        ):
            with patch("shared.domain.credits.get_user_model", AsyncMock(return_value="openai-tts")):
                with patch("shared.domain.credits.CREDIT_PRICES", {"openai-tts": 3}):
                    with patch("services.bot.keyboards.main._short", return_value="TTS"):
                        await btn_voice(msg)
        msg.answer.assert_called()

    async def test_cb_screen_voice_disabled(self):
        from services.bot.handlers.start import cb_screen_voice
        cb = _make_cb(data="screen_voice")
        with patch(f"{_START}.settings") as s:
            s.enable_tts = False
            await cb_screen_voice(cb)
        cb.message.answer.assert_called()

    async def test_cb_screen_voice_enabled(self):
        from services.bot.handlers.start import cb_screen_voice
        cb = _make_cb(data="screen_voice")
        with patch(f"{_START}.settings") as s:
            s.enable_tts = True
            with patch("shared.domain.credits.get_user_model", AsyncMock(return_value="openai-tts")):
                with patch("shared.domain.credits.CREDIT_PRICES", {"openai-tts": 3}):
                    with patch("services.bot.keyboards.main._short", return_value="TTS"):
                        await cb_screen_voice(cb)
        cb.message.answer.assert_called()


class TestScreenMusic:
    async def test_btn_music_disabled(self):
        from services.bot.handlers.start import btn_music
        msg = _make_message()
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111}),
            settings=MagicMock(enable_music=False),
        ):
            await btn_music(msg)
        msg.answer.assert_called()

    async def test_btn_music_enabled(self):
        from services.bot.handlers.start import btn_music
        msg = _make_message()
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111}),
            settings=MagicMock(enable_music=True),
        ):
            with patch("shared.domain.credits.get_user_model", AsyncMock(return_value="musicgen")):
                with patch("shared.domain.credits.CREDIT_PRICES", {"musicgen": 15}):
                    with patch("services.bot.keyboards.main._short", return_value="MusicGen"):
                        await btn_music(msg)
        msg.answer.assert_called()

    async def test_cb_screen_music_disabled(self):
        from services.bot.handlers.start import cb_screen_music
        cb = _make_cb(data="screen_music")
        with patch(f"{_START}.settings") as s:
            s.enable_music = False
            await cb_screen_music(cb)
        cb.message.answer.assert_called()

    async def test_cb_screen_music_enabled(self):
        from services.bot.handlers.start import cb_screen_music
        cb = _make_cb(data="screen_music")
        with patch(f"{_START}.settings") as s:
            s.enable_music = True
            with patch("shared.domain.credits.get_user_model", AsyncMock(return_value="musicgen")):
                with patch("shared.domain.credits.CREDIT_PRICES", {"musicgen": 15}):
                    with patch("services.bot.keyboards.main._short", return_value="MusicGen"):
                        await cb_screen_music(cb)
        cb.message.answer.assert_called()


class TestScreenPhoto:
    async def test_cb_screen_photo(self):
        from services.bot.handlers.start import cb_screen_photo
        cb = _make_cb(data="screen_photo")
        with patch("shared.domain.credits.get_user_model", AsyncMock(return_value="gpt-4o-mini")):
            with patch("services.bot.keyboards.main._short", return_value="GPT"):
                await cb_screen_photo(cb)
        cb.message.answer.assert_called()


class TestScreenDocs:
    async def test_btn_docs(self):
        from services.bot.handlers.start import btn_docs
        msg = _make_message()
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111}),
        ):
            with patch("shared.domain.credits.get_user_model", AsyncMock(return_value="gpt-4o-mini")):
                with patch("shared.domain.credits.CREDIT_PRICES", {"gpt-4o-mini": 1}):
                    with patch("services.bot.keyboards.main._short", return_value="GPT"):
                        await btn_docs(msg)
        msg.answer.assert_called()

    async def test_cb_screen_docs(self):
        from services.bot.handlers.start import cb_screen_docs
        cb = _make_cb(data="screen_docs")
        with patch("shared.domain.credits.get_user_model", AsyncMock(return_value="gpt-4o-mini")):
            with patch("shared.domain.credits.CREDIT_PRICES", {"gpt-4o-mini": 1}):
                with patch("services.bot.keyboards.main._short", return_value="GPT"):
                    await cb_screen_docs(cb)
        cb.message.answer.assert_called()


class TestClearConfirm:
    async def test_btn_clear(self):
        from services.bot.handlers.start import btn_clear
        msg = _make_message()
        with patch(f"{_START}.get_or_create_user", AsyncMock(return_value={"id": 111})):
            await btn_clear(msg)
        msg.answer.assert_called()

    async def test_cb_clear_confirm(self):
        from services.bot.handlers.start import cb_clear_confirm
        cb = _make_cb(data="clear_confirm")
        await cb_clear_confirm(cb)
        cb.message.answer.assert_called()


class TestScreenProfile:
    async def test_btn_profile_no_user(self):
        from services.bot.handlers.start import btn_profile
        msg = _make_message()
        pool, conn = _fake_pool(fetchrow=None, fetch=[])
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111}),
            back_to_main_kb=MagicMock(return_value=MagicMock()),
        ):
            with patch("shared.db.database.get_pool", AsyncMock(return_value=pool)):
                await btn_profile(msg)
        msg.answer.assert_called()

    async def test_btn_profile_with_user(self):
        from services.bot.handlers.start import btn_profile
        msg = _make_message()
        user_row = MagicMock()
        user_row.__getitem__ = lambda self, key: {
            "created_at": datetime(2024, 1, 1),
            "first_name": "Test",
            "username": "test",
            "credits_total_spent": 100,
            "referral_count": 2,
            "total_payments_rub": 200,
        }[key]
        user_row.get = lambda key, default=None: {
            "created_at": datetime(2024, 1, 1),
            "first_name": "Test",
            "username": "test",
            "credits_total_spent": 100,
            "referral_count": 2,
            "total_payments_rub": 200,
        }.get(key, default)

        pool, conn = _fake_pool()
        conn.fetchrow = AsyncMock(return_value=user_row)
        conn.fetch = AsyncMock(return_value=[])

        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111}),
            back_to_main_kb=MagicMock(return_value=MagicMock()),
            settings=MagicMock(legal_base_url="https://example.com"),
        ):
            with patch("shared.db.database.get_pool", AsyncMock(return_value=pool)):
                with patch("shared.domain.credits.get_balance", AsyncMock(return_value={"total": 100, "free": 10, "bought": 90})):
                    with patch("shared.domain.credits.get_user_model", AsyncMock(return_value="gpt-4o-mini")):
                        await btn_profile(msg)
        msg.answer.assert_called()

    async def test_cb_screen_profile_no_user(self):
        from services.bot.handlers.start import cb_screen_profile
        cb = _make_cb(data="screen_profile")
        pool, conn = _fake_pool(fetchrow=None, fetch=[])
        with patch(f"{_START}.back_to_main_kb", MagicMock(return_value=MagicMock())):
            with patch("shared.db.database.get_pool", AsyncMock(return_value=pool)):
                await cb_screen_profile(cb)
        cb.message.answer.assert_called()


class TestScreenTools:
    async def test_cb_screen_tools(self):
        from services.bot.handlers.start import cb_screen_tools
        cb = _make_cb(data="screen_tools")
        await cb_screen_tools(cb)
        cb.message.answer.assert_called()


class TestScreenRef:
    async def test_cb_screen_ref(self):
        from services.bot.handlers.start import cb_screen_ref
        cb = _make_cb(data="screen_ref")
        pool, conn = _fake_pool(fetchval=5)
        with patch(f"{_START}.settings") as s:
            s.bot_username = "neurobox_bot"
            with patch("shared.domain.credits.get_referral_code", AsyncMock(return_value="MYCODE")):
                with patch("shared.domain.credits.get_referral_level", MagicMock(return_value=("Бронза", 1.5))):
                    with patch("shared.domain.credits.REFERRER_CR", 50):
                        with patch("shared.domain.credits.REFEREE_CR", 50):
                            with patch("shared.domain.credits.REFERRAL_LEVELS", [(3, 1.5, "Бронза"), (10, 2.0, "Серебро")]):
                                with patch("shared.db.database.get_pool", AsyncMock(return_value=pool)):
                                    await cb_screen_ref(cb)
        cb.message.answer.assert_called()


class TestScreenSettings:
    async def test_cb_screen_settings(self):
        from services.bot.handlers.start import cb_screen_settings
        cb = _make_cb(data="screen_settings")
        with patch("services.bot.i18n.get_user_lang", AsyncMock(return_value="ru")):
            await cb_screen_settings(cb)
        cb.message.answer.assert_called()

    async def test_cb_choose_lang(self):
        from services.bot.handlers.start import cb_choose_lang
        cb = _make_cb(data="choose_lang")
        await cb_choose_lang(cb)
        cb.message.answer.assert_called()

    async def test_cb_set_lang_ru(self):
        from services.bot.handlers.start import cb_set_lang
        cb = _make_cb(data="set_lang_ru")
        with patch.multiple(
            _START,
            get_balance=AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
            get_trial_status=AsyncMock(return_value={"is_active": False, "can_activate": True, "expires_at": None}),
            get_main_menu_kb=MagicMock(return_value=MagicMock()),
            settings=MagicMock(enable_full_access_48h=False),
        ):
            with patch("services.bot.i18n.set_user_lang", AsyncMock()):
                with patch("services.bot.i18n.t", return_value="Язык изменён"):
                    await cb_set_lang(cb)
        cb.answer.assert_called()

    async def test_cb_set_lang_en(self):
        from services.bot.handlers.start import cb_set_lang
        cb = _make_cb(data="set_lang_en")
        with patch.multiple(
            _START,
            get_balance=AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
            get_trial_status=AsyncMock(return_value={"is_active": False, "can_activate": True, "expires_at": None}),
            get_main_menu_kb=MagicMock(return_value=MagicMock()),
            settings=MagicMock(enable_full_access_48h=False),
        ):
            with patch("services.bot.i18n.set_user_lang", AsyncMock()):
                with patch("services.bot.i18n.t", return_value="Language set"):
                    await cb_set_lang(cb)
        cb.answer.assert_called()


class TestNoop:
    async def test_cb_noop(self):
        from services.bot.handlers.start import cb_noop
        cb = _make_cb(data="noop")
        await cb_noop(cb)
        cb.answer.assert_called()


class TestOurBots:
    async def test_cb_our_bots(self):
        from services.bot.handlers.start import cb_our_bots
        cb = _make_cb(data="our_bots")
        await cb_our_bots(cb)
        cb.message.answer.assert_called()


class TestPrivacyTerms:
    async def test_cmd_privacy_with_url(self):
        from services.bot.handlers.start import cmd_privacy
        msg = _make_message()
        with patch(f"{_START}.settings") as s:
            s.legal_base_url = "https://example.com/"
            await cmd_privacy(msg)
        msg.answer.assert_called()
        assert "privacy" in msg.answer.call_args[0][0]

    async def test_cmd_privacy_no_url(self):
        from services.bot.handlers.start import cmd_privacy
        msg = _make_message()
        with patch(f"{_START}.settings") as s:
            s.legal_base_url = ""
            await cmd_privacy(msg)
        msg.answer.assert_called()

    async def test_cmd_terms_with_url(self):
        from services.bot.handlers.start import cmd_terms
        msg = _make_message()
        with patch(f"{_START}.settings") as s:
            s.legal_base_url = "https://example.com/"
            await cmd_terms(msg)
        msg.answer.assert_called()
        assert "terms" in msg.answer.call_args[0][0]

    async def test_cmd_terms_no_url(self):
        from services.bot.handlers.start import cmd_terms
        msg = _make_message()
        with patch(f"{_START}.settings") as s:
            s.legal_base_url = ""
            await cmd_terms(msg)
        msg.answer.assert_called()


class TestExportMyData:
    async def test_cb_export_my_data_user_found(self):
        from services.bot.handlers.start import cb_export_my_data
        cb = _make_cb(data="export_my_data")
        user_row = MagicMock()
        user_row.__iter__ = MagicMock(return_value=iter([
            ("id", 111), ("username", "test"), ("first_name", "Test"),
            ("language_code", "ru"), ("credits_bought", 0), ("credits_free_today", 10),
            ("credits_total_spent", 0), ("referral_count", 0), ("total_payments_rub", 0),
            ("created_at", datetime(2024, 1, 1)), ("updated_at", datetime(2024, 1, 1)),
        ]))

        pool, conn = _fake_pool()
        conn.fetchrow = AsyncMock(return_value=user_row)
        conn.fetch = AsyncMock(return_value=[])

        with patch("shared.db.database.get_pool", AsyncMock(return_value=pool)):
            await cb_export_my_data(cb)
        cb.message.answer_document.assert_called()

    async def test_cb_export_my_data_no_user(self):
        from services.bot.handlers.start import cb_export_my_data
        cb = _make_cb(data="export_my_data")
        pool, conn = _fake_pool(fetchrow=None, fetch=[])
        with patch("shared.db.database.get_pool", AsyncMock(return_value=pool)):
            await cb_export_my_data(cb)
        cb.message.answer.assert_called()


class TestDeleteAccount:
    async def test_cb_delete_account_shows_confirm(self):
        from services.bot.handlers.start import cb_delete_account
        cb = _make_cb(data="delete_account")
        await cb_delete_account(cb)
        cb.answer.assert_called()
        cb.message.answer.assert_called()

    async def test_cb_delete_account_confirm(self):
        from services.bot.handlers.start import cb_delete_account_confirm
        cb = _make_cb(data="delete_account_confirm")
        pool, conn = _fake_pool()
        with patch("shared.db.database.get_pool", AsyncMock(return_value=pool)):
            await cb_delete_account_confirm(cb)
        cb.message.answer.assert_called()
        conn.execute.assert_called()


class TestAudioMenu:
    async def test_btn_audio_menu_both_disabled(self):
        from services.bot.handlers.start import btn_audio_menu
        msg = _make_message()
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111}),
            settings=MagicMock(enable_tts=False, enable_music=False),
        ):
            await btn_audio_menu(msg)
        msg.answer.assert_called()

    async def test_btn_audio_menu_tts_enabled(self):
        from services.bot.handlers.start import btn_audio_menu
        msg = _make_message()
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111}),
            settings=MagicMock(enable_tts=True, enable_music=False),
        ):
            await btn_audio_menu(msg)
        msg.answer.assert_called()

    async def test_btn_audio_menu_music_enabled(self):
        from services.bot.handlers.start import btn_audio_menu
        msg = _make_message()
        with patch.multiple(
            _START,
            get_or_create_user=AsyncMock(return_value={"id": 111}),
            settings=MagicMock(enable_tts=False, enable_music=True),
        ):
            await btn_audio_menu(msg)
        msg.answer.assert_called()

    async def test_btn_transcribe_menu(self):
        from services.bot.handlers.start import btn_transcribe_menu
        msg = _make_message()
        with patch(f"{_START}.get_or_create_user", AsyncMock(return_value={"id": 111})):
            await btn_transcribe_menu(msg)
        msg.answer.assert_called()


class TestUnsupportedContent:
    async def test_handle_sticker(self):
        from services.bot.handlers.start import handle_sticker
        msg = _make_message()
        await handle_sticker(msg)
        msg.answer.assert_called()

    async def test_handle_contact(self):
        from services.bot.handlers.start import handle_contact
        msg = _make_message()
        await handle_contact(msg)
        msg.answer.assert_called()

    async def test_handle_location(self):
        from services.bot.handlers.start import handle_location
        msg = _make_message()
        await handle_location(msg)
        msg.answer.assert_called()

    async def test_handle_animation(self):
        from services.bot.handlers.start import handle_animation
        msg = _make_message()
        await handle_animation(msg)
        msg.answer.assert_called()


# ═══════════════════════════════════════════════════════════════════════════════
# balance.py tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestBalanceHelpers:
    def test_yookassa_configured_true(self):
        from services.bot.handlers.balance import _yookassa_configured
        with patch(f"{_BALANCE}.settings") as s:
            s.enable_yookassa_payment = True
            s.yookassa_shop_id = "shop123"
            s.yookassa_secret_key = "secret"
            assert _yookassa_configured() is True

    def test_yookassa_configured_false_disabled(self):
        from services.bot.handlers.balance import _yookassa_configured
        with patch(f"{_BALANCE}.settings") as s:
            s.enable_yookassa_payment = False
            s.yookassa_shop_id = "shop123"
            s.yookassa_secret_key = "secret"
            assert _yookassa_configured() is False

    def test_yookassa_configured_false_missing(self):
        from services.bot.handlers.balance import _yookassa_configured
        with patch(f"{_BALANCE}.settings") as s:
            s.enable_yookassa_payment = True
            s.yookassa_shop_id = ""
            s.yookassa_secret_key = ""
            assert _yookassa_configured() is False

    def test_cryptobot_configured_true(self):
        from services.bot.handlers.balance import _cryptobot_configured
        with patch(f"{_BALANCE}.settings") as s:
            s.enable_cryptobot_payment = True
            s.cryptobot_api_token = "token123"
            assert _cryptobot_configured() is True

    def test_cryptobot_configured_false(self):
        from services.bot.handlers.balance import _cryptobot_configured
        with patch(f"{_BALANCE}.settings") as s:
            s.enable_cryptobot_payment = False
            s.cryptobot_api_token = "token123"
            assert _cryptobot_configured() is False

    def test_stars_configured_true(self):
        from services.bot.handlers.balance import _stars_configured
        with patch(f"{_BALANCE}.settings") as s:
            s.enable_stars_payment = True
            assert _stars_configured() is True

    def test_stars_configured_false(self):
        from services.bot.handlers.balance import _stars_configured
        with patch(f"{_BALANCE}.settings") as s:
            s.enable_stars_payment = False
            assert _stars_configured() is False

    def test_balance_kb(self):
        from services.bot.handlers.balance import _balance_kb
        kb = _balance_kb()
        assert kb is not None


class TestBalanceText:
    async def test_balance_text_basic(self):
        from services.bot.handlers.balance import _balance_text
        bal = {"total": 100, "free": 10, "bought": 90}
        with patch(f"{_BALANCE}.settings") as s:
            s.free_daily_credits = 20
            text = await _balance_text(bal)
        assert "100" in text
        assert "10" in text

    async def test_balance_text_with_unlimited_future(self):
        from services.bot.handlers.balance import _balance_text
        bal = {"total": 100, "free": 10, "bought": 90}
        end = datetime.now(timezone.utc) + timedelta(days=5)
        with patch(f"{_BALANCE}.settings") as s:
            s.free_daily_credits = 20
            text = await _balance_text(bal, unlimited_ends_at=end)
        assert "Безлимит" in text

    async def test_balance_text_with_unlimited_past(self):
        from services.bot.handlers.balance import _balance_text
        bal = {"total": 100, "free": 10, "bought": 90}
        end = datetime.now(timezone.utc) - timedelta(days=1)
        with patch(f"{_BALANCE}.settings") as s:
            s.free_daily_credits = 20
            text = await _balance_text(bal, unlimited_ends_at=end)
        assert "Безлимит" not in text

    async def test_balance_text_with_user_id_db(self):
        from services.bot.handlers.balance import _balance_text
        bal = {"total": 100, "free": 10, "bought": 90}
        pool, conn = _fake_pool(fetchval=5)
        with patch("shared.db.database.get_pool", AsyncMock(return_value=pool)):
            with patch(f"{_BALANCE}.settings") as s:
                s.free_daily_credits = 20
                text = await _balance_text(bal, user_id=111)
        assert "100" in text

    async def test_balance_text_naive_unlimited(self):
        from services.bot.handlers.balance import _balance_text
        bal = {"total": 100, "free": 10, "bought": 90}
        end = datetime.utcnow() + timedelta(days=5)  # naive
        with patch(f"{_BALANCE}.settings") as s:
            s.free_daily_credits = 20
            text = await _balance_text(bal, unlimited_ends_at=end)
        assert "Безлимит" in text


class TestMsgBalance:
    async def test_msg_balance(self):
        from services.bot.handlers.balance import msg_balance
        msg = _make_message()
        with patch.multiple(
            _BALANCE,
            get_or_create_user=AsyncMock(return_value={"id": 111}),
            get_balance=AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
            get_unlimited_ends_at=AsyncMock(return_value=None),
            settings=MagicMock(free_daily_credits=20),
        ):
            await msg_balance(msg)
        msg.answer.assert_called()


class TestCbBalance:
    async def test_cb_balance(self):
        from services.bot.handlers.balance import cb_balance
        cb = _make_cb(data="balance")
        with patch.multiple(
            _BALANCE,
            get_balance=AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
            get_unlimited_ends_at=AsyncMock(return_value=None),
            settings=MagicMock(free_daily_credits=20),
        ):
            await cb_balance(cb)
        cb.message.answer.assert_called()


class TestCbBuy:
    async def test_cb_buy_empty_packs(self):
        from services.bot.handlers.balance import cb_buy
        cb = _make_cb(data="buy_credits")
        with patch(f"{_BALANCE}.get_credit_packs", AsyncMock(return_value={})):
            await cb_buy(cb)
        cb.message.answer.assert_called()

    async def test_cb_buy_with_packs(self):
        from services.bot.handlers.balance import cb_buy
        cb = _make_cb(data="buy_credits")
        packs = {
            "basic": {"label": "Basic", "credits": 100, "price_rub": 99, "discount": None},
            "pro": {"label": "Pro", "credits": 500, "price_rub": 399, "discount": "50%"},
        }
        with patch(f"{_BALANCE}.get_credit_packs", AsyncMock(return_value=packs)):
            await cb_buy(cb)
        cb.message.answer.assert_called()


class TestCbBuyPack:
    async def test_cb_buy_pack_valid(self):
        from services.bot.handlers.balance import cb_buy_pack
        cb = _make_cb(data="buy_basic")
        pack = {"id": "basic", "price_rub": 99, "credits": 100, "label": "Basic", "discount": None}
        with patch(f"{_BALANCE}.get_credit_pack", AsyncMock(return_value=pack)):
            await cb_buy_pack(cb)
        cb.message.answer.assert_called()

    async def test_cb_buy_pack_unlimited(self):
        from services.bot.handlers.balance import cb_buy_pack
        cb = _make_cb(data="buy_unlimited")
        pack = {"id": "unlimited", "price_rub": 499, "credits": 0, "label": "Безлимит", "discount": None}
        with patch(f"{_BALANCE}.get_credit_pack", AsyncMock(return_value=pack)):
            await cb_buy_pack(cb)
        cb.message.answer.assert_called()

    async def test_cb_buy_pack_with_discount(self):
        from services.bot.handlers.balance import cb_buy_pack
        cb = _make_cb(data="buy_pro")
        pack = {"id": "pro", "price_rub": 399, "credits": 500, "label": "Pro", "discount": "50%"}
        with patch(f"{_BALANCE}.get_credit_pack", AsyncMock(return_value=pack)):
            await cb_buy_pack(cb)
        cb.message.answer.assert_called()

    async def test_cb_buy_pack_large_credits(self):
        from services.bot.handlers.balance import cb_buy_pack
        cb = _make_cb(data="buy_mega")
        pack = {"id": "mega", "price_rub": 999, "credits": 1500, "label": "Mega", "discount": None}
        with patch(f"{_BALANCE}.get_credit_pack", AsyncMock(return_value=pack)):
            await cb_buy_pack(cb)
        cb.message.answer.assert_called()

    async def test_cb_buy_pack_not_found(self):
        from services.bot.handlers.balance import cb_buy_pack
        cb = _make_cb(data="buy_nonexistent")
        with patch(f"{_BALANCE}.get_credit_pack", AsyncMock(return_value=None)):
            await cb_buy_pack(cb)
        cb.answer.assert_called()


class TestCbConfirm:
    async def test_cb_confirm_no_payment_methods(self):
        from services.bot.handlers.balance import cb_confirm
        cb = _make_cb(data="confirm_buy_basic")
        pack = {"id": "basic", "price_rub": 99, "credits": 100, "label": "Basic", "price_stars": 0, "price_usd": 0}
        with patch.multiple(
            _BALANCE,
            get_credit_pack=AsyncMock(return_value=pack),
            settings=MagicMock(
                enable_yookassa_payment=False, yookassa_shop_id="", yookassa_secret_key="",
                enable_stars_payment=False, enable_cryptobot_payment=False, cryptobot_api_token="",
                enable_test_payments=False,
            ),
        ):
            await cb_confirm(cb)
        cb.message.answer.assert_called()

    async def test_cb_confirm_with_stars(self):
        from services.bot.handlers.balance import cb_confirm
        cb = _make_cb(data="confirm_buy_basic")
        pack = {"id": "basic", "price_rub": 99, "credits": 100, "label": "Basic", "price_stars": 10, "price_usd": 0}
        with patch.multiple(
            _BALANCE,
            get_credit_pack=AsyncMock(return_value=pack),
            settings=MagicMock(
                enable_yookassa_payment=False, yookassa_shop_id="", yookassa_secret_key="",
                enable_stars_payment=True, enable_cryptobot_payment=False, cryptobot_api_token="",
                enable_test_payments=False,
            ),
        ):
            await cb_confirm(cb)
        cb.message.answer.assert_called()

    async def test_cb_confirm_test_payment(self):
        from services.bot.handlers.balance import cb_confirm
        cb = _make_cb(data="confirm_buy_basic")
        pack = {"id": "basic", "price_rub": 99, "credits": 100, "label": "Basic", "price_stars": 0, "price_usd": 0}
        with patch.multiple(
            _BALANCE,
            get_credit_pack=AsyncMock(return_value=pack),
            settings=MagicMock(
                enable_yookassa_payment=False, yookassa_shop_id="", yookassa_secret_key="",
                enable_stars_payment=False, enable_cryptobot_payment=False, cryptobot_api_token="",
                enable_test_payments=True,
            ),
        ):
            await cb_confirm(cb)
        cb.message.answer.assert_called()

    async def test_cb_confirm_unlimited(self):
        from services.bot.handlers.balance import cb_confirm
        cb = _make_cb(data="confirm_buy_unlimited")
        pack = {"id": "unlimited", "price_rub": 499, "credits": 0, "label": "Безлимит", "price_stars": 0, "price_usd": 0}
        with patch.multiple(
            _BALANCE,
            get_credit_pack=AsyncMock(return_value=pack),
            settings=MagicMock(
                enable_yookassa_payment=False, yookassa_shop_id="", yookassa_secret_key="",
                enable_stars_payment=False, enable_cryptobot_payment=False, cryptobot_api_token="",
                enable_test_payments=False,
            ),
        ):
            await cb_confirm(cb)
        cb.message.answer.assert_called()

    async def test_cb_confirm_pack_not_found(self):
        from services.bot.handlers.balance import cb_confirm
        cb = _make_cb(data="confirm_buy_bad")
        with patch(f"{_BALANCE}.get_credit_pack", AsyncMock(return_value=None)):
            await cb_confirm(cb)
        cb.answer.assert_called()


class TestCbPayTest:
    async def test_cb_pay_test_disabled(self):
        from services.bot.handlers.balance import cb_pay_test
        cb = _make_cb(data="pay_test_basic")
        with patch(f"{_BALANCE}.settings") as s:
            s.enable_test_payments = False
            await cb_pay_test(cb)
        cb.answer.assert_called()

    async def test_cb_pay_test_pack_not_found(self):
        from services.bot.handlers.balance import cb_pay_test
        cb = _make_cb(data="pay_test_bad")
        with patch.multiple(
            _BALANCE,
            get_credit_pack=AsyncMock(return_value=None),
            settings=MagicMock(enable_test_payments=True),
        ):
            await cb_pay_test(cb)
        cb.answer.assert_called()

    async def test_cb_pay_test_credits(self):
        from services.bot.handlers.balance import cb_pay_test
        cb = _make_cb(data="pay_test_basic")
        pack = {"id": "basic", "price_rub": 99, "credits": 100, "label": "Basic", "price_stars": 0}
        with patch.multiple(
            _BALANCE,
            get_credit_pack=AsyncMock(return_value=pack),
            add_credits=AsyncMock(return_value=None),
            get_balance=AsyncMock(return_value={"total": 200, "free": 10, "bought": 190}),
            settings=MagicMock(enable_test_payments=True),
        ):
            await cb_pay_test(cb)
        cb.answer.assert_called()
        cb.message.answer.assert_called()

    async def test_cb_pay_test_unlimited(self):
        from services.bot.handlers.balance import cb_pay_test
        cb = _make_cb(data="pay_test_unlimited")
        pack = {"id": "unlimited", "price_rub": 499, "credits": 0, "label": "Безлимит", "price_stars": 0}
        with patch.multiple(
            _BALANCE,
            get_credit_pack=AsyncMock(return_value=pack),
            set_unlimited_until=AsyncMock(return_value=None),
            get_unlimited_ends_at=AsyncMock(return_value=datetime(2025, 6, 1)),
            get_balance=AsyncMock(return_value={"total": 100, "free": 10, "bought": 90}),
            UNLIMITED_DAYS=30,
            settings=MagicMock(enable_test_payments=True),
        ):
            await cb_pay_test(cb)
        cb.answer.assert_called()


class TestCbPayStars:
    async def test_cb_pay_stars_not_found(self):
        from services.bot.handlers.balance import cb_pay_stars
        cb = _make_cb(data="pay_stars_bad")
        with patch(f"{_BALANCE}.get_credit_pack", AsyncMock(return_value=None)):
            await cb_pay_stars(cb)
        cb.answer.assert_called()

    async def test_cb_pay_stars_no_price(self):
        from services.bot.handlers.balance import cb_pay_stars
        cb = _make_cb(data="pay_stars_basic")
        pack = {"id": "basic", "price_rub": 99, "credits": 100, "label": "Basic", "price_stars": 0}
        with patch(f"{_BALANCE}.get_credit_pack", AsyncMock(return_value=pack)):
            await cb_pay_stars(cb)
        cb.answer.assert_called()

    async def test_cb_pay_stars_success(self):
        from services.bot.handlers.balance import cb_pay_stars
        cb = _make_cb(data="pay_stars_basic")
        pack = {"id": "basic", "price_rub": 99, "credits": 100, "label": "Basic", "price_stars": 10}
        with patch(f"{_BALANCE}.get_credit_pack", AsyncMock(return_value=pack)):
            await cb_pay_stars(cb)
        cb.message.answer_invoice.assert_called()


class TestOnPreCheckout:
    async def test_on_pre_checkout(self):
        from services.bot.handlers.balance import on_pre_checkout
        pre_checkout = AsyncMock(spec=types.PreCheckoutQuery)
        pre_checkout.answer = AsyncMock()
        await on_pre_checkout(pre_checkout)
        pre_checkout.answer.assert_called_once_with(ok=True)


class TestOnSuccessfulPayment:
    async def test_on_successful_payment_invalid_payload(self):
        from services.bot.handlers.balance import on_successful_payment
        msg = _make_message()
        payment = MagicMock()
        payment.invoice_payload = "invalid_payload"
        msg.successful_payment = payment
        # Should return early without calling answer
        await on_successful_payment(msg)

    async def test_on_successful_payment_wrong_prefix(self):
        from services.bot.handlers.balance import on_successful_payment
        msg = _make_message()
        payment = MagicMock()
        payment.invoice_payload = "yoo_basic_111"
        msg.successful_payment = payment
        await on_successful_payment(msg)

    async def test_on_successful_payment_pack_not_found(self):
        from services.bot.handlers.balance import on_successful_payment
        msg = _make_message()
        payment = MagicMock()
        payment.invoice_payload = "stars_bad_111"
        msg.successful_payment = payment
        with patch(f"{_BALANCE}.get_credit_pack", AsyncMock(return_value=None)):
            await on_successful_payment(msg)

    async def test_on_successful_payment_already_processed(self):
        from services.bot.handlers.balance import on_successful_payment
        msg = _make_message()
        payment = MagicMock()
        payment.invoice_payload = "stars_basic_111"
        payment.total_amount = 10
        payment.telegram_payment_charge_id = "charge123"
        msg.successful_payment = payment
        pack = {"id": "basic", "credits": 100, "label": "Basic"}
        with patch.multiple(
            _BALANCE,
            get_credit_pack=AsyncMock(return_value=pack),
            create_payment_record=AsyncMock(return_value=None),  # already exists
        ):
            await on_successful_payment(msg)
        msg.answer.assert_called()

    async def test_on_successful_payment_credits(self):
        from services.bot.handlers.balance import on_successful_payment
        msg = _make_message()
        payment = MagicMock()
        payment.invoice_payload = "stars_basic_111"
        payment.total_amount = 10
        payment.telegram_payment_charge_id = "charge123"
        msg.successful_payment = payment
        pack = {"id": "basic", "credits": 100, "label": "Basic"}
        with patch.multiple(
            _BALANCE,
            get_credit_pack=AsyncMock(return_value=pack),
            create_payment_record=AsyncMock(return_value="pay123"),
            confirm_payment_record=AsyncMock(return_value={"pack_name": "basic", "credits_amount": 100}),
            add_credits=AsyncMock(return_value=None),
            get_balance=AsyncMock(return_value={"total": 200, "free": 10, "bought": 190}),
        ):
            await on_successful_payment(msg)
        msg.answer.assert_called()

    async def test_on_successful_payment_unlimited(self):
        from services.bot.handlers.balance import on_successful_payment
        msg = _make_message()
        payment = MagicMock()
        payment.invoice_payload = "stars_unlimited_111"
        payment.total_amount = 100
        payment.telegram_payment_charge_id = "charge456"
        msg.successful_payment = payment
        pack = {"id": "unlimited", "credits": 0, "label": "Безлимит"}
        with patch.multiple(
            _BALANCE,
            get_credit_pack=AsyncMock(return_value=pack),
            create_payment_record=AsyncMock(return_value="pay456"),
            confirm_payment_record=AsyncMock(return_value={"pack_name": "unlimited", "credits_amount": 0}),
            set_unlimited_until=AsyncMock(return_value=None),
            get_unlimited_ends_at=AsyncMock(return_value=datetime(2025, 6, 1)),
            get_balance=AsyncMock(return_value={"total": 0, "free": 10, "bought": 0}),
            UNLIMITED_DAYS=30,
        ):
            await on_successful_payment(msg)
        msg.answer.assert_called()


class TestCbPayCrypto:
    async def test_cb_pay_crypto_pack_not_found(self):
        from services.bot.handlers.balance import cb_pay_crypto
        cb = _make_cb(data="pay_crypto_bad")
        with patch(f"{_BALANCE}.get_credit_pack", AsyncMock(return_value=None)):
            await cb_pay_crypto(cb)
        cb.answer.assert_called()

    async def test_cb_pay_crypto_not_configured(self):
        from services.bot.handlers.balance import cb_pay_crypto
        cb = _make_cb(data="pay_crypto_basic")
        pack = {"id": "basic", "price_usd": 2, "credits": 100, "label": "Basic"}
        with patch.multiple(
            _BALANCE,
            get_credit_pack=AsyncMock(return_value=pack),
            settings=MagicMock(enable_cryptobot_payment=False, cryptobot_api_token=""),
        ):
            await cb_pay_crypto(cb)
        cb.answer.assert_called()

    async def test_cb_pay_crypto_no_usd(self):
        from services.bot.handlers.balance import cb_pay_crypto
        cb = _make_cb(data="pay_crypto_basic")
        pack = {"id": "basic", "price_usd": 0, "credits": 100, "label": "Basic"}
        with patch.multiple(
            _BALANCE,
            get_credit_pack=AsyncMock(return_value=pack),
            settings=MagicMock(enable_cryptobot_payment=True, cryptobot_api_token="token"),
        ):
            await cb_pay_crypto(cb)
        cb.answer.assert_called()

    async def test_cb_pay_crypto_success(self):
        from services.bot.handlers.balance import cb_pay_crypto
        cb = _make_cb(data="pay_crypto_basic")
        pack = {"id": "basic", "price_usd": 2, "credits": 100, "label": "Basic"}
        result = {"ok": True, "pay_url": "https://t.me/CryptoBot?start=pay123", "invoice_id": "inv123"}
        with patch.multiple(
            _BALANCE,
            get_credit_pack=AsyncMock(return_value=pack),
            settings=MagicMock(enable_cryptobot_payment=True, cryptobot_api_token="token"),
        ):
            with patch("shared.domain.cryptobot.create_crypto_invoice", AsyncMock(return_value=result)):
                await cb_pay_crypto(cb)
        cb.message.answer.assert_called()

    async def test_cb_pay_crypto_error(self):
        from services.bot.handlers.balance import cb_pay_crypto
        cb = _make_cb(data="pay_crypto_basic")
        pack = {"id": "basic", "price_usd": 2, "credits": 100, "label": "Basic"}
        result = {"ok": False, "error": "CryptoBot error"}
        with patch.multiple(
            _BALANCE,
            get_credit_pack=AsyncMock(return_value=pack),
            settings=MagicMock(enable_cryptobot_payment=True, cryptobot_api_token="token"),
        ):
            with patch("shared.domain.cryptobot.create_crypto_invoice", AsyncMock(return_value=result)):
                await cb_pay_crypto(cb)
        cb.message.answer.assert_called()


class TestCbPrice:
    async def test_cb_price(self):
        from services.bot.handlers.balance import cb_price
        cb = _make_cb(data="price_list")
        with patch.multiple(
            _BALANCE,
            CREDIT_PRICES={"gpt-4o-mini": 1, "dall-e-3": 5, "musicgen": 15, "suno-v4": 50},
            FREE_MODELS=set(),
            VIDEO_MODELS={},
            IMAGE_MODELS=[("DALL-E 3", "dall-e-3", "5 CR", False)],
            settings=MagicMock(enable_video=False, enable_tts=False, enable_music=False),
        ):
            with patch("shared.config.text_models.TEXT_MODELS", [("GPT-4o mini", "gpt-4o-mini", "1 CR", True, {})]):
                await cb_price(cb)
        cb.message.answer.assert_called()

    async def test_cb_price_with_video_and_music(self):
        from services.bot.handlers.balance import cb_price
        cb = _make_cb(data="price_list")
        video_models = {"hailuo": {"label": "Hailuo", "cr": 75}}
        with patch.multiple(
            _BALANCE,
            CREDIT_PRICES={"gpt-4o-mini": 1, "dall-e-3": 5, "musicgen": 15, "suno-v4": 50},
            FREE_MODELS=set(),
            VIDEO_MODELS=video_models,
            IMAGE_MODELS=[("DALL-E 3", "dall-e-3", "5 CR", False)],
            settings=MagicMock(enable_video=True, enable_tts=True, enable_music=True),
        ):
            with patch("shared.config.text_models.TEXT_MODELS", [("GPT-4o mini", "gpt-4o-mini", "1 CR", True, {})]):
                await cb_price(cb)
        cb.message.answer.assert_called()


class TestHelpCallbacks:
    async def test_cb_hc(self):
        from services.bot.handlers.balance import cb_hc
        cb = _make_cb(data="help_chat")
        await cb_hc(cb)
        cb.message.answer.assert_called()

    async def test_cb_hi(self):
        from services.bot.handlers.balance import cb_hi
        cb = _make_cb(data="help_images")
        await cb_hi(cb)
        cb.message.answer.assert_called()

    async def test_cb_hvid_disabled(self):
        from services.bot.handlers.balance import cb_hvid
        cb = _make_cb(data="help_video")
        with patch(f"{_BALANCE}.settings") as s:
            s.enable_video = False
            await cb_hvid(cb)
        cb.message.answer.assert_called()
        assert "временно" in cb.message.answer.call_args[0][0]

    async def test_cb_hvid_enabled(self):
        from services.bot.handlers.balance import cb_hvid
        cb = _make_cb(data="help_video")
        with patch(f"{_BALANCE}.settings") as s:
            s.enable_video = True
            await cb_hvid(cb)
        cb.message.answer.assert_called()

    async def test_cb_hv_tts_enabled(self):
        from services.bot.handlers.balance import cb_hv
        cb = _make_cb(data="help_voice")
        with patch(f"{_BALANCE}.settings") as s:
            s.enable_tts = True
            await cb_hv(cb)
        cb.message.answer.assert_called()

    async def test_cb_hv_tts_disabled(self):
        from services.bot.handlers.balance import cb_hv
        cb = _make_cb(data="help_voice")
        with patch(f"{_BALANCE}.settings") as s:
            s.enable_tts = False
            await cb_hv(cb)
        cb.message.answer.assert_called()

    async def test_cb_hm_music_enabled(self):
        from services.bot.handlers.balance import cb_hm
        cb = _make_cb(data="help_music")
        with patch.multiple(
            _BALANCE,
            CREDIT_PRICES={"musicgen": 15},
            settings=MagicMock(enable_music=True),
        ):
            await cb_hm(cb)
        cb.message.answer.assert_called()

    async def test_cb_hm_music_disabled(self):
        from services.bot.handlers.balance import cb_hm
        cb = _make_cb(data="help_music")
        with patch(f"{_BALANCE}.settings") as s:
            s.enable_music = False
            await cb_hm(cb)
        cb.message.answer.assert_called()


class TestCbTxHistory:
    async def test_cb_tx_history_empty(self):
        from services.bot.handlers.balance import cb_tx_history
        cb = _make_cb(data="tx_history")
        pool, conn = _fake_pool(fetch=[])
        with patch("shared.db.database.get_pool", AsyncMock(return_value=pool)):
            await cb_tx_history(cb)
        cb.message.answer.assert_called()

    async def test_cb_tx_history_with_rows(self):
        from services.bot.handlers.balance import cb_tx_history
        cb = _make_cb(data="tx_history")
        row = MagicMock()
        row.__getitem__ = lambda self, key: {
            "created_at": datetime(2024, 1, 1, 12, 0),
            "amount": -5,
            "type": "spend",
            "description": "GPT-4",
            "model": "gpt-4o-mini",
        }[key]
        pool, conn = _fake_pool()
        conn.fetch = AsyncMock(return_value=[row])
        with patch("shared.db.database.get_pool", AsyncMock(return_value=pool)):
            await cb_tx_history(cb)
        cb.message.answer.assert_called()


class TestCbPayYookassa:
    async def test_cb_pay_yookassa_not_configured(self):
        from services.bot.handlers.balance import cb_pay_yookassa
        cb = _make_cb(data="pay_yoo_basic")
        pack = {"id": "basic", "price_rub": 99, "credits": 100, "label": "Basic"}
        with patch.multiple(
            _BALANCE,
            get_credit_pack=AsyncMock(return_value=pack),
            settings=MagicMock(
                enable_yookassa_payment=False, yookassa_shop_id="", yookassa_secret_key="",
                bot_username="nb_bot",
            ),
        ):
            with patch("shared.redis.store._get_redis", AsyncMock(return_value=None)):
                await cb_pay_yookassa(cb)
        cb.answer.assert_called()

    async def test_cb_pay_yookassa_pack_not_found(self):
        from services.bot.handlers.balance import cb_pay_yookassa
        cb = _make_cb(data="pay_yoo_bad")
        with patch(f"{_BALANCE}.get_credit_pack", AsyncMock(return_value=None)):
            await cb_pay_yookassa(cb)
        cb.answer.assert_called()

    async def test_cb_pay_yookassa_no_bot_username(self):
        from services.bot.handlers.balance import cb_pay_yookassa
        cb = _make_cb(data="pay_yoo_basic")
        pack = {"id": "basic", "price_rub": 99, "credits": 100, "label": "Basic"}
        with patch.multiple(
            _BALANCE,
            get_credit_pack=AsyncMock(return_value=pack),
            settings=MagicMock(
                enable_yookassa_payment=True, yookassa_shop_id="shop", yookassa_secret_key="secret",
                bot_username="",
            ),
        ):
            with patch("shared.redis.store._get_redis", AsyncMock(return_value=None)):
                with patch("shared.domain.yookassa.get_yookassa_availability", AsyncMock(return_value={"available": True})):
                    await cb_pay_yookassa(cb)
        cb.answer.assert_called()

    async def test_cb_pay_yookassa_unavailable(self):
        from services.bot.handlers.balance import cb_pay_yookassa
        cb = _make_cb(data="pay_yoo_basic")
        pack = {"id": "basic", "price_rub": 99, "credits": 100, "label": "Basic", "price_stars": 0, "price_usd": 0}
        with patch.multiple(
            _BALANCE,
            get_credit_pack=AsyncMock(return_value=pack),
            settings=MagicMock(
                enable_yookassa_payment=True, yookassa_shop_id="shop", yookassa_secret_key="secret",
                bot_username="nb_bot", enable_stars_payment=False,
                enable_cryptobot_payment=False, cryptobot_api_token="",
            ),
        ):
            with patch("shared.redis.store._get_redis", AsyncMock(return_value=None)):
                with patch("shared.domain.yookassa.get_yookassa_availability", AsyncMock(return_value={"available": False, "message": "Down"})):
                    await cb_pay_yookassa(cb)
        cb.message.answer.assert_called()
