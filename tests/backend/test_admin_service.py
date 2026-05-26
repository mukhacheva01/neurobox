"""Comprehensive tests for services/backend/services/admin.py.

Coverage strategy:
- Each public function: one happy-path test + one error/edge-case test.
- Pure helpers tested directly.
- DB session is patched at ``shared.db.session.get_session`` so that no
  real SQLAlchemy / database is needed.
- Redis is patched at ``services.backend.services.admin._redis`` to return None
  (no-op cache) or a mock Redis client.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Low-level mock factories
# ---------------------------------------------------------------------------

def _make_mock_result(scalar=0, first=None, all_rows=None):
    """SQLAlchemy Result mock supporting .scalar(), .mappings().first(), .mappings().all()"""
    result = MagicMock()
    result.scalar = MagicMock(return_value=scalar)
    mappings = MagicMock()
    mappings.first = MagicMock(return_value=first)
    mappings.all = MagicMock(return_value=list(all_rows or []))
    result.mappings = MagicMock(return_value=mappings)
    return result


def _make_mock_session(scalar=0, fetchrow=None, fetch=None):
    """SQLAlchemy AsyncSession mock. session.execute() returns a Result mock."""
    session = AsyncMock()
    result = _make_mock_result(scalar=scalar, first=fetchrow, all_rows=fetch or [])
    session.execute = AsyncMock(return_value=result)
    return session


def _patch_session(mock_session):
    """Patch get_session in the admin module as an asynccontextmanager yielding mock_session."""
    @asynccontextmanager
    async def _fake_get_session():
        yield mock_session
    return patch("services.backend.services.admin.get_session", _fake_get_session)


def _patch_redis_none():
    """Patch Redis so all cache calls are no-ops."""
    return patch(
        "services.backend.services.admin._redis",
        AsyncMock(return_value=None),
    )


def _patch_settings(**kwargs):
    attrs = {
        "bot_identifier": "neurobox",
        "infra_monthly_cost_usd": 25.0,
        "usd_to_rub": 95.0,
        "bot_token": "123:test",
        **kwargs,
    }
    m = MagicMock()
    for k, v in attrs.items():
        setattr(m, k, v)
    return patch("shared.config.settings", m)


# ---------------------------------------------------------------------------
# Pure helper function tests
# ---------------------------------------------------------------------------

class TestPeriodInterval:
    def test_day(self):
        from services.backend.services.admin import _period_interval
        lo, hi = _period_interval("day")
        assert lo == timedelta(days=1)
        assert hi == timedelta(days=1)

    def test_week(self):
        from services.backend.services.admin import _period_interval
        lo, _ = _period_interval("week")
        assert lo == timedelta(days=7)

    def test_month(self):
        from services.backend.services.admin import _period_interval
        lo, _ = _period_interval("month")
        assert lo == timedelta(days=30)

    def test_year_explicit(self):
        from services.backend.services.admin import _period_interval
        lo, _ = _period_interval("year")
        assert lo == timedelta(days=365)

    def test_unknown_defaults_to_year(self):
        from services.backend.services.admin import _period_interval
        lo, _ = _period_interval("bogus")
        assert lo == timedelta(days=365)


class TestPeriodDays:
    def test_day(self):
        from services.backend.services.admin import _period_days
        assert _period_days("day") == 1

    def test_week(self):
        from services.backend.services.admin import _period_days
        assert _period_days("week") == 7

    def test_month(self):
        from services.backend.services.admin import _period_days
        assert _period_days("month") == 30

    def test_year_default(self):
        from services.backend.services.admin import _period_days
        assert _period_days("year") == 365

    def test_unknown_defaults_to_year(self):
        from services.backend.services.admin import _period_days
        assert _period_days("anything_else") == 365


class TestSegmentCaseSql:
    def test_returns_string_with_all_segments(self):
        from services.backend.services.admin import _segment_case_sql
        sql = _segment_case_sql()
        assert isinstance(sql, str)
        for seg in ("blocked", "trial", "paid", "reactivated", "churned", "free"):
            assert seg in sql


class TestInfraCostRub:
    def test_full_month(self):
        with _patch_settings(infra_monthly_cost_usd=25.0, usd_to_rub=100.0):
            from services.backend.services.admin import _infra_cost_rub
            result = _infra_cost_rub(30)
            # 25 * 100 * (30/30) = 2500
            assert result == pytest.approx(2500.0, rel=1e-3)

    def test_partial_month(self):
        with _patch_settings(infra_monthly_cost_usd=30.0, usd_to_rub=90.0):
            from services.backend.services.admin import _infra_cost_rub
            result = _infra_cost_rub(15)
            # 30 * 90 * (15/30) = 1350
            assert result == pytest.approx(1350.0, rel=1e-3)

    def test_one_day(self):
        with _patch_settings(infra_monthly_cost_usd=30.0, usd_to_rub=100.0):
            from services.backend.services.admin import _infra_cost_rub
            result = _infra_cost_rub(1)
            # 30 * 100 * (1/30) = 100
            assert result == pytest.approx(100.0, rel=1e-3)


class TestPaymentStatusMap:
    def test_success_maps_to_confirmed(self):
        from services.backend.services.admin import _payment_status_map
        assert _payment_status_map("success") == "confirmed"

    def test_refund_maps_to_refunded(self):
        from services.backend.services.admin import _payment_status_map
        assert _payment_status_map("refund") == "refunded"

    def test_passthrough_for_other_values(self):
        from services.backend.services.admin import _payment_status_map
        assert _payment_status_map("confirmed") == "confirmed"
        assert _payment_status_map("pending") == "pending"
        assert _payment_status_map("unknown") == "unknown"


class TestBotId:
    def test_returns_identifier_from_settings(self):
        with patch("shared.config.settings") as m:
            m.bot_identifier = "mybot"
            from services.backend.services.admin import _bot_id
            assert _bot_id() == "mybot"

    def test_fallback_to_neurobox_when_none(self):
        with patch("shared.config.settings") as m:
            m.bot_identifier = None
            from services.backend.services.admin import _bot_id
            assert _bot_id() == "neurobox"

    def test_fallback_to_neurobox_when_empty_string(self):
        with patch("shared.config.settings") as m:
            m.bot_identifier = ""
            from services.backend.services.admin import _bot_id
            assert _bot_id() == "neurobox"


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

class TestCacheGet:
    async def test_returns_none_when_redis_unavailable(self):
        with _patch_redis_none():
            from services.backend.services.admin import _cache_get
            result = await _cache_get("some:key")
            assert result is None

    async def test_returns_deserialized_json_value(self):
        import json
        mock_r = AsyncMock()
        mock_r.get = AsyncMock(return_value=json.dumps({"hello": "world"}).encode())
        with patch("services.backend.services.admin._redis", AsyncMock(return_value=mock_r)):
            from services.backend.services.admin import _cache_get
            result = await _cache_get("k")
            assert result == {"hello": "world"}

    async def test_returns_none_when_key_missing(self):
        mock_r = AsyncMock()
        mock_r.get = AsyncMock(return_value=None)
        with patch("services.backend.services.admin._redis", AsyncMock(return_value=mock_r)):
            from services.backend.services.admin import _cache_get
            result = await _cache_get("k")
            assert result is None

    async def test_returns_none_on_redis_exception(self):
        mock_r = AsyncMock()
        mock_r.get = AsyncMock(side_effect=Exception("redis down"))
        with patch("services.backend.services.admin._redis", AsyncMock(return_value=mock_r)):
            from services.backend.services.admin import _cache_get
            result = await _cache_get("k")
            assert result is None

    async def test_returns_list_value(self):
        import json
        mock_r = AsyncMock()
        mock_r.get = AsyncMock(return_value=json.dumps([1, 2, 3]).encode())
        with patch("services.backend.services.admin._redis", AsyncMock(return_value=mock_r)):
            from services.backend.services.admin import _cache_get
            result = await _cache_get("k")
            assert result == [1, 2, 3]


class TestCacheSet:
    async def test_no_op_when_redis_unavailable(self):
        with _patch_redis_none():
            from services.backend.services.admin import _cache_set
            await _cache_set("k", {"x": 1})  # should not raise

    async def test_sets_value_with_ttl(self):
        mock_r = AsyncMock()
        mock_r.set = AsyncMock()
        with patch("services.backend.services.admin._redis", AsyncMock(return_value=mock_r)):
            from services.backend.services.admin import _cache_set
            await _cache_set("k", {"x": 1}, ttl_sec=60)
            mock_r.set.assert_called_once()
            call_kwargs = mock_r.set.call_args
            # Verify ex=60 was passed
            assert call_kwargs[1].get("ex") == 60 or 60 in call_kwargs[0]

    async def test_swallows_exception_on_write_error(self):
        mock_r = AsyncMock()
        mock_r.set = AsyncMock(side_effect=Exception("write error"))
        with patch("services.backend.services.admin._redis", AsyncMock(return_value=mock_r)):
            from services.backend.services.admin import _cache_set
            await _cache_set("k", {"x": 1})  # should not raise

    async def test_default_ttl_is_300(self):
        mock_r = AsyncMock()
        mock_r.set = AsyncMock()
        with patch("services.backend.services.admin._redis", AsyncMock(return_value=mock_r)):
            from services.backend.services.admin import _cache_set
            await _cache_set("k", "value")
            mock_r.set.assert_called_once()
            call_kwargs = mock_r.set.call_args
            assert call_kwargs[1].get("ex") == 300


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------

class TestGetStats:
    def _make_stat_session(
        self,
        total_users=100,
        new_users=5,
        new_prev=3,
        revenue=1000.0,
        rev_prev=800.0,
        paying=2,
        confirmed=3,
        total_gen=50,
        dau=10,
        wau=30,
        mau=80,
        ai_cost=2.5,
        referrals=1,
        likes=20,
        dislikes=5,
    ):
        # Call order in get_stats (16 total execute calls):
        # 1-12: scalar calls (total_users, new_users, new_prev, revenue, rev_prev,
        #        paying, confirmed, total_gen, dau, wau, mau, ai_cost)
        # 13: mappings().all() for segment_rows
        # 14-16: scalar calls (referrals, likes, dislikes)
        segment_rows = [
            {"status": "free", "cnt": 60},
            {"status": "paid", "cnt": 20},
            {"status": "trial", "cnt": 10},
            {"status": "churned", "cnt": 10},
        ]
        side_effects = [
            _make_mock_result(scalar=total_users),
            _make_mock_result(scalar=new_users),
            _make_mock_result(scalar=new_prev),
            _make_mock_result(scalar=revenue),
            _make_mock_result(scalar=rev_prev),
            _make_mock_result(scalar=paying),
            _make_mock_result(scalar=confirmed),
            _make_mock_result(scalar=total_gen),
            _make_mock_result(scalar=dau),
            _make_mock_result(scalar=wau),
            _make_mock_result(scalar=mau),
            _make_mock_result(scalar=ai_cost),
            _make_mock_result(all_rows=segment_rows),  # segment_rows (call 13)
            _make_mock_result(scalar=referrals),
            _make_mock_result(scalar=likes),
            _make_mock_result(scalar=dislikes),
        ]
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=side_effects)
        return session

    async def test_get_stats_day_returns_all_keys(self):
        session = self._make_stat_session()
        with _patch_session(session), _patch_redis_none(), _patch_settings():
            from services.backend.services.admin import get_stats
            result = await get_stats("day")
        assert result["period"] == "day"
        expected_keys = (
            "total_users", "new_users", "new_users_change_pct",
            "revenue", "revenue_change_pct", "paying_users",
            "total_generations", "cr_trial_to_paid", "arpu", "arppu",
            "churn_pct", "referrals", "likes", "dislikes", "rating_pct",
            "dau", "wau", "mau", "stickiness_pct",
            "ai_cost_usd", "ai_cost_rub", "infra_cost_rub", "margin_rub",
            "segment_counts",
        )
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    async def test_get_stats_week(self):
        session = self._make_stat_session()
        with _patch_session(session), _patch_redis_none(), _patch_settings():
            from services.backend.services.admin import get_stats
            result = await get_stats("week")
        assert result["period"] == "week"

    async def test_get_stats_month(self):
        session = self._make_stat_session()
        with _patch_session(session), _patch_redis_none(), _patch_settings():
            from services.backend.services.admin import get_stats
            result = await get_stats("month")
        assert result["period"] == "month"

    async def test_get_stats_year(self):
        session = self._make_stat_session()
        with _patch_session(session), _patch_redis_none(), _patch_settings():
            from services.backend.services.admin import get_stats
            result = await get_stats("year")
        assert result["period"] == "year"

    async def test_get_stats_cache_hit_returns_cached(self):
        cached_data = {"period": "day", "total_users": 999}
        with patch(
            "services.backend.services.admin._cache_get",
            AsyncMock(return_value=cached_data),
        ):
            from services.backend.services.admin import get_stats
            result = await get_stats("day")
        assert result["total_users"] == 999

    async def test_get_stats_zero_prev_values_gives_none_pct(self):
        """When prev-period values are 0, change_pct should be None."""
        session = self._make_stat_session(new_prev=0, rev_prev=0)
        with _patch_session(session), _patch_redis_none(), _patch_settings():
            from services.backend.services.admin import get_stats
            result = await get_stats("day")
        assert result["new_users_change_pct"] is None
        assert result["revenue_change_pct"] is None

    async def test_get_stats_zero_mau_stickiness_none(self):
        session = self._make_stat_session(mau=0)
        with _patch_session(session), _patch_redis_none(), _patch_settings():
            from services.backend.services.admin import get_stats
            result = await get_stats("day")
        assert result["stickiness_pct"] is None

    async def test_get_stats_segment_counts_populated(self):
        session = self._make_stat_session()
        with _patch_session(session), _patch_redis_none(), _patch_settings():
            from services.backend.services.admin import get_stats
            result = await get_stats("day")
        assert "free" in result["segment_counts"]
        assert result["segment_counts"]["free"] == 60
        assert result["segment_counts"]["paid"] == 20

    async def test_get_stats_cache_is_set_after_db_call(self):
        session = self._make_stat_session()
        mock_cache_set = AsyncMock()
        with _patch_session(session), \
             patch("services.backend.services.admin._cache_get", AsyncMock(return_value=None)), \
             patch("services.backend.services.admin._cache_set", mock_cache_set), \
             _patch_settings():
            from services.backend.services.admin import get_stats
            await get_stats("day")
        mock_cache_set.assert_called_once()

    async def test_get_stats_arpu_arppu_none_when_no_payments(self):
        session = self._make_stat_session(paying=0, confirmed=0, revenue=0.0)
        with _patch_session(session), _patch_redis_none(), _patch_settings():
            from services.backend.services.admin import get_stats
            result = await get_stats("day")
        assert result["arpu"] is None
        assert result["arppu"] is None

    async def test_get_stats_rating_pct_none_when_no_ratings(self):
        session = self._make_stat_session(likes=0, dislikes=0)
        with _patch_session(session), _patch_redis_none(), _patch_settings():
            from services.backend.services.admin import get_stats
            result = await get_stats("day")
        assert result["rating_pct"] is None

    async def test_get_stats_margin_calculation(self):
        session = self._make_stat_session(revenue=10000.0, ai_cost=10.0)
        with _patch_settings(infra_monthly_cost_usd=25.0, usd_to_rub=100.0):
            with _patch_session(session), _patch_redis_none():
                from services.backend.services.admin import get_stats
                result = await get_stats("day")
        # margin = revenue - ai_cost_rub - infra_cost_rub
        assert isinstance(result["margin_rub"], float)


# ---------------------------------------------------------------------------
# get_chart
# ---------------------------------------------------------------------------

class TestGetChart:
    async def test_chart_day_returns_12_points(self):
        # day chart: 4 mappings().all() calls for rows_u, rows_r, rows_l, rows_d
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(all_rows=[]),
            _make_mock_result(all_rows=[]),
            _make_mock_result(all_rows=[]),
            _make_mock_result(all_rows=[]),
        ])
        with _patch_session(session), _patch_redis_none():
            from services.backend.services.admin import get_chart
            result = await get_chart("day")
        assert result["labels"] == [f"{i*2:02d}:00" for i in range(12)]
        assert len(result["new_users"]) == 12
        assert len(result["revenue"]) == 12
        assert len(result["likes"]) == 12
        assert len(result["dislikes"]) == 12

    async def test_chart_week_returns_7_points(self):
        # week chart: 7 days × 4 scalar() calls = 28 scalar results
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[_make_mock_result(scalar=0)] * 28)
        with _patch_session(session), _patch_redis_none():
            from services.backend.services.admin import get_chart
            result = await get_chart("week")
        assert len(result["new_users"]) == 7
        assert result["labels"] == ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    async def test_chart_month_returns_15_points(self):
        # month chart: 15 points × 4 scalar() calls = 60 scalar results
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[_make_mock_result(scalar=0)] * 60)
        with _patch_session(session), _patch_redis_none():
            from services.backend.services.admin import get_chart
            result = await get_chart("month")
        assert len(result["new_users"]) == 15
        assert len(result["labels"]) == 15

    async def test_chart_year_returns_12_points_with_month_labels(self):
        # year chart: 12 points × 4 scalar() calls = 48 scalar results
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[_make_mock_result(scalar=0)] * 48)
        with _patch_session(session), _patch_redis_none():
            from services.backend.services.admin import get_chart
            result = await get_chart("year")
        assert len(result["new_users"]) == 12
        assert result["labels"] == [
            "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
            "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
        ]

    async def test_chart_cache_hit_returns_cached(self):
        cached = {"labels": [], "new_users": [], "revenue": [], "likes": [], "dislikes": []}
        with patch(
            "services.backend.services.admin._cache_get",
            AsyncMock(return_value=cached),
        ):
            from services.backend.services.admin import get_chart
            result = await get_chart("day")
        assert result is cached

    async def test_chart_day_with_hour_data_rows(self):
        """Rows with hour attribute are correctly mapped into 12-point output."""
        def make_row(hour_val, c_val, s_val=100.0):
            r = MagicMock()
            h = MagicMock()
            h.hour = hour_val
            r.__getitem__ = MagicMock(
                side_effect=lambda k: h if k == "h" else c_val if k == "c" else s_val
            )
            return r

        rows_u = [make_row(0, 3), make_row(2, 7)]
        rows_r = [make_row(4, 0, 500.0)]
        rows_l = [make_row(6, 10)]
        rows_d = [make_row(8, 2)]

        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(all_rows=rows_u),
            _make_mock_result(all_rows=rows_r),
            _make_mock_result(all_rows=rows_l),
            _make_mock_result(all_rows=rows_d),
        ])
        with _patch_session(session), _patch_redis_none():
            from services.backend.services.admin import get_chart
            result = await get_chart("day")
        assert len(result["new_users"]) == 12
        assert result["new_users"][0] == 3   # hour 0 → index 0
        assert result["new_users"][1] == 7   # hour 2 → index 1

    async def test_chart_sets_cache_after_db_call(self):
        # week chart: 7 × 4 = 28 scalar results
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[_make_mock_result(scalar=0)] * 28)
        mock_cache_set = AsyncMock()
        with _patch_session(session), \
             patch("services.backend.services.admin._cache_get", AsyncMock(return_value=None)), \
             patch("services.backend.services.admin._cache_set", mock_cache_set):
            from services.backend.services.admin import get_chart
            await get_chart("week")
        mock_cache_set.assert_called_once()

    async def test_chart_week_revenue_values_are_floats(self):
        # 7 days × 4 scalar calls (nu, rev, li, di)
        scalar_values = [5, 1000, 3, 1] * 7
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[_make_mock_result(scalar=v) for v in scalar_values])
        with _patch_session(session), _patch_redis_none():
            from services.backend.services.admin import get_chart
            result = await get_chart("week")
        for val in result["revenue"]:
            assert isinstance(val, float)


# ---------------------------------------------------------------------------
# get_models_stats
# ---------------------------------------------------------------------------

class TestGetModelsStats:
    async def test_returns_list_of_dicts_ordered(self):
        rows = [
            {"name": "gpt-4o", "count": 120},
            {"name": "gpt-3.5-turbo", "count": 80},
        ]
        session = _make_mock_session(fetch=rows)
        with _patch_session(session), _patch_redis_none():
            from services.backend.services.admin import get_models_stats
            result = await get_models_stats()
        assert len(result) == 2
        assert result[0] == {"name": "gpt-4o", "count": 120}
        assert result[1] == {"name": "gpt-3.5-turbo", "count": 80}

    async def test_cache_hit_bypasses_db(self):
        cached = [{"name": "gpt-4o", "count": 50}]
        with patch(
            "services.backend.services.admin._cache_get",
            AsyncMock(return_value=cached),
        ):
            from services.backend.services.admin import get_models_stats
            result = await get_models_stats()
        assert result is cached

    async def test_empty_result(self):
        session = _make_mock_session(fetch=[])
        with _patch_session(session), _patch_redis_none():
            from services.backend.services.admin import get_models_stats
            result = await get_models_stats()
        assert result == []

    async def test_cache_set_called_after_db(self):
        session = _make_mock_session(fetch=[])
        mock_cache_set = AsyncMock()
        with _patch_session(session), \
             patch("services.backend.services.admin._cache_get", AsyncMock(return_value=None)), \
             patch("services.backend.services.admin._cache_set", mock_cache_set):
            from services.backend.services.admin import get_models_stats
            await get_models_stats()
        mock_cache_set.assert_called_once()


# ---------------------------------------------------------------------------
# get_retention
# ---------------------------------------------------------------------------

class TestGetRetention:
    def _make_retention_session(self, total=100, d_values=(10, 20, 40, 60, 70)):
        import datetime as dt_mod
        cohort_date = dt_mod.date(2024, 4, 1)
        cohort_rows = [{"cohort_date": cohort_date, "total": total}]
        # First call: mappings().all() for cohorts; then 5 scalar() calls for d1..d30
        side_effects = [_make_mock_result(all_rows=cohort_rows)]
        for v in d_values:
            side_effects.append(_make_mock_result(scalar=v))
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=side_effects)
        return session

    async def test_returns_list_with_correct_keys(self):
        session = self._make_retention_session()
        with _patch_session(session), _patch_redis_none():
            from services.backend.services.admin import get_retention
            result = await get_retention()
        assert isinstance(result, list)
        assert len(result) == 1
        item = result[0]
        for key in ("date", "total", "d1", "d3", "d7", "d14", "d30"):
            assert key in item

    async def test_retention_percentages_are_correct(self):
        session = self._make_retention_session(total=100, d_values=(10, 20, 40, 60, 70))
        with _patch_session(session), _patch_redis_none():
            from services.backend.services.admin import get_retention
            result = await get_retention()
        item = result[0]
        assert item["d1"] == pytest.approx(10.0)
        assert item["d3"] == pytest.approx(20.0)
        assert item["d7"] == pytest.approx(40.0)
        assert item["d14"] == pytest.approx(60.0)
        assert item["d30"] == pytest.approx(70.0)

    async def test_retention_with_zero_total_returns_zeros(self):
        session = self._make_retention_session(total=0, d_values=(0, 0, 0, 0, 0))
        with _patch_session(session), _patch_redis_none():
            from services.backend.services.admin import get_retention
            result = await get_retention()
        assert result[0]["d1"] == 0
        assert result[0]["d30"] == 0

    async def test_cache_hit(self):
        cached = [{"date": "2024-04-01", "total": 50, "d1": 10.0, "d3": 20.0, "d7": 30.0, "d14": 40.0, "d30": 50.0}]
        with patch(
            "services.backend.services.admin._cache_get",
            AsyncMock(return_value=cached),
        ):
            from services.backend.services.admin import get_retention
            result = await get_retention()
        assert result is cached

    async def test_multiple_cohorts(self):
        import datetime as dt_mod
        dates = [dt_mod.date(2024, 4, 1 + i * 7) for i in range(3)]
        cohort_rows = [{"cohort_date": d, "total": 50} for d in dates]
        # 1 all() call for cohorts + 3 cohorts × 5 scalar calls = 16 total
        side_effects = [_make_mock_result(all_rows=cohort_rows)]
        for v in [5, 10, 20, 30, 40] * 3:
            side_effects.append(_make_mock_result(scalar=v))
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=side_effects)
        with _patch_session(session), _patch_redis_none():
            from services.backend.services.admin import get_retention
            result = await get_retention()
        assert len(result) == 3


# ---------------------------------------------------------------------------
# get_promos
# ---------------------------------------------------------------------------

class TestGetPromos:
    async def test_returns_list_with_promo_fields(self):
        rows = [
            {"code": "PROMO10", "uses": 5, "revenue": 500.0},
            {"code": "SAVE20", "uses": 3, "revenue": 300.0},
        ]
        session = _make_mock_session(fetch=rows)
        with _patch_session(session):
            from services.backend.services.admin import get_promos
            result = await get_promos()
        assert len(result) == 2
        assert result[0]["code"] == "PROMO10"
        assert result[0]["uses"] == 5
        assert result[0]["revenue"] == pytest.approx(500.0)
        assert result[0]["cr"] is None

    async def test_empty_promos(self):
        session = _make_mock_session(fetch=[])
        with _patch_session(session):
            from services.backend.services.admin import get_promos
            result = await get_promos()
        assert result == []

    async def test_none_revenue_coerced_to_zero(self):
        rows = [{"code": "TEST", "uses": 1, "revenue": None}]
        session = _make_mock_session(fetch=rows)
        with _patch_session(session):
            from services.backend.services.admin import get_promos
            result = await get_promos()
        assert result[0]["revenue"] == 0.0

    async def test_cr_always_none(self):
        rows = [{"code": "A", "uses": 100, "revenue": 9999.0}]
        session = _make_mock_session(fetch=rows)
        with _patch_session(session):
            from services.backend.services.admin import get_promos
            result = await get_promos()
        assert result[0]["cr"] is None


# ---------------------------------------------------------------------------
# get_referrals_top
# ---------------------------------------------------------------------------

class TestGetReferralsTop:
    async def test_returns_list_with_expected_fields(self):
        rows = [
            {
                "user_id": 1001, "first_name": "Alice", "username": "alice_tg",
                "count": 10, "revenue": 1500.0,
            },
        ]
        session = _make_mock_session(fetch=rows)
        with _patch_session(session):
            from services.backend.services.admin import get_referrals_top
            result = await get_referrals_top()
        assert len(result) == 1
        assert result[0]["user_id"] == 1001
        assert result[0]["name"] == "Alice"
        assert result[0]["username"] == "alice_tg"
        assert result[0]["count"] == 10
        assert result[0]["revenue"] == pytest.approx(1500.0)

    async def test_none_revenue_coerced_to_zero(self):
        rows = [{"user_id": 2, "first_name": "Bob", "username": None, "count": 3, "revenue": None}]
        session = _make_mock_session(fetch=rows)
        with _patch_session(session):
            from services.backend.services.admin import get_referrals_top
            result = await get_referrals_top()
        assert result[0]["revenue"] == 0.0
        assert result[0]["username"] is None

    async def test_empty_result(self):
        session = _make_mock_session(fetch=[])
        with _patch_session(session):
            from services.backend.services.admin import get_referrals_top
            result = await get_referrals_top()
        assert result == []


# ---------------------------------------------------------------------------
# get_hourly_msk
# ---------------------------------------------------------------------------

class TestGetHourlyMsk:
    async def test_returns_list_of_24_zeroes_by_default(self):
        session = _make_mock_session(fetch=[])
        with _patch_session(session):
            from services.backend.services.admin import get_hourly_msk
            result = await get_hourly_msk()
        assert result == [0] * 24

    async def test_values_placed_at_correct_hour_index(self):
        rows = [{"h": 3, "c": 15}, {"h": 12, "c": 42}, {"h": 23, "c": 7}]
        session = _make_mock_session(fetch=rows)
        with _patch_session(session):
            from services.backend.services.admin import get_hourly_msk
            result = await get_hourly_msk()
        assert len(result) == 24
        assert result[3] == 15
        assert result[12] == 42
        assert result[23] == 7

    async def test_none_hour_defaults_to_index_zero(self):
        rows = [{"h": None, "c": 5}]
        session = _make_mock_session(fetch=rows)
        with _patch_session(session):
            from services.backend.services.admin import get_hourly_msk
            result = await get_hourly_msk()
        assert result[0] == 5

    async def test_out_of_range_hour_ignored(self):
        rows = [{"h": 25, "c": 99}]
        session = _make_mock_session(fetch=rows)
        with _patch_session(session):
            from services.backend.services.admin import get_hourly_msk
            result = await get_hourly_msk()
        assert all(v == 0 for v in result)


# ---------------------------------------------------------------------------
# get_trends
# ---------------------------------------------------------------------------

class TestGetTrends:
    async def test_returns_14_data_points(self):
        # 14 days × 2 scalar() calls (users + revenue) = 28 total
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[_make_mock_result(scalar=v) for v in range(28)])
        with _patch_session(session):
            from services.backend.services.admin import get_trends
            result = await get_trends()
        assert len(result["labels"]) == 14
        assert len(result["users"]) == 14
        assert len(result["revenue"]) == 14

    async def test_label_format_is_DD_MM(self):
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[_make_mock_result(scalar=0)] * 28)
        with _patch_session(session):
            from services.backend.services.admin import get_trends
            result = await get_trends()
        for label in result["labels"]:
            assert "." in label
            assert len(label) == 5

    async def test_none_values_coerced_to_zero(self):
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[_make_mock_result(scalar=None)] * 28)
        with _patch_session(session):
            from services.backend.services.admin import get_trends
            result = await get_trends()
        assert all(v == 0 for v in result["users"])
        assert all(v == 0.0 for v in result["revenue"])

    async def test_returns_dict_with_expected_keys(self):
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[_make_mock_result(scalar=5)] * 28)
        with _patch_session(session):
            from services.backend.services.admin import get_trends
            result = await get_trends()
        assert "labels" in result
        assert "users" in result
        assert "revenue" in result


# ---------------------------------------------------------------------------
# get_users_list
# ---------------------------------------------------------------------------

class TestGetUsersList:
    def _make_user_row(self, uid=1001, unlimited_ends_at=None, referral_count=0):
        now = datetime.utcnow()
        data = {
            "id": uid,
            "first_name": "TestUser",
            "username": "testuser",
            "credits_bought": 100,
            "credits_free_today": 50,
            "credits_free_reset": now,
            "is_blocked": False,
            "total_payments_rub": 500.0,
            "referral_count": referral_count,
            "created_at": now,
            "last_active_at": now,
            "unlimited_ends_at": unlimited_ends_at,
            "acquisition_channel": "organic",
            "utm_source": None,
            "segment": "free",
        }
        r = MagicMock()
        r.__getitem__ = MagicMock(side_effect=lambda k: data[k])
        r.get = MagicMock(side_effect=lambda k, default=None: data.get(k, default))
        # Make dict-key access work too
        for k, v in data.items():
            r[k] = v
        return r

    async def test_basic_list_returns_expected_structure(self):
        user_row = self._make_user_row()
        # Call 1: scalar() for total=10, Call 2: mappings().all() for rows,
        # Call 3: scalar() for gen count per user=25
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(scalar=10),
            _make_mock_result(all_rows=[user_row]),
            _make_mock_result(scalar=25),
        ])
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import get_users_list
            result = await get_users_list(
                search=None, status_filter=None,
                sort="created_at", dir="desc",
                page=1, limit=20,
            )
        assert "total" in result
        assert "users" in result
        assert "page" in result
        assert "limit" in result
        assert result["total"] == 10
        assert result["page"] == 1
        assert result["limit"] == 20

    async def test_with_search_filter_empty_result(self):
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(scalar=0),
            _make_mock_result(all_rows=[]),
        ])
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import get_users_list
            result = await get_users_list(
                search="Alice", status_filter=None,
                sort="first_name", dir="asc",
                page=1, limit=10,
            )
        assert result["users"] == []

    async def test_with_blocked_status_filter(self):
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(scalar=0),
            _make_mock_result(all_rows=[]),
        ])
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import get_users_list
            result = await get_users_list(
                search=None, status_filter="blocked",
                sort="created_at", dir="desc",
                page=2, limit=10,
            )
        assert result["page"] == 2

    async def test_with_segment_status_filter(self):
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(scalar=5),
            _make_mock_result(all_rows=[]),
        ])
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import get_users_list
            result = await get_users_list(
                search=None, status_filter="paid",
                sort="ltv", dir="desc",
                page=1, limit=20,
            )
        assert result["total"] == 5

    async def test_unlimited_user_is_flagged(self):
        future = datetime.utcnow() + timedelta(days=10)
        user_row = self._make_user_row(unlimited_ends_at=future)
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(scalar=1),
            _make_mock_result(all_rows=[user_row]),
            _make_mock_result(scalar=5),
        ])
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import get_users_list
            result = await get_users_list(
                search=None, status_filter=None,
                sort="created_at", dir="desc",
                page=1, limit=20,
            )
        assert result["users"][0]["is_unlimited"] is True

    async def test_expired_unlimited_user_is_not_flagged(self):
        past = datetime.utcnow() - timedelta(days=1)
        user_row = self._make_user_row(unlimited_ends_at=past)
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(scalar=1),
            _make_mock_result(all_rows=[user_row]),
            _make_mock_result(scalar=0),
        ])
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import get_users_list
            result = await get_users_list(
                search=None, status_filter=None,
                sort="created_at", dir="desc",
                page=1, limit=20,
            )
        assert result["users"][0]["is_unlimited"] is False

    async def test_all_sort_columns_resolve(self):
        sort_keys = ("first_name", "telegram_id", "status", "ltv", "created_at", "last_active_at", "unknown")
        for sort_key in sort_keys:
            session = _make_mock_session()
            session.execute = AsyncMock(side_effect=[
                _make_mock_result(scalar=0),
                _make_mock_result(all_rows=[]),
            ])
            with _patch_session(session), patch("shared.config.settings") as m:
                m.bot_identifier = "neurobox"
                from services.backend.services.admin import get_users_list
                result = await get_users_list(
                    search=None, status_filter=None,
                    sort=sort_key, dir="asc",
                    page=1, limit=5,
                )
            assert "users" in result

    async def test_bot_id_appended_to_bots_field(self):
        user_row = self._make_user_row()
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(scalar=1),
            _make_mock_result(all_rows=[user_row]),
            _make_mock_result(scalar=3),
        ])
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import get_users_list
            result = await get_users_list(
                search=None, status_filter=None,
                sort="created_at", dir="desc",
                page=1, limit=20,
            )
        assert result["users"][0]["bots"] == ["neurobox"]

    async def test_search_and_status_filter_combined(self):
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(scalar=0),
            _make_mock_result(all_rows=[]),
        ])
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import get_users_list
            result = await get_users_list(
                search="Bob", status_filter="free",
                sort="created_at", dir="desc",
                page=1, limit=10,
            )
        assert result["total"] == 0


# ---------------------------------------------------------------------------
# get_user_detail
# ---------------------------------------------------------------------------

class TestGetUserDetail:
    def _base_user(self, **overrides):
        now = datetime.utcnow()
        base = {
            "id": 5000,
            "first_name": "Jane",
            "username": "jane_t",
            "credits_bought": 200,
            "credits_free_today": 10,
            "is_blocked": False,
            "total_payments_rub": 0.0,
            "referral_count": 0,
            "created_at": now,
            "last_active_at": now,
            "unlimited_ends_at": None,
            "full_access_48h_ends_at": None,
            "trial_started_at": None,
            "acquisition_channel": None,
            "utm_source": None,
            "utm_medium": None,
            "utm_campaign": None,
            "utm_content": None,
            "utm_term": None,
            "start_payload": None,
            "first_paid_at": None,
            "last_paid_at": None,
            "referred_by": None,
        }
        base.update(overrides)
        row = MagicMock()
        row.__getitem__ = MagicMock(side_effect=lambda k: base[k])
        row.get = MagicMock(side_effect=lambda k, default=None: base.get(k, default))
        for k, v in base.items():
            row[k] = v
        return row

    def _pay_mock(self, confirmed_count=0):
        pay_row = {"confirmed_count": confirmed_count}
        m = MagicMock()
        m.get = MagicMock(side_effect=lambda k, d=None: pay_row.get(k, d))
        m.__getitem__ = MagicMock(side_effect=lambda k: pay_row[k])
        return m

    def _make_detail_session(self, u, pay, gen=0, notes=None, pays=None, tx=None):
        """Build a session for get_user_detail.

        Calls in order:
        1. mappings().first() -> u (user row)
        2. mappings().first() -> pay (confirmed_count row)
        3. scalar()           -> gen
        4. mappings().all()   -> notes_rows
        5. mappings().all()   -> pays
        6. mappings().all()   -> tx
        """
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(first=u),
            _make_mock_result(first=pay),
            _make_mock_result(scalar=gen),
            _make_mock_result(all_rows=notes or []),
            _make_mock_result(all_rows=pays or []),
            _make_mock_result(all_rows=tx or []),
        ])
        return session

    async def test_returns_none_when_user_not_found(self):
        session = _make_mock_session(fetchrow=None)
        with _patch_session(session):
            from services.backend.services.admin import get_user_detail
            result = await get_user_detail(9999)
        assert result is None

    async def test_free_user_status(self):
        u = self._base_user()
        session = self._make_detail_session(u, self._pay_mock(0), gen=7)
        with _patch_session(session):
            from services.backend.services.admin import get_user_detail
            result = await get_user_detail(5000)
        assert result is not None
        assert result["status"] == "free"
        assert "payments" in result
        assert "transactions" in result

    async def test_blocked_user_status(self):
        u = self._base_user(is_blocked=True)
        session = self._make_detail_session(u, self._pay_mock(0), gen=0)
        with _patch_session(session):
            from services.backend.services.admin import get_user_detail
            result = await get_user_detail(5000)
        assert result["status"] == "blocked"

    async def test_trial_48h_status(self):
        future = datetime.utcnow() + timedelta(hours=24)
        u = self._base_user(full_access_48h_ends_at=future)
        session = self._make_detail_session(u, self._pay_mock(0), gen=0)
        with _patch_session(session):
            from services.backend.services.admin import get_user_detail
            result = await get_user_detail(5000)
        assert result["status"] == "trial"

    async def test_trial_45min_status(self):
        recent = datetime.utcnow() - timedelta(minutes=10)
        u = self._base_user(trial_started_at=recent)
        session = self._make_detail_session(u, self._pay_mock(0), gen=0)
        with _patch_session(session):
            from services.backend.services.admin import get_user_detail
            result = await get_user_detail(5000)
        assert result["status"] == "trial"

    async def test_paid_status_single_payment(self):
        future = datetime.utcnow() + timedelta(days=5)
        u = self._base_user(unlimited_ends_at=future)
        session = self._make_detail_session(u, self._pay_mock(1), gen=3)
        with _patch_session(session):
            from services.backend.services.admin import get_user_detail
            result = await get_user_detail(5000)
        assert result["status"] == "paid"

    async def test_reactivated_status_multiple_payments(self):
        future = datetime.utcnow() + timedelta(days=5)
        u = self._base_user(unlimited_ends_at=future)
        session = self._make_detail_session(u, self._pay_mock(3), gen=10)
        with _patch_session(session):
            from services.backend.services.admin import get_user_detail
            result = await get_user_detail(5000)
        assert result["status"] == "reactivated"

    async def test_churned_status(self):
        u = self._base_user(total_payments_rub=500.0)
        session = self._make_detail_session(u, self._pay_mock(0), gen=0)
        with _patch_session(session):
            from services.backend.services.admin import get_user_detail
            result = await get_user_detail(5000)
        assert result["status"] == "churned"

    async def test_notes_joined_with_separator(self):
        u = self._base_user()
        note1 = {"note": "Note A", "created_at": datetime.utcnow()}
        note2 = {"note": "Note B", "created_at": datetime.utcnow()}
        session = self._make_detail_session(u, self._pay_mock(0), gen=0, notes=[note1, note2])
        with _patch_session(session):
            from services.backend.services.admin import get_user_detail
            result = await get_user_detail(5000)
        assert "Note A" in result["notes"]
        assert "Note B" in result["notes"]
        assert "|" in result["notes"]

    async def test_empty_notes_is_empty_string(self):
        u = self._base_user()
        session = self._make_detail_session(u, self._pay_mock(0), gen=0, notes=[])
        with _patch_session(session):
            from services.backend.services.admin import get_user_detail
            result = await get_user_detail(5000)
        assert result["notes"] == ""

    async def test_payments_and_transactions_in_result(self):
        u = self._base_user()
        payment_row = {
            "payment_id": "pay_001",
            "created_at": datetime.utcnow(),
            "pack_name": "basic",
            "amount_rub": 299.0,
            "status": "confirmed",
            "promo_code": None,
        }
        p = MagicMock()
        p.__getitem__ = MagicMock(side_effect=lambda k: payment_row[k])
        p.get = MagicMock(side_effect=lambda k, d=None: payment_row.get(k, d))

        tx_row = {
            "created_at": datetime.utcnow(),
            "amount": 50,
            "type": "admin_add",
            "description": "Test",
        }
        t = MagicMock()
        t.__getitem__ = MagicMock(side_effect=lambda k: tx_row[k])
        t.get = MagicMock(side_effect=lambda k, d=None: tx_row.get(k, d))

        session = self._make_detail_session(u, self._pay_mock(0), gen=5, notes=[], pays=[p], tx=[t])
        with _patch_session(session):
            from services.backend.services.admin import get_user_detail
            result = await get_user_detail(5000)
        assert len(result["payments"]) == 1
        assert result["payments"][0]["id"] == "pay_001"
        assert result["payments"][0]["amount"] == pytest.approx(299.0)
        assert len(result["transactions"]) == 1
        assert result["transactions"][0]["amount"] == 50

    async def test_negative_transaction_amount_is_absolute(self):
        u = self._base_user()
        tx_row = {
            "created_at": datetime.utcnow(),
            "amount": -30,
            "type": "deduct",
            "description": "Spend",
        }
        t = MagicMock()
        t.__getitem__ = MagicMock(side_effect=lambda k: tx_row[k])
        t.get = MagicMock(side_effect=lambda k, d=None: tx_row.get(k, d))

        session = self._make_detail_session(u, self._pay_mock(0), gen=0, notes=[], pays=[], tx=[t])
        with _patch_session(session):
            from services.backend.services.admin import get_user_detail
            result = await get_user_detail(5000)
        assert result["transactions"][0]["amount"] == 30
        assert result["transactions"][0]["type"] == "-"

    async def test_result_contains_all_utm_fields(self):
        u = self._base_user()
        session = self._make_detail_session(u, self._pay_mock(0), gen=0)
        with _patch_session(session):
            from services.backend.services.admin import get_user_detail
            result = await get_user_detail(5000)
        assert result["utm_source"] is None
        assert result["acquisition_channel"] is None


# ---------------------------------------------------------------------------
# block_user / unblock_user
# ---------------------------------------------------------------------------

class TestBlockUnblock:
    async def test_block_user_returns_true_and_calls_execute(self):
        session = _make_mock_session()
        with _patch_session(session):
            from services.backend.services.admin import block_user
            result = await block_user(1234)
        assert result is True
        session.execute.assert_awaited_once()
        sql_arg = str(session.execute.call_args[0][0])
        assert "is_blocked = TRUE" in sql_arg

    async def test_unblock_user_returns_true_and_calls_execute(self):
        session = _make_mock_session()
        with _patch_session(session):
            from services.backend.services.admin import unblock_user
            result = await unblock_user(1234)
        assert result is True
        session.execute.assert_awaited_once()
        sql_arg = str(session.execute.call_args[0][0])
        assert "is_blocked = FALSE" in sql_arg

    async def test_block_passes_telegram_id(self):
        session = _make_mock_session()
        with _patch_session(session):
            from services.backend.services.admin import block_user
            await block_user(9876)
        # Named params dict is the second positional arg to session.execute
        params = session.execute.call_args[0][1]
        assert params.get("uid") == 9876

    async def test_unblock_passes_telegram_id(self):
        session = _make_mock_session()
        with _patch_session(session):
            from services.backend.services.admin import unblock_user
            await unblock_user(9876)
        params = session.execute.call_args[0][1]
        assert params.get("uid") == 9876


# ---------------------------------------------------------------------------
# add_credits_to_user
# ---------------------------------------------------------------------------

class TestAddCreditsToUser:
    async def test_calls_add_credits_domain_function(self):
        mock_add = AsyncMock()
        with patch("shared.domain.credits.add_credits", mock_add):
            from services.backend.services.admin import add_credits_to_user
            result = await add_credits_to_user(
                telegram_id=1001, amount=100,
                description="Test add", admin_tg_id=9,
            )
        assert result is True
        mock_add.assert_awaited_once_with(1001, 100, "admin_add", "Test add")

    async def test_none_description_uses_default_with_admin_id(self):
        mock_add = AsyncMock()
        with patch("shared.domain.credits.add_credits", mock_add):
            from services.backend.services.admin import add_credits_to_user
            result = await add_credits_to_user(
                telegram_id=1001, amount=50,
                description=None, admin_tg_id=42,
            )
        assert result is True
        call_args = mock_add.call_args[0]
        assert "42" in call_args[3]  # admin_tg_id embedded in description


# ---------------------------------------------------------------------------
# deduct_credits_from_user
# ---------------------------------------------------------------------------

class TestDeductCreditsFromUser:
    async def test_user_not_found_returns_false(self):
        session = _make_mock_session(fetchrow=None)
        with _patch_session(session):
            from services.backend.services.admin import deduct_credits_from_user
            result = await deduct_credits_from_user(9999, 50, "test", 1)
        assert result is False

    async def test_amount_exceeds_total_returns_false(self):
        row = {"credits_bought": 10, "credits_free_today": 5}
        session = _make_mock_session(fetchrow=row)
        with _patch_session(session):
            from services.backend.services.admin import deduct_credits_from_user
            result = await deduct_credits_from_user(1001, 100, None, 1)
        assert result is False

    async def test_deduct_from_free_credits_only(self):
        row = {"credits_bought": 50, "credits_free_today": 30}
        session = _make_mock_session()
        # Call 1: mappings().first() for user row; calls 2,3: execute() for UPDATE + INSERT
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(first=row),
            _make_mock_result(),
            _make_mock_result(),
        ])
        with _patch_session(session):
            from services.backend.services.admin import deduct_credits_from_user
            result = await deduct_credits_from_user(1001, 20, "Test", 9)
        assert result is True
        assert session.execute.await_count == 3  # SELECT + UPDATE free + INSERT transaction

    async def test_deduct_from_both_free_and_bought(self):
        """When amount > free, deducts remainder from bought."""
        row = {"credits_bought": 50, "credits_free_today": 10}
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(first=row),
            _make_mock_result(),
            _make_mock_result(),
        ])
        with _patch_session(session):
            from services.backend.services.admin import deduct_credits_from_user
            result = await deduct_credits_from_user(1001, 30, None, 5)
        assert result is True
        assert session.execute.await_count == 3  # SELECT + UPDATE bought + INSERT transaction

    async def test_none_description_embeds_admin_id(self):
        row = {"credits_bought": 100, "credits_free_today": 0}
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(first=row),
            _make_mock_result(),
            _make_mock_result(),
        ])
        with _patch_session(session):
            from services.backend.services.admin import deduct_credits_from_user
            result = await deduct_credits_from_user(1001, 10, None, 77)
        assert result is True
        last_call = session.execute.call_args_list[-1]
        assert "77" in str(last_call)

    async def test_exact_total_deduction_returns_true(self):
        """Deducting exactly the total available should succeed."""
        row = {"credits_bought": 20, "credits_free_today": 10}
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(first=row),
            _make_mock_result(),
            _make_mock_result(),
        ])
        with _patch_session(session):
            from services.backend.services.admin import deduct_credits_from_user
            result = await deduct_credits_from_user(1001, 30, "exact", 1)
        assert result is True


# ---------------------------------------------------------------------------
# set_user_unlimited
# ---------------------------------------------------------------------------

class TestSetUserUnlimited:
    async def test_true_calls_set_unlimited_until_domain(self):
        mock_set_until = AsyncMock()
        with patch("shared.domain.credits.set_unlimited_until", mock_set_until):
            from services.backend.services.admin import set_user_unlimited
            result = await set_user_unlimited(1001, True, 99)
        assert result is True
        mock_set_until.assert_awaited_once_with(1001, days=30)

    async def test_false_clears_unlimited_in_db(self):
        session = _make_mock_session()
        with _patch_session(session):
            from services.backend.services.admin import set_user_unlimited
            result = await set_user_unlimited(1001, False, 99)
        assert result is True
        session.execute.assert_awaited_once()
        sql_arg = str(session.execute.call_args[0][0])
        assert "unlimited_ends_at = NULL" in sql_arg


# ---------------------------------------------------------------------------
# add_user_note
# ---------------------------------------------------------------------------

class TestAddUserNote:
    async def test_inserts_note_returns_true(self):
        session = _make_mock_session()
        with _patch_session(session):
            from services.backend.services.admin import add_user_note
            result = await add_user_note(1001, "Some note text", 42)
        assert result is True
        session.execute.assert_awaited_once()

    async def test_note_truncated_to_1000_chars(self):
        session = _make_mock_session()
        long_note = "x" * 2000
        with _patch_session(session):
            from services.backend.services.admin import add_user_note
            await add_user_note(1001, long_note, 42)
        # Named params dict is the second positional arg to session.execute
        params = session.execute.call_args[0][1]
        assert len(params["note"]) <= 1000

    async def test_short_note_not_truncated(self):
        session = _make_mock_session()
        short_note = "hello"
        with _patch_session(session):
            from services.backend.services.admin import add_user_note
            await add_user_note(1001, short_note, 42)
        params = session.execute.call_args[0][1]
        assert params["note"] == "hello"

    async def test_admin_id_passed_to_execute(self):
        session = _make_mock_session()
        with _patch_session(session):
            from services.backend.services.admin import add_user_note
            await add_user_note(5555, "note", 999)
        params = session.execute.call_args[0][1]
        assert params["user_id"] == 5555
        assert params["admin_id"] == 999


# ---------------------------------------------------------------------------
# send_message_to_user
# ---------------------------------------------------------------------------

class TestSendMessageToUser:
    async def test_sends_message_and_returns_true(self):
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()
        mock_bot.session = AsyncMock()
        mock_bot.session.close = AsyncMock()

        with patch("shared.config.settings") as m:
            m.bot_token = "123:test"
            with patch("aiogram.Bot", return_value=mock_bot):
                from services.backend.services.admin import send_message_to_user
                result = await send_message_to_user(1001, "Hello!")
        assert result is True
        mock_bot.send_message.assert_awaited_once_with(1001, "Hello!")
        mock_bot.session.close.assert_awaited_once()

    async def test_session_closed_even_when_send_raises(self):
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(side_effect=Exception("telegram down"))
        mock_bot.session = AsyncMock()
        mock_bot.session.close = AsyncMock()

        with patch("shared.config.settings") as m:
            m.bot_token = "123:test"
            with patch("aiogram.Bot", return_value=mock_bot):
                from services.backend.services.admin import send_message_to_user
                with pytest.raises(Exception, match="telegram down"):
                    await send_message_to_user(1001, "Hello!")
        mock_bot.session.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_payments_list
# ---------------------------------------------------------------------------

class TestGetPaymentsList:
    def _make_payment_row(self, payment_id="pay_abc", provider="yookassa"):
        data = {
            "id": 1,
            "payment_id": payment_id,
            "user_id": 5000,
            "amount_rub": 299.0,
            "pack_name": "basic",
            "status": "confirmed",
            "provider": provider,
            "created_at": datetime.utcnow(),
            "promo_code": None,
            "first_name": "Alice",
            "username": "alice",
        }
        r = MagicMock()
        r.__getitem__ = MagicMock(side_effect=lambda k: data[k])
        r.get = MagicMock(side_effect=lambda k, d=None: data.get(k, d))
        return r

    def _make_payments_session(self, total=0, total_revenue=0.0, refunds=0, refunds_amount=0.0,
                                confirmed_count=0, provider_rows=None, pay_rows=None):
        """Build session for get_payments_list.

        Call order: total scalar, total_revenue scalar, refunds scalar,
        refunds_amount scalar, confirmed_count scalar, provider_rows all(), pay_rows all()
        """
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(scalar=total),
            _make_mock_result(scalar=total_revenue),
            _make_mock_result(scalar=refunds),
            _make_mock_result(scalar=refunds_amount),
            _make_mock_result(scalar=confirmed_count),
            _make_mock_result(all_rows=provider_rows or []),
            _make_mock_result(all_rows=pay_rows or []),
        ])
        return session

    async def test_no_filters_returns_expected_keys(self):
        pay_row = self._make_payment_row()
        provider_row = {"provider": "yookassa", "cnt": 3, "sum_rub": 2990.0}
        session = self._make_payments_session(
            total=10, total_revenue=2990.0, refunds=2, refunds_amount=1000.0,
            confirmed_count=3, provider_rows=[provider_row], pay_rows=[pay_row],
        )
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import get_payments_list
            result = await get_payments_list(
                status_filter=None, bot_filter=None,
                provider_filter=None, page=1, limit=20,
            )
        for key in ("total", "total_revenue", "avg_check", "refunds",
                    "refunds_amount", "confirmed_count", "providers", "payments"):
            assert key in result
        assert result["total"] == 10
        assert len(result["payments"]) == 1
        assert result["payments"][0]["payment_id"] == "pay_abc"

    async def test_status_filter_maps_success_to_confirmed(self):
        session = self._make_payments_session(total=5, total_revenue=1495.0, confirmed_count=5)
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import get_payments_list
            result = await get_payments_list(
                status_filter="success", bot_filter=None,
                provider_filter=None, page=1, limit=10,
            )
        assert result["total"] == 5

    async def test_provider_filter_applied(self):
        session = self._make_payments_session(total=2, total_revenue=598.0, confirmed_count=2)
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import get_payments_list
            result = await get_payments_list(
                status_filter=None, bot_filter=None,
                provider_filter="yookassa", page=1, limit=10,
            )
        assert result["total"] == 2

    async def test_both_filters_applied(self):
        session = self._make_payments_session(total=1, total_revenue=299.0, confirmed_count=1)
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import get_payments_list
            result = await get_payments_list(
                status_filter="confirmed", bot_filter=None,
                provider_filter="stripe", page=2, limit=5,
            )
        assert "payments" in result
        assert result["total"] == 1

    async def test_avg_check_zero_when_no_confirmed_payments(self):
        session = self._make_payments_session(total=0, confirmed_count=0)
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import get_payments_list
            result = await get_payments_list(
                status_filter=None, bot_filter=None,
                provider_filter=None, page=1, limit=20,
            )
        assert result["avg_check"] == 0

    async def test_provider_none_falls_back_to_unknown(self):
        provider_row = MagicMock()
        provider_row.__getitem__ = MagicMock(
            side_effect=lambda k: {"provider": None, "cnt": 1, "sum_rub": 100.0}[k]
        )
        pay_row = self._make_payment_row()
        session = self._make_payments_session(
            total=1, total_revenue=100.0, confirmed_count=1,
            provider_rows=[provider_row], pay_rows=[pay_row],
        )
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import get_payments_list
            result = await get_payments_list(
                status_filter=None, bot_filter=None,
                provider_filter=None, page=1, limit=20,
            )
        assert result["providers"][0]["provider"] == "unknown"

    async def test_refund_status_filter(self):
        session = self._make_payments_session(total=3, refunds=3, refunds_amount=897.0)
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import get_payments_list
            result = await get_payments_list(
                status_filter="refund", bot_filter=None,
                provider_filter=None, page=1, limit=10,
            )
        assert "payments" in result


# ---------------------------------------------------------------------------
# get_errors_list
# ---------------------------------------------------------------------------

class TestGetErrorsList:
    def _make_error_row(self):
        data = {
            "id": 1,
            "time": datetime.utcnow(),
            "level": "error",
            "source": "request",
            "bot": "neurobox",
            "message": "Something failed",
            "user_id": 1001,
            "task_type": "text",
            "model": "gpt-4o",
            "count": 1,
        }
        r = MagicMock()
        r.__getitem__ = MagicMock(side_effect=lambda k: data[k])
        r.get = MagicMock(side_effect=lambda k, d=None: data.get(k, d))
        return r

    async def test_returns_total_and_errors_keys(self):
        err_row = self._make_error_row()
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(scalar=5),
            _make_mock_result(all_rows=[err_row]),
        ])
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import get_errors_list
            result = await get_errors_list(
                level=None, bot_filter=None,
                sort="time", dir="desc",
                page=1, limit=20,
            )
        assert "total" in result
        assert "errors" in result
        assert result["total"] == 5
        assert len(result["errors"]) == 1

    async def test_error_row_has_expected_fields(self):
        err_row = self._make_error_row()
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(scalar=1),
            _make_mock_result(all_rows=[err_row]),
        ])
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import get_errors_list
            result = await get_errors_list(
                level=None, bot_filter=None,
                sort="time", dir="desc",
                page=1, limit=10,
            )
        err = result["errors"][0]
        for field in ("id", "time", "level", "source", "bot", "message", "user_id", "count"):
            assert field in err

    async def test_sort_by_level_ascending(self):
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(scalar=0),
            _make_mock_result(all_rows=[]),
        ])
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import get_errors_list
            result = await get_errors_list(
                level=None, bot_filter=None,
                sort="level", dir="asc",
                page=1, limit=10,
            )
        assert result["errors"] == []

    async def test_sort_by_count_descending(self):
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(scalar=0),
            _make_mock_result(all_rows=[]),
        ])
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import get_errors_list
            result = await get_errors_list(
                level=None, bot_filter=None,
                sort="count", dir="desc",
                page=2, limit=5,
            )
        assert "total" in result

    async def test_unknown_sort_key_defaults_to_time(self):
        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=[
            _make_mock_result(scalar=0),
            _make_mock_result(all_rows=[]),
        ])
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import get_errors_list
            result = await get_errors_list(
                level=None, bot_filter=None,
                sort="nonexistent", dir="asc",
                page=1, limit=10,
            )
        assert "errors" in result


# ---------------------------------------------------------------------------
# get_errors_top
# ---------------------------------------------------------------------------

class TestGetErrorsTop:
    async def test_returns_list_with_error_fields(self):
        data = {
            "id": 10,
            "time": datetime.utcnow(),
            "level": "critical",
            "bot": "neurobox",
            "message": "DB connection failed",
            "user_id": None,
            "count": 42,
        }
        r = MagicMock()
        r.__getitem__ = MagicMock(side_effect=lambda k: data[k])
        session = _make_mock_session(fetch=[r])
        with _patch_session(session):
            from services.backend.services.admin import get_errors_top
            result = await get_errors_top()
        assert len(result) == 1
        assert result[0]["count"] == 42
        assert result[0]["level"] == "critical"
        assert result[0]["message"] == "DB connection failed"

    async def test_empty_result(self):
        session = _make_mock_session(fetch=[])
        with _patch_session(session):
            from services.backend.services.admin import get_errors_top
            result = await get_errors_top()
        assert result == []

    async def test_null_count_defaults_to_one(self):
        data = {
            "id": 1,
            "time": datetime.utcnow(),
            "level": "warning",
            "bot": "neurobox",
            "message": "Minor issue",
            "user_id": None,
            "count": None,
        }
        r = MagicMock()
        r.__getitem__ = MagicMock(side_effect=lambda k: data[k])
        session = _make_mock_session(fetch=[r])
        with _patch_session(session):
            from services.backend.services.admin import get_errors_top
            result = await get_errors_top()
        assert result[0]["count"] == 1


# ---------------------------------------------------------------------------
# log_admin_audit
# ---------------------------------------------------------------------------

class TestLogAdminAudit:
    async def test_inserts_audit_row(self):
        session = _make_mock_session()
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import log_admin_audit
            await log_admin_audit(
                admin_tg_id=42,
                action="block_user",
                entity_type="user",
                entity_id="1001",
                details={"reason": "spam"},
                admin_user_id=42,
                admin_login="admin",
                admin_role="owner",
            )
        session.execute.assert_awaited_once()

    async def test_none_details_passes_none_to_db(self):
        session = _make_mock_session()
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import log_admin_audit
            await log_admin_audit(
                admin_tg_id=None,
                action="view_stats",
                entity_type=None,
                entity_id=None,
                details=None,
            )
        session.execute.assert_awaited_once()
        # Named params dict is the second positional arg to session.execute
        params = session.execute.call_args[0][1]
        assert params["details"] is None

    async def test_details_dict_is_json_serialized(self):
        session = _make_mock_session()
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import log_admin_audit
            await log_admin_audit(
                admin_tg_id=1,
                action="export",
                entity_type="payments",
                entity_id=None,
                details={"format": "csv"},
                admin_user_id=1,
                admin_login="superadmin",
                admin_role="owner",
            )
        params = session.execute.call_args[0][1]
        import json
        parsed = json.loads(params["details"])
        assert parsed["format"] == "csv"

    async def test_bot_identifier_is_first_param(self):
        session = _make_mock_session()
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "mybot"
            from services.backend.services.admin import log_admin_audit
            await log_admin_audit(
                admin_tg_id=1,
                action="test_action",
                entity_type=None,
                entity_id=None,
                details=None,
            )
        params = session.execute.call_args[0][1]
        assert params["bot_identifier"] == "mybot"

    async def test_action_is_second_param(self):
        session = _make_mock_session()
        with _patch_session(session), patch("shared.config.settings") as m:
            m.bot_identifier = "neurobox"
            from services.backend.services.admin import log_admin_audit
            await log_admin_audit(
                admin_tg_id=1,
                action="delete_user",
                entity_type=None,
                entity_id=None,
                details=None,
            )
        params = session.execute.call_args[0][1]
        assert params["action"] == "delete_user"
