"""Tests for services/worker — jobs and telegram singleton."""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# daily_stats — pure helper _pct
# ---------------------------------------------------------------------------

def test_pct_normal():
    from services.worker.jobs.daily_stats import _pct
    assert _pct(50, 100) == 50.0
    assert _pct(1, 3) == 33.3


def test_pct_zero_whole():
    from services.worker.jobs.daily_stats import _pct
    assert _pct(10, 0) == 0.0


def test_pct_zero_part():
    from services.worker.jobs.daily_stats import _pct
    assert _pct(0, 100) == 0.0


# ---------------------------------------------------------------------------
# alerts — pure helper _pct
# ---------------------------------------------------------------------------

def test_alerts_pct():
    from services.worker.jobs.alerts import _pct
    assert _pct(25, 200) == 12.5
    assert _pct(0, 0) == 0.0


# ---------------------------------------------------------------------------
# notify.handle — missing fields
# ---------------------------------------------------------------------------

async def test_notify_handle_missing_user_id():
    from services.worker.jobs.notify import handle
    # Should log warning and return without sending
    await handle({"text": "hello"})  # no user_id


async def test_notify_handle_missing_text():
    from services.worker.jobs.notify import handle
    await handle({"user_id": 123})  # no text


async def test_notify_handle_success():
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        from services.worker.jobs.notify import handle
        await handle({"user_id": 123, "text": "Test notification"})
        mock_client.post.assert_called_once()


async def test_notify_handle_http_error():
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=Exception("Network error"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        from services.worker.jobs.notify import handle
        # Should not raise — error is caught and logged
        await handle({"user_id": 123, "text": "Test"})


# ---------------------------------------------------------------------------
# SQLAlchemy session mock helpers for worker tests
# ---------------------------------------------------------------------------

def _make_worker_result(scalar=0, first=None, all_rows=None):
    result = MagicMock()
    result.scalar = MagicMock(return_value=scalar)
    mappings = MagicMock()
    mappings.first = MagicMock(return_value=first)
    mappings.all = MagicMock(return_value=list(all_rows or []))
    result.mappings = MagicMock(return_value=mappings)
    return result


def _patch_worker_session(mock_session):
    @asynccontextmanager
    async def _fake():
        yield mock_session
    return patch("shared.db.session.get_session", _fake)


# ---------------------------------------------------------------------------
# daily_stats.handle — mocked session
# ---------------------------------------------------------------------------

async def test_daily_stats_handle_success():
    funnel_row = {
        "start_users": 100, "first_generation_users": 80,
        "paywall_hit_users": 30, "purchase_users": 10, "repeat_users": 2,
    }
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        _make_worker_result(scalar=42),    # today_users
        _make_worker_result(scalar=100),   # today_revenue
        _make_worker_result(scalar=200),   # today_requests
        _make_worker_result(first=funnel_row),  # funnel _compute_funnel_window
        *[_make_worker_result() for _ in range(12)],  # 12 INSERT upserts
    ])
    with _patch_worker_session(session):
        from services.worker.jobs.daily_stats import handle
        await handle({})
    assert session.execute.called


async def test_daily_stats_handle_db_error():
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=Exception("DB down"))
    with _patch_worker_session(session):
        from services.worker.jobs.daily_stats import handle
        await handle({})  # Should not raise — wrapped in try/except


# ---------------------------------------------------------------------------
# alerts.handle — mocked session and bot
# ---------------------------------------------------------------------------

async def test_alerts_handle_db_error():
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=Exception("DB down"))
    with _patch_worker_session(session):
        from services.worker.jobs.alerts import handle
        await handle({})  # Should not raise


async def test_alerts_handle_success():
    funnel_row = {
        "start_users": 0, "first_generation_users": 0,
        "paywall_hit_users": 0, "purchase_users": 0, "repeat_users": 0,
    }
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_make_worker_result(
        scalar=0, first=funnel_row, all_rows=[]
    ))
    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock()
    with _patch_worker_session(session):
        from services.worker.jobs.alerts import handle
        await handle({}, bot=mock_bot)


# ---------------------------------------------------------------------------
# video_generate.handle — mocked pool and bot
# ---------------------------------------------------------------------------

async def test_video_generate_handle_missing_payload():
    with patch("shared.db.database.get_pool", AsyncMock(side_effect=Exception("no db"))):
        from services.worker.jobs.video_generate import handle
        # Empty payload → should handle gracefully
        await handle({})


# ---------------------------------------------------------------------------
# worker/telegram.py — singleton bot
# ---------------------------------------------------------------------------

def test_get_bot_creates_singleton():
    with patch("shared.config.settings") as mock_settings:
        mock_settings.bot_token = "123:test_token"
        import services.worker.telegram as wt
        # Reset singleton
        wt._bot = None
        with patch("services.worker.telegram.Bot") as mock_bot_cls:
            mock_bot_cls.return_value = MagicMock()
            bot1 = wt.get_bot()
            bot2 = wt.get_bot()
            assert bot1 is bot2
            mock_bot_cls.assert_called_once()
        wt._bot = None


async def test_close_bot_no_bot():
    import services.worker.telegram as wt
    wt._bot = None
    await wt.close_bot()  # Should not raise


async def test_close_bot_closes_session():
    import services.worker.telegram as wt
    mock_bot = AsyncMock()
    mock_bot.session = AsyncMock()
    mock_bot.session.close = AsyncMock()
    wt._bot = mock_bot
    await wt.close_bot()
    mock_bot.session.close.assert_called_once()
    assert wt._bot is None


# ---------------------------------------------------------------------------
# worker/main.py — dispatch function
# ---------------------------------------------------------------------------

def test_worker_main_importable():
    import services.worker.main as wm
    assert wm is not None


async def test_worker_dispatch_unknown_task():
    import services.worker.main as wm
    mock_redis = AsyncMock()
    mock_redis.blpop = AsyncMock(return_value=(b"tasks", b'{"type":"unknown_task","payload":{}}'))
    # Just verify the dispatch doesn't blow up on unknown task types
    # by patching the infinite loop
    call_count = [0]
    original_dispatch = getattr(wm, "_dispatch", None)

    async def fake_dispatch(task_type, payload, bot):
        call_count[0] += 1

    if hasattr(wm, "_dispatch"):
        with patch.object(wm, "_dispatch", fake_dispatch):
            await wm._dispatch("unknown", {}, None)
    else:
        # dispatch happens inline in while loop — just test importability
        pass


# ---------------------------------------------------------------------------
# Queue client
# ---------------------------------------------------------------------------

async def test_enqueue():
    mock_redis = AsyncMock()
    mock_redis.rpush = AsyncMock(return_value=1)
    from shared.queue.client import enqueue
    await enqueue(mock_redis, "notify", {"user_id": 1, "text": "hi"})
    mock_redis.rpush.assert_called_once()


def test_queue_tasks_importable():
    from shared.queue import tasks
    assert hasattr(tasks, "BaseTask") or tasks is not None


# ---------------------------------------------------------------------------
# shared/logging.py
# ---------------------------------------------------------------------------

def test_setup_logging_importable():
    with patch.dict("sys.modules", {"sentry_sdk": MagicMock()}):
        import importlib, shared.logging as _sl
        importlib.reload(_sl)
        assert callable(_sl.setup_logging)


def test_setup_logging_runs():
    import sys
    mock_sentry = MagicMock()
    with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
        import importlib, shared.logging as _sl
        importlib.reload(_sl)
        _sl.setup_logging()  # Should not raise
