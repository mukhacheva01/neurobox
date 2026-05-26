"""Контракт описания бота и основных модулей НейроБокс."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_image_models_have_openrouter_route():
    from services.bot.handlers.model_select import IMAGE_MODELS
    from shared.providers.openrouter_image import MODEL_MAP

    for _name, model_id, _price_str, _is_free in IMAGE_MODELS:
        assert model_id in MODEL_MAP


def test_image_models_have_credit_price():
    from services.bot.handlers.model_select import IMAGE_MODELS
    from shared.domain.credits import CREDIT_PRICES

    for _name, model_id, _price_str, _is_free in IMAGE_MODELS:
        assert model_id in CREDIT_PRICES
        assert CREDIT_PRICES[model_id] >= 0


def test_openrouter_image_text_and_image_models_consistent():
    from shared.providers.openrouter_image import _TEXT_AND_IMAGE_MODELS, MODEL_MAP

    used_api_models = set(MODEL_MAP.values())
    for api_id in _TEXT_AND_IMAGE_MODELS:
        assert api_id in used_api_models


def test_main_registers_expected_routers():
    main_src = (ROOT / "services/bot/main.py").read_text(encoding="utf-8")
    expected = [
        "start.router",
        "image.router",
        "video.router",
        "voice.router",
        "music.router",
        "model_select.router",
        "balance.router",
        "text.router",
        "guide.router",
        "admin_router",
    ]
    for name in expected:
        assert name in main_src


def test_bot_has_many_models_available():
    from services.bot.handlers.model_select import IMAGE_MODELS, MUSIC_MODELS
    from shared.config.text_models import TEXT_MODELS
    from shared.domain.credits import VIDEO_MODELS

    total = len(TEXT_MODELS) + len(IMAGE_MODELS) + len(VIDEO_MODELS) + len(MUSIC_MODELS)
    assert total >= 30


def test_credit_packs_defined():
    from shared.domain.credits import CREDIT_PACKS

    assert "trial" in CREDIT_PACKS or "start" in CREDIT_PACKS
    for _pack_id, data in CREDIT_PACKS.items():
        assert "credits" in data and data["credits"] >= 0
        assert "label" in data


def test_video_models_have_cr_and_endpoint():
    from shared.domain.credits import VIDEO_MODELS

    for _model_id, info in VIDEO_MODELS.items():
        assert "cr" in info and info["cr"] > 0
        assert "endpoint" in info and info["endpoint"]


def test_music_models_have_credit_price():
    from services.bot.handlers.model_select import MUSIC_MODELS
    from shared.domain.credits import CREDIT_PRICES

    for _name, model_id, _price_str, _is_free in MUSIC_MODELS:
        assert model_id in CREDIT_PRICES
        assert CREDIT_PRICES[model_id] > 0


def test_openrouter_aspect_ratios_covered():
    from shared.providers.openrouter_image import ASPECT_MAP

    assert ASPECT_MAP.get("landscape") == "16:9"
    assert ASPECT_MAP.get("square") == "1:1"
    assert ASPECT_MAP.get("portrait") == "9:16"


def test_commands_from_main_include_core():
    main_src = (ROOT / "services/bot/main.py").read_text(encoding="utf-8")
    commands = re.findall(r'BotCommand\(command="([a-z0-9_]+)"', main_src)
    assert commands
    for cmd in ("start", "guide", "balance", "model", "privacy", "terms", "paysupport"):
        assert cmd in commands
    assert "img" in commands


def test_settings_has_required_and_optional_flags():
    from shared.config import settings

    for attr in (
        "bot_token",
        "database_url",
        "redis_url",
        "admin_id_list",
        "openrouter_api_key",
        "enable_tts",
        "enable_video",
        "enable_music",
        "enable_stars_payment",
    ):
        assert hasattr(settings, attr)


def test_bot_canonical_description_exists():
    from services.bot.bot_description import BOT_SHORT_DESCRIPTION

    assert "AI-бот" in BOT_SHORT_DESCRIPTION
    assert "текст" in BOT_SHORT_DESCRIPTION.lower()
    assert "картин" in BOT_SHORT_DESCRIPTION.lower()
    assert "документ" in BOT_SHORT_DESCRIPTION.lower()
    assert "транскри" in BOT_SHORT_DESCRIPTION.lower()
    assert "видео" not in BOT_SHORT_DESCRIPTION.lower()
    assert "музык" not in BOT_SHORT_DESCRIPTION.lower()
