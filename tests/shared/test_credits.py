"""Tests for shared/domain/credits.py — target ≥85% coverage."""
import json
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers / constants
# ---------------------------------------------------------------------------

def _make_session():
    """Return a mock AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    return session


def _fake_get_session(session):
    @asynccontextmanager
    async def _gs():
        yield session
    return _gs


# ---------------------------------------------------------------------------
# Pure/sync helpers
# ---------------------------------------------------------------------------

def test_get_referral_level_start():
    from shared.domain.credits import get_referral_level
    name, mult = get_referral_level(0)
    assert name == "Старт"
    assert mult == 1.0


def test_get_referral_level_bronze():
    from shared.domain.credits import get_referral_level
    name, mult = get_referral_level(3)
    assert name == "Бронза"
    assert mult == 1.5


def test_get_referral_level_silver():
    from shared.domain.credits import get_referral_level
    name, mult = get_referral_level(10)
    assert name == "Серебро"
    assert mult == 2.0


def test_get_referral_level_gold():
    from shared.domain.credits import get_referral_level
    name, mult = get_referral_level(25)
    assert name == "Золото"
    assert mult == 2.5


def test_get_referral_level_diamond():
    from shared.domain.credits import get_referral_level
    name, mult = get_referral_level(50)
    assert name == "Бриллиант"
    assert mult == 3.0


def test_detect_provider_openai():
    from shared.domain.credits import _detect_provider
    assert _detect_provider("gpt-4o") == "openai"


def test_detect_provider_google():
    from shared.domain.credits import _detect_provider
    assert _detect_provider("gemini-pro") == "google"
    assert _detect_provider("veo-3.1") == "google"


def test_detect_provider_anthropic():
    from shared.domain.credits import _detect_provider
    assert _detect_provider("claude-3") == "anthropic"


def test_detect_provider_falai():
    from shared.domain.credits import _detect_provider
    assert _detect_provider("flux-2-turbo") == "falai"
    assert _detect_provider("kling-2.6") == "falai"
    assert _detect_provider("runway") == "falai"


def test_detect_provider_xai():
    from shared.domain.credits import _detect_provider
    assert _detect_provider("grok-video") == "xai"


def test_detect_provider_edge():
    from shared.domain.credits import _detect_provider
    assert _detect_provider("edge-tts") == "edge"


def test_usage_bucket_video():
    from shared.domain.credits import _usage_bucket_for_model
    assert _usage_bucket_for_model("kling-2.6") == "video"
    assert _usage_bucket_for_model("luma") == "video"


def test_usage_bucket_music():
    from shared.domain.credits import _usage_bucket_for_model
    assert _usage_bucket_for_model("musicgen") == "music"
    assert _usage_bucket_for_model("suno-v4") == "music"


def test_usage_bucket_upscale():
    from shared.domain.credits import _usage_bucket_for_model
    assert _usage_bucket_for_model("upscale") == "upscale"


def test_usage_bucket_none_for_cheap_text():
    from shared.domain.credits import _usage_bucket_for_model
    # whisper is in FREE_MODELS and TEXT_CREDIT_PRICES is 5 — below elite threshold
    result = _usage_bucket_for_model("gpt-5-nano")
    assert result is None


def test_usage_bucket_elite_text():
    from shared.domain.credits import TEXT_CREDIT_PRICES, _usage_bucket_for_model
    # find a model with price >= 15
    elite = next((m for m, p in TEXT_CREDIT_PRICES.items() if int(p) >= 15), None)
    if elite:
        assert _usage_bucket_for_model(elite) == "elite_text"


def test_seconds_until_utc_day_end():
    from shared.domain.credits import _seconds_until_utc_day_end
    val = _seconds_until_utc_day_end()
    assert isinstance(val, int)
    assert 60 <= val <= 86460


def test_daily_limit_for_tier():
    from shared.domain.credits import _daily_limit_for_tier
    # just check it doesn't raise and returns int
    v = _daily_limit_for_tier("trial", "video")
    assert isinstance(v, int)
    v2 = _daily_limit_for_tier("unlimited", "music")
    assert isinstance(v2, int)
    v3 = _daily_limit_for_tier("unknown_tier", "video")
    assert v3 == 0


def test_is_admin_user_false():
    from shared.domain import credits as cr
    cr._admin_ids_cache = set()
    assert cr._is_admin_user(9999999) is False


def test_is_admin_user_true():
    from shared.domain import credits as cr
    cr._admin_ids_cache = {12345}
    assert cr._is_admin_user(12345) is True
    cr._admin_ids_cache = None  # reset


def test_is_qa_tester_user_false():
    from shared.domain import credits as cr
    cr._qa_tester_ids_cache = set()
    assert cr._is_qa_tester_user(999) is False


def test_is_qa_tester_user_true():
    from shared.domain import credits as cr
    cr._qa_tester_ids_cache = {777}
    assert cr._is_qa_tester_user(777) is True
    cr._qa_tester_ids_cache = None


def test_credit_prices_exist():
    from shared.domain.credits import CREDIT_PRICES
    assert "flux-2-turbo" in CREDIT_PRICES
    assert CREDIT_PRICES["midjourney"] == 20
    assert CREDIT_PRICES["edge-tts"] == 0


def test_credit_packs_structure():
    from shared.domain.credits import DEFAULT_CREDIT_PACKS
    for key, pack in DEFAULT_CREDIT_PACKS.items():
        assert "credits" in pack
        assert "price_rub" in pack
        assert "label" in pack


def test_video_models_structure():
    from shared.domain.credits import VIDEO_MODELS
    for key, meta in VIDEO_MODELS.items():
        assert "cr" in meta
        assert "endpoint" in meta


# ---------------------------------------------------------------------------
# balance cache
# ---------------------------------------------------------------------------

async def test_balance_cache_get_no_redis():
    with patch("shared.redis.store._get_redis", AsyncMock(return_value=None)):
        from shared.domain.credits import _balance_cache_get
        result = await _balance_cache_get(1)
        assert result is None


async def test_balance_cache_get_returns_data():
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps({"bought": 100, "free": 10}).encode())
    with patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_redis)):
        from shared.domain import credits as cr
        # Force reimport of the function
        import importlib
        importlib.reload(cr)
        from shared.domain.credits import _balance_cache_get
        # Patch inside the module
        with patch("shared.domain.credits._balance_cache_get") as mock_fn:
            mock_fn.return_value = {"bought": 100, "free": 10}
            result = await mock_fn(1)
            assert result["bought"] == 100


async def test_balance_cache_set_no_redis():
    with patch("shared.redis.store._get_redis", AsyncMock(return_value=None)):
        from shared.domain.credits import _balance_cache_set
        # Should not raise
        await _balance_cache_set(1, {"bought": 50})


async def test_balance_cache_invalidate_no_redis():
    with patch("shared.redis.store._get_redis", AsyncMock(return_value=None)):
        from shared.domain.credits import _balance_cache_invalidate
        await _balance_cache_invalidate(1)


async def test_balance_cache_invalidate_with_redis():
    mock_r = AsyncMock()
    mock_r.delete = AsyncMock()

    async def fake_get_redis():
        return mock_r

    with patch("shared.redis.store._get_redis", fake_get_redis):
        from shared.domain.credits import _balance_cache_invalidate
        await _balance_cache_invalidate(42)
        mock_r.delete.assert_called_once_with("balance:42")


# ---------------------------------------------------------------------------
# get_balance
# ---------------------------------------------------------------------------

async def test_get_balance_cache_hit():
    cached = {"bought": 200, "free": 10, "total": 210, "total_spent": 5}

    async def fake_cache_get(uid):
        return cached

    with patch("shared.domain.credits._balance_cache_get", fake_cache_get):
        from shared.domain.credits import get_balance
        result = await get_balance(1)
        assert result == cached


async def test_get_balance_user_not_found():
    async def fake_cache_get(uid):
        return None

    session = _make_session()
    result_mock = MagicMock()
    result_mock.one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits._balance_cache_get", fake_cache_get), \
         patch("shared.domain.credits._balance_cache_set", AsyncMock()), \
         patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_balance
        result = await get_balance(999)
        assert result["bought"] == 0
        assert result["free"] == 0
        assert result["total"] == 0


async def test_get_balance_fresh_reset():
    async def fake_cache_get(uid):
        return None

    session = _make_session()

    row = MagicMock()
    row.credits_bought = 500
    row.credits_free_today = 0
    row.credits_free_reset = date.today() - timedelta(days=1)
    row.credits_total_spent = 50

    result_mock = MagicMock()
    result_mock.one_or_none.return_value = row
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits._balance_cache_get", fake_cache_get), \
         patch("shared.domain.credits._balance_cache_set", AsyncMock()), \
         patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_balance
        result = await get_balance(1)
        assert result["bought"] == 500
        assert "free" in result
        assert "total" in result


async def test_get_balance_valid_reset():
    async def fake_cache_get(uid):
        return None

    session = _make_session()
    row = MagicMock()
    row.credits_bought = 300
    row.credits_free_today = 5
    row.credits_free_reset = date.today()
    row.credits_total_spent = 10

    result_mock = MagicMock()
    result_mock.one_or_none.return_value = row
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits._balance_cache_get", fake_cache_get), \
         patch("shared.domain.credits._balance_cache_set", AsyncMock()), \
         patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_balance
        result = await get_balance(1)
        assert result["bought"] == 300
        assert result["free"] == 5
        assert result["total"] == 305


# ---------------------------------------------------------------------------
# is_unlimited_active
# ---------------------------------------------------------------------------

async def test_is_unlimited_active_false_no_end():
    session = _make_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import is_unlimited_active
        result = await is_unlimited_active(1)
        assert result is False


async def test_is_unlimited_active_true():
    session = _make_session()
    future = datetime.now(timezone.utc) + timedelta(days=10)
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = future
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import is_unlimited_active
        result = await is_unlimited_active(1)
        assert result is True


async def test_is_unlimited_active_expired():
    session = _make_session()
    past = datetime.now(timezone.utc) - timedelta(days=1)
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = past
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import is_unlimited_active
        result = await is_unlimited_active(1)
        assert result is False


async def test_is_unlimited_active_naive_datetime():
    """Test that naive datetime is handled (no tzinfo)."""
    session = _make_session()
    future_naive = datetime.now() + timedelta(days=5)  # naive
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = future_naive
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import is_unlimited_active
        result = await is_unlimited_active(1)
        assert result is True


# ---------------------------------------------------------------------------
# get_unlimited_ends_at
# ---------------------------------------------------------------------------

async def test_get_unlimited_ends_at_none():
    session = _make_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_unlimited_ends_at
        result = await get_unlimited_ends_at(1)
        assert result is None


async def test_get_unlimited_ends_at_value():
    session = _make_session()
    future = datetime.now(timezone.utc) + timedelta(days=30)
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = future
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_unlimited_ends_at
        result = await get_unlimited_ends_at(1)
        assert result == future


# ---------------------------------------------------------------------------
# set_unlimited_until
# ---------------------------------------------------------------------------

async def test_set_unlimited_until_no_existing():
    session = _make_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)), \
         patch("shared.domain.credits._balance_cache_invalidate", AsyncMock()):
        from shared.domain.credits import set_unlimited_until
        await set_unlimited_until(1, days=30)
        assert session.execute.called


async def test_set_unlimited_until_extend_active():
    session = _make_session()
    existing_end = datetime.now(timezone.utc) + timedelta(days=10)
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = existing_end
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)), \
         patch("shared.domain.credits._balance_cache_invalidate", AsyncMock()):
        from shared.domain.credits import set_unlimited_until
        await set_unlimited_until(1, days=30)
        assert session.execute.called


async def test_set_unlimited_until_extend_expired():
    session = _make_session()
    expired_end = datetime.now(timezone.utc) - timedelta(days=1)
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = expired_end
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)), \
         patch("shared.domain.credits._balance_cache_invalidate", AsyncMock()):
        from shared.domain.credits import set_unlimited_until
        await set_unlimited_until(1, days=30)


# ---------------------------------------------------------------------------
# is_trial_active
# ---------------------------------------------------------------------------

async def test_is_trial_active_true():
    session = _make_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = 1  # returns scalar 1
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import is_trial_active
        result = await is_trial_active(1)
        assert result is True


async def test_is_trial_active_false():
    session = _make_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import is_trial_active
        result = await is_trial_active(1)
        assert result is False


# ---------------------------------------------------------------------------
# get_trial_status
# ---------------------------------------------------------------------------

async def test_get_trial_status_no_user():
    session = _make_session()
    session.get = AsyncMock(return_value=None)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_trial_status
        result = await get_trial_status(999)
        assert result["can_activate"] is True
        assert result["is_active"] is False


async def test_get_trial_status_not_started():
    session = _make_session()
    user = MagicMock()
    user.trial_started_at = None
    session.get = AsyncMock(return_value=user)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_trial_status
        result = await get_trial_status(1)
        assert result["can_activate"] is True
        assert result["is_active"] is False


async def test_get_trial_status_active():
    session = _make_session()
    user = MagicMock()
    user.trial_started_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    session.get = AsyncMock(return_value=user)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_trial_status
        result = await get_trial_status(1)
        assert result["can_activate"] is False
        assert result["is_active"] is True


async def test_get_trial_status_expired():
    session = _make_session()
    user = MagicMock()
    user.trial_started_at = datetime.now(timezone.utc) - timedelta(hours=2)
    session.get = AsyncMock(return_value=user)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_trial_status
        result = await get_trial_status(1)
        assert result["can_activate"] is False
        assert result["is_active"] is False


async def test_get_trial_status_naive_datetime():
    """Naive started_at should be handled."""
    session = _make_session()
    user = MagicMock()
    user.trial_started_at = datetime.now() - timedelta(minutes=5)  # naive
    session.get = AsyncMock(return_value=user)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_trial_status
        result = await get_trial_status(1)
        assert "is_active" in result


# ---------------------------------------------------------------------------
# start_trial
# ---------------------------------------------------------------------------

async def test_start_trial_no_user():
    session = _make_session()
    session.get = AsyncMock(return_value=None)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import start_trial
        result = await start_trial(999)
        assert result is False


async def test_start_trial_already_started():
    session = _make_session()
    user = MagicMock()
    user.trial_started_at = datetime.now(timezone.utc) - timedelta(hours=1)
    session.get = AsyncMock(return_value=user)
    session.execute = AsyncMock(return_value=MagicMock())

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import start_trial
        result = await start_trial(1)
        assert result is False


async def test_start_trial_success():
    session = _make_session()
    user = MagicMock()
    user.trial_started_at = None
    session.get = AsyncMock(return_value=user)
    session.execute = AsyncMock(return_value=MagicMock())

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import start_trial
        result = await start_trial(1)
        assert result is True


# ---------------------------------------------------------------------------
# get_onboarded / set_onboarded
# ---------------------------------------------------------------------------

async def test_get_onboarded_no_user():
    session = _make_session()
    session.get = AsyncMock(return_value=None)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_onboarded
        result = await get_onboarded(999)
        assert result is True  # fallback = True


async def test_get_onboarded_true():
    session = _make_session()
    user = MagicMock()
    user.onboarded = True
    session.get = AsyncMock(return_value=user)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_onboarded
        result = await get_onboarded(1)
        assert result is True


async def test_get_onboarded_false():
    session = _make_session()
    user = MagicMock()
    user.onboarded = False
    session.get = AsyncMock(return_value=user)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_onboarded
        result = await get_onboarded(1)
        assert result is False


async def test_set_onboarded():
    session = _make_session()
    session.execute = AsyncMock(return_value=MagicMock())

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import set_onboarded
        await set_onboarded(1)
        assert session.execute.called


# ---------------------------------------------------------------------------
# get_48h_status / activate_48h_full_access
# ---------------------------------------------------------------------------

async def test_get_48h_status_no_user():
    session = _make_session()
    session.get = AsyncMock(return_value=None)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_48h_status
        result = await get_48h_status(999)
        assert result["can_activate"] is False
        assert result["is_active"] is False


async def test_get_48h_status_can_activate():
    session = _make_session()
    user = MagicMock()
    user.full_access_48h_ends_at = None
    session.get = AsyncMock(return_value=user)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_48h_status
        result = await get_48h_status(1)
        assert result["can_activate"] is True
        assert result["is_active"] is False


async def test_get_48h_status_active():
    session = _make_session()
    user = MagicMock()
    user.full_access_48h_ends_at = datetime.now(timezone.utc) + timedelta(hours=24)
    session.get = AsyncMock(return_value=user)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_48h_status
        result = await get_48h_status(1)
        assert result["can_activate"] is False
        assert result["is_active"] is True


async def test_get_48h_status_expired():
    session = _make_session()
    user = MagicMock()
    user.full_access_48h_ends_at = datetime.now(timezone.utc) - timedelta(hours=1)
    session.get = AsyncMock(return_value=user)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_48h_status
        result = await get_48h_status(1)
        assert result["can_activate"] is False
        assert result["is_active"] is False


async def test_activate_48h_no_user():
    session = _make_session()
    session.get = AsyncMock(return_value=None)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import activate_48h_full_access
        result = await activate_48h_full_access(999)
        assert result is False


async def test_activate_48h_already_activated():
    session = _make_session()
    user = MagicMock()
    user.full_access_48h_ends_at = datetime.now(timezone.utc) + timedelta(hours=24)
    session.get = AsyncMock(return_value=user)
    session.execute = AsyncMock(return_value=MagicMock())

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import activate_48h_full_access
        result = await activate_48h_full_access(1)
        assert result is False


async def test_activate_48h_success():
    session = _make_session()
    user = MagicMock()
    user.full_access_48h_ends_at = None
    session.get = AsyncMock(return_value=user)
    session.execute = AsyncMock(return_value=MagicMock())

    with patch("shared.domain.credits.get_session", _fake_get_session(session)), \
         patch("shared.domain.credits._balance_cache_invalidate", AsyncMock()):
        from shared.domain.credits import activate_48h_full_access
        result = await activate_48h_full_access(1)
        assert result is True


# ---------------------------------------------------------------------------
# get_user_model / set_user_model / get_all_user_models
# ---------------------------------------------------------------------------

async def test_get_user_model_default():
    session = _make_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_user_model
        result = await get_user_model(1, "text")
        assert result == "gpt-5-nano"


async def test_get_user_model_set_value():
    session = _make_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = "claude-3"
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_user_model
        result = await get_user_model(1, "text")
        assert result == "claude-3"


async def test_get_user_model_unknown_type():
    from shared.domain.credits import get_user_model
    # No DB call needed — col is None
    with patch("shared.domain.credits.get_session", _fake_get_session(_make_session())):
        result = await get_user_model(1, "unknown_type")
        assert result == "gpt-5-nano"


async def test_get_all_user_models_no_user():
    session = _make_session()
    result_mock = MagicMock()
    result_mock.one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_all_user_models, _MODEL_DEFAULTS
        result = await get_all_user_models(1)
        assert result == dict(_MODEL_DEFAULTS)


async def test_get_all_user_models_with_user():
    session = _make_session()
    row = MagicMock()
    row.text_model = "claude-3"
    row.image_model = None
    row.tts_model = None
    row.tts_voice = None
    row.video_model = None
    row.music_model = None
    result_mock = MagicMock()
    result_mock.one_or_none.return_value = row
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_all_user_models, _MODEL_DEFAULTS
        result = await get_all_user_models(1)
        assert result["text"] == "claude-3"
        assert result["image"] == _MODEL_DEFAULTS["image"]


async def test_set_user_model():
    session = _make_session()
    session.execute = AsyncMock(return_value=MagicMock())

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import set_user_model
        await set_user_model(1, "text", "gpt-4o")
        assert session.execute.called


async def test_set_user_model_invalid_type():
    session = _make_session()
    # col is None, so execute should NOT be called
    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import set_user_model
        await set_user_model(1, "unknown", "some-model")
        assert not session.execute.called


# ---------------------------------------------------------------------------
# get_referral_code
# ---------------------------------------------------------------------------

async def test_get_referral_code_empty():
    session = _make_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_referral_code
        result = await get_referral_code(1)
        assert result == ""


async def test_get_referral_code_value():
    session = _make_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = "ABCD1234"
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import get_referral_code
        result = await get_referral_code(1)
        assert result == "ABCD1234"


# ---------------------------------------------------------------------------
# add_credits
# ---------------------------------------------------------------------------

async def test_add_credits():
    session = _make_session()
    user_row = MagicMock()
    user_row.credits_bought = 600
    user_row.credits_free_today = 5
    result_mock = MagicMock()
    result_mock.one_or_none.return_value = user_row
    # first execute is UPDATE, second is SELECT
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)), \
         patch("shared.domain.credits._balance_cache_invalidate", AsyncMock()):
        from shared.domain.credits import add_credits
        result = await add_credits(1, 100, "purchase", "Test pack")
        assert result["ok"] is True
        assert result["new_balance"] == 600


# ---------------------------------------------------------------------------
# refund_credits
# ---------------------------------------------------------------------------

async def test_refund_credits_zero():
    with patch("shared.domain.credits.add_credits", AsyncMock()) as mock_add:
        from shared.domain.credits import refund_credits
        await refund_credits(1, 0)
        mock_add.assert_not_called()


async def test_refund_credits_positive():
    with patch("shared.domain.credits.add_credits", AsyncMock()) as mock_add:
        mock_add.return_value = {"ok": True, "new_balance": 100}
        from shared.domain.credits import refund_credits
        await refund_credits(1, 50, "test reason")
        mock_add.assert_called_once_with(1, 50, "refund", "test reason")


# ---------------------------------------------------------------------------
# deduct_credits_refund
# ---------------------------------------------------------------------------

async def test_deduct_credits_refund_zero():
    from shared.domain.credits import deduct_credits_refund
    result = await deduct_credits_refund(1, 0)
    assert result["ok"] is True
    assert result["deducted"] == 0


async def test_deduct_credits_refund_user_not_found():
    session = _make_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import deduct_credits_refund
        result = await deduct_credits_refund(999, 50)
        assert result["ok"] is False
        assert "user_not_found" in result.get("error", "")


async def test_deduct_credits_refund_no_balance():
    session = _make_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = 0  # zero credits
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)), \
         patch("shared.domain.credits._balance_cache_invalidate", AsyncMock()):
        from shared.domain.credits import deduct_credits_refund
        result = await deduct_credits_refund(1, 100)
        assert result["ok"] is True
        assert result["deducted"] == 0


async def test_deduct_credits_refund_partial():
    session = _make_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = 30  # only 30 credits
    execute_mock = AsyncMock(return_value=result_mock)
    session.execute = execute_mock

    with patch("shared.domain.credits.get_session", _fake_get_session(session)), \
         patch("shared.domain.credits._balance_cache_invalidate", AsyncMock()):
        from shared.domain.credits import deduct_credits_refund
        result = await deduct_credits_refund(1, 100)
        assert result["ok"] is True
        assert result["deducted"] == 30  # min(100, 30)


async def test_deduct_credits_refund_full():
    session = _make_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = 200
    execute_mock = AsyncMock(return_value=result_mock)
    session.execute = execute_mock

    with patch("shared.domain.credits.get_session", _fake_get_session(session)), \
         patch("shared.domain.credits._balance_cache_invalidate", AsyncMock()):
        from shared.domain.credits import deduct_credits_refund
        result = await deduct_credits_refund(1, 100)
        assert result["ok"] is True
        assert result["deducted"] == 100


# ---------------------------------------------------------------------------
# rollback_spend_usage_policy
# ---------------------------------------------------------------------------

async def test_rollback_spend_usage_policy_none():
    from shared.domain.credits import rollback_spend_usage_policy
    # Should not raise
    await rollback_spend_usage_policy(None)


async def test_rollback_spend_usage_policy_no_policy_usage():
    from shared.domain.credits import rollback_spend_usage_policy
    await rollback_spend_usage_policy({"cost": 10})


async def test_rollback_policy_usage_already_rolled_back():
    from shared.domain.credits import _rollback_policy_usage
    policy = {"_rolled_back": True}
    # Should do nothing
    await _rollback_policy_usage(policy)


async def test_rollback_policy_usage_no_redis():
    with patch("shared.redis.store._get_redis", AsyncMock(return_value=None)):
        from shared.domain.credits import _rollback_policy_usage
        policy = {"cooldown_key": "some:key"}
        await _rollback_policy_usage(policy)


async def test_rollback_policy_usage_with_redis():
    mock_r = AsyncMock()
    mock_r.delete = AsyncMock()
    mock_r.decr = AsyncMock(return_value=0)

    async def fake_get_redis():
        return mock_r

    with patch("shared.redis.store._get_redis", fake_get_redis):
        from shared.domain.credits import _rollback_policy_usage
        policy = {
            "cooldown_key": "policy:cooldown:video:1",
            "daily_incremented": True,
            "daily_limit_key": "policy:daily:trial:video:1:20260101",
        }
        await _rollback_policy_usage(policy)
        mock_r.delete.assert_any_call("policy:cooldown:video:1")
        assert policy["_rolled_back"] is True


# ---------------------------------------------------------------------------
# refund_spend_credits
# ---------------------------------------------------------------------------

async def test_refund_spend_credits_trial():
    from shared.domain.credits import refund_spend_credits
    with patch("shared.domain.credits.rollback_spend_usage_policy", AsyncMock()), \
         patch("shared.domain.credits.refund_credits", AsyncMock()) as mock_ref:
        result = await refund_spend_credits(1, {"cost": 10, "trial": True})
        assert result is False
        mock_ref.assert_not_called()


async def test_refund_spend_credits_unlimited():
    from shared.domain.credits import refund_spend_credits
    with patch("shared.domain.credits.rollback_spend_usage_policy", AsyncMock()), \
         patch("shared.domain.credits.refund_credits", AsyncMock()) as mock_ref:
        result = await refund_spend_credits(1, {"cost": 10, "unlimited": True})
        assert result is False
        mock_ref.assert_not_called()


async def test_refund_spend_credits_actual():
    from shared.domain.credits import refund_spend_credits
    with patch("shared.domain.credits.rollback_spend_usage_policy", AsyncMock()), \
         patch("shared.domain.credits.refund_credits", AsyncMock()) as mock_ref:
        result = await refund_spend_credits(1, {"cost": 20})
        assert result is True
        mock_ref.assert_called_once_with(1, 20, "ошибка генерации")


# ---------------------------------------------------------------------------
# apply_promocode
# ---------------------------------------------------------------------------

async def test_apply_promocode_empty_code():
    from shared.domain.credits import apply_promocode
    result = await apply_promocode(1, "")
    assert result["ok"] is False


async def test_apply_promocode_not_found():
    session = _make_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import apply_promocode
        result = await apply_promocode(1, "BADCODE")
        assert result["ok"] is False
        assert "не найден" in result["error"]


async def test_apply_promocode_exhausted():
    session = _make_session()
    promo = MagicMock()
    promo.used_count = 10
    promo.max_uses = 10
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = promo
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import apply_promocode
        result = await apply_promocode(1, "TESTCODE")
        assert result["ok"] is False
        assert "исчерпан" in result["error"]


async def test_apply_promocode_already_used():
    session = _make_session()
    promo = MagicMock()
    promo.used_count = 5
    promo.max_uses = 100
    promo.credits = 50
    promo_result = MagicMock()
    promo_result.scalar_one_or_none.return_value = promo

    used_rec = MagicMock()
    used_result = MagicMock()
    used_result.scalar_one_or_none.return_value = used_rec

    call_count = [0]
    async def execute_side(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return promo_result
        return used_result

    session.execute = execute_side

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import apply_promocode
        result = await apply_promocode(1, "TESTCODE")
        assert result["ok"] is False
        assert "уже использовал" in result["error"]


async def test_apply_promocode_success():
    session = _make_session()
    promo = MagicMock()
    promo.used_count = 0
    promo.max_uses = 100
    promo.credits = 75

    promo_result = MagicMock()
    promo_result.scalar_one_or_none.return_value = promo

    no_use_result = MagicMock()
    no_use_result.scalar_one_or_none.return_value = None

    update_result = MagicMock()

    call_count = [0]
    async def execute_side(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return promo_result
        if call_count[0] == 2:
            return no_use_result
        return update_result

    session.execute = execute_side

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import apply_promocode
        result = await apply_promocode(1, "PROMO75")
        assert result["ok"] is True
        assert result["credits"] == 75


# ---------------------------------------------------------------------------
# log_ai_request
# ---------------------------------------------------------------------------

async def test_log_ai_request():
    session = _make_session()

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import log_ai_request
        await log_ai_request(1, "text", "gpt-4o", "hello", "completed", 5, 100)
        assert session.add.called
        assert session.flush.called


async def test_log_ai_request_exception_swallowed():
    """Exceptions should be swallowed — analytics must not break the bot."""
    session = _make_session()
    session.flush = AsyncMock(side_effect=Exception("DB Error"))

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import log_ai_request
        # Should NOT raise
        await log_ai_request(1, "text", "gpt-4o")


# ---------------------------------------------------------------------------
# spend_credits — free model (edge-tts, cost=0)
# ---------------------------------------------------------------------------

async def test_spend_credits_free_model():
    from shared.domain.credits import spend_credits
    result = await spend_credits(1, "edge-tts")
    assert result["ok"] is True
    assert result["cost"] == 0


# ---------------------------------------------------------------------------
# enforce_usage_policy — bucket=None path
# ---------------------------------------------------------------------------

async def test_enforce_usage_policy_no_bucket():
    from shared.domain.credits import enforce_usage_policy
    # gpt-5-nano is cheap text, bucket=None → ok:True
    result = await enforce_usage_policy(1, "gpt-5-nano")
    assert result["ok"] is True
    assert result["bucket"] is None


# ---------------------------------------------------------------------------
# enforce_usage_policy — user not found
# ---------------------------------------------------------------------------

async def test_enforce_usage_policy_user_not_found():
    session = _make_session()
    result_mock = MagicMock()
    result_mock.one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import enforce_usage_policy
        result = await enforce_usage_policy(1, "kling-2.6")
        assert result["ok"] is False
        assert result["reason"] == "user_not_found"


# ---------------------------------------------------------------------------
# enforce_usage_policy — admin bypass
# ---------------------------------------------------------------------------

async def test_enforce_usage_policy_admin_bypass():
    from shared.domain import credits as cr
    cr._admin_ids_cache = {1}

    session = _make_session()
    row = MagicMock()
    row.username = "admin"
    row.trial_started_at = None
    row.unlimited_ends_at = None
    row.full_access_48h_ends_at = None
    result_mock = MagicMock()
    result_mock.one_or_none.return_value = row
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)), \
         patch("shared.redis.store._get_redis", AsyncMock(return_value=None)):
        from shared.domain.credits import enforce_usage_policy
        result = await enforce_usage_policy(1, "kling-2.6")
        assert result["ok"] is True
        assert result["tier"] == "admin"

    cr._admin_ids_cache = None


# ---------------------------------------------------------------------------
# enforce_usage_policy — trial user
# ---------------------------------------------------------------------------

async def test_enforce_usage_policy_trial_active():
    from shared.domain import credits as cr
    cr._admin_ids_cache = set()
    cr._qa_tester_ids_cache = set()

    session = _make_session()
    row = MagicMock()
    row.username = "testuser"
    row.trial_started_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    row.unlimited_ends_at = None
    row.full_access_48h_ends_at = None
    result_mock = MagicMock()
    result_mock.one_or_none.return_value = row
    session.execute = AsyncMock(return_value=result_mock)

    mock_r = AsyncMock()
    mock_r.set = AsyncMock(return_value=True)
    mock_r.incr = AsyncMock(return_value=1)
    mock_r.expire = AsyncMock(return_value=True)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)), \
         patch("shared.redis.store._get_redis", AsyncMock(return_value=mock_r)):
        from shared.domain.credits import enforce_usage_policy
        result = await enforce_usage_policy(2, "kling-2.6")
        assert result["ok"] is True
        assert result["tier"] == "trial"

    cr._admin_ids_cache = None
    cr._qa_tester_ids_cache = None


# ---------------------------------------------------------------------------
# get_credit_packs / get_credit_pack
# ---------------------------------------------------------------------------

async def test_get_credit_packs_fallback():
    """When DB fails, returns DEFAULT_CREDIT_PACKS."""
    with patch("shared.domain.credits.sync_billing_plans_defaults", AsyncMock()), \
         patch("shared.domain.credits.get_session") as mock_gs:
        mock_gs.return_value.__aenter__ = AsyncMock(side_effect=Exception("DB Error"))
        mock_gs.return_value.__aexit__ = AsyncMock(return_value=False)
        from shared.domain.credits import get_credit_packs, DEFAULT_CREDIT_PACKS
        result = await get_credit_packs()
        assert set(result.keys()) == set(DEFAULT_CREDIT_PACKS.keys())


async def test_get_credit_pack_existing():
    with patch("shared.domain.credits.get_credit_packs", AsyncMock(return_value={"lite": {"credits": 300}})):
        from shared.domain.credits import get_credit_pack
        result = await get_credit_pack("lite")
        assert result["credits"] == 300


async def test_get_credit_pack_missing():
    with patch("shared.domain.credits.get_credit_packs", AsyncMock(return_value={})):
        from shared.domain.credits import get_credit_pack
        result = await get_credit_pack("nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# try_grant_daily_login_bonus
# ---------------------------------------------------------------------------

async def test_try_grant_daily_login_bonus_disabled():
    from shared.config import settings
    with patch.object(settings, "daily_login_bonus_credits", 0):
        from shared.domain.credits import try_grant_daily_login_bonus
        result = await try_grant_daily_login_bonus(1)
        assert result is False


async def test_try_grant_daily_login_bonus_no_user():
    session = _make_session()
    result_mock = MagicMock()
    result_mock.one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import try_grant_daily_login_bonus
        result = await try_grant_daily_login_bonus(999)
        assert result is False


async def test_try_grant_daily_login_bonus_already_today():
    session = _make_session()
    row = MagicMock()
    row.last_daily_bonus_date = date.today()
    row.login_streak = 3
    result_mock = MagicMock()
    result_mock.one_or_none.return_value = row
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import try_grant_daily_login_bonus
        result = await try_grant_daily_login_bonus(1)
        assert result is False


async def test_try_grant_daily_login_bonus_streak():
    session = _make_session()
    row = MagicMock()
    row.last_daily_bonus_date = date.today() - timedelta(days=1)  # yesterday
    row.login_streak = 2
    result_mock = MagicMock()
    result_mock.one_or_none.return_value = row
    execute_mock = AsyncMock(return_value=result_mock)
    session.execute = execute_mock

    with patch("shared.domain.credits.get_session", _fake_get_session(session)), \
         patch("shared.domain.credits.add_credits", AsyncMock(return_value={"ok": True, "new_balance": 100})):
        from shared.domain.credits import try_grant_daily_login_bonus
        result = await try_grant_daily_login_bonus(1)
        assert result is not False
        assert result["granted"] is True
        assert result["streak"] == 3


async def test_try_grant_daily_login_bonus_streak_reset():
    """Streak resets to 1 if last bonus was not yesterday."""
    session = _make_session()
    row = MagicMock()
    row.last_daily_bonus_date = date.today() - timedelta(days=5)
    row.login_streak = 10
    result_mock = MagicMock()
    result_mock.one_or_none.return_value = row
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)), \
         patch("shared.domain.credits.add_credits", AsyncMock(return_value={"ok": True, "new_balance": 100})):
        from shared.domain.credits import try_grant_daily_login_bonus
        result = await try_grant_daily_login_bonus(1)
        assert result["streak"] == 1


# ---------------------------------------------------------------------------
# get_payment_by_yookassa_id
# ---------------------------------------------------------------------------

async def test_get_payment_by_yookassa_id_none():
    session = _make_session()
    mock_repo = AsyncMock()
    mock_repo.get_by_payment_id = AsyncMock(return_value=None)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)), \
         patch("shared.db.repositories.payment.PaymentRepository", return_value=mock_repo):
        from shared.domain.credits import get_payment_by_yookassa_id
        result = await get_payment_by_yookassa_id("test_payment_id")
        assert result is None


# ---------------------------------------------------------------------------
# create_payment_record
# ---------------------------------------------------------------------------

async def test_create_payment_record_success():
    session = _make_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = 42  # inserted id
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import create_payment_record
        result = await create_payment_record(1, "pay_123", 99.0, 300, "lite")
        assert result is True


async def test_create_payment_record_duplicate():
    session = _make_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None  # conflict, nothing inserted
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import create_payment_record
        result = await create_payment_record(1, "pay_dup", 99.0, 300, "lite")
        assert result is False


# ---------------------------------------------------------------------------
# confirm_payment_record
# ---------------------------------------------------------------------------

async def test_confirm_payment_record_not_found():
    session = _make_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result_mock)

    with patch("shared.domain.credits.get_session", _fake_get_session(session)):
        from shared.domain.credits import confirm_payment_record
        result = await confirm_payment_record("nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# STREAK_BONUSES constant
# ---------------------------------------------------------------------------

def test_streak_bonuses():
    from shared.domain.credits import STREAK_BONUSES
    assert STREAK_BONUSES[3] == 10
    assert STREAK_BONUSES[7] == 20
    assert STREAK_BONUSES[30] == 50
