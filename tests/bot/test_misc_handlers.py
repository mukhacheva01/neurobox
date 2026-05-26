"""Tests for misc bot handlers: guide, model_select, modes, tools, feedback,
saved_export, ref_promo_stats, subscribe_remind."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import types
from aiogram.fsm.context import FSMContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(user_id: int = 12345, username: str = "testuser", first_name: str = "Test"):
    u = MagicMock()
    u.id = user_id
    u.username = username
    u.first_name = first_name
    return u


def _make_message(text: str = "hi", user_id: int = 12345):
    msg = AsyncMock(spec=types.Message)
    msg.from_user = _make_user(user_id)
    msg.text = text
    msg.answer = AsyncMock()
    msg.answer_document = AsyncMock()
    msg.chat = MagicMock()
    msg.chat.id = user_id
    msg.reply_to_message = None
    msg.bot = AsyncMock()
    return msg


def _make_callback(data: str = "test", user_id: int = 12345):
    cb = AsyncMock(spec=types.CallbackQuery)
    cb.from_user = _make_user(user_id)
    cb.data = data
    cb.message = _make_message(user_id=user_id)
    cb.answer = AsyncMock()
    return cb


def _make_pool(fetchval=None, fetchrow=None, fetch=None):
    """Create a mock asyncpg pool."""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchval = AsyncMock(return_value=fetchval)
    conn.fetchrow = AsyncMock(return_value=fetchrow)
    conn.fetch = AsyncMock(return_value=fetch or [])

    pool = AsyncMock()
    pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=conn),
                                                    __aexit__=AsyncMock(return_value=False)))
    pool._conn = conn  # convenience reference
    return pool


# ===========================================================================
# guide.py tests
# ===========================================================================

class TestGuideHelpers:
    def test_guide_menu_kb_returns_markup(self):
        from services.bot.handlers.guide import _guide_menu_kb
        kb = _guide_menu_kb()
        assert kb is not None
        # Validate it has inline buttons (InlineKeyboardMarkup)
        assert hasattr(kb, "inline_keyboard")

    def test_section_nav_kb_first_section(self):
        from services.bot.handlers.guide import _section_nav_kb
        kb = _section_nav_kb("start")
        # First section: only "Далее" nav button, no "Назад"
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        texts = [b.text for b in all_buttons]
        assert any("Далее" in t or "К разделам" in t for t in texts)
        assert not any("Назад" in t for t in texts)

    def test_section_nav_kb_last_section(self):
        from services.bot.handlers.guide import _section_nav_kb, SECTIONS_ORDER
        kb = _section_nav_kb(SECTIONS_ORDER[-1])
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        texts = [b.text for b in all_buttons]
        assert any("Назад" in t for t in texts)
        assert not any("Далее" in t for t in texts)

    def test_section_nav_kb_middle_section(self):
        from services.bot.handlers.guide import _section_nav_kb
        kb = _section_nav_kb("images")
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        texts = [b.text for b in all_buttons]
        assert any("Назад" in t for t in texts)
        assert any("Далее" in t for t in texts)

    def test_section_nav_kb_unknown_section(self):
        from services.bot.handlers.guide import _section_nav_kb
        # Unknown section: idx == -1, no prev/next buttons
        kb = _section_nav_kb("nonexistent")
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        texts = [b.text for b in all_buttons]
        assert not any("Назад" in t for t in texts)
        assert not any("Далее" in t for t in texts)

    def test_text_quick_start(self):
        from services.bot.handlers.guide import _text_quick_start
        result = _text_quick_start()
        assert "НейроБокс" in result
        assert "CR" in result

    def test_text_models_section(self):
        from services.bot.handlers.guide import _text_models_section
        result = _text_models_section()
        assert "Текстовые" in result

    def test_text_images_section(self):
        from services.bot.handlers.guide import _text_images_section
        result = _text_images_section()
        assert "картинок" in result.lower() or "Генерация" in result

    def test_text_video_section(self):
        from services.bot.handlers.guide import _text_video_section
        result = _text_video_section()
        assert "Видео" in result or "видео" in result

    def test_text_voice_section_tts_enabled(self):
        from services.bot.handlers.guide import _text_voice_section
        with patch("services.bot.handlers.guide.settings") as mock_s:
            mock_s.enable_tts = True
            mock_s.enable_music = True
            mock_s.serper_api_key = ""
            mock_s.free_daily_credits = 50
            result = _text_voice_section()
        assert "TTS" in result or "Озвучка" in result

    def test_text_voice_section_tts_disabled(self):
        from services.bot.handlers.guide import _text_voice_section
        with patch("services.bot.handlers.guide.settings") as mock_s:
            mock_s.enable_tts = False
            mock_s.enable_music = False
            mock_s.serper_api_key = ""
            mock_s.free_daily_credits = 50
            result = _text_voice_section()
        assert "Голос" in result or "отключена" in result

    def test_text_tools_section_with_search(self):
        from services.bot.handlers.guide import _text_tools_section
        with patch("services.bot.handlers.guide.settings") as mock_s:
            mock_s.serper_api_key = "somekey"
            result = _text_tools_section()
        assert "/search" in result

    def test_text_tools_section_without_search(self):
        from services.bot.handlers.guide import _text_tools_section
        with patch("services.bot.handlers.guide.settings") as mock_s:
            mock_s.serper_api_key = ""
            result = _text_tools_section()
        assert "/search" not in result

    def test_text_credits_section(self):
        from services.bot.handlers.guide import _text_credits_section
        result = _text_credits_section()
        assert "кредиты" in result.lower() or "CR" in result

    def test_text_bonuses_section(self):
        from services.bot.handlers.guide import _text_bonuses_section
        result = _text_bonuses_section()
        assert "Бонусы" in result

    def test_text_referral_section(self):
        from services.bot.handlers.guide import _text_referral_section
        result = _text_referral_section()
        assert "друг" in result.lower()

    def test_text_choose_model(self):
        from services.bot.handlers.guide import _text_choose_model
        result = _text_choose_model()
        assert "модель" in result.lower() or "модел" in result.lower()

    def test_text_faq(self):
        from services.bot.handlers.guide import _text_faq
        result = _text_faq()
        assert "FAQ" in result or "вопрос" in result.lower()

    async def test_get_section_text_packs(self):
        from services.bot.handlers.guide import _get_section_text
        fake_packs = {
            "start": {"label": "Старт", "credits": 100, "price_rub": 49, "discount": ""},
        }
        with patch("services.bot.handlers.guide.get_credit_packs", AsyncMock(return_value=fake_packs)):
            with patch("services.bot.handlers.guide.settings") as mock_s:
                mock_s.enable_stars_payment = True
                mock_s.enable_yookassa_payment = False
                mock_s.enable_cryptobot_payment = False
                result = await _get_section_text("packs")
        assert "Пакеты" in result or "CR" in result

    async def test_get_section_text_nonpacks(self):
        from services.bot.handlers.guide import _get_section_text
        result = await _get_section_text("start")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_get_section_text_unknown_falls_back(self):
        from services.bot.handlers.guide import _get_section_text
        result = await _get_section_text("totally_unknown_section")
        assert isinstance(result, str)


class TestGuideHandlers:
    async def test_msg_guide_command(self):
        from services.bot.handlers.guide import msg_guide
        msg = _make_message("/guide")
        await msg_guide(msg)
        msg.answer.assert_called_once()
        call_kwargs = msg.answer.call_args
        assert "Гайд" in (call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("text", ""))

    async def test_msg_guide_help(self):
        from services.bot.handlers.guide import msg_guide
        msg = _make_message("/help")
        await msg_guide(msg)
        msg.answer.assert_called_once()

    async def test_cb_guide_menu(self):
        from services.bot.handlers.guide import cb_guide_menu
        cb = _make_callback("guide:menu")
        await cb_guide_menu(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()

    async def test_cb_guide_section_valid(self):
        from services.bot.handlers.guide import cb_guide_section
        fake_packs = {
            "start": {"label": "Старт", "credits": 100, "price_rub": 49, "discount": ""},
        }
        with patch("services.bot.handlers.guide.get_credit_packs", AsyncMock(return_value=fake_packs)):
            cb = _make_callback("guide:text")
            await cb_guide_section(cb)
        cb.answer.assert_called()
        cb.message.answer.assert_called_once()

    async def test_cb_guide_section_packs(self):
        from services.bot.handlers.guide import cb_guide_section
        fake_packs = {"start": {"label": "Старт", "credits": 100, "price_rub": 49, "discount": ""}}
        with patch("services.bot.handlers.guide.get_credit_packs", AsyncMock(return_value=fake_packs)):
            with patch("services.bot.handlers.guide.settings") as mock_s:
                mock_s.enable_stars_payment = False
                mock_s.enable_yookassa_payment = False
                mock_s.enable_cryptobot_payment = False
                cb = _make_callback("guide:packs")
                await cb_guide_section(cb)
        cb.answer.assert_called()
        cb.message.answer.assert_called_once()

    async def test_cb_guide_section_invalid(self):
        from services.bot.handlers.guide import cb_guide_section
        cb = _make_callback("guide:nonexistent")
        await cb_guide_section(cb)
        cb.answer.assert_called()
        cb.message.answer.assert_not_called()

    async def test_cb_guide_section_empty_part(self):
        from services.bot.handlers.guide import cb_guide_section
        cb = _make_callback("guide:")
        await cb_guide_section(cb)
        cb.answer.assert_called()
        # falls back to showing menu
        cb.message.answer.assert_called_once()

    async def test_cb_guide_section_menu_data(self):
        from services.bot.handlers.guide import cb_guide_section
        cb = _make_callback("guide:menu")
        await cb_guide_section(cb)
        cb.answer.assert_called()
        cb.message.answer.assert_called_once()


# ===========================================================================
# model_select.py tests
# ===========================================================================

class TestModelSelectHelpers:
    def test_image_price_label_flux_turbo(self):
        from services.bot.handlers.model_select import _image_price_label
        label = _image_price_label("flux-2-turbo")
        assert "⚡" in label

    def test_image_price_label_midjourney(self):
        from services.bot.handlers.model_select import _image_price_label
        label = _image_price_label("midjourney")
        assert "⭐" in label

    def test_image_price_label_other(self):
        from services.bot.handlers.model_select import _image_price_label
        label = _image_price_label("dall-e-3")
        assert "⚡" not in label
        assert "⭐" not in label
        assert "CR" in label

    def test_image_models_with_prices_structure(self):
        from services.bot.handlers.model_select import IMAGE_MODELS
        assert len(IMAGE_MODELS) > 0
        name, mid, price_str, is_free = IMAGE_MODELS[0]
        assert isinstance(name, str)
        assert isinstance(mid, str)
        assert "CR" in price_str
        assert isinstance(is_free, bool)

    def test_music_models_with_prices_structure(self):
        from services.bot.handlers.model_select import MUSIC_MODELS
        assert len(MUSIC_MODELS) > 0
        name, mid, price_str, _ = MUSIC_MODELS[0]
        assert isinstance(name, str)
        assert isinstance(mid, str)
        assert "CR" in price_str

    def test_text_model_display_name_found(self):
        from services.bot.handlers.model_select import _text_model_display_name
        from shared.config.text_models import TEXT_MODELS
        if TEXT_MODELS:
            first_mid = TEXT_MODELS[0][1]
            first_name = TEXT_MODELS[0][0]
            assert _text_model_display_name(first_mid) == first_name

    def test_text_model_display_name_not_found(self):
        from services.bot.handlers.model_select import _text_model_display_name
        result = _text_model_display_name("unknown-model-xyz")
        assert result == "unknown-model-xyz"

    def test_image_model_display_name_found(self):
        from services.bot.handlers.model_select import _image_model_display_name, IMAGE_MODELS
        first_name, first_mid, _, _ = IMAGE_MODELS[0]
        assert _image_model_display_name(first_mid) == first_name

    def test_image_model_display_name_not_found(self):
        from services.bot.handlers.model_select import _image_model_display_name
        assert _image_model_display_name("does-not-exist") == "does-not-exist"

    def test_music_model_display_name_found(self):
        from services.bot.handlers.model_select import _music_model_display_name, MUSIC_MODELS
        first_name, first_mid, _, _ = MUSIC_MODELS[0]
        assert _music_model_display_name(first_mid) == first_name

    def test_music_model_display_name_not_found(self):
        from services.bot.handlers.model_select import _music_model_display_name
        assert _music_model_display_name("unknown") == "unknown"


class TestModelSelectHandlers:
    async def test_msg_select_model(self):
        from services.bot.handlers.model_select import msg_select_model
        msg = _make_message("⚙️ Модели")
        with patch("services.bot.handlers.model_select.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.model_select.get_user_model", AsyncMock(return_value="gpt-5-nano")):
                with patch("services.bot.handlers.model_select.settings") as mock_s:
                    mock_s.enable_video = False
                    mock_s.enable_tts = False
                    mock_s.enable_music = False
                    await msg_select_model(msg)
        msg.answer.assert_called_once()

    async def test_msg_select_model_all_features(self):
        from services.bot.handlers.model_select import msg_select_model
        msg = _make_message("/model")
        with patch("services.bot.handlers.model_select.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.model_select.get_user_model", AsyncMock(return_value="gpt-5-nano")):
                with patch("services.bot.handlers.model_select.settings") as mock_s:
                    mock_s.enable_video = True
                    mock_s.enable_tts = True
                    mock_s.enable_music = True
                    await msg_select_model(msg)
        msg.answer.assert_called_once()

    async def test_cb_select_model(self):
        from services.bot.handlers.model_select import cb_select_model
        cb = _make_callback("select_model")
        with patch("services.bot.handlers.model_select.get_user_model", AsyncMock(return_value="gpt-5-nano")):
            with patch("services.bot.handlers.model_select.settings") as mock_s:
                mock_s.enable_video = False
                mock_s.enable_tts = False
                mock_s.enable_music = False
                await cb_select_model(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()

    async def test_cb_select_text(self):
        from services.bot.handlers.model_select import cb_select_text
        cb = _make_callback("select_text_model")
        with patch("services.bot.handlers.model_select.get_user_model", AsyncMock(return_value="gpt-5-nano")):
            await cb_select_text(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()

    async def test_cb_select_image(self):
        from services.bot.handlers.model_select import cb_select_image
        cb = _make_callback("select_image_model")
        with patch("services.bot.handlers.model_select.get_user_model", AsyncMock(return_value="flux-2-turbo")):
            await cb_select_image(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()

    async def test_cb_set_text_valid(self):
        from services.bot.handlers.model_select import cb_set_text
        from shared.config.text_models import TEXT_MODELS
        if not TEXT_MODELS:
            pytest.skip("No text models configured")
        valid_mid = TEXT_MODELS[0][1]
        cb = _make_callback(f"set_text_{valid_mid}")
        with patch("services.bot.handlers.model_select.set_user_model", AsyncMock()):
            await cb_set_text(cb)
        cb.answer.assert_called()
        cb.message.answer.assert_called_once()

    async def test_cb_set_text_invalid(self):
        from services.bot.handlers.model_select import cb_set_text
        cb = _make_callback("set_text_totally-invalid-model-xyz")
        await cb_set_text(cb)
        cb.answer.assert_called_once_with("Не найдена", show_alert=True)
        cb.message.answer.assert_not_called()

    async def test_cb_set_img_valid(self):
        from services.bot.handlers.model_select import cb_set_img, IMAGE_MODELS
        valid_mid = IMAGE_MODELS[0][1]
        cb = _make_callback(f"set_img_{valid_mid}")
        with patch("services.bot.handlers.model_select.set_user_model", AsyncMock()):
            await cb_set_img(cb)
        cb.answer.assert_called()
        cb.message.answer.assert_called_once()

    async def test_cb_set_img_invalid(self):
        from services.bot.handlers.model_select import cb_set_img
        cb = _make_callback("set_img_totally-invalid-xyz")
        await cb_set_img(cb)
        cb.answer.assert_called_once_with("Не найдена", show_alert=True)
        cb.message.answer.assert_not_called()

    async def test_cb_select_music_disabled(self):
        from services.bot.handlers.model_select import cb_select_music
        cb = _make_callback("select_music_model")
        with patch("services.bot.handlers.model_select.settings") as mock_s:
            mock_s.enable_music = False
            await cb_select_music(cb)
        cb.answer.assert_called_once_with("Музыка временно недоступна", show_alert=True)

    async def test_cb_select_music_enabled(self):
        from services.bot.handlers.model_select import cb_select_music
        cb = _make_callback("select_music_model")
        with patch("services.bot.handlers.model_select.settings") as mock_s:
            mock_s.enable_music = True
            with patch("services.bot.handlers.model_select.get_user_model", AsyncMock(return_value="musicgen")):
                await cb_select_music(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()

    async def test_cb_set_music_disabled(self):
        from services.bot.handlers.model_select import cb_set_music
        cb = _make_callback("set_music_musicgen")
        with patch("services.bot.handlers.model_select.settings") as mock_s:
            mock_s.enable_music = False
            await cb_set_music(cb)
        cb.answer.assert_called_once_with("Музыка временно недоступна", show_alert=True)

    async def test_cb_set_music_invalid(self):
        from services.bot.handlers.model_select import cb_set_music
        cb = _make_callback("set_music_unknown-model-xyz")
        with patch("services.bot.handlers.model_select.settings") as mock_s:
            mock_s.enable_music = True
            await cb_set_music(cb)
        cb.answer.assert_called_once_with("Не найдена", show_alert=True)

    async def test_cb_set_music_valid(self):
        from services.bot.handlers.model_select import cb_set_music, MUSIC_MODELS
        valid_mid = MUSIC_MODELS[0][1]
        cb = _make_callback(f"set_music_{valid_mid}")
        with patch("services.bot.handlers.model_select.settings") as mock_s:
            mock_s.enable_music = True
            with patch("services.bot.handlers.model_select.set_user_model", AsyncMock()):
                await cb_set_music(cb)
        cb.answer.assert_called()
        cb.message.answer.assert_called_once()


# ===========================================================================
# modes.py tests
# ===========================================================================

class TestModesHandlers:
    async def test_msg_mode_open(self):
        from services.bot.handlers.modes import msg_mode_open
        msg = _make_message("🎭 Режим чата")
        with patch("services.bot.handlers.modes.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.modes.get_current_mode_display", AsyncMock(return_value="Обычный")):
                with patch("services.bot.handlers.modes.categories_kb", return_value=MagicMock()):
                    await msg_mode_open(msg)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "режим" in call_text.lower() or "Режим" in call_text

    async def test_cb_mode_open(self):
        from services.bot.handlers.modes import cb_mode_open
        cb = _make_callback("mode_open")
        with patch("services.bot.handlers.modes.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.modes.get_current_mode_display", AsyncMock(return_value="Обычный")):
                with patch("services.bot.handlers.modes.categories_kb", return_value=MagicMock()):
                    await cb_mode_open(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()

    async def test_cb_mode_category_custom_with_prompt(self):
        from services.bot.handlers.modes import cb_mode_category
        cb = _make_callback("mode_cat:custom")
        with patch("services.bot.handlers.modes.get_custom_mode_prompt", AsyncMock(return_value="My custom prompt text")):
            with patch("services.bot.handlers.modes.custom_mode_kb", return_value=MagicMock()):
                await cb_mode_category(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()
        call_text = cb.message.answer.call_args[0][0]
        assert "Мой режим" in call_text

    async def test_cb_mode_category_custom_without_prompt(self):
        from services.bot.handlers.modes import cb_mode_category
        cb = _make_callback("mode_cat:custom")
        with patch("services.bot.handlers.modes.get_custom_mode_prompt", AsyncMock(return_value=None)):
            with patch("services.bot.handlers.modes.custom_mode_kb", return_value=MagicMock()):
                await cb_mode_category(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()
        call_text = cb.message.answer.call_args[0][0]
        assert "промпт" in call_text.lower()

    async def test_cb_mode_category_no_modes(self):
        from services.bot.handlers.modes import cb_mode_category
        cb = _make_callback("mode_cat:Программирование")
        with patch("services.bot.handlers.modes.get_modes_by_category", AsyncMock(return_value=[])):
            with patch("services.bot.handlers.modes.back_to_main_kb", return_value=MagicMock()):
                await cb_mode_category(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()
        call_text = cb.message.answer.call_args[0][0]
        assert "нет" in call_text.lower() or "пока" in call_text.lower()

    async def test_cb_mode_category_with_modes(self):
        from services.bot.handlers.modes import cb_mode_category
        cb = _make_callback("mode_cat:Программирование")
        fake_modes = [{"id": 1, "name": "Python Dev", "emoji": "🐍", "description": ""}]
        with patch("services.bot.handlers.modes.get_modes_by_category", AsyncMock(return_value=fake_modes)):
            with patch("services.bot.handlers.modes.modes_in_category_kb", return_value=MagicMock()):
                await cb_mode_category(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()

    async def test_cb_mode_category_known_label(self):
        from services.bot.handlers.modes import cb_mode_category
        # Test with a category that has a predefined label
        cb = _make_callback("mode_cat:Универсальный")
        fake_modes = [{"id": 1, "name": "General", "emoji": "🔮", "description": ""}]
        with patch("services.bot.handlers.modes.get_modes_by_category", AsyncMock(return_value=fake_modes)):
            with patch("services.bot.handlers.modes.modes_in_category_kb", return_value=MagicMock()):
                await cb_mode_category(cb)
        cb.message.answer.assert_called_once()
        call_text = cb.message.answer.call_args[0][0]
        assert "Универсальный" in call_text

    async def test_cb_mode_select_valid(self):
        from services.bot.handlers.modes import cb_mode_select
        cb = _make_callback("mode_select:42")
        fake_mode = {"id": 42, "name": "Dev", "emoji": "💻", "description": ""}
        with patch("services.bot.handlers.modes.get_mode_by_id", AsyncMock(return_value=fake_mode)):
            with patch("services.bot.handlers.modes.set_mode", AsyncMock()):
                with patch("services.bot.handlers.modes.back_to_main_kb", return_value=MagicMock()):
                    await cb_mode_select(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()
        call_text = cb.message.answer.call_args[0][0]
        assert "Dev" in call_text

    async def test_cb_mode_select_not_found(self):
        from services.bot.handlers.modes import cb_mode_select
        cb = _make_callback("mode_select:9999")
        with patch("services.bot.handlers.modes.get_mode_by_id", AsyncMock(return_value=None)):
            with patch("services.bot.handlers.modes.back_to_main_kb", return_value=MagicMock()):
                await cb_mode_select(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()
        call_text = cb.message.answer.call_args[0][0]
        assert "не найден" in call_text.lower()

    async def test_cb_mode_select_invalid_id(self):
        from services.bot.handlers.modes import cb_mode_select
        cb = _make_callback("mode_select:notanumber")
        await cb_mode_select(cb)
        # ValueError caught, returns without answering
        cb.message.answer.assert_not_called()

    async def test_cb_custom_edit(self):
        from services.bot.handlers.modes import cb_custom_edit
        cb = _make_callback("mode_custom_edit")
        state = AsyncMock(spec=FSMContext)
        state.set_state = AsyncMock()
        await cb_custom_edit(cb, state)
        cb.answer.assert_called_once()
        state.set_state.assert_called_once()
        cb.message.answer.assert_called_once()

    async def test_cb_custom_delete(self):
        from services.bot.handlers.modes import cb_custom_delete
        cb = _make_callback("mode_custom_delete")
        with patch("services.bot.handlers.modes.set_custom_mode", AsyncMock()):
            with patch("services.bot.handlers.modes.back_to_main_kb", return_value=MagicMock()):
                await cb_custom_delete(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()

    async def test_mode_enter_prompt_valid(self):
        from services.bot.handlers.modes import mode_enter_prompt
        msg = _make_message("This is my system prompt for the bot.")
        state = AsyncMock(spec=FSMContext)
        state.clear = AsyncMock()
        with patch("services.bot.handlers.modes.set_custom_mode", AsyncMock()):
            with patch("services.bot.handlers.modes.back_to_main_kb", return_value=MagicMock()):
                await mode_enter_prompt(msg, state)
        state.clear.assert_called_once()
        msg.answer.assert_called_once()

    async def test_mode_enter_prompt_empty(self):
        from services.bot.handlers.modes import mode_enter_prompt
        msg = _make_message("   ")
        msg.text = "   "
        state = AsyncMock(spec=FSMContext)
        await mode_enter_prompt(msg, state)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "непустой" in call_text

    async def test_mode_enter_prompt_long_text_truncated(self):
        from services.bot.handlers.modes import mode_enter_prompt
        long_text = "a" * 3000
        msg = _make_message(long_text)
        state = AsyncMock(spec=FSMContext)
        state.clear = AsyncMock()
        with patch("services.bot.handlers.modes.set_custom_mode", AsyncMock()) as mock_set:
            with patch("services.bot.handlers.modes.back_to_main_kb", return_value=MagicMock()):
                await mode_enter_prompt(msg, state)
        # Verify that the saved text was truncated to 2000 chars
        saved_text = mock_set.call_args[0][1]
        assert len(saved_text) <= 2000

    async def test_mode_non_text(self):
        from services.bot.handlers.modes import mode_non_text
        msg = _make_message()
        msg.text = None
        state = AsyncMock(spec=FSMContext)
        await mode_non_text(msg, state)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "текст" in call_text.lower()

    async def test_mode_cancel(self):
        from services.bot.handlers.modes import mode_cancel
        msg = _make_message("/cancel")
        state = AsyncMock(spec=FSMContext)
        state.clear = AsyncMock()
        with patch("services.bot.handlers.modes.back_to_main_kb", return_value=MagicMock()):
            await mode_cancel(msg, state)
        state.clear.assert_called_once()
        msg.answer.assert_called_once()


# ===========================================================================
# tools.py tests
# ===========================================================================

class TestToolsHelpers:
    def test_arg_from_command_with_arg(self):
        from services.bot.handlers.tools import _arg_from_command
        assert _arg_from_command("/search hello world") == "hello world"

    def test_arg_from_command_without_arg(self):
        from services.bot.handlers.tools import _arg_from_command
        assert _arg_from_command("/search") == ""

    def test_arg_from_command_empty(self):
        from services.bot.handlers.tools import _arg_from_command
        assert _arg_from_command("") == ""

    def test_strip_html_basic(self):
        from services.bot.handlers.tools import _strip_html
        result = _strip_html("<html><body><p>Hello World</p></body></html>")
        assert "Hello World" in result
        assert "<" not in result

    def test_strip_html_empty(self):
        from services.bot.handlers.tools import _strip_html
        assert _strip_html("") == ""


class TestToolsHandlers:
    async def test_cmd_search_no_serper_key(self):
        from services.bot.handlers.tools import cmd_search
        msg = _make_message("/search query")
        with patch("services.bot.handlers.tools.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.tools.settings") as mock_s:
                mock_s.serper_api_key = ""
                await cmd_search(msg)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "недоступен" in call_text.lower() or "недоступ" in call_text.lower()

    async def test_cmd_search_no_query(self):
        from services.bot.handlers.tools import cmd_search
        msg = _make_message("/search")
        with patch("services.bot.handlers.tools.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.tools.settings") as mock_s:
                mock_s.serper_api_key = "somekey"
                await cmd_search(msg)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "/search" in call_text

    async def test_cmd_search_insufficient_credits(self):
        from services.bot.handlers.tools import cmd_search
        msg = _make_message("/search best laptops")
        with patch("services.bot.handlers.tools.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.tools.settings") as mock_s:
                mock_s.serper_api_key = "somekey"
                with patch("services.bot.handlers.tools.spend_credits", AsyncMock(return_value={"ok": False, "message": "Недостаточно CR"})):
                    await cmd_search(msg)
        msg.answer.assert_called()
        # Should have answered with the error message
        any_call_with_credits_msg = any(
            "Недостаточно CR" in str(c) for c in msg.answer.call_args_list
        )
        assert any_call_with_credits_msg

    async def test_cmd_search_no_credits_no_message(self):
        from services.bot.handlers.tools import cmd_search
        msg = _make_message("/search query text")
        with patch("services.bot.handlers.tools.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.tools.settings") as mock_s:
                mock_s.serper_api_key = "somekey"
                with patch("services.bot.handlers.tools.spend_credits", AsyncMock(return_value={"ok": False})):
                    with patch("services.bot.handlers.tools.smart_paywall_message", AsyncMock(return_value=("paywall text", None))):
                        await cmd_search(msg)
        msg.answer.assert_called()

    async def test_cmd_search_no_snippets(self):
        from services.bot.handlers.tools import cmd_search
        msg = _make_message("/search query text")
        status_msg = AsyncMock()
        msg.answer.return_value = status_msg
        with patch("services.bot.handlers.tools.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.tools.settings") as mock_s:
                mock_s.serper_api_key = "validkey"
                with patch("services.bot.handlers.tools.spend_credits", AsyncMock(return_value={"ok": True, "bought": 10, "free": 5})):
                    with patch("services.bot.handlers.tools._search_serper", AsyncMock(return_value="")):
                        with patch("services.bot.handlers.tools.refund_spend_credits", AsyncMock()):
                            await cmd_search(msg)
        status_msg.edit_text.assert_called_once()
        call_text = status_msg.edit_text.call_args[0][0]
        assert "результат" in call_text.lower() or "вернен" in call_text.lower() or "возвращен" in call_text.lower() or "CR" in call_text

    async def test_cmd_search_ai_error(self):
        from services.bot.handlers.tools import cmd_search
        msg = _make_message("/search query text")
        status_msg = AsyncMock()
        msg.answer.return_value = status_msg
        with patch("services.bot.handlers.tools.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.tools.settings") as mock_s:
                mock_s.serper_api_key = "validkey"
                with patch("services.bot.handlers.tools.spend_credits", AsyncMock(return_value={"ok": True, "bought": 10, "free": 5})):
                    with patch("services.bot.handlers.tools._search_serper", AsyncMock(return_value="some results")):
                        with patch("services.bot.handlers.tools.generate_text", AsyncMock(return_value={"ok": False, "error": "AI down"})):
                            with patch("services.bot.handlers.tools.refund_spend_credits", AsyncMock()):
                                await cmd_search(msg)
        status_msg.edit_text.assert_called_once()

    async def test_cmd_search_success(self):
        from services.bot.handlers.tools import cmd_search
        msg = _make_message("/search query text")
        status_msg = AsyncMock()
        msg.answer.return_value = status_msg
        with patch("services.bot.handlers.tools.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.tools.settings") as mock_s:
                mock_s.serper_api_key = "validkey"
                with patch("services.bot.handlers.tools.spend_credits", AsyncMock(return_value={"ok": True, "bought": 10, "free": 5})):
                    with patch("services.bot.handlers.tools._search_serper", AsyncMock(return_value="some snippets")):
                        with patch("services.bot.handlers.tools.generate_text", AsyncMock(return_value={"ok": True, "text": "AI answer"})):
                            await cmd_search(msg)
        status_msg.edit_text.assert_called_once()
        call_text = status_msg.edit_text.call_args[0][0]
        assert "AI answer" in call_text

    async def test_cmd_summary_no_url(self):
        from services.bot.handlers.tools import cmd_summary
        msg = _make_message("/summary")
        with patch("services.bot.handlers.tools.get_or_create_user", AsyncMock()):
            await cmd_summary(msg)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "/summary" in call_text

    async def test_cmd_summary_invalid_url(self):
        from services.bot.handlers.tools import cmd_summary
        msg = _make_message("/summary not-a-url")
        with patch("services.bot.handlers.tools.get_or_create_user", AsyncMock()):
            await cmd_summary(msg)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "/summary" in call_text

    async def test_cmd_summary_no_credits(self):
        from services.bot.handlers.tools import cmd_summary
        msg = _make_message("/summary https://example.com/article")
        with patch("services.bot.handlers.tools.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.tools.spend_credits", AsyncMock(return_value={"ok": False, "message": "Нет CR"})):
                await cmd_summary(msg)
        msg.answer.assert_called()

    async def test_cmd_summary_http_error(self):
        import httpx
        from services.bot.handlers.tools import cmd_summary
        msg = _make_message("/summary https://example.com/article")
        status_msg = AsyncMock()
        msg.answer.return_value = status_msg
        with patch("services.bot.handlers.tools.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.tools.spend_credits", AsyncMock(return_value={"ok": True, "bought": 5, "free": 2})):
                with patch("services.bot.handlers.tools.refund_spend_credits", AsyncMock()):
                    with patch("httpx.AsyncClient") as mock_client_cls:
                        mock_client = AsyncMock()
                        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                        mock_client.__aexit__ = AsyncMock(return_value=False)
                        mock_client.get = AsyncMock(side_effect=RuntimeError("connection failed"))
                        mock_client_cls.return_value = mock_client
                        await cmd_summary(msg)
        status_msg.edit_text.assert_called_once()
        call_text = status_msg.edit_text.call_args[0][0]
        assert "загрузить" in call_text.lower() or "CR" in call_text

    async def test_cmd_summary_too_short_text(self):
        import httpx
        from services.bot.handlers.tools import cmd_summary
        msg = _make_message("/summary https://example.com/article")
        status_msg = AsyncMock()
        msg.answer.return_value = status_msg

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>Short</body></html>"

        with patch("services.bot.handlers.tools.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.tools.spend_credits", AsyncMock(return_value={"ok": True, "bought": 5, "free": 2})):
                with patch("services.bot.handlers.tools.refund_spend_credits", AsyncMock()):
                    with patch("services.bot.handlers.tools._strip_html", return_value="Too short"):
                        with patch("httpx.AsyncClient") as mock_client_cls:
                            mock_client = AsyncMock()
                            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                            mock_client.__aexit__ = AsyncMock(return_value=False)
                            mock_client.get = AsyncMock(return_value=mock_resp)
                            mock_client_cls.return_value = mock_client
                            await cmd_summary(msg)
        status_msg.edit_text.assert_called_once()
        call_text = status_msg.edit_text.call_args[0][0]
        assert "мало текста" in call_text.lower() or "CR" in call_text

    async def test_cmd_summary_success(self):
        from services.bot.handlers.tools import cmd_summary
        msg = _make_message("/summary https://example.com/article")
        status_msg = AsyncMock()
        msg.answer.return_value = status_msg

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<p>" + "Long article text. " * 50 + "</p>"

        with patch("services.bot.handlers.tools.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.tools.spend_credits", AsyncMock(return_value={"ok": True, "bought": 5, "free": 2})):
                with patch("services.bot.handlers.tools._strip_html", return_value="Long article text. " * 50):
                    with patch("services.bot.handlers.tools.generate_text", AsyncMock(return_value={"ok": True, "text": "Summary text"})):
                        with patch("httpx.AsyncClient") as mock_client_cls:
                            mock_client = AsyncMock()
                            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                            mock_client.__aexit__ = AsyncMock(return_value=False)
                            mock_client.get = AsyncMock(return_value=mock_resp)
                            mock_client_cls.return_value = mock_client
                            await cmd_summary(msg)
        status_msg.edit_text.assert_called_once()
        call_text = status_msg.edit_text.call_args[0][0]
        assert "Summary text" in call_text

    async def test_cmd_code_no_code(self):
        from services.bot.handlers.tools import cmd_code
        msg = _make_message("/code")
        with patch("services.bot.handlers.tools.get_or_create_user", AsyncMock()):
            await cmd_code(msg)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "/code" in call_text

    async def test_cmd_code_no_credits(self):
        from services.bot.handlers.tools import cmd_code
        msg = _make_message("/code print('hello')")
        with patch("services.bot.handlers.tools.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.tools.spend_credits", AsyncMock(return_value={"ok": False, "message": "Нет CR"})):
                await cmd_code(msg)
        msg.answer.assert_called()

    async def test_cmd_code_ai_error(self):
        from services.bot.handlers.tools import cmd_code
        msg = _make_message("/code print('hello')")
        status_msg = AsyncMock()
        msg.answer.return_value = status_msg
        with patch("services.bot.handlers.tools.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.tools.spend_credits", AsyncMock(return_value={"ok": True, "bought": 5, "free": 2})):
                with patch("services.bot.handlers.tools.generate_text", AsyncMock(return_value={"ok": False, "error": "AI error"})):
                    with patch("services.bot.handlers.tools.refund_spend_credits", AsyncMock()):
                        await cmd_code(msg)
        status_msg.edit_text.assert_called_once()

    async def test_cmd_code_success(self):
        from services.bot.handlers.tools import cmd_code
        msg = _make_message("/code print('hello')")
        status_msg = AsyncMock()
        msg.answer.return_value = status_msg
        with patch("services.bot.handlers.tools.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.tools.spend_credits", AsyncMock(return_value={"ok": True, "bought": 5, "free": 2})):
                with patch("services.bot.handlers.tools.generate_text", AsyncMock(return_value={"ok": True, "text": "Code analysis here"})):
                    await cmd_code(msg)
        status_msg.edit_text.assert_called_once()
        call_text = status_msg.edit_text.call_args[0][0]
        assert "Code analysis here" in call_text

    async def test_cmd_code_no_credits_no_message(self):
        from services.bot.handlers.tools import cmd_code
        msg = _make_message("/code x = 1")
        with patch("services.bot.handlers.tools.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.tools.spend_credits", AsyncMock(return_value={"ok": False})):
                with patch("services.bot.handlers.tools.smart_paywall_message", AsyncMock(return_value=("paywall", None))):
                    await cmd_code(msg)
        msg.answer.assert_called()


# ===========================================================================
# feedback.py tests
# ===========================================================================

class TestFeedbackHandlers:
    async def test_cb_screen_feedback(self):
        from services.bot.handlers.feedback import cb_screen_feedback
        cb = _make_callback("screen_feedback")
        with patch("services.bot.handlers.feedback.get_admin_text", AsyncMock(return_value="Support text")):
            await cb_screen_feedback(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()

    async def test_cb_screen_support(self):
        from services.bot.handlers.feedback import cb_screen_feedback
        cb = _make_callback("screen_support")
        with patch("services.bot.handlers.feedback.get_admin_text", AsyncMock(return_value="Support text")):
            await cb_screen_feedback(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()

    async def test_cmd_paysupport(self):
        from services.bot.handlers.feedback import cmd_paysupport
        msg = _make_message("/paysupport")
        with patch("services.bot.handlers.feedback.get_admin_text", AsyncMock(return_value="Support text")):
            await cmd_paysupport(msg)
        msg.answer.assert_called_once()

    def test_is_feedback_msg_valid(self):
        from services.bot.handlers.feedback import _is_feedback_msg
        msg = _make_message("Обратная связь: это отличный бот")
        assert _is_feedback_msg(msg) is True

    def test_is_feedback_msg_case_insensitive(self):
        from services.bot.handlers.feedback import _is_feedback_msg
        msg = _make_message("ОБРАТНАЯ СВЯЗЬ: текст")
        assert _is_feedback_msg(msg) is True

    def test_is_feedback_msg_not_feedback(self):
        from services.bot.handlers.feedback import _is_feedback_msg
        msg = _make_message("Привет, как дела?")
        assert _is_feedback_msg(msg) is False

    async def test_msg_feedback_inline_empty_body(self):
        from services.bot.handlers.feedback import msg_feedback_inline
        msg = _make_message("Обратная связь:")
        await msg_feedback_inline(msg)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "текст" in call_text.lower()

    async def test_msg_feedback_inline_too_long(self):
        from services.bot.handlers.feedback import msg_feedback_inline, MAX_FEEDBACK_LEN
        long_body = "x" * (MAX_FEEDBACK_LEN + 1)
        msg = _make_message(f"Обратная связь: {long_body}")
        await msg_feedback_inline(msg)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "длинное" in call_text.lower() or "макс" in call_text.lower()

    async def test_msg_feedback_inline_success_no_admins(self):
        from services.bot.handlers.feedback import msg_feedback_inline
        msg = _make_message("Обратная связь: Всё работает отлично!")
        pool = _make_pool()

        with patch("services.bot.handlers.feedback.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.feedback.get_pool", AsyncMock(return_value=pool)):
                with patch("services.bot.handlers.feedback.settings") as mock_s:
                    mock_s.admin_id_list = []
                    await msg_feedback_inline(msg)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "Спасибо" in call_text

    async def test_msg_feedback_inline_success_with_admins(self):
        from services.bot.handlers.feedback import msg_feedback_inline
        msg = _make_message("Обратная связь: Хочу предложить новую фичу!")
        pool = _make_pool()

        with patch("services.bot.handlers.feedback.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.feedback.get_pool", AsyncMock(return_value=pool)):
                with patch("services.bot.handlers.feedback.settings") as mock_s:
                    mock_s.admin_id_list = [111, 222]
                    await msg_feedback_inline(msg)
        msg.answer.assert_called_once()
        # Bot should have sent to admins
        assert msg.bot.send_message.call_count >= 1

    async def test_msg_feedback_inline_admin_send_fails_silently(self):
        from services.bot.handlers.feedback import msg_feedback_inline
        msg = _make_message("Обратная связь: Test feedback")
        msg.bot.send_message = AsyncMock(side_effect=Exception("Bot API error"))
        pool = _make_pool()

        with patch("services.bot.handlers.feedback.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.feedback.get_pool", AsyncMock(return_value=pool)):
                with patch("services.bot.handlers.feedback.settings") as mock_s:
                    mock_s.admin_id_list = [111]
                    # Should not raise even if bot.send_message fails
                    await msg_feedback_inline(msg)
        msg.answer.assert_called_once()


# ===========================================================================
# saved_export.py tests
# ===========================================================================

class TestSavedExportHandlers:
    async def test_send_favorites_empty(self):
        from services.bot.handlers.saved_export import _send_favorites
        msg = _make_message()
        with patch("services.bot.handlers.saved_export.list_saved_prompts", AsyncMock(return_value=[])):
            await _send_favorites(msg, 12345)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "нет" in call_text.lower() or "пока" in call_text.lower()

    async def test_send_favorites_with_items(self):
        from services.bot.handlers.saved_export import _send_favorites
        msg = _make_message()
        prompts = [
            {"id": 1, "title": "My Prompt 1", "content": "content1"},
            {"id": 2, "title": "My Prompt 2", "content": "content2"},
        ]
        with patch("services.bot.handlers.saved_export.list_saved_prompts", AsyncMock(return_value=prompts)):
            await _send_favorites(msg, 12345)
        msg.answer.assert_called_once()
        call_kwargs = msg.answer.call_args[1] if msg.answer.call_args[1] else {}
        assert "reply_markup" in call_kwargs or msg.answer.call_args[0]

    async def test_send_export_empty(self):
        from services.bot.handlers.saved_export import _send_export
        msg = _make_message()
        with patch("services.bot.handlers.saved_export.get_chat_history_for_export", AsyncMock(return_value=[])):
            await _send_export(msg, 12345)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "пуст" in call_text.lower()

    async def test_send_export_with_history(self):
        from services.bot.handlers.saved_export import _send_export
        msg = _make_message()
        rows = [
            {"role": "user", "content": "Hello", "created_at": datetime(2025, 1, 1, 12, 0)},
            {"role": "assistant", "content": "Hi there!", "created_at": datetime(2025, 1, 1, 12, 1)},
        ]
        with patch("services.bot.handlers.saved_export.get_chat_history_for_export", AsyncMock(return_value=rows)):
            await _send_export(msg, 12345)
        msg.answer_document.assert_called_once()

    async def test_cmd_favorites(self):
        from services.bot.handlers.saved_export import cmd_favorites
        msg = _make_message("/favorites")
        with patch("services.bot.handlers.saved_export.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.saved_export.list_saved_prompts", AsyncMock(return_value=[])):
                await cmd_favorites(msg)
        msg.answer.assert_called_once()

    async def test_cmd_export(self):
        from services.bot.handlers.saved_export import cmd_export
        msg = _make_message("/export")
        with patch("services.bot.handlers.saved_export.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.saved_export.get_chat_history_for_export", AsyncMock(return_value=[])):
                await cmd_export(msg)
        msg.answer.assert_called_once()

    async def test_cmd_save_with_inline_text(self):
        from services.bot.handlers.saved_export import cmd_save
        msg = _make_message("/save Write a poem about the moon")
        with patch("services.bot.handlers.saved_export.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.saved_export.save_prompt", AsyncMock(return_value=42)):
                await cmd_save(msg)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "42" in call_text or "Сохранил" in call_text

    async def test_cmd_save_with_reply(self):
        from services.bot.handlers.saved_export import cmd_save
        msg = _make_message("/save")
        reply = _make_message("Content from reply message")
        msg.reply_to_message = reply
        with patch("services.bot.handlers.saved_export.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.saved_export.save_prompt", AsyncMock(return_value=7)):
                await cmd_save(msg)
        msg.answer.assert_called_once()

    async def test_cmd_save_from_history(self):
        from services.bot.handlers.saved_export import cmd_save
        msg = _make_message("/save")
        msg.reply_to_message = None
        history = [
            {"role": "user", "content": "What is Python?", "created_at": datetime(2025, 1, 1)},
            {"role": "assistant", "content": "Python is a language.", "created_at": datetime(2025, 1, 1)},
        ]
        with patch("services.bot.handlers.saved_export.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.saved_export.get_chat_history_for_export", AsyncMock(return_value=history)):
                with patch("services.bot.handlers.saved_export.save_prompt", AsyncMock(return_value=3)):
                    await cmd_save(msg)
        msg.answer.assert_called_once()

    async def test_cmd_save_no_content(self):
        from services.bot.handlers.saved_export import cmd_save
        msg = _make_message("/save")
        msg.reply_to_message = None
        with patch("services.bot.handlers.saved_export.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.saved_export.get_chat_history_for_export", AsyncMock(return_value=[])):
                await cmd_save(msg)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "/save" in call_text

    async def test_cb_screen_favorites(self):
        from services.bot.handlers.saved_export import cb_screen_favorites
        cb = _make_callback("screen_favorites")
        with patch("services.bot.handlers.saved_export.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.saved_export.list_saved_prompts", AsyncMock(return_value=[])):
                await cb_screen_favorites(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()

    async def test_cb_run_saved_not_found(self):
        from services.bot.handlers.saved_export import cb_run_saved
        cb = _make_callback("run_saved_999")
        with patch("services.bot.handlers.saved_export.get_saved_prompt", AsyncMock(return_value=None)):
            await cb_run_saved(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()
        call_text = cb.message.answer.call_args[0][0]
        assert "не найден" in call_text.lower()

    async def test_cb_run_saved_no_credits(self):
        from services.bot.handlers.saved_export import cb_run_saved
        cb = _make_callback("run_saved_1")
        prompt_row = {"content": "Write a poem", "title": "Poem"}
        with patch("services.bot.handlers.saved_export.get_saved_prompt", AsyncMock(return_value=prompt_row)):
            with patch("services.bot.handlers.saved_export.get_user_model", AsyncMock(return_value="gpt-5-nano")):
                with patch("services.bot.handlers.saved_export.spend_credits", AsyncMock(return_value={"ok": False, "message": "Нет CR"})):
                    await cb_run_saved(cb)
        cb.message.answer.assert_called()

    async def test_cb_run_saved_success(self):
        from services.bot.handlers.saved_export import cb_run_saved
        cb = _make_callback("run_saved_1")
        prompt_row = {"content": "Write a poem", "title": "Poem"}
        with patch("services.bot.handlers.saved_export.get_saved_prompt", AsyncMock(return_value=prompt_row)):
            with patch("services.bot.handlers.saved_export.get_user_model", AsyncMock(return_value="gpt-5-nano")):
                with patch("services.bot.handlers.saved_export.spend_credits", AsyncMock(return_value={"ok": True, "bought": 5, "free": 2})):
                    with patch("services.bot.handlers.saved_export.get_chat_history", AsyncMock(return_value=[])):
                        with patch("services.bot.handlers.saved_export.get_system_prompt", AsyncMock(return_value=None)):
                            with patch("services.bot.handlers.saved_export.generate_text", AsyncMock(return_value={"ok": True, "text": "Here is your poem"})):
                                with patch("services.bot.handlers.saved_export.append_chat_message", AsyncMock()):
                                    cb.message.chat.do = AsyncMock()
                                    await cb_run_saved(cb)
        cb.message.answer.assert_called()
        call_text = cb.message.answer.call_args[0][0]
        assert "Here is your poem" in call_text

    async def test_cb_run_saved_ai_error(self):
        from services.bot.handlers.saved_export import cb_run_saved
        cb = _make_callback("run_saved_1")
        prompt_row = {"content": "Write a poem", "title": "Poem"}
        with patch("services.bot.handlers.saved_export.get_saved_prompt", AsyncMock(return_value=prompt_row)):
            with patch("services.bot.handlers.saved_export.get_user_model", AsyncMock(return_value="gpt-5-nano")):
                with patch("services.bot.handlers.saved_export.spend_credits", AsyncMock(return_value={"ok": True, "bought": 5, "free": 2})):
                    with patch("services.bot.handlers.saved_export.get_chat_history", AsyncMock(return_value=[])):
                        with patch("services.bot.handlers.saved_export.get_system_prompt", AsyncMock(return_value=None)):
                            with patch("services.bot.handlers.saved_export.generate_text", AsyncMock(return_value={"ok": False, "error": "AI broke"})):
                                cb.message.chat.do = AsyncMock()
                                await cb_run_saved(cb)
        cb.message.answer.assert_called()
        call_text = cb.message.answer.call_args[0][0]
        assert "AI broke" in call_text or "❌" in call_text

    async def test_cb_export_chat(self):
        from services.bot.handlers.saved_export import cb_export
        cb = _make_callback("export_chat")
        with patch("services.bot.handlers.saved_export.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.saved_export.get_chat_history_for_export", AsyncMock(return_value=[])):
                await cb_export(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()

    async def test_cb_run_saved_no_credits_no_message(self):
        from services.bot.handlers.saved_export import cb_run_saved
        cb = _make_callback("run_saved_1")
        prompt_row = {"content": "Write a poem", "title": "Poem"}
        with patch("services.bot.handlers.saved_export.get_saved_prompt", AsyncMock(return_value=prompt_row)):
            with patch("services.bot.handlers.saved_export.get_user_model", AsyncMock(return_value="gpt-5-nano")):
                with patch("services.bot.handlers.saved_export.spend_credits", AsyncMock(return_value={"ok": False})):
                    await cb_run_saved(cb)
        cb.message.answer.assert_called()
        call_text = cb.message.answer.call_args[0][0]
        assert "кредит" in call_text.lower()


# ===========================================================================
# ref_promo_stats.py tests
# ===========================================================================

class TestRefPromoStatsHandlers:
    async def test_send_ref_screen_basic(self):
        from services.bot.handlers.ref_promo_stats import _send_ref_screen
        msg = _make_message()
        pool = _make_pool(fetchval=0)

        with patch("services.bot.handlers.ref_promo_stats.get_referral_code", AsyncMock(return_value="ABC123")):
            with patch("services.bot.handlers.ref_promo_stats.get_pool", AsyncMock(return_value=pool)):
                with patch("services.bot.handlers.ref_promo_stats.settings") as mock_s:
                    mock_s.bot_username = "neurobox_bot"
                    await _send_ref_screen(msg, 12345)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "ABC123" in call_text or "neurobox_bot" in call_text

    async def test_send_ref_screen_max_level(self):
        from services.bot.handlers.ref_promo_stats import _send_ref_screen
        msg = _make_message()
        pool = _make_pool(fetchval=100)  # 100 referrals = max level

        with patch("services.bot.handlers.ref_promo_stats.get_referral_code", AsyncMock(return_value="XYZ")):
            with patch("services.bot.handlers.ref_promo_stats.get_pool", AsyncMock(return_value=pool)):
                with patch("services.bot.handlers.ref_promo_stats.settings") as mock_s:
                    mock_s.bot_username = "neurobox_bot"
                    await _send_ref_screen(msg, 12345)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "Максимальный" in call_text

    async def test_send_mystats_user_not_found(self):
        from services.bot.handlers.ref_promo_stats import _send_mystats
        msg = _make_message()
        pool = _make_pool(fetchrow=None, fetchval=0)

        with patch("services.bot.handlers.ref_promo_stats.get_pool", AsyncMock(return_value=pool)):
            await _send_mystats(msg, 12345)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "недоступна" in call_text.lower()

    async def test_send_mystats_found(self):
        from services.bot.handlers.ref_promo_stats import _send_mystats
        msg = _make_message()

        user_row = {
            "credits_total_spent": 250,
            "referral_count": 3,
            "total_payments_rub": 500.0,
            "created_at": datetime(2025, 1, 1),
        }

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=user_row)
        conn.fetchval = AsyncMock(return_value=10)

        pool = AsyncMock()
        pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False)
        ))

        with patch("services.bot.handlers.ref_promo_stats.get_pool", AsyncMock(return_value=pool)):
            await _send_mystats(msg, 12345)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "250" in call_text
        assert "3" in call_text

    async def test_cmd_ref(self):
        from services.bot.handlers.ref_promo_stats import cmd_ref
        msg = _make_message("/ref")
        pool = _make_pool(fetchval=0)

        with patch("services.bot.handlers.ref_promo_stats.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.ref_promo_stats.get_referral_code", AsyncMock(return_value="REF123")):
                with patch("services.bot.handlers.ref_promo_stats.get_pool", AsyncMock(return_value=pool)):
                    with patch("services.bot.handlers.ref_promo_stats.settings") as mock_s:
                        mock_s.bot_username = "test_bot"
                        await cmd_ref(msg)
        msg.answer.assert_called_once()

    async def test_cmd_promo_no_code(self):
        from services.bot.handlers.ref_promo_stats import cmd_promo
        msg = _make_message("/promo")
        with patch("services.bot.handlers.ref_promo_stats.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.ref_promo_stats.apply_promocode", AsyncMock(return_value={"ok": False, "error": "Не найден"})):
                await cmd_promo(msg)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "❌" in call_text

    async def test_cmd_promo_invalid(self):
        from services.bot.handlers.ref_promo_stats import cmd_promo
        msg = _make_message("/promo BADCODE")
        with patch("services.bot.handlers.ref_promo_stats.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.ref_promo_stats.apply_promocode", AsyncMock(return_value={"ok": False, "error": "Неверный код"})):
                await cmd_promo(msg)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "Неверный код" in call_text

    async def test_cmd_promo_success(self):
        from services.bot.handlers.ref_promo_stats import cmd_promo
        msg = _make_message("/promo WELCOME100")
        with patch("services.bot.handlers.ref_promo_stats.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.ref_promo_stats.apply_promocode", AsyncMock(return_value={"ok": True, "credits": 100})):
                await cmd_promo(msg)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "100" in call_text
        assert "✅" in call_text

    async def test_cmd_mystats(self):
        from services.bot.handlers.ref_promo_stats import cmd_mystats
        msg = _make_message("/mystats")
        user_row = {
            "credits_total_spent": 50,
            "referral_count": 0,
            "total_payments_rub": 0,
            "created_at": datetime(2025, 1, 1),
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=user_row)
        conn.fetchval = AsyncMock(return_value=5)
        pool = AsyncMock()
        pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False)
        ))
        with patch("services.bot.handlers.ref_promo_stats.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.ref_promo_stats.get_pool", AsyncMock(return_value=pool)):
                await cmd_mystats(msg)
        msg.answer.assert_called_once()

    async def test_cb_mystats(self):
        from services.bot.handlers.ref_promo_stats import cb_mystats
        cb = _make_callback("mystats")
        user_row = {
            "credits_total_spent": 50,
            "referral_count": 0,
            "total_payments_rub": 0,
            "created_at": datetime(2025, 1, 1),
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=user_row)
        conn.fetchval = AsyncMock(return_value=5)
        pool = AsyncMock()
        pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False)
        ))
        with patch("services.bot.handlers.ref_promo_stats.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.ref_promo_stats.get_pool", AsyncMock(return_value=pool)):
                await cb_mystats(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()


# ===========================================================================
# subscribe_remind.py tests
# ===========================================================================

class TestSubscribeRemindHelpers:
    def test_parse_remind_time_minutes(self):
        from services.bot.handlers.subscribe_remind import _parse_remind_time
        delta, body = _parse_remind_time("30м купить молоко")
        assert delta == timedelta(minutes=30)
        assert body == "купить молоко"

    def test_parse_remind_time_min_full(self):
        from services.bot.handlers.subscribe_remind import _parse_remind_time
        delta, body = _parse_remind_time("15 минут позвонить маме")
        assert delta == timedelta(minutes=15)
        assert body == "позвонить маме"

    def test_parse_remind_time_hours(self):
        from services.bot.handlers.subscribe_remind import _parse_remind_time
        delta, body = _parse_remind_time("2ч проверить почту")
        assert delta == timedelta(hours=2)
        assert body == "проверить почту"

    def test_parse_remind_time_hours_full(self):
        from services.bot.handlers.subscribe_remind import _parse_remind_time
        delta, body = _parse_remind_time("1 час встреча")
        assert delta == timedelta(hours=1)
        assert body == "встреча"

    def test_parse_remind_time_days(self):
        from services.bot.handlers.subscribe_remind import _parse_remind_time
        delta, body = _parse_remind_time("3д заплатить аренду")
        assert delta == timedelta(days=3)
        assert body == "заплатить аренду"

    def test_parse_remind_time_days_full(self):
        from services.bot.handlers.subscribe_remind import _parse_remind_time
        delta, body = _parse_remind_time("7 дней продлить домен")
        assert delta == timedelta(days=7)
        assert body == "продлить домен"

    def test_parse_remind_time_invalid_no_body(self):
        from services.bot.handlers.subscribe_remind import _parse_remind_time
        delta, body = _parse_remind_time("invalid format")
        assert delta is None
        assert body is None

    def test_parse_remind_time_empty(self):
        from services.bot.handlers.subscribe_remind import _parse_remind_time
        delta, body = _parse_remind_time("")
        assert delta is None
        assert body is None

    def test_is_remind_msg_valid(self):
        from services.bot.handlers.subscribe_remind import _is_remind_msg
        msg = _make_message("Напомни 30м купить молоко")
        assert _is_remind_msg(msg) is True

    def test_is_remind_msg_too_short(self):
        from services.bot.handlers.subscribe_remind import _is_remind_msg
        msg = _make_message("Напомни")
        assert _is_remind_msg(msg) is False

    def test_is_remind_msg_not_remind(self):
        from services.bot.handlers.subscribe_remind import _is_remind_msg
        msg = _make_message("Привет, как дела?")
        assert _is_remind_msg(msg) is False


class TestSubscribeRemindHandlers:
    async def test_msg_remind_invalid_format(self):
        from services.bot.handlers.subscribe_remind import msg_remind
        msg = _make_message("Напомни что-то непонятное")
        await msg_remind(msg)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "Формат" in call_text or "формат" in call_text

    async def test_msg_remind_valid_minutes(self):
        from services.bot.handlers.subscribe_remind import msg_remind
        msg = _make_message("Напомни 30м купить молоко")
        pool = _make_pool()

        with patch("services.bot.handlers.subscribe_remind.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.subscribe_remind.get_pool", AsyncMock(return_value=pool)):
                await msg_remind(msg)
        msg.answer.assert_called_once()
        call_text = msg.answer.call_args[0][0]
        assert "купить молоко" in call_text or "✅" in call_text

    async def test_msg_remind_valid_hours(self):
        from services.bot.handlers.subscribe_remind import msg_remind
        msg = _make_message("Напомни 1ч позвонить")
        pool = _make_pool()

        with patch("services.bot.handlers.subscribe_remind.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.subscribe_remind.get_pool", AsyncMock(return_value=pool)):
                await msg_remind(msg)
        msg.answer.assert_called_once()

    async def test_msg_remind_valid_days(self):
        from services.bot.handlers.subscribe_remind import msg_remind
        msg = _make_message("Напомни 2д проверить email")
        pool = _make_pool()

        with patch("services.bot.handlers.subscribe_remind.get_or_create_user", AsyncMock()):
            with patch("services.bot.handlers.subscribe_remind.get_pool", AsyncMock(return_value=pool)):
                await msg_remind(msg)
        msg.answer.assert_called_once()

    async def test_cb_reminders_empty(self):
        from services.bot.handlers.subscribe_remind import cb_reminders
        cb = _make_callback("screen_reminders")
        pool = _make_pool(fetch=[])

        with patch("services.bot.handlers.subscribe_remind.get_pool", AsyncMock(return_value=pool)):
            await cb_reminders(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()
        call_text = cb.message.answer.call_args[0][0]
        assert "нет" in call_text.lower() or "напомни" in call_text.lower()

    async def test_cb_reminders_with_items(self):
        from services.bot.handlers.subscribe_remind import cb_reminders
        cb = _make_callback("screen_reminders")

        reminder_row = MagicMock()
        reminder_row.__getitem__ = lambda self, key: {
            "id": 1,
            "text": "Buy milk",
            "remind_at": datetime(2026, 5, 3, 10, 0),
            "sent": False,
        }[key]

        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[reminder_row])
        pool = AsyncMock()
        pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False)
        ))

        with patch("services.bot.handlers.subscribe_remind.get_pool", AsyncMock(return_value=pool)):
            await cb_reminders(cb)
        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()
        call_text = cb.message.answer.call_args[0][0]
        assert "Напоминания" in call_text or "Buy milk" in call_text

    async def test_cb_reminders_sent_status(self):
        from services.bot.handlers.subscribe_remind import cb_reminders
        cb = _make_callback("screen_reminders")

        reminder_row = MagicMock()
        reminder_row.__getitem__ = lambda self, key: {
            "id": 2,
            "text": "Done task",
            "remind_at": datetime(2026, 5, 1, 9, 0),
            "sent": True,
        }[key]

        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[reminder_row])
        pool = AsyncMock()
        pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False)
        ))

        with patch("services.bot.handlers.subscribe_remind.get_pool", AsyncMock(return_value=pool)):
            await cb_reminders(cb)
        cb.message.answer.assert_called_once()
        call_text = cb.message.answer.call_args[0][0]
        assert "✅" in call_text
