"""Tests for small bot handlers: admin_cmd, coming_soon, mode_prompt."""
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram import types


def _make_user(user_id=12345):
    u = MagicMock()
    u.id = user_id
    u.username = "testuser"
    u.first_name = "Test"
    return u


def _make_message(text="hi", user_id=12345):
    msg = AsyncMock(spec=types.Message)
    msg.from_user = _make_user(user_id)
    msg.text = text
    msg.answer = AsyncMock()
    msg.chat = MagicMock()
    msg.chat.id = user_id
    return msg


def _make_callback(data="test", user_id=12345):
    cb = AsyncMock(spec=types.CallbackQuery)
    cb.from_user = _make_user(user_id)
    cb.data = data
    cb.message = _make_message(user_id=user_id)
    cb.answer = AsyncMock()
    return cb


def _fake_pool():
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=42)
    conn.execute = AsyncMock()
    pool = AsyncMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=False),
    ))
    return pool, conn


# ===========================================================================
# admin_cmd.py
# ===========================================================================

def test_is_admin_true():
    from services.bot.handlers.admin_cmd import is_admin
    with patch("services.bot.handlers.admin_cmd.settings") as s:
        s.admin_id_list = [12345]
        assert is_admin(12345) is True


def test_is_admin_false():
    from services.bot.handlers.admin_cmd import is_admin
    with patch("services.bot.handlers.admin_cmd.settings") as s:
        s.admin_id_list = [99999]
        assert is_admin(12345) is False


async def test_show_admin_dashboard_not_admin():
    from services.bot.handlers.admin_cmd import _show_admin_dashboard
    target = AsyncMock()
    with patch("services.bot.handlers.admin_cmd.settings") as s:
        s.admin_id_list = []
        await _show_admin_dashboard(target, 12345)
    target.answer.assert_not_called()


async def test_show_admin_dashboard_success():
    from services.bot.handlers.admin_cmd import _show_admin_dashboard
    pool, conn = _fake_pool()
    conn.fetchval = AsyncMock(side_effect=[100, 5000.0, 20, 300])
    target = AsyncMock()
    with patch("services.bot.handlers.admin_cmd.settings") as s, \
         patch("services.bot.handlers.admin_cmd.get_pool", AsyncMock(return_value=pool)):
        s.admin_id_list = [12345]
        await _show_admin_dashboard(target, 12345)
    target.answer.assert_called_once()


async def test_show_admin_dashboard_db_error():
    from services.bot.handlers.admin_cmd import _show_admin_dashboard
    target = AsyncMock()
    with patch("services.bot.handlers.admin_cmd.settings") as s, \
         patch("services.bot.handlers.admin_cmd.get_pool", AsyncMock(side_effect=Exception("DB down"))):
        s.admin_id_list = [12345]
        await _show_admin_dashboard(target, 12345)
    target.answer.assert_called_once()
    assert "Ошибка" in target.answer.call_args[0][0]


async def test_cmd_admin_not_admin():
    from services.bot.handlers.admin_cmd import cmd_admin
    msg = _make_message("/admin", user_id=99999)
    with patch("services.bot.handlers.admin_cmd.settings") as s, \
         patch("services.bot.handlers.admin_cmd._admin_denied", AsyncMock()) as mock_denied:
        s.admin_id_list = [12345]
        await cmd_admin(msg)
    mock_denied.assert_called_once()


async def test_cmd_admin_is_admin():
    from services.bot.handlers.admin_cmd import cmd_admin
    msg = _make_message("/admin", user_id=12345)
    with patch("services.bot.handlers.admin_cmd.settings") as s, \
         patch("services.bot.handlers.admin_cmd._show_admin_dashboard", AsyncMock()) as mock_dash:
        s.admin_id_list = [12345]
        await cmd_admin(msg)
    mock_dash.assert_called_once()


async def test_cb_open_admin_not_admin():
    from services.bot.handlers.admin_cmd import cb_open_admin
    cb = _make_callback("open_admin", user_id=99999)
    with patch("services.bot.handlers.admin_cmd.settings") as s, \
         patch("services.bot.handlers.admin_cmd._admin_denied", AsyncMock()) as mock_denied:
        s.admin_id_list = [12345]
        await cb_open_admin(cb)
    mock_denied.assert_called_once()


async def test_cb_open_admin_is_admin():
    from services.bot.handlers.admin_cmd import cb_open_admin
    cb = _make_callback("open_admin", user_id=12345)
    with patch("services.bot.handlers.admin_cmd.settings") as s, \
         patch("services.bot.handlers.admin_cmd._show_admin_dashboard", AsyncMock()) as mock_dash:
        s.admin_id_list = [12345]
        await cb_open_admin(cb)
    cb.answer.assert_called_once()
    mock_dash.assert_called_once()


# ===========================================================================
# coming_soon.py
# ===========================================================================

async def test_coming_soon_sticker():
    from services.bot.handlers.coming_soon import handle_sticker
    msg = _make_message()
    msg.sticker = MagicMock()
    await handle_sticker(msg)
    msg.answer.assert_called_once()


async def test_coming_soon_animation():
    from services.bot.handlers.coming_soon import handle_animation
    msg = _make_message()
    msg.animation = MagicMock()
    await handle_animation(msg)
    msg.answer.assert_called_once()


async def test_coming_soon_contact():
    from services.bot.handlers.coming_soon import handle_contact
    msg = _make_message()
    msg.contact = MagicMock()
    await handle_contact(msg)
    msg.answer.assert_called_once()


async def test_coming_soon_location():
    from services.bot.handlers.coming_soon import handle_location
    msg = _make_message()
    msg.location = MagicMock()
    await handle_location(msg)
    msg.answer.assert_called_once()


# ===========================================================================
# mode_prompt.py
# ===========================================================================

async def test_cb_persona_reset():
    from services.bot.handlers.mode_prompt import cb_persona
    cb = _make_callback("persona_reset")
    with patch("services.bot.handlers.mode_prompt.set_system_prompt", AsyncMock()):
        await cb_persona(cb)
    cb.answer.assert_called_once()
    cb.message.answer.assert_called_once()
    assert "сброшен" in cb.message.answer.call_args[0][0]


async def test_cb_persona_known():
    from services.bot.handlers.mode_prompt import cb_persona
    cb = _make_callback("persona_Программист")
    with patch("services.bot.handlers.mode_prompt.set_system_prompt", AsyncMock()) as mock_set:
        await cb_persona(cb)
    cb.answer.assert_called_once()
    mock_set.assert_called_once()
    assert "Программист" in cb.message.answer.call_args[0][0]


async def test_cb_persona_unknown():
    from services.bot.handlers.mode_prompt import cb_persona
    cb = _make_callback("persona_НесуществующийРежим")
    with patch("services.bot.handlers.mode_prompt.set_system_prompt", AsyncMock()):
        await cb_persona(cb)
    cb.answer.assert_called_once()
    assert "не найден" in cb.message.answer.call_args[0][0]


async def test_cb_persona_copywriter():
    from services.bot.handlers.mode_prompt import cb_persona
    cb = _make_callback("persona_Копирайтер")
    with patch("services.bot.handlers.mode_prompt.set_system_prompt", AsyncMock()) as mock_set:
        await cb_persona(cb)
    mock_set.assert_called_once()


async def test_cb_persona_all_names():
    """All persona names are reachable."""
    from services.bot.handlers.mode_prompt import cb_persona, PERSONAS
    with patch("services.bot.handlers.mode_prompt.set_system_prompt", AsyncMock()):
        for name, _ in PERSONAS:
            cb = _make_callback(f"persona_{name}")
            await cb_persona(cb)
