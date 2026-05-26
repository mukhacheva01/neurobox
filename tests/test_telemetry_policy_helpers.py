import asyncio


def test_telemetry_helpers_call_ai_request_and_events(monkeypatch):
    import shared.domain.analytics as analytics
    import shared.domain.credits as credits
    from shared.domain import telemetry

    calls = []

    async def fake_log_ai_request(user_id, task_type, model, prompt="", status="completed", credits_charged=0, duration_ms=0, error_message=""):
        calls.append(("ai", user_id, task_type, model, status, credits_charged, duration_ms, error_message, prompt))

    async def fake_track(event_name, user_id, **props):
        calls.append(("event", event_name, user_id, props))

    monkeypatch.setattr(credits, "log_ai_request", fake_log_ai_request)
    monkeypatch.setattr(analytics, "track", fake_track)

    asyncio.run(telemetry.log_ai_success(1, "image", "flux-2-turbo", "cat", 5, 123, success_event="image_generated"))
    asyncio.run(telemetry.log_ai_error(1, "image", "flux-2-turbo", "cat", 5, 456, "boom", error_event="image_error"))

    assert any(c[0] == "ai" and c[4] == "completed" for c in calls)
    assert any(c[0] == "ai" and c[4] == "error" and c[7] == "boom" for c in calls)
    assert any(c[0] == "event" and c[1] == "image_generated" for c in calls)
    assert any(c[0] == "event" and c[1] == "image_error" for c in calls)


def test_rollback_spend_usage_policy_is_idempotent(monkeypatch):
    import shared.domain.credits as credits
    import shared.redis.store as redis_store

    class FakeRedis:
        def __init__(self):
            self.values = {"policy:daily:test": 2}
            self.deleted = []
            self.decr_calls = 0

        async def delete(self, key):
            self.deleted.append(key)
            self.values.pop(key, None)
            return 1

        async def decr(self, key):
            self.decr_calls += 1
            self.values[key] = int(self.values.get(key, 0)) - 1
            return self.values[key]

    fake = FakeRedis()

    async def fake_get_redis():
        return fake

    monkeypatch.setattr(redis_store, "_get_redis", fake_get_redis)

    spend = {
        "policy_usage": {
            "cooldown_key": "policy:cooldown:test:1",
            "daily_limit_key": "policy:daily:test",
            "daily_incremented": True,
        }
    }

    asyncio.run(credits.rollback_spend_usage_policy(spend))
    assert "policy:cooldown:test:1" in fake.deleted
    assert fake.decr_calls == 1
    assert spend["policy_usage"].get("_rolled_back") is True

    asyncio.run(credits.rollback_spend_usage_policy(spend))
    assert fake.decr_calls == 1, "повторный rollback не должен повторно уменьшать счётчик"
