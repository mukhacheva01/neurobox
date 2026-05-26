"""Бизнес-логика Admin API: SQLAlchemy async session + Redis cache."""
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text

from shared.db.session import get_session


async def _redis():
    from shared.redis.store import _get_redis
    return await _get_redis()

async def _cache_get(key: str) -> Any:
    r = await _redis()
    if not r:
        return None
    try:
        import json
        raw = await r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None

async def _cache_set(key: str, value: Any, ttl_sec: int = 300):
    r = await _redis()
    if not r:
        return
    try:
        import json
        await r.set(key, json.dumps(value, default=str), ex=ttl_sec)
    except Exception:
        pass

def _bot_id():
    from shared.config import settings
    return getattr(settings, "bot_identifier", None) or "neurobox"


# --- Периоды (UTC; для МСК hourly отдельно) ---
def _period_interval(period: str):
    if period == "day":
        return timedelta(days=1), timedelta(days=1)
    if period == "week":
        return timedelta(days=7), timedelta(days=7)
    if period == "month":
        return timedelta(days=30), timedelta(days=30)
    return timedelta(days=365), timedelta(days=365)


def _period_days(period: str) -> int:
    if period == "day":
        return 1
    if period == "week":
        return 7
    if period == "month":
        return 30
    return 365


def _segment_case_sql() -> str:
    return """
    CASE
      WHEN u.is_blocked THEN 'blocked'
      WHEN u.full_access_48h_ends_at IS NOT NULL AND u.full_access_48h_ends_at > NOW() THEN 'trial'
      WHEN u.trial_started_at IS NOT NULL AND u.trial_started_at + INTERVAL '45 minutes' > NOW() THEN 'trial'
      WHEN u.unlimited_ends_at IS NOT NULL AND u.unlimited_ends_at > NOW() THEN
        CASE WHEN COALESCE(pay.confirmed_count, 0) > 1 THEN 'reactivated' ELSE 'paid' END
      WHEN COALESCE(u.total_payments_rub, 0) > 0 THEN 'churned'
      ELSE 'free'
    END
    """


def _infra_cost_rub(days: int) -> float:
    from shared.config import settings
    monthly_usd = float(getattr(settings, "infra_monthly_cost_usd", 25.0) or 25.0)
    usd_to_rub = float(getattr(settings, "usd_to_rub", 95.0) or 95.0)
    return round((monthly_usd * usd_to_rub) * (days / 30.0), 2)


async def get_stats(period: str) -> dict:
    cache_key = f"neurobox:admin:stats:{period}"
    cached = await _cache_get(cache_key)
    if cached:
        return cached
    interval, _ = _period_interval(period)
    days = _period_days(period)
    async with get_session() as session:
        # total_users
        total_users = (await session.execute(text("SELECT COUNT(*) FROM users"))).scalar()
        # new_users за период
        new_users = (await session.execute(
            text("SELECT COUNT(*) FROM users WHERE created_at >= NOW() - :interval::interval"),
            {"interval": interval},
        )).scalar()
        # new_users предыдущий период
        new_prev = (await session.execute(
            text("SELECT COUNT(*) FROM users WHERE created_at >= NOW() - :interval::interval - :interval2::interval AND created_at < NOW() - :interval2::interval"),
            {"interval": interval, "interval2": interval},
        )).scalar()
        new_users_change_pct = (100 * (new_users - new_prev) / new_prev) if new_prev else None

        # revenue за период (confirmed)
        revenue = (await session.execute(
            text("""SELECT COALESCE(SUM(amount_rub), 0) FROM payments
               WHERE status = 'confirmed' AND confirmed_at >= NOW() - :interval::interval"""),
            {"interval": interval},
        )).scalar()
        revenue = float(revenue or 0)
        rev_prev = (await session.execute(
            text("""SELECT COALESCE(SUM(amount_rub), 0) FROM payments
               WHERE status = 'confirmed' AND confirmed_at >= NOW() - :interval::interval - :interval2::interval
               AND confirmed_at < NOW() - :interval2::interval"""),
            {"interval": interval, "interval2": interval},
        )).scalar()
        revenue_change_pct = (100 * (revenue - float(rev_prev or 0)) / float(rev_prev)) if rev_prev else None

        # paying_users за период
        paying_users = (await session.execute(
            text("""SELECT COUNT(DISTINCT user_id) FROM payments
               WHERE status = 'confirmed' AND confirmed_at >= NOW() - :interval::interval"""),
            {"interval": interval},
        )).scalar()
        paying_users = paying_users or 0
        confirmed_count = (await session.execute(
            text("""SELECT COUNT(*) FROM payments
               WHERE status = 'confirmed' AND confirmed_at >= NOW() - :interval::interval"""),
            {"interval": interval},
        )).scalar()
        confirmed_count = confirmed_count or 0

        # total_generations за период (ai_requests completed)
        total_generations = (await session.execute(
            text("""SELECT COUNT(*) FROM ai_requests
               WHERE started_at >= NOW() - :interval::interval AND status = 'completed'"""),
            {"interval": interval},
        )).scalar()
        total_generations = total_generations or 0

        dau = (await session.execute(text("SELECT COUNT(DISTINCT user_id) FROM ai_requests WHERE started_at >= NOW() - INTERVAL '1 day'"))).scalar()
        wau = (await session.execute(text("SELECT COUNT(DISTINCT user_id) FROM ai_requests WHERE started_at >= NOW() - INTERVAL '7 days'"))).scalar()
        mau = (await session.execute(text("SELECT COUNT(DISTINCT user_id) FROM ai_requests WHERE started_at >= NOW() - INTERVAL '30 days'"))).scalar()
        dau, wau, mau = dau or 0, wau or 0, mau or 0
        stickiness_pct = (100 * dau / mau) if mau else None

        ai_cost_usd = (await session.execute(
            text("SELECT COALESCE(SUM(cost_usd), 0) FROM ai_requests WHERE started_at >= NOW() - :interval::interval"),
            {"interval": interval},
        )).scalar()
        ai_cost_usd = float(ai_cost_usd or 0)
        from shared.config import settings as cfg
        usd_to_rub = float(getattr(cfg, "usd_to_rub", 95.0) or 95.0)
        ai_cost_rub = round(ai_cost_usd * usd_to_rub, 2)
        infra_cost_rub = _infra_cost_rub(days)
        margin_rub = round(revenue - ai_cost_rub - infra_cost_rub, 2)

        segment_rows = (await session.execute(
            text(f"""
            SELECT seg.status, COUNT(*) AS cnt
            FROM (
                SELECT {_segment_case_sql()} AS status
                FROM users u
                LEFT JOIN (
                    SELECT user_id, COUNT(*) AS confirmed_count
                    FROM payments
                    WHERE status = 'confirmed'
                    GROUP BY user_id
                ) pay ON pay.user_id = u.id
            ) seg
            GROUP BY seg.status
            """),
        )).mappings().all()
        segment_counts = {r["status"]: int(r["cnt"] or 0) for r in segment_rows}

        # cr_trial_to_paid, churn — упрощённо
        cr_trial_to_paid = (paying_users / new_users * 100) if new_users else None
        churn_pct = None

        arpu = (revenue / paying_users) if paying_users else None
        arppu = (revenue / confirmed_count) if confirmed_count else None

        # referrals за период (новые referred_by)
        referrals = (await session.execute(
            text("SELECT COUNT(*) FROM users WHERE referred_by IS NOT NULL AND created_at >= NOW() - :interval::interval"),
            {"interval": interval},
        )).scalar()
        referrals = referrals or 0

        # likes / dislikes (response_ratings)
        likes = (await session.execute(
            text("SELECT COUNT(*) FROM response_ratings WHERE rating = 'up' AND created_at >= NOW() - :interval::interval"),
            {"interval": interval},
        )).scalar()
        dislikes = (await session.execute(
            text("SELECT COUNT(*) FROM response_ratings WHERE rating = 'down' AND created_at >= NOW() - :interval::interval"),
            {"interval": interval},
        )).scalar()
        likes, dislikes = likes or 0, dislikes or 0
        total_r = likes + dislikes
        rating_pct = (100 * likes / total_r) if total_r else None
    out = {
        "period": period,
        "total_users": total_users or 0,
        "new_users": new_users or 0,
        "new_users_change_pct": new_users_change_pct,
        "revenue": revenue,
        "revenue_change_pct": revenue_change_pct,
        "paying_users": paying_users,
        "total_generations": total_generations,
        "cr_trial_to_paid": cr_trial_to_paid,
        "arpu": arpu,
        "arppu": arppu,
        "churn_pct": churn_pct,
        "referrals": referrals,
        "likes": likes,
        "dislikes": dislikes,
        "rating_pct": rating_pct,
        "dau": dau,
        "wau": wau,
        "mau": mau,
        "stickiness_pct": stickiness_pct,
        "ai_cost_usd": ai_cost_usd,
        "ai_cost_rub": ai_cost_rub,
        "infra_cost_rub": infra_cost_rub,
        "margin_rub": margin_rub,
        "segment_counts": segment_counts,
    }
    await _cache_set(cache_key, out)
    return out


async def get_chart(period: str) -> dict:
    cache_key = f"neurobox:admin:chart:{period}"
    cached = await _cache_get(cache_key)
    if cached:
        return cached
    interval, _ = _period_interval(period)
    labels = []
    new_users = []
    revenue = []
    likes = []
    dislikes = []
    if period == "day":
        labels = [f"{i*2:02d}:00" for i in range(12)]
        async with get_session() as session:
            row_u = (await session.execute(
                text("""SELECT date_trunc('hour', created_at) AS h, COUNT(*) AS c
                   FROM users WHERE created_at >= NOW() - INTERVAL '1 day'
                   GROUP BY 1 ORDER BY 1"""),
            )).mappings().all()
            row_r = (await session.execute(
                text("""SELECT date_trunc('hour', confirmed_at) AS h, COALESCE(SUM(amount_rub), 0) AS s
                   FROM payments WHERE status = 'confirmed' AND confirmed_at >= NOW() - INTERVAL '1 day'
                   GROUP BY 1 ORDER BY 1"""),
            )).mappings().all()
            row_l = (await session.execute(
                text("""SELECT date_trunc('hour', created_at) AS h, COUNT(*) AS c
                   FROM response_ratings WHERE rating = 'up' AND created_at >= NOW() - INTERVAL '1 day'
                   GROUP BY 1 ORDER BY 1"""),
            )).mappings().all()
            row_d = (await session.execute(
                text("""SELECT date_trunc('hour', created_at) AS h, COUNT(*) AS c
                   FROM response_ratings WHERE rating = 'down' AND created_at >= NOW() - INTERVAL '1 day'
                   GROUP BY 1 ORDER BY 1"""),
            )).mappings().all()
        by_hour = {i: {"users": 0, "revenue": 0.0, "likes": 0, "dislikes": 0} for i in range(24)}
        for r in row_u:
            h = r["h"].hour if hasattr(r["h"], "hour") else 0
            if 0 <= h < 24:
                by_hour[h]["users"] = r["c"]
        for r in row_r:
            h = r["h"].hour if hasattr(r["h"], "hour") else 0
            if 0 <= h < 24:
                by_hour[h]["revenue"] = float(r["s"])
        for r in row_l:
            h = r["h"].hour if hasattr(r["h"], "hour") else 0
            if 0 <= h < 24:
                by_hour[h]["likes"] = r["c"]
        for r in row_d:
            h = r["h"].hour if hasattr(r["h"], "hour") else 0
            if 0 <= h < 24:
                by_hour[h]["dislikes"] = r["c"]
        for i in range(0, 24, 2):
            d = by_hour.get(i, {})
            new_users.append(d.get("users", 0))
            revenue.append(d.get("revenue", 0))
            likes.append(d.get("likes", 0))
            dislikes.append(d.get("dislikes", 0))
    else:
        days = 7 if period == "week" else 30 if period == "month" else 365
        weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        async with get_session() as session:
            if period == "week":
                labels = weekdays
                for d in range(7):
                    nu = (await session.execute(
                        text("SELECT COUNT(*) FROM users WHERE created_at >= NOW() - :total_interval::interval - :d_interval::interval AND created_at < NOW() - :total_interval::interval - :d1_interval::interval"),
                        {"total_interval": timedelta(days=days), "d_interval": timedelta(days=d), "d1_interval": timedelta(days=d + 1)},
                    )).scalar()
                    rev = (await session.execute(
                        text("""SELECT COALESCE(SUM(amount_rub), 0) FROM payments
                           WHERE status = 'confirmed' AND confirmed_at >= NOW() - :total_interval::interval - :d_interval::interval
                           AND confirmed_at < NOW() - :total_interval::interval - :d1_interval::interval"""),
                        {"total_interval": timedelta(days=days), "d_interval": timedelta(days=d), "d1_interval": timedelta(days=d + 1)},
                    )).scalar()
                    li = (await session.execute(
                        text("SELECT COUNT(*) FROM response_ratings WHERE rating = 'up' AND created_at >= NOW() - :total_interval::interval - :d_interval::interval AND created_at < NOW() - :total_interval::interval - :d1_interval::interval"),
                        {"total_interval": timedelta(days=days), "d_interval": timedelta(days=d), "d1_interval": timedelta(days=d + 1)},
                    )).scalar()
                    di = (await session.execute(
                        text("SELECT COUNT(*) FROM response_ratings WHERE rating = 'down' AND created_at >= NOW() - :total_interval::interval - :d_interval::interval AND created_at < NOW() - :total_interval::interval - :d1_interval::interval"),
                        {"total_interval": timedelta(days=days), "d_interval": timedelta(days=d), "d1_interval": timedelta(days=d + 1)},
                    )).scalar()
                    new_users.append(nu or 0)
                    revenue.append(float(rev or 0))
                    likes.append(li or 0)
                    dislikes.append(di or 0)
            else:
                # month: 15 точек; year: 12 месяцев
                if period == "month":
                    step = 2
                    n_points = 15
                else:
                    step = 1
                    n_points = 12
                    labels = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]
                if period == "month":
                    labels = [str(1 + i * 2) for i in range(15)]
                for i in range(n_points):
                    nu = (await session.execute(
                        text("SELECT COUNT(*) FROM users WHERE created_at >= NOW() - :interval::interval - :d_interval::interval AND created_at < NOW() - :interval::interval - :d1_interval::interval"),
                        {"interval": interval, "d_interval": timedelta(days=i * step), "d1_interval": timedelta(days=(i + 1) * step)},
                    )).scalar()
                    rev = (await session.execute(
                        text("""SELECT COALESCE(SUM(amount_rub), 0) FROM payments
                           WHERE status = 'confirmed' AND confirmed_at >= NOW() - :interval::interval - :d_interval::interval
                           AND confirmed_at < NOW() - :interval::interval - :d1_interval::interval"""),
                        {"interval": interval, "d_interval": timedelta(days=i * step), "d1_interval": timedelta(days=(i + 1) * step)},
                    )).scalar()
                    li = (await session.execute(
                        text("SELECT COUNT(*) FROM response_ratings WHERE rating = 'up' AND created_at >= NOW() - :interval::interval - :d_interval::interval AND created_at < NOW() - :interval::interval - :d1_interval::interval"),
                        {"interval": interval, "d_interval": timedelta(days=i * step), "d1_interval": timedelta(days=(i + 1) * step)},
                    )).scalar()
                    di = (await session.execute(
                        text("SELECT COUNT(*) FROM response_ratings WHERE rating = 'down' AND created_at >= NOW() - :interval::interval - :d_interval::interval AND created_at < NOW() - :interval::interval - :d1_interval::interval"),
                        {"interval": interval, "d_interval": timedelta(days=i * step), "d1_interval": timedelta(days=(i + 1) * step)},
                    )).scalar()
                    new_users.append(nu or 0)
                    revenue.append(float(rev or 0))
                    likes.append(li or 0)
                    dislikes.append(di or 0)
    out = {"labels": labels, "new_users": new_users, "revenue": revenue, "likes": likes, "dislikes": dislikes}
    await _cache_set(cache_key, out)
    return out


async def get_models_stats() -> list:
    cache_key = "neurobox:admin:models"
    cached = await _cache_get(cache_key)
    if cached:
        return cached
    async with get_session() as session:
        rows = (await session.execute(
            text("SELECT model AS name, COUNT(*) AS count FROM ai_requests WHERE status = 'completed' GROUP BY model ORDER BY count DESC"),
        )).mappings().all()
    out = [{"name": r["name"], "count": r["count"]} for r in rows]
    await _cache_set(cache_key, out)
    return out


async def get_retention() -> list:
    cache_key = "neurobox:admin:retention"
    cached = await _cache_get(cache_key)
    if cached:
        return cached
    # Когорты за последние 4 недели (неделя = понедельник)
    async with get_session() as session:
        cohorts = (await session.execute(
            text("""SELECT date_trunc('week', created_at)::date AS cohort_date,
                      COUNT(*) AS total
               FROM users WHERE created_at >= NOW() - INTERVAL '4 weeks'
               GROUP BY 1 ORDER BY 1 DESC LIMIT 4"""),
        )).mappings().all()
        out = []
        for c in cohorts:
            cohort_date = c["cohort_date"]
            total = c["total"]
            # D1: пользователи, у которых есть ai_requests или сообщение на cohort_date+1
            d1 = (await session.execute(
                text("""SELECT COUNT(DISTINCT u.id) FROM users u
                   INNER JOIN ai_requests a ON a.user_id = u.id
                   WHERE date_trunc('week', u.created_at)::date = :cohort_date::date
                   AND a.started_at >= :cohort_date::date + INTERVAL '1 day'
                   AND a.started_at < :cohort_date::date + INTERVAL '2 days'"""),
                {"cohort_date": cohort_date},
            )).scalar()
            d3 = (await session.execute(
                text("""SELECT COUNT(DISTINCT u.id) FROM users u
                   INNER JOIN ai_requests a ON a.user_id = u.id
                   WHERE date_trunc('week', u.created_at)::date = :cohort_date::date
                   AND a.started_at >= :cohort_date::date + INTERVAL '1 day'
                   AND a.started_at <= :cohort_date::date + INTERVAL '3 days'"""),
                {"cohort_date": cohort_date},
            )).scalar()
            d7 = (await session.execute(
                text("""SELECT COUNT(DISTINCT u.id) FROM users u
                   INNER JOIN ai_requests a ON a.user_id = u.id
                   WHERE date_trunc('week', u.created_at)::date = :cohort_date::date
                   AND a.started_at >= :cohort_date::date + INTERVAL '1 day'
                   AND a.started_at <= :cohort_date::date + INTERVAL '7 days'"""),
                {"cohort_date": cohort_date},
            )).scalar()
            d14 = (await session.execute(
                text("""SELECT COUNT(DISTINCT u.id) FROM users u
                   INNER JOIN ai_requests a ON a.user_id = u.id
                   WHERE date_trunc('week', u.created_at)::date = :cohort_date::date
                   AND a.started_at >= :cohort_date::date + INTERVAL '1 day'
                   AND a.started_at <= :cohort_date::date + INTERVAL '14 days'"""),
                {"cohort_date": cohort_date},
            )).scalar()
            d30 = (await session.execute(
                text("""SELECT COUNT(DISTINCT u.id) FROM users u
                   INNER JOIN ai_requests a ON a.user_id = u.id
                   WHERE date_trunc('week', u.created_at)::date = :cohort_date::date
                   AND a.started_at >= :cohort_date::date + INTERVAL '1 day'
                   AND a.started_at <= :cohort_date::date + INTERVAL '30 days'"""),
                {"cohort_date": cohort_date},
            )).scalar()
            out.append({
                "date": str(cohort_date),
                "total": total,
                "d1": round(100 * (d1 or 0) / total, 1) if total else 0,
                "d3": round(100 * (d3 or 0) / total, 1) if total else 0,
                "d7": round(100 * (d7 or 0) / total, 1) if total else 0,
                "d14": round(100 * (d14 or 0) / total, 1) if total else 0,
                "d30": round(100 * (d30 or 0) / total, 1) if total else 0,
            })
    await _cache_set(cache_key, out)
    return out


async def get_promos() -> list:
    async with get_session() as session:
        rows = (await session.execute(
            text("""SELECT p.code, COALESCE(p.used_count, 0)::int AS uses,
                      (SELECT COALESCE(SUM(amount_rub), 0) FROM payments WHERE status = 'confirmed' AND promo_code = p.code) AS revenue
               FROM promocodes p"""),
        )).mappings().all()
    return [{"code": r["code"], "uses": r["uses"], "revenue": float(r["revenue"] or 0), "cr": None} for r in rows]


async def get_referrals_top() -> list:
    async with get_session() as session:
        rows = (await session.execute(
            text("""SELECT u.id AS user_id, u.first_name, u.username, u.referral_count AS count,
                      (SELECT COALESCE(SUM(amount_rub), 0) FROM payments p WHERE p.user_id IN (SELECT id FROM users WHERE referred_by = u.id) AND p.status = 'confirmed') AS revenue
               FROM users u WHERE u.referral_count > 0 ORDER BY u.referral_count DESC LIMIT 20"""),
        )).mappings().all()
    return [
        {"user_id": r["user_id"], "name": r["first_name"], "username": r["username"], "count": r["count"], "revenue": float(r["revenue"] or 0)}
        for r in rows
    ]


async def get_hourly_msk() -> list:
    """Активность по часам 0-23 МСК за последние 7 дней. UTC+3."""
    # В PostgreSQL: created_at в UTC; час МСК = EXTRACT(HOUR FROM created_at + INTERVAL '3 hours')
    async with get_session() as session:
        rows = (await session.execute(
            text("""SELECT EXTRACT(HOUR FROM (started_at + INTERVAL '3 hours'))::int AS h, COUNT(*) AS c
               FROM ai_requests WHERE started_at >= NOW() - INTERVAL '7 days'
               GROUP BY 1 ORDER BY 1"""),
        )).mappings().all()
    by_h = [0] * 24
    for r in rows:
        h = int(r["h"]) if r["h"] is not None else 0
        if 0 <= h < 24:
            by_h[h] = r["c"]
    return by_h


async def get_trends() -> dict:
    labels = []
    users = []
    revenue = []
    async with get_session() as session:
        for d in range(14):
            dt = datetime.utcnow().date() - timedelta(days=13 - d)
            labels.append(dt.strftime("%d.%m"))
            u = (await session.execute(
                text("SELECT COUNT(*) FROM users WHERE created_at::date = :dt"),
                {"dt": dt},
            )).scalar()
            r = (await session.execute(
                text("""SELECT COALESCE(SUM(amount_rub), 0) FROM payments
                   WHERE status = 'confirmed' AND confirmed_at::date = :dt"""),
                {"dt": dt},
            )).scalar()
            users.append(u or 0)
            revenue.append(float(r or 0))
    return {"labels": labels, "users": users, "revenue": revenue}


async def get_users_list(search: str | None, status_filter: str | None, sort: str, dir: str, page: int, limit: int) -> dict:
    dir_sql = "DESC" if dir == "desc" else "ASC"
    sort_col = {
        "first_name": "u.first_name",
        "telegram_id": "u.id",
        "status": "segment",
        "ltv": "u.total_payments_rub",
        "created_at": "u.created_at",
        "last_active_at": "u.last_active_at",
    }.get(sort, "u.created_at")
    where = []
    params: dict = {}
    if search:
        where.append("(u.first_name ILIKE :search OR u.username ILIKE :search OR u.id::text LIKE :search)")
        params["search"] = f"%{search}%"
    if status_filter:
        if status_filter == "blocked":
            where.append("u.is_blocked = TRUE")
        else:
            params["status_filter"] = status_filter
            where.append(f"{_segment_case_sql()} = :status_filter")
    where_sql = " AND ".join(where) if where else "TRUE"
    params["limit"] = limit
    params["offset"] = (page - 1) * limit
    async with get_session() as session:
        base_sql = f"""
            FROM users u
            LEFT JOIN (
                SELECT user_id, COUNT(*) AS confirmed_count
                FROM payments
                WHERE status = 'confirmed'
                GROUP BY user_id
            ) pay ON pay.user_id = u.id
            WHERE {where_sql}
        """
        total = (await session.execute(text(f"SELECT COUNT(*) {base_sql}"), params)).scalar()
        rows = (await session.execute(
            text(f"""SELECT u.id, u.first_name, u.username, u.credits_bought, u.credits_free_today, u.credits_free_reset,
                   u.is_blocked, u.total_payments_rub, u.referral_count, u.created_at, u.last_active_at, u.unlimited_ends_at,
                   {_segment_case_sql()} AS segment
            {base_sql}
            ORDER BY {sort_col} {dir_sql} NULLS LAST
            LIMIT :limit OFFSET :offset"""),
            params,
        )).mappings().all()
        users_out = []
        for r in rows:
            credits = (r["credits_bought"] or 0) + (r["credits_free_today"] or 0)
            is_unlimited = r["unlimited_ends_at"] and r["unlimited_ends_at"] > datetime.utcnow()
            gen = (await session.execute(
                text("SELECT COUNT(*) FROM ai_requests WHERE user_id = :user_id"),
                {"user_id": r["id"]},
            )).scalar()
            users_out.append({
                "telegram_id": r["id"],
                "first_name": r["first_name"],
                "username": r["username"],
                "status": r["segment"],
                "ltv": float(r["total_payments_rub"] or 0),
                "credits": credits,
                "is_unlimited": bool(is_unlimited),
                "generations": gen or 0,
                "referral_count": r["referral_count"] or 0,
                "created_at": r["created_at"],
                "last_active_at": r.get("last_active_at"),
                "source": "referral" if (r["referral_count"] or 0) > 0 else "organic",
                "acquisition_channel": None,
                "utm_source": None,
                "bots": [_bot_id()],
            })
    return {"total": total or 0, "page": page, "limit": limit, "users": users_out}


async def get_user_detail(telegram_id: int) -> dict | None:
    async with get_session() as session:
        u = (await session.execute(
            text("SELECT * FROM users WHERE id = :uid"),
            {"uid": telegram_id},
        )).mappings().first()
        if not u:
            return None
        credits = (u["credits_bought"] or 0) + (u["credits_free_today"] or 0)
        is_unlimited = u.get("unlimited_ends_at") and u["unlimited_ends_at"] > datetime.utcnow()
        pay = (await session.execute(
            text("SELECT COUNT(*) AS confirmed_count FROM payments WHERE user_id = :uid AND status = 'confirmed'"),
            {"uid": telegram_id},
        )).mappings().first()
        confirmed_count = int((pay or {}).get("confirmed_count") or 0)
        if u["is_blocked"]:
            status = "blocked"
        elif u.get("full_access_48h_ends_at") and u["full_access_48h_ends_at"] > datetime.utcnow():
            status = "trial"
        elif u.get("trial_started_at") and u["trial_started_at"] + timedelta(minutes=45) > datetime.utcnow():
            status = "trial"
        elif is_unlimited:
            status = "reactivated" if confirmed_count > 1 else "paid"
        elif float(u.get("total_payments_rub") or 0) > 0:
            status = "churned"
        else:
            status = "free"
        gen = (await session.execute(
            text("SELECT COUNT(*) FROM ai_requests WHERE user_id = :uid"),
            {"uid": telegram_id},
        )).scalar()
        notes_rows = (await session.execute(
            text("SELECT note, created_at FROM user_notes WHERE user_id = :uid ORDER BY created_at DESC"),
            {"uid": telegram_id},
        )).mappings().all()
        notes = " | ".join(r["note"] for r in notes_rows) if notes_rows else ""
        pays = (await session.execute(
            text("""SELECT payment_id, created_at, pack_name, amount_rub, status, promo_code
               FROM payments WHERE user_id = :uid ORDER BY created_at DESC LIMIT 50"""),
            {"uid": telegram_id},
        )).mappings().all()
        tx = (await session.execute(
            text("""SELECT created_at, amount, type, description FROM credit_transactions
               WHERE user_id = :uid ORDER BY created_at DESC LIMIT 50"""),
            {"uid": telegram_id},
        )).mappings().all()
    return {
        "telegram_id": telegram_id,
        "first_name": u["first_name"],
        "last_name": None,
        "username": u["username"],
        "status": status,
        "ltv": float(u["total_payments_rub"] or 0),
        "credits": credits,
        "is_unlimited": bool(is_unlimited),
        "generations": gen or 0,
        "referral_count": u["referral_count"] or 0,
        "referrer_id": u.get("referred_by"),
        "created_at": u["created_at"],
        "last_active_at": u.get("last_active_at"),
        "acquisition_channel": None,
        "utm_source": None,
        "utm_medium": None,
        "utm_campaign": u.get("utm_campaign"),
        "utm_content": u.get("utm_content"),
        "utm_term": u.get("utm_term"),
        "start_payload": u.get("start_payload"),
        "first_paid_at": u.get("first_paid_at"),
        "last_paid_at": u.get("last_paid_at"),
        "notes": notes,
        "payments": [{"id": p["payment_id"], "date": p["created_at"], "plan": p["pack_name"], "amount": float(p["amount_rub"]), "status": p["status"], "promo": p.get("promo_code")} for p in pays],
        "transactions": [{"date": t["created_at"], "type": "+" if (t["amount"] or 0) >= 0 else "-", "amount": abs(t["amount"] or 0), "description": t["description"]} for t in tx],
    }


async def block_user(telegram_id: int) -> bool:
    async with get_session() as session:
        await session.execute(
            text("UPDATE users SET is_blocked = TRUE, updated_at = NOW() WHERE id = :uid"),
            {"uid": telegram_id},
        )
    return True


async def unblock_user(telegram_id: int) -> bool:
    async with get_session() as session:
        await session.execute(
            text("UPDATE users SET is_blocked = FALSE, updated_at = NOW() WHERE id = :uid"),
            {"uid": telegram_id},
        )
    return True


async def add_credits_to_user(telegram_id: int, amount: int, description: str | None, admin_tg_id: int) -> bool:
    from shared.domain.credits import add_credits
    await add_credits(telegram_id, amount, "admin_add", description or f"Начислено админом {admin_tg_id}")
    return True


async def deduct_credits_from_user(telegram_id: int, amount: int, description: str | None, admin_tg_id: int) -> bool:
    async with get_session() as session:
        row = (await session.execute(
            text("SELECT credits_bought, credits_free_today FROM users WHERE id = :uid"),
            {"uid": telegram_id},
        )).mappings().first()
        if not row:
            return False
        bought = row["credits_bought"] or 0
        free = row["credits_free_today"] or 0
        total = bought + free
        if amount > total:
            return False
        if free >= amount:
            new_free = free - amount
            new_bought = bought
            await session.execute(
                text("UPDATE users SET credits_free_today = :new_free, updated_at = NOW() WHERE id = :uid"),
                {"new_free": new_free, "uid": telegram_id},
            )
        else:
            deduct_from_bought = amount - free
            new_free = 0
            new_bought = bought - deduct_from_bought
            await session.execute(
                text("UPDATE users SET credits_free_today = 0, credits_bought = credits_bought - :deduct, updated_at = NOW() WHERE id = :uid"),
                {"deduct": deduct_from_bought, "uid": telegram_id},
            )
        await session.execute(
            text("""INSERT INTO credit_transactions (user_id, amount, credits_bought_after, credits_free_after, type, description)
               VALUES (:user_id, :amount, :credits_bought_after, :credits_free_after, 'admin_deduct', :description)"""),
            {
                "user_id": telegram_id,
                "amount": -amount,
                "credits_bought_after": new_bought,
                "credits_free_after": new_free,
                "description": description or f"Списано админом {admin_tg_id}",
            },
        )
    return True


async def set_user_unlimited(telegram_id: int, is_unlimited: bool, admin_tg_id: int) -> bool:
    if is_unlimited:
        from shared.domain.credits import set_unlimited_until
        await set_unlimited_until(telegram_id, days=30)
    else:
        async with get_session() as session:
            await session.execute(
                text("UPDATE users SET unlimited_ends_at = NULL, updated_at = NOW() WHERE id = :uid"),
                {"uid": telegram_id},
            )
    return True


async def add_user_note(telegram_id: int, text_: str, admin_tg_id: int) -> bool:
    async with get_session() as session:
        await session.execute(
            text("INSERT INTO user_notes (user_id, admin_id, note) VALUES (:user_id, :admin_id, :note)"),
            {"user_id": telegram_id, "admin_id": admin_tg_id, "note": text_[:1000]},
        )
    return True


async def send_message_to_user(telegram_id: int, text_: str) -> bool:
    from aiogram import Bot

    from shared.config import settings
    bot = Bot(token=settings.bot_token)
    try:
        await bot.send_message(telegram_id, text_)
        return True
    finally:
        await bot.session.close()


def _payment_status_map(s: str) -> str:
    if s == "success":
        return "confirmed"
    if s == "refund":
        return "refunded"
    return s


async def get_payments_list(
    status_filter: str | None,
    bot_filter: str | None,
    provider_filter: str | None,
    page: int,
    limit: int,
) -> dict:
    where = []
    params: dict = {}
    if status_filter:
        where.append("p.status = :status_filter")
        params["status_filter"] = _payment_status_map(status_filter)
    if provider_filter:
        where.append("p.provider = :provider_filter")
        params["provider_filter"] = provider_filter
    where_sql = " AND ".join(where) if where else "TRUE"
    params["limit"] = limit
    params["offset"] = (page - 1) * limit
    async with get_session() as session:
        total = (await session.execute(
            text(f"SELECT COUNT(*) FROM payments p WHERE {where_sql}"),
            params,
        )).scalar()
        total_revenue = (await session.execute(
            text(f"SELECT COALESCE(SUM(amount_rub), 0) FROM payments p WHERE status = 'confirmed' AND {where_sql}"),
            params,
        )).scalar()
        total_revenue = float(total_revenue or 0)
        refunds = (await session.execute(
            text("SELECT COUNT(*) FROM payments WHERE status = 'refunded'"),
        )).scalar()
        refunds_amount = (await session.execute(
            text("SELECT COALESCE(SUM(amount_rub), 0) FROM payments WHERE status = 'refunded'"),
        )).scalar()
        confirmed_count = (await session.execute(
            text(f"SELECT COUNT(*) FROM payments p WHERE status = 'confirmed' AND {where_sql}"),
            params,
        )).scalar()
        provider_rows = (await session.execute(
            text(
                f"SELECT provider, COUNT(*) AS cnt, COALESCE(SUM(amount_rub), 0) AS sum_rub "
                f"FROM payments p WHERE status = 'confirmed' AND {where_sql} GROUP BY provider ORDER BY sum_rub DESC, cnt DESC"
            ),
            params,
        )).mappings().all()
        rows = (await session.execute(
            text(f"""SELECT p.id, p.payment_id, p.user_id, p.amount_rub, p.pack_name, p.status, p.provider, p.created_at, p.promo_code,
                   u.first_name, u.username
            FROM payments p
            LEFT JOIN users u ON u.id = p.user_id
            WHERE {where_sql}
            ORDER BY p.created_at DESC
            LIMIT :limit OFFSET :offset"""),
            params,
        )).mappings().all()
    payments_out = []
    for r in rows:
        payments_out.append({
            "payment_id": r["payment_id"],
            "date": r["created_at"],
            "user": {"telegram_id": r["user_id"], "first_name": r["first_name"], "username": r["username"]},
            "bot": _bot_id(),
            "plan": r["pack_name"],
            "amount": float(r["amount_rub"]),
            "status": r["status"],
            "provider": r.get("provider"),
            "promo": r.get("promo_code"),
        })
    avg = (total_revenue / confirmed_count) if confirmed_count else 0
    providers = [{"provider": r["provider"] or "unknown", "count": r["cnt"], "revenue": float(r["sum_rub"] or 0)} for r in provider_rows]
    return {
        "total": total or 0,
        "total_revenue": total_revenue,
        "avg_check": avg,
        "refunds": refunds or 0,
        "refunds_amount": float(refunds_amount or 0),
        "confirmed_count": confirmed_count or 0,
        "providers": providers,
        "payments": payments_out,
    }


async def get_errors_list(level: str | None, bot_filter: str | None, sort: str, dir: str, page: int, limit: int) -> dict:
    sort_col = {"time": "time", "level": "level", "count": "count"}.get(sort, "time")
    dir_sql = "DESC" if dir == "desc" else "ASC"
    params: dict = {"limit": limit, "offset": (page - 1) * limit}
    async with get_session() as session:
        total = (await session.execute(
            text("""
            SELECT COUNT(*) FROM (
                SELECT id FROM ai_requests WHERE error_message IS NOT NULL
                UNION ALL
                SELECT id FROM error_logs
            ) e
            """),
        )).scalar()
        bot_id_literal = repr(_bot_id())
        rows = (await session.execute(
            text(f"""SELECT * FROM (
                    SELECT id, started_at AS time, 'error'::text AS level, {bot_id_literal}::text AS bot, error_message AS message,
                           user_id, 1::bigint AS count, 'request'::text AS source, task_type, model
                    FROM ai_requests
                    WHERE error_message IS NOT NULL
                    UNION ALL
                    SELECT id, last_seen AS time, level, bot, message, user_id, count, 'system'::text AS source, NULL::text AS task_type, NULL::text AS model
                    FROM error_logs
                ) e
                ORDER BY {sort_col} {dir_sql}
                LIMIT :limit OFFSET :offset"""),
            params,
        )).mappings().all()
    errors_out = [{"id": r["id"], "time": r["time"], "level": r["level"], "source": r["source"], "bot": r["bot"], "message": r["message"], "user_id": r["user_id"], "task_type": r.get("task_type"), "model": r.get("model"), "count": r["count"] or 1} for r in rows]
    return {"total": total or 0, "errors": errors_out}


async def get_errors_top() -> list:
    async with get_session() as session:
        rows = (await session.execute(
            text("""SELECT id, last_seen AS time, level, bot, message, user_id, count
               FROM error_logs WHERE last_seen >= NOW() - INTERVAL '7 days'
               ORDER BY count DESC LIMIT 5"""),
        )).mappings().all()
    return [{"id": r["id"], "time": r["time"], "level": r["level"], "bot": r["bot"], "message": r["message"], "user_id": r["user_id"], "count": r["count"] or 1} for r in rows]


async def log_admin_audit(
    admin_tg_id: int | None,
    action: str,
    entity_type: str | None,
    entity_id: str | None,
    details: dict | None,
    admin_user_id: int | None = None,
    admin_login: str | None = None,
    admin_role: str | None = None,
):
    async with get_session() as session:
        await session.execute(
            text("""INSERT INTO admin_audit_log (
                   bot_identifier, action, entity_type, entity_id, details,
                   admin_user_id, admin_login, admin_role
               )
               VALUES (:bot_identifier, :action, :entity_type, :entity_id, :details, :admin_user_id, :admin_login, :admin_role)"""),
            {
                "bot_identifier": _bot_id(),
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "details": __import__("json").dumps(details) if details else None,
                "admin_user_id": admin_user_id,
                "admin_login": admin_login,
                "admin_role": admin_role,
            },
        )
