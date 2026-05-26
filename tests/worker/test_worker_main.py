"""Tests for services/worker/main.py — Redis task queue worker.

Strategy
--------
* _get_redis uses lazy imports (``from redis.asyncio import Redis`` inside the
  function body), so we patch ``redis.asyncio.Redis`` in sys.modules rather
  than a module-level attribute.
* process_task also uses lazy imports for each job handler, so we patch via
  sys.modules stubs or patch the import path at call time.
* main() contains an infinite while-loop; tests drive it by injecting a
  CancelledError after one iteration via AsyncMock side_effect lists.
* asyncio_mode = auto (pytest.ini) — bare ``async def test_*`` functions work.
"""

from __future__ import annotations

import asyncio
import json
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_redis(blpop_values=None):
    """Return a mock redis client.

    blpop_values: list of return values for successive blpop() calls.
    The last element is always a CancelledError to terminate the loop.
    """
    r = AsyncMock()
    r.rpush = AsyncMock(return_value=1)
    r.aclose = AsyncMock()

    if blpop_values is None:
        blpop_values = []

    # Append CancelledError as sentinel to break the infinite loop
    side_effects = list(blpop_values) + [asyncio.CancelledError()]
    r.blpop = AsyncMock(side_effect=side_effects)
    return r


def _make_fake_job_module(name: str) -> ModuleType:
    """Return a stub module with an async handle() function."""
    mod = ModuleType(name)
    mod.handle = AsyncMock()
    return mod


# ---------------------------------------------------------------------------
# _get_redis
# ---------------------------------------------------------------------------

class TestGetRedis:
    async def test_returns_redis_instance_on_success(self):
        mock_redis_instance = AsyncMock()
        mock_redis_cls = MagicMock()
        mock_redis_cls.from_url = MagicMock(return_value=mock_redis_instance)

        mock_redis_asyncio = MagicMock()
        mock_redis_asyncio.Redis = mock_redis_cls

        mock_settings = MagicMock()
        mock_settings.redis_url = "redis://localhost:6379/0"

        with patch.dict(sys.modules, {"redis.asyncio": mock_redis_asyncio}):
            with patch("shared.config.settings", mock_settings):
                import importlib
                import services.worker.main as wm
                importlib.reload(wm)
                result = await wm._get_redis()

        assert result is mock_redis_instance

    async def test_returns_none_when_redis_from_url_raises(self):
        """If Redis.from_url raises, _get_redis must return None."""
        import services.worker.main as wm
        mock_redis_cls = MagicMock()
        mock_redis_cls.from_url = MagicMock(side_effect=Exception("connection refused"))
        with patch.dict(sys.modules, {"redis.asyncio": MagicMock(Redis=mock_redis_cls)}):
            result = await wm._get_redis()
        assert result is None

    async def test_returns_none_when_settings_raises(self):
        mock_redis_cls = MagicMock()
        mock_redis_cls.from_url = MagicMock(side_effect=Exception("connection refused"))

        mock_redis_asyncio = MagicMock()
        mock_redis_asyncio.Redis = mock_redis_cls

        mock_settings = MagicMock()
        mock_settings.redis_url = "redis://bad_host:6379"

        with patch.dict(sys.modules, {"redis.asyncio": mock_redis_asyncio}):
            with patch("shared.config.settings", mock_settings):
                import services.worker.main as wm
                result = await wm._get_redis()

        assert result is None


# ---------------------------------------------------------------------------
# process_task — dispatch logic
# ---------------------------------------------------------------------------

class TestProcessTask:
    async def test_dispatch_notify(self):
        mock_handle = AsyncMock()
        fake_notify = _make_fake_job_module("services.worker.jobs.notify")
        fake_notify.handle = mock_handle

        with patch.dict(sys.modules, {"services.worker.jobs.notify": fake_notify}):
            import services.worker.main as wm
            await wm.process_task({"type": "notify", "user_id": 1, "text": "hello"})

        mock_handle.assert_called_once_with({"type": "notify", "user_id": 1, "text": "hello"})

    async def test_dispatch_video_generate(self):
        mock_handle = AsyncMock()
        fake_mod = _make_fake_job_module("services.worker.jobs.video_generate")
        fake_mod.handle = mock_handle

        with patch.dict(sys.modules, {"services.worker.jobs.video_generate": fake_mod}):
            import services.worker.main as wm
            task = {"type": "video_generate", "user_id": 2}
            await wm.process_task(task)

        mock_handle.assert_called_once_with(task)

    async def test_dispatch_daily_stats(self):
        mock_handle = AsyncMock()
        fake_mod = _make_fake_job_module("services.worker.jobs.daily_stats")
        fake_mod.handle = mock_handle

        with patch.dict(sys.modules, {"services.worker.jobs.daily_stats": fake_mod}):
            import services.worker.main as wm
            task = {"type": "daily_stats"}
            await wm.process_task(task)

        mock_handle.assert_called_once_with(task)

    async def test_dispatch_metrics_alert(self):
        mock_handle = AsyncMock()
        fake_mod = _make_fake_job_module("services.worker.jobs.alerts")
        fake_mod.handle = mock_handle

        with patch.dict(sys.modules, {"services.worker.jobs.alerts": fake_mod}):
            import services.worker.main as wm
            task = {"type": "metrics_alert"}
            await wm.process_task(task)

        mock_handle.assert_called_once_with(task)

    async def test_unknown_task_type_does_not_raise(self):
        import services.worker.main as wm
        # Should just log a warning and return without raising
        await wm.process_task({"type": "totally_unknown_task"})

    async def test_none_task_type_does_not_raise(self):
        import services.worker.main as wm
        await wm.process_task({"user_id": 99})  # no "type" key

    async def test_empty_task_does_not_raise(self):
        import services.worker.main as wm
        await wm.process_task({})

    async def test_task_type_logged(self):
        """Log call is made with the task type."""
        import services.worker.main as wm
        with patch("services.worker.main.log") as mock_log:
            await wm.process_task({"type": "unknown_xyz", "user_id": 5})
        # log.info should be called first, then log.warning for unknown type
        assert mock_log.info.called or mock_log.warning.called


# ---------------------------------------------------------------------------
# main() — startup and loop behaviour
# ---------------------------------------------------------------------------

class TestMainFunction:
    async def test_main_sleeps_forever_when_redis_unavailable(self):
        """When _get_redis returns None, main() enters the sleep-forever branch."""
        import services.worker.main as wm

        sleep_calls = []

        async def _fake_sleep(seconds):
            sleep_calls.append(seconds)
            raise asyncio.CancelledError()

        with patch("services.worker.main._get_redis", AsyncMock(return_value=None)), \
             patch("shared.db.database.get_pool", AsyncMock()), \
             patch("asyncio.sleep", _fake_sleep):
            try:
                await wm.main()
            except asyncio.CancelledError:
                pass

        assert sleep_calls == [60]

    async def test_main_processes_single_valid_task(self):
        """One valid JSON task is consumed, then CancelledError ends the loop."""
        import services.worker.main as wm

        raw_task = json.dumps({"type": "notify", "user_id": 7, "text": "hi"}).encode()
        mock_r = _make_redis(blpop_values=[(b"neurobox:tasks", raw_task)])

        processed = []
        async def _fake_process(task):
            processed.append(task)

        with patch("services.worker.main._get_redis", AsyncMock(return_value=mock_r)), \
             patch("services.worker.main.process_task", _fake_process), \
             patch("shared.db.database.get_pool", AsyncMock()):
            try:
                await wm.main()
            except asyncio.CancelledError:
                pass

        assert len(processed) >= 1
        assert processed[0]["type"] == "notify"

    async def test_main_handles_invalid_json(self):
        """Bad JSON in queue triggers warning log but does not crash the loop."""
        import services.worker.main as wm

        mock_r = _make_redis(blpop_values=[(b"neurobox:tasks", b"NOT_JSON")])

        with patch("services.worker.main._get_redis", AsyncMock(return_value=mock_r)), \
             patch("shared.db.database.get_pool", AsyncMock()), \
             patch("services.worker.main.log") as mock_log:
            try:
                await wm.main()
            except asyncio.CancelledError:
                pass

        assert mock_log.warning.called

    async def test_main_requeues_failed_task_on_first_retry(self):
        """A task that raises on process_task gets re-queued with _retry=1."""
        import services.worker.main as wm

        task_data = {"type": "notify", "user_id": 1}
        raw_task = json.dumps(task_data).encode()
        mock_r = _make_redis(blpop_values=[(b"neurobox:tasks", raw_task)])

        async def _failing_process(task):
            raise ValueError("handler exploded")

        with patch("services.worker.main._get_redis", AsyncMock(return_value=mock_r)), \
             patch("services.worker.main.process_task", _failing_process), \
             patch("shared.db.database.get_pool", AsyncMock()):
            try:
                await wm.main()
            except asyncio.CancelledError:
                pass

        # rpush must have been called once to re-queue
        mock_r.rpush.assert_called_once()
        requeued_raw = mock_r.rpush.call_args[0][1]
        requeued = json.loads(requeued_raw)
        assert requeued["_retry"] == 1

    async def test_main_sends_to_dlq_after_max_retries(self):
        """A task that has already reached MAX_TASK_RETRIES is moved to DLQ."""
        import services.worker.main as wm

        task_data = {"type": "notify", "user_id": 1, "_retry": wm.MAX_TASK_RETRIES}
        raw_task = json.dumps(task_data).encode()
        mock_r = _make_redis(blpop_values=[(b"neurobox:tasks", raw_task)])

        async def _failing_process(task):
            raise ValueError("still failing")

        with patch("services.worker.main._get_redis", AsyncMock(return_value=mock_r)), \
             patch("services.worker.main.process_task", _failing_process), \
             patch("shared.db.database.get_pool", AsyncMock()):
            try:
                await wm.main()
            except asyncio.CancelledError:
                pass

        # rpush should be called with DLQ_KEY
        rpush_calls = mock_r.rpush.call_args_list
        dlq_call = next(
            (c for c in rpush_calls if c[0][0] == wm.DLQ_KEY),
            None,
        )
        assert dlq_call is not None, "Expected a push to DLQ"

    async def test_main_closes_redis_on_exit(self):
        """After the loop exits (CancelledError), redis.aclose() is called."""
        import services.worker.main as wm

        mock_r = _make_redis(blpop_values=[])  # immediately CancelledError

        with patch("services.worker.main._get_redis", AsyncMock(return_value=mock_r)), \
             patch("services.worker.main.process_task", AsyncMock()), \
             patch("shared.db.database.get_pool", AsyncMock()):
            try:
                await wm.main()
            except asyncio.CancelledError:
                pass

        mock_r.aclose.assert_called_once()

    async def test_main_handles_db_pool_init_failure(self):
        """If get_pool() raises, main() logs error and continues to Redis."""
        import services.worker.main as wm

        mock_r = _make_redis(blpop_values=[])

        with patch("services.worker.main._get_redis", AsyncMock(return_value=mock_r)), \
             patch("shared.db.database.get_pool", AsyncMock(side_effect=Exception("DB down"))), \
             patch("services.worker.main.log") as mock_log:
            try:
                await wm.main()
            except asyncio.CancelledError:
                pass

        assert mock_log.error.called

    async def test_main_handles_none_blpop_result(self):
        """When blpop times out (returns None), loop continues without error."""
        import services.worker.main as wm

        # First call: timeout → None; second call: CancelledError
        mock_r = _make_redis(blpop_values=[None])

        processed = []
        async def _fake_process(task):
            processed.append(task)

        with patch("services.worker.main._get_redis", AsyncMock(return_value=mock_r)), \
             patch("services.worker.main.process_task", _fake_process), \
             patch("shared.db.database.get_pool", AsyncMock()):
            try:
                await wm.main()
            except asyncio.CancelledError:
                pass

        # No real tasks consumed — the stats_counter still ticks
        # but no user task should appear in processed
        user_tasks = [t for t in processed if t.get("type") not in ("daily_stats", "metrics_alert")]
        assert user_tasks == []

    async def test_main_loop_error_sleeps_before_retry(self):
        """A generic exception in the loop body results in asyncio.sleep(10)."""
        import services.worker.main as wm

        sleep_calls = []
        call_count = [0]

        async def _fake_sleep(seconds):
            sleep_calls.append(seconds)

        # First blpop raises a generic error (not CancelledError), second raises CancelledError
        mock_r = AsyncMock()
        mock_r.rpush = AsyncMock()
        mock_r.aclose = AsyncMock()
        mock_r.blpop = AsyncMock(side_effect=[
            Exception("unexpected redis error"),
            asyncio.CancelledError(),
        ])

        with patch("services.worker.main._get_redis", AsyncMock(return_value=mock_r)), \
             patch("services.worker.main.process_task", AsyncMock()), \
             patch("shared.db.database.get_pool", AsyncMock()), \
             patch("asyncio.sleep", _fake_sleep):
            try:
                await wm.main()
            except asyncio.CancelledError:
                pass

        assert 10 in sleep_calls

    async def test_main_periodic_tasks_fired_at_720_iterations(self):
        """After 720 loop iterations, daily_stats and metrics_alert are dispatched."""
        import services.worker.main as wm

        # Produce 720 None results (timeouts) then a CancelledError
        blpop_results = [None] * 720 + [asyncio.CancelledError()]
        mock_r = AsyncMock()
        mock_r.rpush = AsyncMock()
        mock_r.aclose = AsyncMock()
        mock_r.blpop = AsyncMock(side_effect=blpop_results)

        processed_types = []
        async def _fake_process(task):
            processed_types.append(task.get("type"))

        with patch("services.worker.main._get_redis", AsyncMock(return_value=mock_r)), \
             patch("services.worker.main.process_task", _fake_process), \
             patch("shared.db.database.get_pool", AsyncMock()):
            try:
                await wm.main()
            except asyncio.CancelledError:
                pass

        assert "daily_stats" in processed_types
        assert "metrics_alert" in processed_types


# ---------------------------------------------------------------------------
# Constants / module-level attributes
# ---------------------------------------------------------------------------

def test_queue_key_constant():
    import services.worker.main as wm
    assert wm.QUEUE_KEY == "neurobox:tasks"


def test_dlq_key_constant():
    import services.worker.main as wm
    assert wm.DLQ_KEY == "neurobox:tasks:dlq"


def test_max_task_retries_constant():
    import services.worker.main as wm
    assert wm.MAX_TASK_RETRIES == 3


def test_module_importable():
    import services.worker.main as wm
    assert wm is not None
    assert callable(wm.process_task)
    assert callable(wm.main)
    assert callable(wm._get_redis)
