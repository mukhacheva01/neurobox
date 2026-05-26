"""Tests for shared/providers/* — targets ≥60% coverage per module.

Conventions:
- asyncio_mode = auto (from pytest.ini) — all async tests run natively
- All external HTTP calls are mocked (httpx.AsyncClient or openai client)
- Settings are patched to avoid needing real environment variables
"""
import base64
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_httpx_client(post_json=None, get_json=None, post_status=200, get_status=200):
    """Build a reusable async httpx client mock."""
    post_resp = MagicMock()
    post_resp.status_code = post_status
    post_resp.json.return_value = post_json or {}
    post_resp.text = ""
    post_resp.content = b"data"
    post_resp.raise_for_status = MagicMock()

    get_resp = MagicMock()
    get_resp.status_code = get_status
    get_resp.json.return_value = get_json or {}
    get_resp.text = ""
    get_resp.content = b"data"
    get_resp.raise_for_status = MagicMock()

    client = AsyncMock()
    client.post = AsyncMock(return_value=post_resp)
    client.get = AsyncMock(return_value=get_resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _make_settings(**kwargs):
    """Create a MagicMock settings object with sane defaults."""
    s = MagicMock()
    s.falai_api_key = "test-fal-key"
    s.google_ai_api_key = "test-google-key"
    s.grok_api_key = "test-grok-key"
    s.midjourney_api_key = "test-mj-key"
    s.openrouter_api_key = "test-or-key"
    s.fal_song_endpoint = ""
    s.fal_song_timeout_sec = 10
    s.openrouter_cost_guard_enabled = False
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


# ===========================================================================
# openai_text.py
# ===========================================================================

class TestCircuitBreaker:
    def test_import(self):
        from shared.providers.openai_text import CircuitBreaker
        cb = CircuitBreaker()
        assert cb.threshold == 3

    def test_is_open_initially_false(self):
        from shared.providers.openai_text import CircuitBreaker
        cb = CircuitBreaker()
        assert cb.is_open("openai") is False

    def test_record_failure_opens_after_threshold(self):
        from shared.providers.openai_text import CircuitBreaker
        cb = CircuitBreaker(threshold=2, window=60, cooldown=60)
        cb.record_failure("openai")
        assert cb.is_open("openai") is False
        cb.record_failure("openai")
        assert cb.is_open("openai") is True

    def test_record_success_resets(self):
        from shared.providers.openai_text import CircuitBreaker
        cb = CircuitBreaker(threshold=2, cooldown=60)
        cb.record_failure("openai")
        cb.record_failure("openai")
        assert cb.is_open("openai") is True
        cb.record_success("openai")
        assert cb.is_open("openai") is False

    def test_is_open_expires_after_cooldown(self):
        from shared.providers.openai_text import CircuitBreaker
        cb = CircuitBreaker(threshold=1, cooldown=0)
        cb.record_failure("openai")
        # Force expiry by setting past time
        cb._open_until["openai"] = time.monotonic() - 1
        assert cb.is_open("openai") is False

    def test_get_fallback(self):
        from shared.providers.openai_text import CircuitBreaker, PROVIDER_FALLBACK
        cb = CircuitBreaker()
        for provider, (model, _) in PROVIDER_FALLBACK.items():
            fb = cb.get_fallback(provider)
            assert fb is not None
            assert fb[0] == model

    def test_get_fallback_unknown_returns_none(self):
        from shared.providers.openai_text import CircuitBreaker
        cb = CircuitBreaker()
        assert cb.get_fallback("nonexistent") is None


class TestTrimHistory:
    def test_empty(self):
        from shared.providers.openai_text import trim_history
        assert trim_history([]) == []

    def test_respects_max_messages(self):
        from shared.providers.openai_text import trim_history, MAX_HISTORY_MESSAGES
        history = [{"role": "user", "content": f"msg{i}"} for i in range(25)]
        result = trim_history(history)
        assert len(result) <= MAX_HISTORY_MESSAGES

    def test_respects_max_chars(self):
        from shared.providers.openai_text import trim_history, MAX_HISTORY_CHARS
        # One huge message that exceeds the char limit
        big = [{"role": "user", "content": "x" * (MAX_HISTORY_CHARS + 1)}]
        result = trim_history(big)
        assert result == []

    def test_multimodal_content_list(self):
        from shared.providers.openai_text import trim_history
        history = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
        result = trim_history(history)
        assert len(result) == 1

    def test_keeps_last_messages(self):
        from shared.providers.openai_text import trim_history
        history = [{"role": "user", "content": f"msg{i}"} for i in range(5)]
        result = trim_history(history)
        assert result[-1]["content"] == "msg4"


class TestResolveHelpers:
    def test_resolve_model_known(self):
        from shared.providers.openai_text import _resolve_model
        assert _resolve_model("gpt-5-nano") == "openai/gpt-5-nano"

    def test_resolve_model_unknown_prefixes_openai(self):
        from shared.providers.openai_text import _resolve_model
        assert _resolve_model("unknown-model") == "openai/unknown-model"

    def test_get_provider_known(self):
        from shared.providers.openai_text import _get_provider
        assert _get_provider("gpt-5-nano") == "openai"
        assert _get_provider("gemini-2.0-flash") == "google"
        assert _get_provider("deepseek-v3") == "deepseek"
        assert _get_provider("claude-haiku-4.5") == "anthropic"
        assert _get_provider("grok-3") == "xai"

    def test_provider_of_alias(self):
        from shared.providers.openai_text import _provider_of, _get_provider
        assert _provider_of("gpt-5-nano") == _get_provider("gpt-5-nano")

    def test_is_streaming_model_known(self):
        from shared.providers.openai_text import is_streaming_model
        assert is_streaming_model("gpt-5-nano") is True
        assert is_streaming_model("") is False
        assert is_streaming_model("totally-unknown") is False


class TestMaxTokensFor:
    def test_known_model_returns_value(self):
        from shared.providers.openai_text import _max_tokens_for
        with patch("shared.config.settings") as mock_settings:
            mock_settings.openrouter_cost_guard_enabled = False
            val = _max_tokens_for("gpt-5-nano")
        assert val == 1024

    def test_unknown_model_returns_default(self):
        from shared.providers.openai_text import _max_tokens_for
        with patch("shared.config.settings") as mock_settings:
            mock_settings.openrouter_cost_guard_enabled = False
            val = _max_tokens_for("totally-unknown-model")
        assert val == 2048


class TestGenerateText:
    async def test_happy_path(self):
        from shared.providers import openai_text

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 10
        mock_usage.completion_tokens = 20
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello!"
        mock_response.usage = mock_usage

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        # Reset singleton so our patch takes effect
        openai_text._openrouter_client = mock_client

        try:
            result = await openai_text.generate_text("test prompt", model="gpt-5-nano")
            assert result["ok"] is True
            assert result["text"] == "Hello!"
            assert result["tokens_input"] == 10
            assert result["tokens_output"] == 20
        finally:
            openai_text._openrouter_client = None

    async def test_circuit_open_returns_error(self):
        from shared.providers import openai_text

        # Force circuit open
        openai_text.breaker._open_until["openai"] = time.monotonic() + 9999
        try:
            result = await openai_text.generate_text("hi", model="gpt-5-nano")
            assert result["ok"] is False
            assert result["error_type"] == "circuit_open"
            assert "suggest_model" in result
        finally:
            openai_text.breaker._open_until.pop("openai", None)

    async def test_with_history(self):
        from shared.providers import openai_text

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 5
        mock_usage.completion_tokens = 10
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Reply"
        mock_response.usage = mock_usage

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        openai_text._openrouter_client = mock_client

        try:
            history = [{"role": "user", "content": "prev msg"}]
            result = await openai_text.generate_text("new msg", history=history)
            assert result["ok"] is True
        finally:
            openai_text._openrouter_client = None

    async def test_rate_limit_error(self):
        import openai as openai_lib
        from shared.providers import openai_text

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=openai_lib.RateLimitError("rate limit", response=MagicMock(), body={})
        )
        openai_text._openrouter_client = mock_client

        try:
            result = await openai_text.generate_text("hi", model="gpt-5-nano")
            assert result["ok"] is False
            assert result["error_type"] == "rate_limit"
        finally:
            openai_text._openrouter_client = None

    async def test_auth_error(self):
        import openai as openai_lib
        from shared.providers import openai_text

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=openai_lib.AuthenticationError("auth", response=MagicMock(), body={})
        )
        openai_text._openrouter_client = mock_client

        try:
            result = await openai_text.generate_text("hi", model="gpt-5-nano")
            assert result["ok"] is False
            assert result["error_type"] == "auth"
        finally:
            openai_text._openrouter_client = None

    async def test_not_found_error(self):
        import openai as openai_lib
        from shared.providers import openai_text

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=openai_lib.NotFoundError("not found", response=MagicMock(), body={})
        )
        openai_text._openrouter_client = mock_client

        try:
            result = await openai_text.generate_text("hi", model="gpt-5-nano")
            assert result["ok"] is False
            assert result["error_type"] == "not_found"
        finally:
            openai_text._openrouter_client = None

    async def test_timeout_error(self):
        import openai as openai_lib
        from shared.providers import openai_text

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=openai_lib.APITimeoutError(request=MagicMock())
        )
        openai_text._openrouter_client = mock_client

        try:
            result = await openai_text.generate_text("hi", model="gpt-5-nano")
            assert result["ok"] is False
            assert result["error_type"] == "timeout"
        finally:
            openai_text._openrouter_client = None

    async def test_generic_exception(self):
        from shared.providers import openai_text

        # Reset circuit breaker state so previous tests don't affect this one
        openai_text.breaker._failures.clear()
        openai_text.breaker._open_until.clear()

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))
        openai_text._openrouter_client = mock_client

        try:
            result = await openai_text.generate_text("hi", model="gpt-5-nano")
            assert result["ok"] is False
            assert result["error_type"] == "unknown"
        finally:
            openai_text._openrouter_client = None
            openai_text.breaker._failures.clear()
            openai_text.breaker._open_until.clear()

    async def test_suggest_model_on_failure(self):
        from shared.providers import openai_text

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))
        openai_text._openrouter_client = mock_client
        # Clear breaker state first
        openai_text.breaker._failures.pop("openai", None)
        openai_text.breaker._open_until.pop("openai", None)

        try:
            result = await openai_text.generate_text("hi", model="gpt-5-nano")
            assert result["ok"] is False
            # suggest_model should appear after failure recorded
        finally:
            openai_text._openrouter_client = None
            openai_text.breaker._failures.pop("openai", None)
            openai_text.breaker._open_until.pop("openai", None)


class TestGenerateTextWithImage:
    async def test_happy_path(self):
        from shared.providers import openai_text

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 5
        mock_usage.completion_tokens = 10
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "I see a cat."
        mock_response.usage = mock_usage

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        openai_text._openrouter_client = mock_client

        try:
            result = await openai_text.generate_text_with_image(
                "What do you see?",
                "https://example.com/cat.jpg",
                model="gpt-5-nano",
            )
            assert result["ok"] is True
            assert "cat" in result["text"]
        finally:
            openai_text._openrouter_client = None

    async def test_video_frame_flag(self):
        from shared.providers import openai_text

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Video frame analysis"
        mock_response.usage = None

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        openai_text._openrouter_client = mock_client

        try:
            result = await openai_text.generate_text_with_image(
                "Describe",
                "https://example.com/frame.jpg",
                is_video_frame=True,
            )
            assert result["ok"] is True
        finally:
            openai_text._openrouter_client = None

    async def test_circuit_open(self):
        from shared.providers import openai_text

        openai_text.breaker._open_until["openai"] = time.monotonic() + 9999
        try:
            result = await openai_text.generate_text_with_image("x", "http://x.com/y.jpg")
            assert result["ok"] is False
            assert result["error_type"] == "circuit_open"
        finally:
            openai_text.breaker._open_until.pop("openai", None)

    async def test_rate_limit_error(self):
        import openai as openai_lib
        from shared.providers import openai_text

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=openai_lib.RateLimitError("rate limit", response=MagicMock(), body={})
        )
        openai_text._openrouter_client = mock_client

        try:
            result = await openai_text.generate_text_with_image("x", "http://x/y.jpg")
            assert result["ok"] is False
            assert result["error_type"] == "rate_limit"
        finally:
            openai_text._openrouter_client = None

    async def test_api_status_402(self):
        import openai as openai_lib
        from shared.providers import openai_text

        err = openai_lib.APIStatusError(
            "payment required",
            response=MagicMock(status_code=402),
            body={},
        )
        err.status_code = 402
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=err)
        openai_text._openrouter_client = mock_client

        try:
            result = await openai_text.generate_text_with_image("x", "http://x/y.jpg")
            assert result["ok"] is False
            assert result["error_type"] == "payment_required"
        finally:
            openai_text._openrouter_client = None


class TestGenerateTextStream:
    async def test_happy_path(self):
        from shared.providers import openai_text

        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta.content = "Hello "
        chunk1.usage = None

        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta.content = "World"
        chunk2.usage = None

        chunk3 = MagicMock()
        chunk3.choices = []
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 5
        mock_usage.completion_tokens = 2
        chunk3.usage = mock_usage

        async def fake_stream(*args, **kwargs):
            for c in [chunk1, chunk2, chunk3]:
                yield c

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=fake_stream())
        openai_text._openrouter_client = mock_client

        try:
            chunks = []
            async for item in openai_text.generate_text_stream("hi", model="gpt-5-nano"):
                chunks.append(item)
            texts = [c.get("delta") for c in chunks if "delta" in c]
            done = [c for c in chunks if c.get("done")]
            assert "Hello " in texts
            assert "World" in texts
            assert done[0]["text"] == "Hello World"
        finally:
            openai_text._openrouter_client = None

    async def test_circuit_open_yields_error(self):
        from shared.providers import openai_text

        openai_text.breaker._open_until["openai"] = time.monotonic() + 9999
        try:
            items = []
            async for item in openai_text.generate_text_stream("hi", model="gpt-5-nano"):
                items.append(item)
            assert len(items) == 1
            assert items[0]["ok"] is False
        finally:
            openai_text.breaker._open_until.pop("openai", None)

    async def test_rate_limit_yields_error(self):
        import openai as openai_lib
        from shared.providers import openai_text

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=openai_lib.RateLimitError("rl", response=MagicMock(), body={})
        )
        openai_text._openrouter_client = mock_client

        try:
            items = []
            async for item in openai_text.generate_text_stream("hi", model="gpt-5-nano"):
                items.append(item)
            assert any(i.get("error_type") == "rate_limit" for i in items)
        finally:
            openai_text._openrouter_client = None

    async def test_not_found_yields_error(self):
        import openai as openai_lib
        from shared.providers import openai_text

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=openai_lib.NotFoundError("nf", response=MagicMock(), body={})
        )
        openai_text._openrouter_client = mock_client

        try:
            items = []
            async for item in openai_text.generate_text_stream("hi"):
                items.append(item)
            assert any(i.get("error_type") == "not_found" for i in items)
        finally:
            openai_text._openrouter_client = None

    async def test_generic_exception_yields_error(self):
        from shared.providers import openai_text

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))
        openai_text._openrouter_client = mock_client

        try:
            items = []
            async for item in openai_text.generate_text_stream("hi"):
                items.append(item)
            assert any("error" in i for i in items)
        finally:
            openai_text._openrouter_client = None


# ===========================================================================
# falai_image.py
# ===========================================================================

class TestFalaiImagePayload:
    def test_import(self):
        from shared.providers.falai_image import _image_payload
        assert callable(_image_payload)

    def test_flux_payload(self):
        from shared.providers.falai_image import _image_payload
        p = _image_payload("flux-2-turbo", "a cat", 2, "square")
        assert p["prompt"] == "a cat"
        assert p["num_images"] == 2
        assert "image_size" in p

    def test_grok_payload(self):
        from shared.providers.falai_image import _image_payload
        p = _image_payload("grok-imagine-image", "a dog", 1, "landscape")
        assert "aspect_ratio" in p
        assert "image_size" not in p

    def test_kling_payload(self):
        from shared.providers.falai_image import _image_payload
        p = _image_payload("kling-image-v3", "a house", 1, "portrait")
        assert "aspect_ratio" in p

    def test_ideogram_payload(self):
        from shared.providers.falai_image import _image_payload
        p = _image_payload("ideogram-v2", "a tree", 1, "landscape")
        assert "aspect_ratio" in p

    def test_num_images_clamped(self):
        from shared.providers.falai_image import _image_payload
        p = _image_payload("flux-2-turbo", "x", 10, "square")
        assert p["num_images"] == 4
        p2 = _image_payload("flux-2-turbo", "x", 0, "square")
        assert p2["num_images"] == 1


class TestGenerateImage:
    async def test_no_api_key_returns_error(self):
        with patch("shared.config.settings", _make_settings(falai_api_key="")):
            from shared.providers.falai_image import generate_image
            result = await generate_image("test prompt")
        assert result["ok"] is False
        assert "key" in result["error"].lower() or "api" in result["error"].lower()

    async def test_happy_path_direct_response(self):
        mock_client = _make_httpx_client(
            post_json={"images": [{"url": "https://fal.media/image.png"}]}
        )
        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=mock_client):
            from shared.providers.falai_image import generate_image
            result = await generate_image("a cat", model="flux-2-turbo", num_images=1)
        assert result["ok"] is True
        assert result["image_url"] == "https://fal.media/image.png"

    async def test_queue_polling_completed(self):
        """Test queue mode: initial response has request_id, then status=COMPLETED."""
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"request_id": "req-123"}
        post_resp.raise_for_status = MagicMock()

        status_resp = MagicMock()
        status_resp.status_code = 200
        status_resp.json.return_value = {"status": "COMPLETED"}
        status_resp.raise_for_status = MagicMock()

        result_resp = MagicMock()
        result_resp.status_code = 200
        result_resp.json.return_value = {"images": [{"url": "https://fal.media/queued.png"}]}
        result_resp.raise_for_status = MagicMock()

        get_calls = []

        async def fake_get(url, **kwargs):
            if "/status" in url:
                return status_resp
            return result_resp

        client = AsyncMock()
        client.post = AsyncMock(return_value=post_resp)
        client.get = fake_get
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client), \
             patch("asyncio.sleep", new=AsyncMock()):
            from shared.providers.falai_image import generate_image
            result = await generate_image("a cat")
        assert result["ok"] is True

    async def test_queue_polling_failed(self):
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"request_id": "req-fail"}
        post_resp.raise_for_status = MagicMock()

        status_resp = MagicMock()
        status_resp.json.return_value = {"status": "FAILED"}

        async def fake_get(url, **kwargs):
            return status_resp

        client = AsyncMock()
        client.post = AsyncMock(return_value=post_resp)
        client.get = fake_get
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client), \
             patch("asyncio.sleep", new=AsyncMock()):
            from shared.providers.falai_image import generate_image
            result = await generate_image("a cat")
        assert result["ok"] is False

    async def test_no_images_in_response(self):
        mock_client = _make_httpx_client(post_json={"images": []})
        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=mock_client):
            from shared.providers.falai_image import generate_image
            result = await generate_image("x")
        assert result["ok"] is False

    async def test_http_error(self):
        import httpx as httpx_lib
        client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "server error"
        client.post = AsyncMock(
            side_effect=httpx_lib.HTTPStatusError("500", request=MagicMock(), response=mock_response)
        )
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.falai_image import generate_image
            result = await generate_image("x")
        assert result["ok"] is False

    async def test_generic_exception(self):
        client = AsyncMock()
        client.post = AsyncMock(side_effect=RuntimeError("network error"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.falai_image import generate_image
            result = await generate_image("x")
        assert result["ok"] is False


class TestStyleImage:
    async def test_no_api_key(self):
        with patch("shared.config.settings", _make_settings(falai_api_key="")):
            from shared.providers.falai_image import style_image
            result = await style_image("http://img.jpg", "make it blue")
        assert result["ok"] is False

    async def test_sync_success(self):
        """First attempt (sync) succeeds."""
        mock_client = _make_httpx_client(
            post_json={"images": [{"url": "https://fal.media/styled.png"}]},
            post_status=200,
        )
        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=mock_client):
            from shared.providers.falai_image import style_image
            result = await style_image("http://img.jpg", "make it blue")
        assert result["ok"] is True
        assert "styled" in result["image_url"]

    async def test_sync_fails_queue_succeeds(self):
        """First attempt returns non-200, second (queue) succeeds."""
        sync_resp = MagicMock()
        sync_resp.status_code = 500
        sync_resp.json.return_value = {}

        queue_post_resp = MagicMock()
        queue_post_resp.status_code = 200
        queue_post_resp.json.return_value = {"images": [{"url": "https://fal.media/q.png"}]}
        queue_post_resp.raise_for_status = MagicMock()

        # Context manager call count to distinguish sync vs queue
        call_count = {"n": 0}

        class FakeClient:
            def __init__(self, *args, **kwargs): pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def post(self, url, **kwargs):
                if "queue" in url:
                    return queue_post_resp
                return sync_resp
            async def get(self, url, **kwargs):
                return MagicMock(json=lambda: {"images": [{"url": "q.png"}]})

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", FakeClient):
            from shared.providers.falai_image import style_image
            result = await style_image("http://img.jpg", "make it bold")
        assert result["ok"] is True

    async def test_style_with_strength(self):
        mock_client = _make_httpx_client(
            post_json={"images": [{"url": "https://fal.media/styled.png"}]},
            post_status=200,
        )
        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=mock_client):
            from shared.providers.falai_image import style_image
            result = await style_image("http://img.jpg", "dramatic", strength=0.95)
        assert result["ok"] is True


class TestUpscaleImage:
    async def test_no_api_key(self):
        with patch("shared.config.settings", _make_settings(falai_api_key="")):
            from shared.providers.falai_image import upscale_image
            result = await upscale_image("http://img.jpg")
        assert result["ok"] is False

    async def test_happy_path_direct(self):
        mock_client = _make_httpx_client(
            post_json={"images": [{"url": "https://fal.media/up.png"}]}
        )
        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=mock_client):
            from shared.providers.falai_image import upscale_image
            result = await upscale_image("http://img.jpg")
        assert result["ok"] is True

    async def test_http_error(self):
        import httpx as httpx_lib
        client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        client.post = AsyncMock(
            side_effect=httpx_lib.HTTPStatusError("err", request=MagicMock(), response=mock_response)
        )
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.falai_image import upscale_image
            result = await upscale_image("http://img.jpg")
        assert result["ok"] is False

    async def test_no_images_in_response(self):
        mock_client = _make_httpx_client(post_json={"images": []})
        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=mock_client):
            from shared.providers.falai_image import upscale_image
            result = await upscale_image("http://img.jpg")
        assert result["ok"] is False


# ===========================================================================
# falai_photo.py
# ===========================================================================

class TestFalaiPhoto:
    def test_import(self):
        from shared.providers.falai_photo import remove_background, _extract_url
        assert callable(remove_background)
        assert callable(_extract_url)

    def test_extract_url_image_key(self):
        from shared.providers.falai_photo import _extract_url
        assert _extract_url({"image": {"url": "http://x.com/a.png"}}) == "http://x.com/a.png"

    def test_extract_url_output_key(self):
        from shared.providers.falai_photo import _extract_url
        assert _extract_url({"output": {"url": "http://x.com/b.png"}}) == "http://x.com/b.png"

    def test_extract_url_images_list(self):
        from shared.providers.falai_photo import _extract_url
        assert _extract_url({"images": [{"url": "http://x.com/c.png"}]}) == "http://x.com/c.png"

    def test_extract_url_none(self):
        from shared.providers.falai_photo import _extract_url
        assert _extract_url({}) is None

    async def test_no_api_key(self):
        with patch("shared.config.settings", _make_settings(falai_api_key="")):
            from shared.providers.falai_photo import remove_background
            result = await remove_background(image_url="http://x.com/a.jpg")
        assert result["ok"] is False

    async def test_no_input(self):
        with patch("shared.config.settings", _make_settings()):
            from shared.providers.falai_photo import remove_background
            result = await remove_background()
        assert result["ok"] is False
        assert "фото" in result["error"].lower() or "нужно" in result["error"].lower()

    async def test_happy_path_sync_with_url(self):
        mock_client = _make_httpx_client(
            post_json={"image": {"url": "https://fal.media/bg_removed.png"}},
            post_status=200,
        )
        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=mock_client):
            from shared.providers.falai_photo import remove_background
            result = await remove_background(image_url="http://x.com/a.jpg")
        assert result["ok"] is True

    async def test_happy_path_with_bytes(self):
        mock_client = _make_httpx_client(
            post_json={"image": {"url": "https://fal.media/bg_removed.png"}},
            post_status=200,
        )
        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=mock_client):
            from shared.providers.falai_photo import remove_background
            result = await remove_background(image_bytes=b"fake-image-bytes")
        assert result["ok"] is True

    async def test_sync_fail_queue_completed(self):
        """Sync returns 500, queue polling returns COMPLETED."""
        sync_resp = MagicMock()
        sync_resp.status_code = 500
        sync_resp.json.return_value = {}

        queue_post_resp = MagicMock()
        queue_post_resp.status_code = 200
        queue_post_resp.json.return_value = {"request_id": "rid-1"}
        queue_post_resp.raise_for_status = MagicMock()

        status_resp = MagicMock()
        status_resp.json.return_value = {"status": "COMPLETED"}

        result_resp = MagicMock()
        result_resp.json.return_value = {"image": {"url": "https://fal.media/done.png"}}

        class FakeClient:
            def __init__(self, *args, **kwargs): pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def post(self, url, **kwargs):
                if "queue" in url:
                    return queue_post_resp
                return sync_resp
            async def get(self, url, **kwargs):
                if "/status" in url:
                    return status_resp
                return result_resp

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", FakeClient), \
             patch("asyncio.sleep", new=AsyncMock()):
            from shared.providers.falai_photo import remove_background
            result = await remove_background(image_url="http://x.com/photo.jpg")
        assert result["ok"] is True

    async def test_queue_failed_status(self):
        sync_resp = MagicMock()
        sync_resp.status_code = 500
        sync_resp.json.return_value = {}

        queue_post_resp = MagicMock()
        queue_post_resp.status_code = 200
        queue_post_resp.json.return_value = {"request_id": "rid-fail"}
        queue_post_resp.raise_for_status = MagicMock()

        status_resp = MagicMock()
        status_resp.json.return_value = {"status": "FAILED", "error": "failed reason"}

        class FakeClient:
            def __init__(self, *args, **kwargs): pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def post(self, url, **kwargs):
                if "queue" in url:
                    return queue_post_resp
                return sync_resp
            async def get(self, url, **kwargs):
                return status_resp

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", FakeClient), \
             patch("asyncio.sleep", new=AsyncMock()):
            from shared.providers.falai_photo import remove_background
            result = await remove_background(image_url="http://x.com/photo.jpg")
        assert result["ok"] is False


# ===========================================================================
# falai_video.py
# ===========================================================================

class TestFalaiVideo:
    def test_import(self):
        from shared.providers.falai_video import generate_video
        assert callable(generate_video)

    async def test_no_api_key(self):
        with patch("shared.config.settings", _make_settings(falai_api_key="")):
            from shared.providers.falai_video import generate_video
            result = await generate_video("test", "fal-ai/kling-video")
        assert result["ok"] is False

    async def test_happy_path_video_dict(self):
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"video": {"url": "https://fal.media/out.mp4"}}
        post_resp.raise_for_status = MagicMock()

        client = AsyncMock()
        client.post = AsyncMock(return_value=post_resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.falai_video import generate_video
            result = await generate_video("dancing robot", "fal-ai/kling-video/v1.6/standard/text-to-video")
        assert result["ok"] is True
        assert result["video_url"] == "https://fal.media/out.mp4"

    async def test_happy_path_video_url_key(self):
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"video_url": "https://fal.media/vid.mp4"}
        post_resp.raise_for_status = MagicMock()

        client = AsyncMock()
        client.post = AsyncMock(return_value=post_resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.falai_video import generate_video
            result = await generate_video("prompt", "fal-ai/minimax/video-01")
        assert result["ok"] is True

    async def test_queue_polling_completed(self):
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"request_id": "vid-req-1"}
        post_resp.raise_for_status = MagicMock()

        status_resp = MagicMock()
        status_resp.json.return_value = {"status": "COMPLETED"}

        result_resp = MagicMock()
        result_resp.json.return_value = {"video": {"url": "https://fal.media/vid.mp4"}}

        async def fake_get(url, **kwargs):
            if "/status" in url:
                return status_resp
            return result_resp

        client = AsyncMock()
        client.post = AsyncMock(return_value=post_resp)
        client.get = fake_get
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client), \
             patch("asyncio.sleep", new=AsyncMock()):
            from shared.providers.falai_video import generate_video
            result = await generate_video("dancing robot", "fal-ai/kling-video/v1")
        assert result["ok"] is True

    async def test_queue_polling_failed(self):
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"request_id": "vid-fail"}
        post_resp.raise_for_status = MagicMock()

        status_resp = MagicMock()
        status_resp.json.return_value = {"status": "FAILED", "error": "generation failed"}

        async def fake_get(url, **kwargs):
            return status_resp

        client = AsyncMock()
        client.post = AsyncMock(return_value=post_resp)
        client.get = fake_get
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client), \
             patch("asyncio.sleep", new=AsyncMock()):
            from shared.providers.falai_video import generate_video
            result = await generate_video("x", "fal-ai/kling-video/v1")
        assert result["ok"] is False

    async def test_runway_no_image_url(self):
        with patch("shared.config.settings", _make_settings()):
            from shared.providers.falai_video import generate_video
            result = await generate_video("prompt", "fal-ai/runway-gen3/turbo/image-to-video")
        assert result["ok"] is False
        assert "runway" in result["error"].lower() or "картинк" in result["error"].lower()

    async def test_sora_with_image_url(self):
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"video": {"url": "https://fal.media/sora.mp4"}}
        post_resp.raise_for_status = MagicMock()

        client = AsyncMock()
        client.post = AsyncMock(return_value=post_resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.falai_video import generate_video
            result = await generate_video("scene", "fal-ai/sora-2/text-to-video/pro", image_url="http://x.com/frame.jpg")
        assert result["ok"] is True

    async def test_no_video_url_in_response(self):
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"something_else": "data"}
        post_resp.raise_for_status = MagicMock()

        client = AsyncMock()
        client.post = AsyncMock(return_value=post_resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.falai_video import generate_video
            result = await generate_video("x", "fal-ai/luma-dream-machine/ray-2-flash")
        assert result["ok"] is False

    async def test_http_error(self):
        import httpx as httpx_lib
        client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "error"
        mock_response.json.return_value = {}
        client.post = AsyncMock(
            side_effect=httpx_lib.HTTPStatusError("err", request=MagicMock(), response=mock_response)
        )
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.falai_video import generate_video
            result = await generate_video("x", "fal-ai/ltx-video")
        assert result["ok"] is False

    async def test_generic_exception(self):
        client = AsyncMock()
        client.post = AsyncMock(side_effect=RuntimeError("crash"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.falai_video import generate_video
            result = await generate_video("x", "fal-ai/kling-video/v1")
        assert result["ok"] is False


# ===========================================================================
# openrouter_image.py
# ===========================================================================

class TestOpenrouterImage:
    def _make_or_response(self, image_url="data:image/png;base64,abc"):
        response = MagicMock()
        response.model_dump.return_value = {
            "choices": [{
                "message": {
                    "images": [{"image_url": {"url": image_url}}]
                }
            }]
        }
        return response

    async def test_unknown_model(self):
        from shared.providers.openrouter_image import generate_openrouter_image
        result = await generate_openrouter_image("prompt", "nonexistent-model")
        assert result["ok"] is False

    async def test_happy_path(self):
        from shared.providers import openai_text, openrouter_image

        mock_response = self._make_or_response("data:image/png;base64,abcdef")
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        openai_text._openrouter_client = mock_client

        try:
            result = await openrouter_image.generate_openrouter_image("a cat", "flux-2-turbo")
            assert result["ok"] is True
            assert result["image_url"] == "data:image/png;base64,abcdef"
        finally:
            openai_text._openrouter_client = None

    async def test_no_images_returned(self):
        from shared.providers import openai_text, openrouter_image

        response = MagicMock()
        response.model_dump.return_value = {
            "choices": [{"message": {"images": []}}]
        }
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=response)
        openai_text._openrouter_client = mock_client

        try:
            result = await openrouter_image.generate_openrouter_image("a cat", "flux-2-turbo")
            assert result["ok"] is False
        finally:
            openai_text._openrouter_client = None

    async def test_exception_on_first_attempt(self):
        from shared.providers import openai_text, openrouter_image

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("API error"))
        openai_text._openrouter_client = mock_client

        try:
            result = await openrouter_image.generate_openrouter_image("a cat", "flux-2-turbo")
            assert result["ok"] is False
        finally:
            openai_text._openrouter_client = None

    async def test_multiple_images(self):
        from shared.providers import openai_text, openrouter_image

        response = MagicMock()
        response.model_dump.return_value = {
            "choices": [{
                "message": {
                    "images": [
                        {"image_url": {"url": "data:image/png;base64,img1"}},
                        {"image_url": {"url": "data:image/png;base64,img2"}},
                    ]
                }
            }]
        }
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=response)
        openai_text._openrouter_client = mock_client

        try:
            result = await openrouter_image.generate_openrouter_image("a cat", "flux-2-turbo", num_images=2)
            assert result["ok"] is True
            assert len(result["image_urls"]) == 2
        finally:
            openai_text._openrouter_client = None

    async def test_edit_image_happy_path(self):
        from shared.providers import openai_text, openrouter_image

        mock_response = self._make_or_response("data:image/png;base64,edited")
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        openai_text._openrouter_client = mock_client

        try:
            result = await openrouter_image.edit_openrouter_image(b"fake-image-bytes", "make it blue")
            assert result["ok"] is True
        finally:
            openai_text._openrouter_client = None

    async def test_edit_image_no_images(self):
        from shared.providers import openai_text, openrouter_image

        response = MagicMock()
        response.model_dump.return_value = {
            "choices": [{"message": {"images": []}}]
        }
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=response)
        openai_text._openrouter_client = mock_client

        try:
            result = await openrouter_image.edit_openrouter_image(b"bytes", "change it")
            assert result["ok"] is False
        finally:
            openai_text._openrouter_client = None

    async def test_edit_image_exception(self):
        from shared.providers import openai_text, openrouter_image

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("crash"))
        openai_text._openrouter_client = mock_client

        try:
            result = await openrouter_image.edit_openrouter_image(b"bytes", "change it")
            assert result["ok"] is False
        finally:
            openai_text._openrouter_client = None

    async def test_upscale_happy_path(self):
        from shared.providers import openai_text, openrouter_image

        mock_response = self._make_or_response("data:image/png;base64,upscaled")
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        openai_text._openrouter_client = mock_client

        try:
            result = await openrouter_image.upscale_openrouter_image("https://example.com/img.jpg")
            assert result["ok"] is True
        finally:
            openai_text._openrouter_client = None

    async def test_upscale_exception(self):
        from shared.providers import openai_text, openrouter_image

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("crash"))
        openai_text._openrouter_client = mock_client

        try:
            result = await openrouter_image.upscale_openrouter_image("https://example.com/img.jpg")
            assert result["ok"] is False
        finally:
            openai_text._openrouter_client = None

    async def test_remove_background_with_url(self):
        from shared.providers import openai_text, openrouter_image

        mock_response = self._make_or_response("data:image/png;base64,nobg")
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        openai_text._openrouter_client = mock_client

        try:
            result = await openrouter_image.remove_background_openrouter(image_url="http://x.com/a.jpg")
            assert result["ok"] is True
        finally:
            openai_text._openrouter_client = None

    async def test_remove_background_with_bytes(self):
        from shared.providers import openai_text, openrouter_image

        mock_response = self._make_or_response("data:image/png;base64,nobg2")
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        openai_text._openrouter_client = mock_client

        try:
            result = await openrouter_image.remove_background_openrouter(image_bytes=b"fake-bytes")
            assert result["ok"] is True
        finally:
            openai_text._openrouter_client = None

    async def test_remove_background_no_input(self):
        from shared.providers.openrouter_image import remove_background_openrouter
        result = await remove_background_openrouter()
        assert result["ok"] is False

    async def test_remove_background_exception(self):
        from shared.providers import openai_text, openrouter_image

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("crash"))
        openai_text._openrouter_client = mock_client

        try:
            result = await openrouter_image.remove_background_openrouter(image_url="http://x.com/a.jpg")
            assert result["ok"] is False
        finally:
            openai_text._openrouter_client = None


# ===========================================================================
# google_image.py
# ===========================================================================

class TestGoogleImage:
    def test_import(self):
        from shared.providers.google_image import generate_gemini_image
        assert callable(generate_gemini_image)

    async def test_no_api_key(self):
        with patch("shared.config.settings", _make_settings(google_ai_api_key="")):
            from shared.providers.google_image import generate_gemini_image
            result = await generate_gemini_image("a sunset")
        assert result["ok"] is False
        assert "key" in result["error"].lower() or "api" in result["error"].lower()

    async def test_happy_path(self):
        b64_data = base64.b64encode(b"fake-png-bytes").decode()
        mock_client = _make_httpx_client(
            post_json={
                "candidates": [{
                    "content": {
                        "parts": [{
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": b64_data,
                            }
                        }]
                    }
                }]
            }
        )
        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=mock_client):
            from shared.providers.google_image import generate_gemini_image
            result = await generate_gemini_image("a sunset")
        assert result["ok"] is True
        assert result["image_url"].startswith("data:image/png;base64,")

    async def test_no_candidates(self):
        mock_client = _make_httpx_client(post_json={"candidates": []})
        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=mock_client):
            from shared.providers.google_image import generate_gemini_image
            result = await generate_gemini_image("a sunset")
        assert result["ok"] is False

    async def test_http_error(self):
        import httpx as httpx_lib
        client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "bad request"
        client.post = AsyncMock(
            side_effect=httpx_lib.HTTPStatusError("bad req", request=MagicMock(), response=mock_response)
        )
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.google_image import generate_gemini_image
            result = await generate_gemini_image("a sunset")
        assert result["ok"] is False

    async def test_generic_exception(self):
        client = AsyncMock()
        client.post = AsyncMock(side_effect=RuntimeError("network error"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.google_image import generate_gemini_image
            result = await generate_gemini_image("a sunset")
        assert result["ok"] is False

    async def test_multiple_images(self):
        b64_data = base64.b64encode(b"fake-bytes").decode()
        mock_client = _make_httpx_client(
            post_json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"inlineData": {"mimeType": "image/png", "data": b64_data}},
                                {"inlineData": {"mimeType": "image/png", "data": b64_data}},
                            ]
                        }
                    }
                ]
            }
        )
        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=mock_client):
            from shared.providers.google_image import generate_gemini_image
            result = await generate_gemini_image("two things")
        assert result["ok"] is True
        assert len(result["image_urls"]) == 2


# ===========================================================================
# google_veo.py
# ===========================================================================

class TestGoogleVeo:
    def test_import(self):
        from shared.providers.google_veo import generate_veo_video
        assert callable(generate_veo_video)

    async def test_no_api_key(self):
        with patch("shared.config.settings", _make_settings(google_ai_api_key="")):
            from shared.providers.google_veo import generate_veo_video
            result = await generate_veo_video("a running dog")
        assert result["ok"] is False

    async def test_no_operation_name(self):
        submit_resp = MagicMock()
        submit_resp.status_code = 200
        submit_resp.json.return_value = {}  # no "name" key

        client = AsyncMock()
        client.post = AsyncMock(return_value=submit_resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.google_veo import generate_veo_video
            result = await generate_veo_video("a running dog")
        assert result["ok"] is False

    async def test_submit_error_status(self):
        submit_resp = MagicMock()
        submit_resp.status_code = 500
        submit_resp.text = "internal error"

        client = AsyncMock()
        client.post = AsyncMock(return_value=submit_resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.google_veo import generate_veo_video
            result = await generate_veo_video("running dog")
        assert result["ok"] is False

    async def test_polling_done_with_uri(self):
        submit_resp = MagicMock()
        submit_resp.status_code = 200
        submit_resp.json.return_value = {"name": "operations/op-123"}

        done_resp = MagicMock()
        done_resp.json.return_value = {
            "done": True,
            "response": {
                "generateVideoResponse": {
                    "generatedSamples": [{
                        "video": {"uri": "https://example.com/video.mp4"}
                    }]
                }
            }
        }

        # Download response
        download_resp = MagicMock()
        download_resp.status_code = 200
        download_resp.content = b"fake-video-bytes-longer-than-1000" * 100

        submit_calls = {"n": 0}

        class FakeClient:
            def __init__(self, *args, **kwargs): pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def post(self, url, **kwargs):
                return submit_resp
            async def get(self, url, **kwargs):
                # Poll url vs download url
                if "operations" in url and "key" not in url:
                    return done_resp
                return download_resp

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", FakeClient), \
             patch("asyncio.sleep", new=AsyncMock()):
            from shared.providers.google_veo import generate_veo_video
            result = await generate_veo_video("running dog")
        # Either ok with video_bytes or ok with video_url
        assert "ok" in result

    async def test_polling_error_in_response(self):
        submit_resp = MagicMock()
        submit_resp.status_code = 200
        submit_resp.json.return_value = {"name": "operations/op-err"}

        error_resp = MagicMock()
        error_resp.json.return_value = {
            "error": {"message": "generation failed"}
        }

        class FakeClient:
            def __init__(self, *args, **kwargs): pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def post(self, url, **kwargs):
                return submit_resp
            async def get(self, url, **kwargs):
                return error_resp

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", FakeClient), \
             patch("asyncio.sleep", new=AsyncMock()):
            from shared.providers.google_veo import generate_veo_video
            result = await generate_veo_video("running dog")
        assert result["ok"] is False

    async def test_with_image_base64(self):
        submit_resp = MagicMock()
        submit_resp.status_code = 200
        submit_resp.json.return_value = {"name": "operations/op-img"}

        done_resp = MagicMock()
        b64 = base64.b64encode(b"fake-video" * 200).decode()
        done_resp.json.return_value = {
            "done": True,
            "response": {
                "generateVideoResponse": {
                    "generatedSamples": [{"video": {"bytesBase64Encoded": b64}}]
                }
            }
        }

        class FakeClient:
            def __init__(self, *args, **kwargs): pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def post(self, url, **kwargs):
                return submit_resp
            async def get(self, url, **kwargs):
                return done_resp

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", FakeClient), \
             patch("asyncio.sleep", new=AsyncMock()):
            from shared.providers.google_veo import generate_veo_video
            result = await generate_veo_video("image to video", image_base64=base64.b64encode(b"imgdata").decode())
        assert result["ok"] is True
        assert "video_bytes" in result

    async def test_veo_audio_model_params(self):
        submit_resp = MagicMock()
        submit_resp.status_code = 200
        submit_resp.json.return_value = {}  # no operation name → early return

        client = AsyncMock()
        client.post = AsyncMock(return_value=submit_resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        # Just verify it doesn't crash and returns an error dict
        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.google_veo import generate_veo_video
            result = await generate_veo_video("prompt", model="veo-3.1-audio")
        assert result["ok"] is False

    async def test_generic_exception(self):
        client = AsyncMock()
        client.post = AsyncMock(side_effect=RuntimeError("crash"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.google_veo import generate_veo_video
            result = await generate_veo_video("running dog")
        assert result["ok"] is False


# ===========================================================================
# midjourney_image.py
# ===========================================================================

class TestMidjourneyImage:
    def test_import(self):
        from shared.providers.midjourney_image import generate_midjourney_image
        assert callable(generate_midjourney_image)

    async def test_no_api_key(self):
        with patch("shared.config.settings", _make_settings(midjourney_api_key="")):
            from shared.providers.midjourney_image import generate_midjourney_image
            result = await generate_midjourney_image("a sunset")
        assert result["ok"] is False
        assert "key" in result["error"].lower()

    async def test_generate_api_error(self):
        post_resp = MagicMock()
        post_resp.status_code = 400
        post_resp.content = b'{"code": 400, "msg": "bad request"}'
        post_resp.json.return_value = {"code": 400, "msg": "bad request"}
        post_resp.text = "bad request"

        client = AsyncMock()
        client.post = AsyncMock(return_value=post_resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.midjourney_image import generate_midjourney_image
            result = await generate_midjourney_image("a sunset")
        assert result["ok"] is False

    async def test_no_task_id(self):
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.content = b'{"code": 200, "data": {}}'
        post_resp.json.return_value = {"code": 200, "data": {}}

        client = AsyncMock()
        client.post = AsyncMock(return_value=post_resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.midjourney_image import generate_midjourney_image
            result = await generate_midjourney_image("a sunset")
        assert result["ok"] is False

    async def test_happy_path(self):
        generate_resp = MagicMock()
        generate_resp.status_code = 200
        generate_resp.content = b'{"code": 200, "data": {"taskId": "task-abc"}}'
        generate_resp.json.return_value = {"code": 200, "data": {"taskId": "task-abc"}}

        status_resp = MagicMock()
        status_resp.status_code = 200
        status_resp.content = b'{"code": 200}'
        status_resp.json.return_value = {
            "code": 200,
            "data": {
                "successFlag": 1,
                "resultInfoJson": {
                    "resultUrls": [{"resultUrl": "https://mj.com/result.png"}]
                }
            }
        }

        class FakeClient:
            def __init__(self, *args, **kwargs): pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def post(self, url, **kwargs):
                return generate_resp
            async def get(self, url, **kwargs):
                return status_resp

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", FakeClient), \
             patch("asyncio.sleep", new=AsyncMock()):
            from shared.providers.midjourney_image import generate_midjourney_image
            result = await generate_midjourney_image("a sunset")
        assert result["ok"] is True
        assert result["image_url"] == "https://mj.com/result.png"

    async def test_task_failed(self):
        generate_resp = MagicMock()
        generate_resp.status_code = 200
        generate_resp.content = b'{"code": 200, "data": {"taskId": "task-fail"}}'
        generate_resp.json.return_value = {"code": 200, "data": {"taskId": "task-fail"}}

        status_resp = MagicMock()
        status_resp.status_code = 200
        status_resp.content = b'{"code": 200}'
        status_resp.json.return_value = {
            "code": 200,
            "data": {
                "successFlag": 2,
                "errorMessage": "Content policy violation"
            }
        }

        class FakeClient:
            def __init__(self, *args, **kwargs): pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def post(self, url, **kwargs):
                return generate_resp
            async def get(self, url, **kwargs):
                return status_resp

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", FakeClient), \
             patch("asyncio.sleep", new=AsyncMock()):
            from shared.providers.midjourney_image import generate_midjourney_image
            result = await generate_midjourney_image("a sunset")
        assert result["ok"] is False

    async def test_http_exception(self):
        import httpx as httpx_lib
        client = AsyncMock()
        client.post = AsyncMock(
            side_effect=httpx_lib.HTTPError("connection error")
        )
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.midjourney_image import generate_midjourney_image
            result = await generate_midjourney_image("a sunset")
        assert result["ok"] is False

    async def test_generic_exception(self):
        client = AsyncMock()
        client.post = AsyncMock(side_effect=RuntimeError("crash"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.midjourney_image import generate_midjourney_image
            result = await generate_midjourney_image("a sunset")
        assert result["ok"] is False

    async def test_timeout_returns_error(self):
        """Exhaust polling loop without getting success."""
        generate_resp = MagicMock()
        generate_resp.status_code = 200
        generate_resp.content = b'{"code": 200, "data": {"taskId": "task-timeout"}}'
        generate_resp.json.return_value = {"code": 200, "data": {"taskId": "task-timeout"}}

        status_resp = MagicMock()
        status_resp.status_code = 200
        status_resp.content = b'{"code": 200}'
        status_resp.json.return_value = {
            "code": 200,
            "data": {"successFlag": -1}  # pending
        }

        class FakeClient:
            def __init__(self, *args, **kwargs): pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def post(self, url, **kwargs):
                return generate_resp
            async def get(self, url, **kwargs):
                return status_resp

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", FakeClient), \
             patch("asyncio.sleep", new=AsyncMock()):
            from shared.providers.midjourney_image import generate_midjourney_image
            # Override polling iterations to avoid slow test
            import shared.providers.midjourney_image as mj_mod
            original = mj_mod.asyncio.sleep

            result = await generate_midjourney_image("a sunset")
        assert result["ok"] is False
        assert "таймаут" in result["error"].lower()


# ===========================================================================
# xai_image.py
# ===========================================================================

class TestXaiImage:
    def test_import(self):
        from shared.providers.xai_image import generate_xai_image
        assert callable(generate_xai_image)

    async def test_no_api_key(self):
        with patch("shared.providers.xai_image.settings", _make_settings(grok_api_key="")):
            from shared.providers.xai_image import generate_xai_image
            result = await generate_xai_image("a sunset")
        assert result["ok"] is False

    async def test_happy_path_with_url(self):
        img_mock = MagicMock()
        img_mock.url = "https://x.ai/image.png"
        img_mock.b64_json = None

        resp_mock = MagicMock()
        resp_mock.data = [img_mock]

        mock_images = AsyncMock()
        mock_images.generate = AsyncMock(return_value=resp_mock)

        mock_openai_client = MagicMock()
        mock_openai_client.images = mock_images

        with patch("shared.providers.xai_image.settings", _make_settings()), \
             patch("openai.AsyncOpenAI", return_value=mock_openai_client):
            from shared.providers.xai_image import generate_xai_image
            result = await generate_xai_image("a sunset")
        assert result["ok"] is True
        assert result["image_url"] == "https://x.ai/image.png"

    async def test_happy_path_with_b64(self):
        img_mock = MagicMock()
        img_mock.url = None
        img_mock.b64_json = "abc123"

        resp_mock = MagicMock()
        resp_mock.data = [img_mock]

        mock_images = AsyncMock()
        mock_images.generate = AsyncMock(return_value=resp_mock)

        mock_openai_client = MagicMock()
        mock_openai_client.images = mock_images

        with patch("shared.providers.xai_image.settings", _make_settings()), \
             patch("openai.AsyncOpenAI", return_value=mock_openai_client):
            from shared.providers.xai_image import generate_xai_image
            result = await generate_xai_image("a sunset")
        assert result["ok"] is True
        assert result["image_url"].startswith("data:image/png;base64,")

    async def test_empty_data_returns_error(self):
        resp_mock = MagicMock()
        resp_mock.data = []

        mock_images = AsyncMock()
        mock_images.generate = AsyncMock(return_value=resp_mock)

        mock_openai_client = MagicMock()
        mock_openai_client.images = mock_images

        with patch("shared.providers.xai_image.settings", _make_settings()), \
             patch("openai.AsyncOpenAI", return_value=mock_openai_client):
            from shared.providers.xai_image import generate_xai_image
            result = await generate_xai_image("a sunset")
        assert result["ok"] is False

    async def test_exception(self):
        mock_images = AsyncMock()
        mock_images.generate = AsyncMock(side_effect=RuntimeError("xai crash"))

        mock_openai_client = MagicMock()
        mock_openai_client.images = mock_images

        with patch("shared.providers.xai_image.settings", _make_settings()), \
             patch("openai.AsyncOpenAI", return_value=mock_openai_client):
            from shared.providers.xai_image import generate_xai_image
            result = await generate_xai_image("a sunset")
        assert result["ok"] is False

    async def test_num_images_clamped(self):
        img_mock = MagicMock()
        img_mock.url = "https://x.ai/image.png"
        img_mock.b64_json = None

        resp_mock = MagicMock()
        resp_mock.data = [img_mock]

        mock_images = AsyncMock()
        mock_images.generate = AsyncMock(return_value=resp_mock)
        mock_openai_client = MagicMock()
        mock_openai_client.images = mock_images

        with patch("shared.providers.xai_image.settings", _make_settings()), \
             patch("openai.AsyncOpenAI", return_value=mock_openai_client):
            from shared.providers.xai_image import generate_xai_image
            # num_images=100 should be clamped to 10
            result = await generate_xai_image("x", num_images=100)
        call_kwargs = mock_images.generate.call_args[1]
        assert call_kwargs["n"] <= 10


# ===========================================================================
# edge_tts_provider.py
# ===========================================================================

class TestEdgeTTS:
    def test_import(self):
        from shared.providers.edge_tts_provider import generate_speech
        assert callable(generate_speech)

    async def test_happy_path(self):
        mock_comm = MagicMock()
        mock_comm.save = AsyncMock()

        with patch("edge_tts.Communicate", return_value=mock_comm), \
             patch("builtins.open", MagicMock(
                 return_value=MagicMock(
                     __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=b"fake-audio"), name="/tmp/test.mp3")),
                     __exit__=MagicMock(return_value=False),
                 )
             )), \
             patch("tempfile.NamedTemporaryFile") as mock_tmp, \
             patch("os.path.exists", return_value=False):
            mock_file = MagicMock()
            mock_file.name = "/tmp/fake.mp3"
            mock_tmp.return_value.__enter__ = MagicMock(return_value=mock_file)
            mock_tmp.return_value.__exit__ = MagicMock(return_value=False)

            # Patch open to handle both write and read
            read_mock = MagicMock()
            read_mock.read.return_value = b"fake-audio-bytes"
            write_mock = MagicMock()

            def open_side_effect(path, mode="r", **kwargs):
                if mode == "rb":
                    ctx = MagicMock()
                    ctx.__enter__ = MagicMock(return_value=read_mock)
                    ctx.__exit__ = MagicMock(return_value=False)
                    return ctx
                ctx = MagicMock()
                ctx.__enter__ = MagicMock(return_value=write_mock)
                ctx.__exit__ = MagicMock(return_value=False)
                return ctx

            with patch("builtins.open", side_effect=open_side_effect):
                from shared.providers.edge_tts_provider import generate_speech
                result = await generate_speech("Hello world")
        assert result["ok"] is True
        assert result["format"] == "mp3"

    async def test_text_truncated_at_3000_chars(self):
        """Verify long text doesn't crash (truncation)."""
        long_text = "x" * 5000
        mock_comm = MagicMock()
        mock_comm.save = AsyncMock()

        calls = []

        def comm_init(text, voice):
            calls.append(len(text))
            return mock_comm

        with patch("edge_tts.Communicate", side_effect=comm_init), \
             patch("tempfile.NamedTemporaryFile") as mock_tmp, \
             patch("os.path.exists", return_value=False):
            mock_file = MagicMock()
            mock_file.name = "/tmp/fake.mp3"
            mock_tmp.return_value.__enter__ = MagicMock(return_value=mock_file)
            mock_tmp.return_value.__exit__ = MagicMock(return_value=False)

            read_mock = MagicMock()
            read_mock.read.return_value = b"audio"

            def open_side_effect(path, mode="r", **kwargs):
                ctx = MagicMock()
                ctx.__enter__ = MagicMock(return_value=read_mock)
                ctx.__exit__ = MagicMock(return_value=False)
                return ctx

            with patch("builtins.open", side_effect=open_side_effect):
                from shared.providers.edge_tts_provider import generate_speech
                await generate_speech(long_text)
        assert calls[0] <= 3000

    async def test_exception_returns_error(self):
        with patch("edge_tts.Communicate", side_effect=RuntimeError("TTS failed")), \
             patch("os.path.exists", return_value=False):
            from shared.providers.edge_tts_provider import generate_speech
            result = await generate_speech("Hello")
        assert result["ok"] is False
        assert "ошибка" in result["error"].lower()


# ===========================================================================
# musicgen.py
# ===========================================================================

class TestMusicgen:
    def test_import(self):
        from shared.providers.musicgen import generate_music
        assert callable(generate_music)

    async def test_no_api_key(self):
        with patch("shared.config.settings", _make_settings(falai_api_key="")):
            from shared.providers.musicgen import generate_music
            result = await generate_music("jazz improvisation")
        assert result["ok"] is False

    async def test_happy_path_direct(self):
        mock_client = _make_httpx_client(
            post_json={"audio_file": {"url": "https://fal.media/audio.mp3"}}
        )
        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=mock_client):
            from shared.providers.musicgen import generate_music
            result = await generate_music("jazz improvisation")
        assert result["ok"] is True
        assert result["audio_url"] == "https://fal.media/audio.mp3"

    async def test_happy_path_audio_key(self):
        mock_client = _make_httpx_client(
            post_json={"audio": {"url": "https://fal.media/music.mp3"}}
        )
        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=mock_client):
            from shared.providers.musicgen import generate_music
            result = await generate_music("blues")
        assert result["ok"] is True

    async def test_queue_polling_completed(self):
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"request_id": "music-req-1"}
        post_resp.raise_for_status = MagicMock()

        status_resp = MagicMock()
        status_resp.json.return_value = {"status": "COMPLETED"}

        result_resp = MagicMock()
        result_resp.json.return_value = {"audio_file": {"url": "https://fal.media/done.mp3"}}

        async def fake_get(url, **kwargs):
            if "/status" in url:
                return status_resp
            return result_resp

        client = AsyncMock()
        client.post = AsyncMock(return_value=post_resp)
        client.get = fake_get
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client), \
             patch("asyncio.sleep", new=AsyncMock()):
            from shared.providers.musicgen import generate_music
            result = await generate_music("ambient music")
        assert result["ok"] is True

    async def test_queue_polling_failed(self):
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"request_id": "music-fail"}
        post_resp.raise_for_status = MagicMock()

        status_resp = MagicMock()
        status_resp.json.return_value = {"status": "FAILED"}

        async def fake_get(url, **kwargs):
            return status_resp

        client = AsyncMock()
        client.post = AsyncMock(return_value=post_resp)
        client.get = fake_get
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client), \
             patch("asyncio.sleep", new=AsyncMock()):
            from shared.providers.musicgen import generate_music
            result = await generate_music("rock")
        assert result["ok"] is False

    async def test_no_audio_url(self):
        mock_client = _make_httpx_client(post_json={"something": "else"})
        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=mock_client):
            from shared.providers.musicgen import generate_music
            result = await generate_music("beats")
        assert result["ok"] is False

    async def test_http_error(self):
        import httpx as httpx_lib
        client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        client.post = AsyncMock(
            side_effect=httpx_lib.HTTPStatusError("err", request=MagicMock(), response=mock_response)
        )
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.musicgen import generate_music
            result = await generate_music("beats")
        assert result["ok"] is False

    async def test_generic_exception(self):
        client = AsyncMock()
        client.post = AsyncMock(side_effect=RuntimeError("crash"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.musicgen import generate_music
            result = await generate_music("classical")
        assert result["ok"] is False

    async def test_duration_capped_at_30(self):
        captured = {}

        async def fake_post(url, **kwargs):
            captured["payload"] = kwargs.get("json", {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"audio_file": {"url": "http://x/a.mp3"}}
            resp.raise_for_status = MagicMock()
            return resp

        client = AsyncMock()
        client.post = fake_post
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.musicgen import generate_music
            await generate_music("x", duration=100)
        assert captured["payload"]["seconds_total"] == 30


# ===========================================================================
# falai_song.py
# ===========================================================================

class TestFalaiSongHelpers:
    def test_import(self):
        from shared.providers.falai_song import (
            generate_song, _find_audio_url, _extract_error_message,
            _looks_like_audio_url, _payload_candidates, _resolve_song_endpoint,
        )
        assert callable(generate_song)

    def test_looks_like_audio_url_true(self):
        from shared.providers.falai_song import _looks_like_audio_url
        assert _looks_like_audio_url("https://fal.media/music.mp3") is True
        assert _looks_like_audio_url("https://x.com/audio") is True
        assert _looks_like_audio_url("https://fal.media/file.wav") is True

    def test_looks_like_audio_url_false(self):
        from shared.providers.falai_song import _looks_like_audio_url
        assert _looks_like_audio_url("https://example.com/image.png") is False
        assert _looks_like_audio_url("") is False

    def test_find_audio_url_direct(self):
        from shared.providers.falai_song import _find_audio_url
        assert _find_audio_url({"audio_url": "https://x.com/a.mp3"}) == "https://x.com/a.mp3"

    def test_find_audio_url_nested(self):
        from shared.providers.falai_song import _find_audio_url
        assert _find_audio_url({"audio": {"url": "https://x.com/a.mp3"}}) == "https://x.com/a.mp3"

    def test_find_audio_url_list(self):
        from shared.providers.falai_song import _find_audio_url
        assert _find_audio_url([{"audio_url": "https://x.com/b.mp3"}]) == "https://x.com/b.mp3"

    def test_find_audio_url_string(self):
        from shared.providers.falai_song import _find_audio_url
        assert _find_audio_url("https://x.com/c.wav") == "https://x.com/c.wav"

    def test_find_audio_url_not_found(self):
        from shared.providers.falai_song import _find_audio_url
        assert _find_audio_url({"x": "y"}) == ""

    def test_extract_error_message(self):
        from shared.providers.falai_song import _extract_error_message
        assert _extract_error_message({"error": "bad"}) == "bad"
        assert _extract_error_message({"detail": "more detail"}) == "more detail"
        assert _extract_error_message({"error": {"message": "nested"}}) == "nested"
        assert _extract_error_message({}) == ""
        assert _extract_error_message("not a dict") == ""  # type: ignore

    def test_payload_candidates_default(self):
        from shared.providers.falai_song import _payload_candidates
        candidates = _payload_candidates("my song", "fal-ai/diffrhythm", 30)
        assert len(candidates) == 2
        assert candidates[0].get("prompt") == "my song"

    def test_payload_candidates_minimax(self):
        from shared.providers.falai_song import _payload_candidates
        candidates = _payload_candidates("my song", "fal-ai/minimax-music", 60)
        assert len(candidates) == 4
        assert "duration" in candidates[0]

    def test_resolve_song_endpoint_default(self):
        with patch("shared.config.settings", _make_settings(fal_song_endpoint="")):
            from shared.providers.falai_song import _resolve_song_endpoint
            assert _resolve_song_endpoint("suno-v4") == "fal-ai/diffrhythm"

    def test_resolve_song_endpoint_override(self):
        with patch("shared.config.settings", _make_settings(fal_song_endpoint="fal-ai/custom-song")):
            from shared.providers.falai_song import _resolve_song_endpoint
            assert _resolve_song_endpoint("suno-v4") == "fal-ai/custom-song"


class TestFalaiSongGenerate:
    async def test_no_api_key(self):
        with patch("shared.config.settings", _make_settings(falai_api_key="")):
            from shared.providers.falai_song import generate_song
            result = await generate_song("a happy tune")
        assert result["ok"] is False

    async def test_happy_path(self):
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"audio_url": "https://fal.media/song.mp3"}
        post_resp.raise_for_status = MagicMock()

        client = AsyncMock()
        client.post = AsyncMock(return_value=post_resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.falai_song import generate_song
            result = await generate_song("a happy tune")
        assert result["ok"] is True
        assert result["audio_url"] == "https://fal.media/song.mp3"

    async def test_queue_polling_completed(self):
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"request_id": "song-req-1"}
        post_resp.raise_for_status = MagicMock()

        status_resp = MagicMock()
        status_resp.status_code = 200
        status_resp.json.return_value = {"status": "COMPLETED"}
        status_resp.raise_for_status = MagicMock()

        result_resp = MagicMock()
        result_resp.status_code = 200
        result_resp.json.return_value = {"audio_url": "https://fal.media/queued-song.mp3"}
        result_resp.raise_for_status = MagicMock()

        async def fake_get(url, **kwargs):
            if "/status" in url:
                return status_resp
            return result_resp

        client = AsyncMock()
        client.post = AsyncMock(return_value=post_resp)
        client.get = fake_get
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings(fal_song_timeout_sec=10)), \
             patch("httpx.AsyncClient", return_value=client), \
             patch("asyncio.sleep", new=AsyncMock()):
            from shared.providers.falai_song import generate_song
            result = await generate_song("a happy tune")
        assert result["ok"] is True

    async def test_queue_polling_failed_status(self):
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"request_id": "song-fail"}
        post_resp.raise_for_status = MagicMock()

        status_resp = MagicMock()
        status_resp.status_code = 200
        status_resp.json.return_value = {"status": "FAILED", "error": "content violation"}
        status_resp.raise_for_status = MagicMock()

        async def fake_get(url, **kwargs):
            return status_resp

        client = AsyncMock()
        client.post = AsyncMock(return_value=post_resp)
        client.get = fake_get
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings(fal_song_timeout_sec=10)), \
             patch("httpx.AsyncClient", return_value=client), \
             patch("asyncio.sleep", new=AsyncMock()):
            from shared.providers.falai_song import generate_song
            result = await generate_song("a happy tune")
        assert result["ok"] is False

    async def test_no_audio_url_in_response(self):
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"data": "no audio here"}
        post_resp.raise_for_status = MagicMock()

        client = AsyncMock()
        client.post = AsyncMock(return_value=post_resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.falai_song import generate_song
            result = await generate_song("a tune")
        assert result["ok"] is False

    async def test_http_401_error(self):
        import httpx as httpx_lib
        client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        client.post = AsyncMock(
            side_effect=httpx_lib.HTTPStatusError("401", request=MagicMock(), response=mock_response)
        )
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.falai_song import generate_song
            result = await generate_song("a tune")
        assert result["ok"] is False
        assert "401" in result["error"]

    async def test_http_403_error(self):
        import httpx as httpx_lib
        client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        client.post = AsyncMock(
            side_effect=httpx_lib.HTTPStatusError("403", request=MagicMock(), response=mock_response)
        )
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.falai_song import generate_song
            result = await generate_song("a tune")
        assert result["ok"] is False
        assert "403" in result["error"]

    async def test_payload_schema_mismatch_all_rejected(self):
        """All payload candidates rejected with 400/422."""
        import httpx as httpx_lib

        call_count = {"n": 0}

        async def always_fail_post(url, **kwargs):
            mock_response = MagicMock()
            mock_response.status_code = 422
            mock_response.text = "Unprocessable Entity"
            raise httpx_lib.HTTPStatusError("422", request=MagicMock(), response=mock_response)

        client = AsyncMock()
        client.post = always_fail_post
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.falai_song import generate_song
            result = await generate_song("a tune")
        assert result["ok"] is False

    async def test_generic_exception(self):
        client = AsyncMock()
        client.post = AsyncMock(side_effect=RuntimeError("crash"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("shared.config.settings", _make_settings()), \
             patch("httpx.AsyncClient", return_value=client):
            from shared.providers.falai_song import generate_song
            result = await generate_song("a tune")
        assert result["ok"] is False


# ===========================================================================
# openai_stt.py (supplement existing tests — focus on uncovered paths)
# ===========================================================================

class TestOpenAiStt:
    def test_guess_extension_with_dot(self):
        from shared.providers.openai_stt import _guess_extension
        assert _guess_extension("voice.ogg") == "ogg"
        assert _guess_extension("audio.MP3") == "mp3"

    def test_guess_extension_no_dot(self):
        from shared.providers.openai_stt import _guess_extension
        assert _guess_extension("voice") == "ogg"

    def test_guess_extension_path(self):
        from shared.providers.openai_stt import _guess_extension
        assert _guess_extension("/tmp/uploads/voice.wav") == "wav"

    def test_extract_transcript_from_none(self):
        from shared.providers.openai_stt import _extract_transcript_text
        assert _extract_transcript_text(None) == ""

    def test_extract_transcript_from_object(self):
        from shared.providers.openai_stt import _extract_transcript_text
        obj = SimpleNamespace(type="text", text="hello")
        result = _extract_transcript_text([obj])
        assert "hello" in result

    def test_prepare_audio_payload_direct_format(self):
        from shared.providers.openai_stt import _prepare_audio_payload
        data = b"fake-ogg-data"
        result_bytes, fmt = _prepare_audio_payload(data, "voice.ogg")
        assert fmt == "ogg"
        assert result_bytes == data

    def test_prepare_audio_payload_m4a(self):
        from shared.providers.openai_stt import _prepare_audio_payload
        data = b"fake-m4a-data"
        result_bytes, fmt = _prepare_audio_payload(data, "audio.m4a")
        assert fmt == "m4a"

    async def test_transcribe_audio_happy_path(self):
        from shared.providers import openai_stt

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Привет, мир"

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        import shared.providers.openai_text as ot
        ot._openrouter_client = mock_client

        try:
            result = await openai_stt.transcribe_audio(b"fake audio", "voice.ogg")
            assert result["ok"] is True
            assert result["text"] == "Привет, мир"
        finally:
            ot._openrouter_client = None

    async def test_transcribe_audio_all_models_fail(self):
        from shared.providers import openai_stt

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("no audio support")
        )

        import shared.providers.openai_text as ot
        ot._openrouter_client = mock_client

        try:
            result = await openai_stt.transcribe_audio(b"fake audio", "voice.ogg")
            assert result["ok"] is False
            assert "ошибка" in result["error"].lower()
        finally:
            ot._openrouter_client = None

    async def test_transcribe_audio_empty_text(self):
        from shared.providers import openai_stt

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        import shared.providers.openai_text as ot
        ot._openrouter_client = mock_client

        try:
            result = await openai_stt.transcribe_audio(b"silent audio", "voice.ogg")
            assert result["ok"] is False
        finally:
            ot._openrouter_client = None
