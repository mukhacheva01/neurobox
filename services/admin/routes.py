"""Admin panel routes: dashboard, stats, users, payments, audit and support."""
import csv
import io
import os

from flask import Response, flash, redirect, render_template, request, url_for

from services.admin.access import current_admin
from services.admin.audit import log_action
from services.admin.db import get_conn
from shared.config import settings
from shared.domain.admin_runtime import DEFAULT_ADMIN_TEXTS
from shared.domain.credits import DEFAULT_CREDIT_PACKS, UNLIMITED_DAYS


def _delta_str(curr, prev):
    """Строка изменения: +15% или -8%."""
    if prev is None or prev == 0:
        return ""
    if curr is None:
        curr = 0
    if isinstance(curr, float) or isinstance(prev, float):
        pct = 100 * (curr - prev) / float(prev) if prev else 0
    else:
        pct = 100 * (curr - prev) / prev if prev else 0
    if pct > 0:
        return f"+{pct:.1f}%"
    elif pct < 0:
        return f"{pct:.1f}%"
    return "0%"


def _get_period_sql(period):
    """Возвращает (days, interval) для period: day|week|month."""
    if period == "day":
        return 1, "1 day"
    if period == "week":
        return 7, "7 days"
    return 30, "30 days"


def _period_days(period: str) -> int:
    if period == "day":
        return 1
    if period == "week":
        return 7
    if period == "month":
        return 30
    return 365


def _admin_user_id() -> int | None:
    value = current_admin().get("id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _infra_cost_rub_for_days(days: int) -> float:
    monthly_usd = float(getattr(settings, "infra_monthly_cost_usd", 25.0) or 25.0)
    usd_to_rub = float(getattr(settings, "usd_to_rub", 95.0) or 95.0)
    return round((monthly_usd * usd_to_rub) * (days / 30.0), 2)


def _sync_default_content_and_plans(cur, admin_id: int | None = None):
    for key, meta in DEFAULT_ADMIN_TEXTS.items():
        cur.execute(
            """
            INSERT INTO admin_texts (key, title, description, value, enabled, updated_by)
            VALUES (%s, %s, %s, %s, TRUE, %s)
            ON CONFLICT (key) DO NOTHING
            """,
            (key, meta["title"], meta["description"], meta["value"], admin_id),
        )
    for idx, (plan_key, plan) in enumerate(DEFAULT_CREDIT_PACKS.items(), start=1):
        cur.execute(
            """
            INSERT INTO billing_plans (
                plan_key, label, credits, price_rub, price_stars, price_usd,
                discount, enabled, sort_order, is_one_time, is_unlimited, period_days
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,TRUE,%s,%s,%s,%s)
            ON CONFLICT (plan_key) DO NOTHING
            """,
            (
                plan_key,
                plan.get("label", plan_key),
                int(plan.get("credits", 0) or 0),
                float(plan.get("price_rub", 0) or 0),
                int(plan.get("price_stars", 0) or 0),
                float(plan.get("price_usd", 0) or 0),
                str(plan.get("discount", "") or ""),
                idx,
                bool(plan.get("one_time", False)),
                plan_key == "unlimited",
                UNLIMITED_DAYS if plan_key == "unlimited" else None,
            ),
        )


_USER_SEGMENT_SQL = """
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


def dashboard():
    period = request.args.get("period", "week").strip().lower()
    if period not in ("day", "week", "month"):
        period = "week"
    days, interval = _get_period_sql(period)
    prev_days = days * 2  # предыдущий период такой же длины

    conn = get_conn()
    try:
        cur = conn.cursor()

        # === Пользователи ===
        cur.execute("SELECT COUNT(*) FROM users WHERE created_at >= CURRENT_DATE")
        users_day = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) FROM users WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'")
        users_week = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) FROM users WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'")
        users_month = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) FROM users WHERE created_at >= CURRENT_DATE - INTERVAL '365 days'")
        users_year = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) FROM users")
        users_total = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(DISTINCT user_id) FROM ai_requests WHERE started_at >= NOW() - INTERVAL '1 day'")
        dau = cur.fetchone()["count"] or 0
        cur.execute("SELECT COUNT(DISTINCT user_id) FROM ai_requests WHERE started_at >= NOW() - INTERVAL '7 days'")
        wau = cur.fetchone()["count"] or 0
        cur.execute("SELECT COUNT(DISTINCT user_id) FROM ai_requests WHERE started_at >= NOW() - INTERVAL '30 days'")
        mau = cur.fetchone()["count"] or 0
        stickiness = round(100 * dau / mau, 1) if mau else 0

        cur.execute(
            f"""
            SELECT seg.status, COUNT(*) AS cnt
            FROM (
                SELECT {_USER_SEGMENT_SQL} AS status
                FROM users u
                LEFT JOIN (
                    SELECT user_id, COUNT(*) AS confirmed_count
                    FROM payments
                    WHERE status = 'confirmed'
                    GROUP BY user_id
                ) pay ON pay.user_id = u.id
            ) seg
            GROUP BY seg.status
            """
        )
        segment_counts = {r["status"]: r["cnt"] for r in cur.fetchall()}

        # Пользователи за период и предыдущий (для delta)
        cur.execute("SELECT COUNT(*) FROM users WHERE created_at >= NOW() - (%s * INTERVAL '1 day')", (days,))
        users_period = cur.fetchone()["count"]
        cur.execute(
            "SELECT COUNT(*) FROM users WHERE created_at >= NOW() - (%s * INTERVAL '1 day') "
            "AND created_at < NOW() - (%s * INTERVAL '1 day')",
            (prev_days, days),
        )
        users_prev = cur.fetchone()["count"]
        users_delta = _delta_str(users_period, users_prev)

        # === Оплаты ===
        cur.execute("""
            SELECT COALESCE(SUM(amount_rub), 0) AS s, COUNT(*) AS c
            FROM payments WHERE status = 'confirmed' AND confirmed_at >= CURRENT_DATE
        """)
        r = cur.fetchone()
        pay_day_sum, pay_day_cnt = float(r["s"] or 0), r["c"] or 0
        cur.execute("""
            SELECT COALESCE(SUM(amount_rub), 0) AS s, COUNT(*) AS c
            FROM payments WHERE status = 'confirmed' AND confirmed_at >= CURRENT_DATE - INTERVAL '7 days'
        """)
        r = cur.fetchone()
        pay_week_sum, pay_week_cnt = float(r["s"] or 0), r["c"] or 0
        cur.execute("""
            SELECT COALESCE(SUM(amount_rub), 0) AS s, COUNT(*) AS c
            FROM payments WHERE status = 'confirmed' AND confirmed_at >= CURRENT_DATE - INTERVAL '30 days'
        """)
        r = cur.fetchone()
        pay_month_sum, pay_month_cnt = float(r["s"] or 0), r["c"] or 0
        cur.execute("""
            SELECT COALESCE(SUM(amount_rub), 0) AS s, COUNT(*) AS c
            FROM payments WHERE status = 'confirmed' AND confirmed_at >= CURRENT_DATE - INTERVAL '365 days'
        """)
        r = cur.fetchone()
        pay_year_sum, pay_year_cnt = float(r["s"] or 0), r["c"] or 0
        cur.execute("SELECT COALESCE(SUM(amount_rub), 0) AS s, COUNT(*) AS c FROM payments WHERE status = 'confirmed'")
        r = cur.fetchone()
        pay_total_sum, pay_total_cnt = float(r["s"] or 0), r["c"] or 0

        cur.execute(
            "SELECT COALESCE(SUM(amount_rub), 0) AS s, COUNT(*) AS c "
            "FROM payments WHERE status = 'confirmed' AND confirmed_at >= NOW() - (%s * INTERVAL '1 day')",
            (days,),
        )
        r = cur.fetchone()
        pay_period_sum, pay_period_cnt = float(r["s"] or 0), r["c"] or 0
        cur.execute(
            "SELECT COALESCE(SUM(amount_rub), 0) AS s, COUNT(*) AS c "
            "FROM payments WHERE status = 'confirmed' AND confirmed_at >= NOW() - (%s * INTERVAL '1 day') "
            "AND confirmed_at < NOW() - (%s * INTERVAL '1 day')",
            (prev_days, days),
        )
        r = cur.fetchone()
        pay_prev_sum, pay_prev_cnt = float(r["s"] or 0), r["c"] or 0
        pay_delta_sum = _delta_str(pay_period_sum, pay_prev_sum)
        pay_delta_cnt = _delta_str(pay_period_cnt, pay_prev_cnt)

        cur.execute(
            """
            SELECT provider, COUNT(*) AS cnt, COALESCE(SUM(amount_rub), 0) AS sum_rub
            FROM payments
            WHERE status = 'confirmed' AND confirmed_at >= NOW() - (%s * INTERVAL '1 day')
            GROUP BY provider
            ORDER BY sum_rub DESC, cnt DESC
            """,
            (days,),
        )
        provider_split = [
            {"provider": r["provider"] or "unknown", "count": r["cnt"], "sum_rub": float(r["sum_rub"] or 0)}
            for r in cur.fetchall()
        ]

        # Pending payments
        cur.execute("SELECT COALESCE(SUM(amount_rub), 0) AS s, COUNT(*) AS c FROM payments WHERE status = 'pending'")
        r = cur.fetchone()
        pay_pending_sum, pay_pending_cnt = float(r["s"] or 0), r["c"] or 0

        # Last payments (10)
        cur.execute("""
            SELECT p.id, p.user_id, u.username, u.first_name, p.amount_rub, p.credits_amount, p.pack_name, p.confirmed_at, p.status
            FROM payments p
            LEFT JOIN users u ON p.user_id = u.id
            ORDER BY p.confirmed_at DESC NULLS LAST, p.created_at DESC
            LIMIT 10
        """)
        last_payments = cur.fetchall()

        # ARPU
        cur.execute(
            "SELECT COALESCE(SUM(amount_rub), 0) / NULLIF(COUNT(DISTINCT user_id), 0) AS arpu "
            "FROM payments WHERE status = 'confirmed' AND confirmed_at >= NOW() - (%s * INTERVAL '1 day')",
            (days,),
        )
        arpu_row = cur.fetchone()
        arpu = float(arpu_row["arpu"] or 0) if arpu_row and arpu_row.get("arpu") else 0
        arppu = round(pay_period_sum / pay_period_cnt, 2) if pay_period_cnt else 0

        cur.execute(
            """
            SELECT COALESCE(SUM(cost_usd), 0) AS cost_usd
            FROM ai_requests
            WHERE started_at >= NOW() - (%s * INTERVAL '1 day')
            """,
            (days,),
        )
        ai_cost_usd = float((cur.fetchone() or {}).get("cost_usd") or 0)
        usd_to_rub = float(getattr(settings, "usd_to_rub", 95.0) or 95.0)
        ai_cost_rub = round(ai_cost_usd * usd_to_rub, 2)
        infra_cost_rub = _infra_cost_rub_for_days(days)
        margin_rub = round(pay_period_sum - ai_cost_rub - infra_cost_rub, 2)

        # Conversion: users with at least 1 confirmed payment / total users
        cur.execute("SELECT COUNT(DISTINCT user_id) FROM payments WHERE status = 'confirmed'")
        payers_total = cur.fetchone()["count"] or 0
        conversion = round(100 * payers_total / users_total, 1) if users_total else 0

        # Retention: users who returned 1/3/7 days after registration
        cur.execute("""
            SELECT COUNT(DISTINCT u.id) FROM users u
            WHERE u.created_at <= CURRENT_DATE - INTERVAL '1 day'
            AND EXISTS (SELECT 1 FROM ai_requests ar WHERE ar.user_id = u.id
                AND ar.started_at >= u.created_at + INTERVAL '1 day'
                AND ar.started_at < u.created_at + INTERVAL '2 days')
        """)
        ret_1d = cur.fetchone()["count"] or 0
        cur.execute("""
            SELECT COUNT(DISTINCT u.id) FROM users u
            WHERE u.created_at <= CURRENT_DATE - INTERVAL '3 days'
            AND EXISTS (SELECT 1 FROM ai_requests ar WHERE ar.user_id = u.id
                AND ar.started_at >= u.created_at + INTERVAL '3 days'
                AND ar.started_at < u.created_at + INTERVAL '4 days')
        """)
        ret_3d = cur.fetchone()["count"] or 0
        cur.execute("""
            SELECT COUNT(DISTINCT u.id) FROM users u
            WHERE u.created_at <= CURRENT_DATE - INTERVAL '7 days'
            AND EXISTS (SELECT 1 FROM ai_requests ar WHERE ar.user_id = u.id
                AND ar.started_at >= u.created_at + INTERVAL '7 days')
        """)
        ret_7d = cur.fetchone()["count"] or 0
        cur.execute("SELECT COUNT(*) FROM users WHERE created_at <= CURRENT_DATE - INTERVAL '1 day'")
        base_1d = cur.fetchone()["count"] or 1
        cur.execute("SELECT COUNT(*) FROM users WHERE created_at <= CURRENT_DATE - INTERVAL '3 days'")
        base_3d = cur.fetchone()["count"] or 1
        cur.execute("SELECT COUNT(*) FROM users WHERE created_at <= CURRENT_DATE - INTERVAL '7 days'")
        base_7d = cur.fetchone()["count"] or 1
        retention_1d = round(100 * ret_1d / base_1d, 1)
        retention_3d = round(100 * ret_3d / base_3d, 1)
        retention_7d = round(100 * ret_7d / base_7d, 1)

        # Активность по часам
        def activity_by_hour(interval_days):
            cur.execute("""
                SELECT EXTRACT(HOUR FROM (started_at AT TIME ZONE 'Europe/Moscow'))::int AS hour, COUNT(*) AS cnt
                FROM ai_requests
                WHERE started_at >= NOW() - (%s || ' days')::INTERVAL
                GROUP BY EXTRACT(HOUR FROM (started_at AT TIME ZONE 'Europe/Moscow'))
                ORDER BY hour
            """, (interval_days,))
            rows = {r["hour"]: r["cnt"] for r in cur.fetchall()}
            return [{"hour": h, "cnt": rows.get(h, 0)} for h in range(24)]

        activity_day = activity_by_hour(1)
        activity_week = activity_by_hour(7)
        activity_month = activity_by_hour(30)
        max_day = max((x["cnt"] for x in activity_day), default=1)
        max_week = max((x["cnt"] for x in activity_week), default=1)
        max_month = max((x["cnt"] for x in activity_month), default=1)

        # Генерации
        cur.execute("SELECT COUNT(*) FROM ai_requests WHERE started_at >= CURRENT_DATE")
        gen_day = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) FROM ai_requests WHERE started_at >= CURRENT_DATE - INTERVAL '7 days'")
        gen_week = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) FROM ai_requests WHERE started_at >= CURRENT_DATE - INTERVAL '30 days'")
        gen_month = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) FROM ai_requests WHERE started_at >= CURRENT_DATE - INTERVAL '365 days'")
        gen_year = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) FROM ai_requests")
        gen_total = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) FROM ai_requests WHERE started_at >= NOW() - (%s * INTERVAL '1 day')", (days,))
        gen_period = cur.fetchone()["count"]
        cur.execute(
            "SELECT COUNT(*) FROM ai_requests WHERE started_at >= NOW() - (%s * INTERVAL '1 day') "
            "AND started_at < NOW() - (%s * INTERVAL '1 day')",
            (prev_days, days),
        )
        gen_prev = cur.fetchone()["count"]
        gen_delta = _delta_str(gen_period, gen_prev)

        cur.execute("SELECT COUNT(DISTINCT user_id) FROM ai_requests WHERE started_at >= CURRENT_DATE")
        active_today = cur.fetchone()["count"]

        cur.execute(
            """
            SELECT CASE WHEN referred_by IS NOT NULL THEN 'referral' ELSE 'organic' END AS source,
                   COUNT(*) AS cnt
            FROM users
            WHERE created_at >= NOW() - (%s * INTERVAL '1 day')
            GROUP BY 1
            ORDER BY cnt DESC, source ASC
            LIMIT 8
            """,
            (days,),
        )
        top_sources = [
            {"source": r["source"] or "unknown", "count": r["cnt"]}
            for r in cur.fetchall()
        ]

        # Оценки
        ratings_day_up = ratings_day_down = ratings_week_up = ratings_week_down = ratings_month_up = ratings_month_down = 0
        try:
            cur.execute("SELECT rating, COUNT(*) AS c FROM response_ratings WHERE created_at >= CURRENT_DATE GROUP BY rating")
            rday = {r["rating"]: r["c"] for r in cur.fetchall()}
            ratings_day_up = rday.get("up", 0)
            ratings_day_down = rday.get("down", 0)
            cur.execute("SELECT rating, COUNT(*) AS c FROM response_ratings WHERE created_at >= CURRENT_DATE - INTERVAL '7 days' GROUP BY rating")
            rweek = {r["rating"]: r["c"] for r in cur.fetchall()}
            ratings_week_up = rweek.get("up", 0)
            ratings_week_down = rweek.get("down", 0)
            cur.execute("SELECT rating, COUNT(*) AS c FROM response_ratings WHERE created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY rating")
            rmonth = {r["rating"]: r["c"] for r in cur.fetchall()}
            ratings_month_up = rmonth.get("up", 0)
            ratings_month_down = rmonth.get("down", 0)
        except Exception:
            pass

        # Генерации по типу и по модели
        cur.execute("SELECT task_type, COUNT(*) AS cnt FROM ai_requests GROUP BY task_type ORDER BY cnt DESC")
        requests_by_type = [{"task_type": r["task_type"], "cnt": r["cnt"]} for r in cur.fetchall()]
        cur.execute("SELECT model, COUNT(*) AS cnt FROM ai_requests GROUP BY model ORDER BY cnt DESC LIMIT 15")
        requests_by_model = [{"model": r["model"], "cnt": r["cnt"]} for r in cur.fetchall()]

        # Среднее время генерации (duration_ms)
        cur.execute("""
            SELECT task_type, ROUND(AVG(duration_ms)::numeric) AS avg_ms
            FROM ai_requests WHERE duration_ms IS NOT NULL AND duration_ms > 0
            GROUP BY task_type ORDER BY avg_ms DESC NULLS LAST
        """)
        avg_gen_time = [{"task_type": r["task_type"], "avg_ms": int(r["avg_ms"] or 0)} for r in cur.fetchall()]

        # Ошибки
        cur.execute("SELECT COUNT(*) FROM ai_requests WHERE started_at >= CURRENT_DATE - INTERVAL '7 days' AND error_message IS NOT NULL")
        errors_week = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) FROM ai_requests WHERE started_at >= CURRENT_DATE - INTERVAL '7 days'")
        total_week = cur.fetchone()["count"] or 1
        errors_week_pct = round(100 * errors_week / total_week, 1)

        cur.execute("""
            SELECT LEFT(error_message, 120) AS err, COUNT(*) AS cnt
            FROM ai_requests WHERE error_message IS NOT NULL AND started_at >= NOW() - INTERVAL '7 days'
            GROUP BY LEFT(error_message, 120) ORDER BY cnt DESC LIMIT 8
        """)
        top_errors = [{"err": r["err"], "cnt": r["cnt"]} for r in cur.fetchall()]

        cur.execute("SELECT COUNT(*) FROM users WHERE is_blocked = TRUE")
        banned_total = cur.fetchone()["count"]

        # Промокоды
        promo_uses_cnt = promo_codes_cnt = 0
        try:
            cur.execute("SELECT COUNT(*) FROM promo_uses WHERE used_at >= NOW() - INTERVAL '30 days'")
            promo_uses_cnt = cur.fetchone()["count"] or 0
            cur.execute("SELECT COUNT(*) FROM promocodes")
            promo_codes_cnt = cur.fetchone()["count"] or 0
        except Exception:
            pass

        # Рефералы
        cur.execute("SELECT COUNT(*) FROM users WHERE referred_by IS NOT NULL")
        referred_total = cur.fetchone()["count"] or 0
        cur.execute("""
            SELECT COUNT(DISTINCT u.id) FROM users u
            JOIN payments p ON p.user_id = u.id
            WHERE u.referred_by IS NOT NULL AND p.status = 'confirmed'
        """)
        referred_paid = cur.fetchone()["count"] or 0

        # Тренды по дням (14 дней)
        cur.execute("""
            SELECT date_trunc('day', created_at)::date AS d, COUNT(*) AS cnt
            FROM users WHERE created_at >= CURRENT_DATE - INTERVAL '14 days'
            GROUP BY date_trunc('day', created_at) ORDER BY d
        """)
        users_trend = {str(r["d"]): r["cnt"] for r in cur.fetchall()}
        cur.execute("""
            SELECT date_trunc('day', confirmed_at)::date AS d, COUNT(*) AS cnt, COALESCE(SUM(amount_rub), 0) AS s
            FROM payments WHERE status = 'confirmed' AND confirmed_at >= CURRENT_DATE - INTERVAL '14 days'
            GROUP BY date_trunc('day', confirmed_at) ORDER BY d
        """)
        pay_trend = {str(r["d"]): {"cnt": r["cnt"], "sum": float(r["s"] or 0)} for r in cur.fetchall()}
        cur.execute("""
            SELECT date_trunc('day', started_at)::date AS d, COUNT(*) AS cnt
            FROM ai_requests WHERE started_at >= CURRENT_DATE - INTERVAL '14 days'
            GROUP BY date_trunc('day', started_at) ORDER BY d
        """)
        gen_trend = {str(r["d"]): r["cnt"] for r in cur.fetchall()}

        from datetime import date, timedelta
        dates_14 = [(date.today() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(13, -1, -1)]
        trends = [{
            "day": d,
            "users": users_trend.get(d, 0),
            "pay_cnt": pay_trend.get(d, {}).get("cnt", 0),
            "pay_sum": pay_trend.get(d, {}).get("sum", 0),
            "gen": gen_trend.get(d, 0),
        } for d in dates_14]
        max_trend_users = max((t["users"] for t in trends), default=1) or 1
        max_trend_pay = max((t["pay_sum"] for t in trends), default=1) or 1
        max_trend_gen = max((t["gen"] for t in trends), default=1) or 1

        # Алерты
        alerts = []
        if errors_week_pct > 15 and total_week > 10:
            alerts.append({"type": "danger", "msg": f"Высокий % ошибок: {errors_week_pct}% за неделю"})
        if pay_pending_cnt > 5:
            alerts.append({"type": "warn", "msg": f"Ожидают оплаты: {pay_pending_cnt} платежей на {pay_pending_sum:.0f} ₽"})

        return render_template(
            "dashboard.html",
            period=period,
            users_day=users_day, users_week=users_week, users_month=users_month, users_year=users_year, users_total=users_total,
            users_delta=users_delta, users_period=users_period,
            pay_day_sum=pay_day_sum, pay_day_cnt=pay_day_cnt,
            pay_week_sum=pay_week_sum, pay_week_cnt=pay_week_cnt,
            pay_month_sum=pay_month_sum, pay_month_cnt=pay_month_cnt,
            pay_year_sum=pay_year_sum, pay_year_cnt=pay_year_cnt,
            pay_total_sum=pay_total_sum, pay_total_cnt=pay_total_cnt,
            pay_period_sum=pay_period_sum, pay_period_cnt=pay_period_cnt,
            pay_delta_sum=pay_delta_sum, pay_delta_cnt=pay_delta_cnt,
            pay_pending_sum=pay_pending_sum, pay_pending_cnt=pay_pending_cnt,
            provider_split=provider_split,
            last_payments=last_payments,
            arpu=arpu, arppu=arppu, conversion=conversion,
            dau=dau, wau=wau, mau=mau, stickiness=stickiness,
            segment_counts=segment_counts,
            ai_cost_usd=ai_cost_usd, ai_cost_rub=ai_cost_rub, infra_cost_rub=infra_cost_rub, margin_rub=margin_rub,
            retention_1d=retention_1d, retention_3d=retention_3d, retention_7d=retention_7d,
            activity_day=activity_day, activity_week=activity_week, activity_month=activity_month,
            max_day=max_day, max_week=max_week, max_month=max_month,
            gen_day=gen_day, gen_week=gen_week, gen_month=gen_month, gen_year=gen_year, gen_total=gen_total,
            gen_delta=gen_delta, gen_period=gen_period,
            active_today=active_today,
            ratings_day_up=ratings_day_up, ratings_day_down=ratings_day_down,
            ratings_week_up=ratings_week_up, ratings_week_down=ratings_week_down,
            ratings_month_up=ratings_month_up, ratings_month_down=ratings_month_down,
            requests_by_type=requests_by_type, requests_by_model=requests_by_model,
            avg_gen_time=avg_gen_time,
            errors_week=errors_week, errors_week_pct=errors_week_pct,
            top_errors=top_errors, banned_total=banned_total,
            promo_uses_cnt=promo_uses_cnt, promo_codes_cnt=promo_codes_cnt,
            referred_total=referred_total, referred_paid=referred_paid,
            top_sources=top_sources,
            trends=trends, max_trend_users=max_trend_users, max_trend_pay=max_trend_pay, max_trend_gen=max_trend_gen,
            alerts=alerts,
        )
    finally:
        conn.close()


def payments_list():
    status_filter = request.args.get("status", "").strip()
    provider_filter = request.args.get("provider", "").strip()
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    per_page = 30
    offset = (page - 1) * per_page

    conn = get_conn()
    try:
        cur = conn.cursor()
        params = []
        where = "1=1"
        if status_filter:
            where += " AND p.status = %s"
            params.append(status_filter)
        if provider_filter:
            where += " AND p.provider = %s"
            params.append(provider_filter)
        cur.execute(f"SELECT COUNT(*) FROM payments p WHERE {where}", params)
        total = cur.fetchone()["count"]
        cur.execute(
            f"""
            SELECT
                COALESCE(SUM(CASE WHEN p.status = 'confirmed' THEN p.amount_rub ELSE 0 END), 0) AS revenue_confirmed,
                COALESCE(SUM(CASE WHEN p.status = 'refunded' THEN p.amount_rub ELSE 0 END), 0) AS refunds_sum,
                COUNT(*) FILTER (WHERE p.status = 'refunded') AS refunds_cnt
            FROM payments p
            WHERE {where}
            """,
            params,
        )
        summary = cur.fetchone() or {}
        revenue_confirmed = float(summary.get("revenue_confirmed") or 0)
        refunds_sum = float(summary.get("refunds_sum") or 0)
        refunds_cnt = int(summary.get("refunds_cnt") or 0)
        avg_check = round(revenue_confirmed / max(1, len([1 for _ in []])), 2)
        cur.execute(
            f"SELECT COUNT(*) AS cnt FROM payments p WHERE {where} AND p.status = 'confirmed'",
            params,
        )
        confirmed_cnt = cur.fetchone()["cnt"] or 0
        avg_check = round(revenue_confirmed / confirmed_cnt, 2) if confirmed_cnt else 0
        cur.execute(
            f"""
            SELECT p.provider, COUNT(*) AS cnt, COALESCE(SUM(CASE WHEN p.status = 'confirmed' THEN p.amount_rub ELSE 0 END), 0) AS sum_rub
            FROM payments p
            WHERE {where}
            GROUP BY p.provider
            ORDER BY sum_rub DESC, cnt DESC
            """,
            params,
        )
        providers = cur.fetchall()
        cur.execute(f"""
            SELECT p.id, p.user_id, u.username, u.first_name, p.amount_rub, p.credits_amount, p.pack_name, p.status, p.provider,
                   p.created_at, p.confirmed_at, p.payment_id, p.promo_code
            FROM payments p
            LEFT JOIN users u ON p.user_id = u.id
            WHERE {where}
            ORDER BY p.created_at DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])
        rows = cur.fetchall()
        return render_template(
            "payments.html",
            payments=rows,
            total=total,
            page=page,
            per_page=per_page,
            status_filter=status_filter,
            provider_filter=provider_filter,
            revenue_confirmed=revenue_confirmed,
            avg_check=avg_check,
            refunds_sum=refunds_sum,
            refunds_cnt=refunds_cnt,
            confirmed_cnt=confirmed_cnt,
            providers=providers,
        )
    finally:
        conn.close()


def payments_export():
    status_filter = request.args.get("status", "").strip()
    provider_filter = request.args.get("provider", "").strip()
    conn = get_conn()
    try:
        cur = conn.cursor()
        where = "1=1"
        params = []
        if status_filter:
            where += " AND p.status = %s"
            params.append(status_filter)
        if provider_filter:
            where += " AND p.provider = %s"
            params.append(provider_filter)
        cur.execute(f"""
            SELECT p.id, p.user_id, u.username, u.first_name, p.amount_rub, p.credits_amount, p.pack_name, p.status, p.provider, p.promo_code, p.created_at, p.confirmed_at, p.payment_id
            FROM payments p
            LEFT JOIN users u ON p.user_id = u.id
            WHERE {where}
            ORDER BY p.created_at DESC
        """, params)
        rows = cur.fetchall()
        output = io.StringIO()
        w = csv.writer(output)
        w.writerow(["id", "user_id", "username", "first_name", "amount_rub", "credits_amount", "pack_name", "status", "provider", "promo_code", "created_at", "confirmed_at", "payment_id"])
        for r in rows:
            w.writerow([r.get("id"), r.get("user_id"), r.get("username") or "", r.get("first_name") or "", r.get("amount_rub"), r.get("credits_amount"), r.get("pack_name") or "", r.get("status"), r.get("provider") or "", r.get("promo_code") or "", r.get("created_at"), r.get("confirmed_at"), r.get("payment_id") or ""])
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=payments.csv"})
    finally:
        conn.close()


def errors_page():
    user_filter = request.args.get("user_id", "").strip()
    sort_by = request.args.get("sort", "date")
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    per_page = 50
    offset = (page - 1) * per_page

    conn = get_conn()
    try:
        cur = conn.cursor()
        params = []
        where_clauses = ["e.message IS NOT NULL"]
        if user_filter:
            if user_filter.isdigit():
                where_clauses.append("e.user_id = %s")
                params.append(int(user_filter))
            else:
                where_clauses.append("(u.username ILIKE %s OR u.first_name ILIKE %s)")
                params.extend([f"%{user_filter}%", f"%{user_filter}%"])
        where_sql = " AND ".join(where_clauses)
        order_sql = "e.time DESC" if sort_by == "date" else "u.username NULLS LAST, e.time DESC"
        base_sql = f"""
            FROM (
                SELECT id, user_id, task_type, model, error_message AS message, started_at AS time, 'request' AS source
                FROM ai_requests
                WHERE error_message IS NOT NULL
                UNION ALL
                SELECT id, user_id, NULL AS task_type, NULL AS model, message, last_seen AS time, 'system' AS source
                FROM error_logs
            ) e
            LEFT JOIN users u ON e.user_id = u.id
            WHERE {where_sql}
        """
        cur.execute(f"SELECT COUNT(*) FROM ({'SELECT 1 ' + base_sql}) q", params)
        total = cur.fetchone()["count"]
        cur.execute(f"""
            SELECT e.id, e.user_id, u.username, u.first_name, e.task_type, e.message AS error_message, e.time AS started_at, e.model, e.source
            {base_sql}
            ORDER BY {order_sql}
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])
        rows = cur.fetchall()
        return render_template("errors.html", errors=rows, total=total, page=page, per_page=per_page, user_filter=user_filter, sort_by=sort_by)
    finally:
        conn.close()


def errors_export():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT e.id, e.user_id, u.username, u.first_name, e.task_type, e.message AS error_message, e.time AS started_at, e.model, e.source
            FROM (
                SELECT id, user_id, task_type, model, error_message AS message, started_at AS time, 'request' AS source
                FROM ai_requests WHERE error_message IS NOT NULL
                UNION ALL
                SELECT id, user_id, NULL AS task_type, NULL AS model, message, last_seen AS time, 'system' AS source
                FROM error_logs
            ) e
            LEFT JOIN users u ON e.user_id = u.id
            ORDER BY e.time DESC
            LIMIT 5000
        """)
        rows = cur.fetchall()
        output = io.StringIO()
        w = csv.writer(output)
        w.writerow(["id", "user_id", "username", "first_name", "task_type", "error_message", "started_at", "model", "source"])
        for r in rows:
            w.writerow([r.get("id"), r.get("user_id"), r.get("username") or "", r.get("first_name") or "", r.get("task_type"), (r.get("error_message") or "")[:500], r.get("started_at"), r.get("model"), r.get("source")])
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=errors.csv"})
    finally:
        conn.close()


def stats_page():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT date_trunc('day', created_at)::date AS day, COUNT(*) AS cnt
            FROM users WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY date_trunc('day', created_at) ORDER BY day
        """)
        users_by_day = [{"day": str(r["day"]), "cnt": r["cnt"]} for r in cur.fetchall()]
        cur.execute("""
            SELECT date_trunc('day', confirmed_at)::date AS day, COUNT(*) AS cnt, COALESCE(SUM(amount_rub), 0) AS sum_rub
            FROM payments WHERE status = 'confirmed' AND confirmed_at >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY date_trunc('day', confirmed_at) ORDER BY day
        """)
        payments_by_day = [{"day": str(r["day"]), "cnt": r["cnt"], "sum_rub": float(r["sum_rub"] or 0)} for r in cur.fetchall()]
        cur.execute("SELECT task_type, COUNT(*) AS cnt FROM ai_requests GROUP BY task_type ORDER BY cnt DESC")
        requests_by_type = [{"task_type": r["task_type"], "cnt": r["cnt"]} for r in cur.fetchall()]
        cur.execute("SELECT COUNT(DISTINCT user_id) FROM ai_requests WHERE started_at >= CURRENT_DATE")
        active_today = cur.fetchone()["count"] or 0
        cur.execute("SELECT COUNT(*) FROM ai_requests WHERE started_at >= CURRENT_DATE")
        gen_today = cur.fetchone()["count"] or 0
        return render_template("stats.html", users_by_day=users_by_day, payments_by_day=payments_by_day, requests_by_type=requests_by_type, active_today=active_today, gen_today=gen_today)
    finally:
        conn.close()


def users_list():
    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip()
    sort = (request.args.get("sort") or "created_at").strip()
    direction = "DESC" if (request.args.get("dir") or "desc").strip().lower() != "asc" else "ASC"
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    per_page = 25
    offset = (page - 1) * per_page
    conn = get_conn()
    try:
        cur = conn.cursor()
        where = []
        params = []
        if q:
            if q.isdigit():
                where.append("(u.id = %s OR u.username ILIKE %s OR u.first_name ILIKE %s)")
                params.extend((int(q), f"%{q}%", f"%{q}%"))
            else:
                where.append("(u.username ILIKE %s OR u.first_name ILIKE %s)")
                params.extend((f"%{q}%", f"%{q}%"))
        if status:
            where.append(f"{_USER_SEGMENT_SQL} = %s")
            params.append(status)
        where_sql = " AND ".join(where) if where else "TRUE"
        sort_map = {
            "created_at": "u.created_at",
            "last_active_at": "u.last_active_at",
            "ltv": "u.total_payments_rub",
            "username": "u.username",
            "status": "segment",
        }
        sort_sql = sort_map.get(sort, "u.created_at")
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
        cur.execute(f"SELECT COUNT(*) AS count {base_sql}", params)
        total = cur.fetchone()["count"]
        cur.execute(
            f"""
            SELECT u.id, u.username, u.first_name, u.credits_bought, u.credits_free_today,
                   u.created_at, u.is_blocked, u.total_payments_rub, u.unlimited_ends_at,
                   u.trial_started_at, u.full_access_48h_ends_at, u.referral_count,
                   u.last_active_at,
                   {_USER_SEGMENT_SQL} AS segment
            {base_sql}
            ORDER BY {sort_sql} {direction} NULLS LAST
            LIMIT %s OFFSET %s
            """,
            params + [per_page, offset],
        )
        rows = cur.fetchall()
        return render_template(
            "users.html",
            users=rows,
            total=total,
            page=page,
            per_page=per_page,
            q=q,
            status_filter=status,
            sort=sort,
            direction=direction.lower(),
        )
    finally:
        conn.close()


def users_export():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT u.id, u.username, u.first_name, u.credits_bought, u.credits_free_today,
                   u.created_at, u.is_blocked, u.total_payments_rub, u.last_active_at,
                   CASE WHEN u.referred_by IS NOT NULL THEN 'referral' ELSE 'organic' END AS source,
                   {_USER_SEGMENT_SQL} AS segment
            FROM users u
            LEFT JOIN (
                SELECT user_id, COUNT(*) AS confirmed_count
                FROM payments
                WHERE status = 'confirmed'
                GROUP BY user_id
            ) pay ON pay.user_id = u.id
            ORDER BY u.created_at DESC
            LIMIT 10000
            """
        )
        rows = cur.fetchall()
        output = io.StringIO()
        w = csv.writer(output)
        w.writerow(["id", "username", "first_name", "credits_bought", "credits_free_today", "created_at", "is_blocked", "segment", "ltv", "last_active_at", "source"])
        for r in rows:
            w.writerow([r.get("id"), r.get("username") or "", r.get("first_name") or "", r.get("credits_bought"), r.get("credits_free_today"), r.get("created_at"), r.get("is_blocked"), r.get("segment"), r.get("total_payments_rub"), r.get("last_active_at"), r.get("source") or ""])
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=users.csv"})
    finally:
        conn.close()


def user_detail(user_id):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        if not user:
            return "User not found", 404
        cur.execute(
            """
            SELECT id, amount_rub, credits_amount, status, provider, promo_code, created_at, confirmed_at
            FROM payments
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (user_id,),
        )
        payments = cur.fetchall()
        cur.execute("SELECT amount, type, description, created_at FROM credit_transactions WHERE user_id = %s ORDER BY created_at DESC LIMIT 20", (user_id,))
        transactions = cur.fetchall()
        cur.execute("SELECT note, created_at FROM user_notes WHERE user_id = %s ORDER BY created_at DESC LIMIT 10", (user_id,))
        notes = cur.fetchall()
        cur.execute(
            """
            SELECT role, content, created_at
            FROM chat_messages
            WHERE user_id = %s
            ORDER BY id DESC
            LIMIT 20
            """,
            (user_id,),
        )
        messages = list(reversed(cur.fetchall()))
        cur.execute(
            """
            SELECT id, text, status, admin_note, created_at, updated_at
            FROM feedback
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (user_id,),
        )
        feedback_rows = cur.fetchall()
        return render_template(
            "user_detail.html",
            user=dict(user),
            payments=payments,
            transactions=transactions,
            notes=notes,
            messages=messages,
            feedback_rows=feedback_rows,
        )
    finally:
        conn.close()


def audit_log():
    action_filter = (request.args.get("action") or "").strip()
    entity_filter = (request.args.get("entity_type") or "").strip()
    conn = get_conn()
    try:
        cur = conn.cursor()
        where = ["1=1"]
        params = []
        if action_filter:
            where.append("action = %s")
            params.append(action_filter)
        if entity_filter:
            where.append("details ->> 'entity_type' = %s")
            params.append(entity_filter)
        where_sql = " AND ".join(where)
        cur.execute(
            f"""
            SELECT id, action, admin_user, target, details, created_at
            FROM admin_audit_log
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT 300
            """,
            params,
        )
        raw_rows = cur.fetchall()
        rows = []
        for row in raw_rows:
            details = row.get("details") if isinstance(row.get("details"), dict) else {}
            target = row.get("target")
            entity_type_value = details.get("entity_type")
            entity_id_value = details.get("entity_id")
            if not entity_type_value and isinstance(target, str) and ":" in target:
                entity_type_value, entity_id_value = target.split(":", 1)
            elif not entity_id_value:
                entity_id_value = target
            rows.append(
                {
                    "id": row.get("id"),
                    "action": row.get("action"),
                    "entity_type": entity_type_value,
                    "entity_id": entity_id_value,
                    "ip": details.get("ip"),
                    "created_at": row.get("created_at"),
                    "admin_login": row.get("admin_user"),
                    "admin_role": details.get("admin_role"),
                    "details": details or None,
                }
            )
        return render_template("audit.html", rows=rows, action_filter=action_filter, entity_filter=entity_filter)
    finally:
        conn.close()


def feedback_list():
    status_filter = (request.args.get("status") or "").strip()
    conn = get_conn()
    try:
        cur = conn.cursor()
        where = "1=1"
        params = []
        if status_filter:
            where += " AND f.status = %s"
            params.append(status_filter)
        cur.execute(
            f"""
            SELECT f.id, f.user_id, f.text, f.status, f.admin_note, f.created_at, f.updated_at, f.resolved_at,
                   u.username, u.first_name
            FROM feedback f
            LEFT JOIN users u ON u.id = f.user_id
            WHERE {where}
            ORDER BY CASE f.status WHEN 'new' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END, f.created_at DESC
            LIMIT 300
            """,
            params,
        )
        rows = cur.fetchall()
        return render_template("feedback.html", rows=rows, status_filter=status_filter)
    finally:
        conn.close()


def feedback_action(feedback_id: int):
    action = (request.form.get("action") or "").strip()
    admin_note = (request.form.get("admin_note") or "").strip()[:2000]
    status = (request.form.get("status") or "").strip()
    allowed = {"new", "in_progress", "resolved", "closed"}
    conn = get_conn()
    try:
        cur = conn.cursor()
        if action == "update":
            if status not in allowed:
                flash("Неверный статус", "error")
                return redirect(url_for("feedback_list"))
            resolved_at = "NOW()" if status in {"resolved", "closed"} else "NULL"
            cur.execute(
                f"""
                UPDATE feedback
                SET status = %s,
                    admin_note = %s,
                    handled_by = %s,
                    updated_at = NOW(),
                    resolved_at = {resolved_at}
                WHERE id = %s
                """,
                (status, admin_note or None, _admin_user_id(), feedback_id),
            )
            conn.commit()
            log_action("feedback_update", entity_type="feedback", entity_id=feedback_id, details={"status": status}, ip=_admin_ip())
            flash("Обращение обновлено")
    finally:
        conn.close()
    return redirect(request.referrer or url_for("feedback_list"))


def content_texts():
    conn = get_conn()
    try:
        cur = conn.cursor()
        _sync_default_content_and_plans(cur, _admin_user_id())
        if request.method == "POST":
            key = (request.form.get("key") or "").strip()
            value = (request.form.get("value") or "").strip()
            title = (request.form.get("title") or "").strip()
            description = (request.form.get("description") or "").strip()
            enabled = request.form.get("enabled") == "on"
            if key and value:
                cur.execute(
                    """
                    INSERT INTO admin_texts (key, title, description, value, enabled, updated_by, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (key) DO UPDATE SET
                        title = EXCLUDED.title,
                        description = EXCLUDED.description,
                        value = EXCLUDED.value,
                        enabled = EXCLUDED.enabled,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = NOW()
                    """,
                    (key, title or key, description or None, value, enabled, _admin_user_id()),
                )
                conn.commit()
                log_action("content_update", entity_type="admin_text", entity_id=key, ip=_admin_ip())
                flash("Текст обновлён")
        cur.execute("SELECT key, title, description, value, enabled, updated_at FROM admin_texts ORDER BY key ASC")
        rows = cur.fetchall()
        return render_template("content.html", rows=rows)
    finally:
        conn.close()


def tariffs_list():
    conn = get_conn()
    try:
        cur = conn.cursor()
        _sync_default_content_and_plans(cur, _admin_user_id())
        if request.method == "POST":
            plan_key = (request.form.get("plan_key") or "").strip()
            if plan_key:
                cur.execute(
                    """
                    UPDATE billing_plans
                    SET label = %s,
                        credits = %s,
                        price_rub = %s,
                        price_stars = %s,
                        price_usd = %s,
                        discount = %s,
                        enabled = %s,
                        sort_order = %s,
                        is_one_time = %s,
                        period_days = %s,
                        updated_at = NOW()
                    WHERE plan_key = %s
                    """,
                    (
                        (request.form.get("label") or "").strip() or plan_key,
                        int(request.form.get("credits") or 0),
                        float(request.form.get("price_rub") or 0),
                        int(request.form.get("price_stars") or 0),
                        float(request.form.get("price_usd") or 0),
                        (request.form.get("discount") or "").strip(),
                        request.form.get("enabled") == "on",
                        int(request.form.get("sort_order") or 100),
                        request.form.get("is_one_time") == "on",
                        int(request.form.get("period_days") or 0) or None,
                        plan_key,
                    ),
                )
                conn.commit()
                log_action("tariff_update", entity_type="billing_plan", entity_id=plan_key, ip=_admin_ip())
                flash("Тариф обновлён")
        cur.execute(
            """
            SELECT plan_key, label, credits, price_rub, price_stars, price_usd, discount,
                   enabled, sort_order, is_one_time, is_unlimited, period_days, updated_at
            FROM billing_plans
            ORDER BY sort_order ASC, plan_key ASC
            """
        )
        rows = cur.fetchall()
        return render_template("tariffs.html", rows=rows)
    finally:
        conn.close()


def _admin_ip():
    return request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr


def user_action(user_id):
    action = request.form.get("action")
    conn = get_conn()
    try:
        cur = conn.cursor()
        if action == "ban":
            cur.execute("UPDATE users SET is_blocked = TRUE WHERE id = %s", (user_id,))
            conn.commit()
            log_action("user_block", entity_id=user_id, ip=_admin_ip())
            flash("Пользователь заблокирован")
        elif action == "unban":
            cur.execute("UPDATE users SET is_blocked = FALSE WHERE id = %s", (user_id,))
            conn.commit()
            log_action("user_unblock", entity_id=user_id, ip=_admin_ip())
            flash("Пользователь разблокирован")
        elif action == "add_credits":
            amount = request.form.get("amount")
            try:
                amount = int(amount)
                if amount > 0:
                    cur.execute("UPDATE users SET credits_bought = COALESCE(credits_bought, 0) + %s WHERE id = %s", (amount, user_id))
                    cur.execute(
                        "INSERT INTO credit_transactions (user_id, amount, credits_bought_after, credits_free_after, type, description) SELECT %s, %s, credits_bought, credits_free_today, 'admin_add', 'Начислено из веб-админки' FROM users WHERE id = %s",
                        (user_id, amount, user_id),
                    )
                    conn.commit()
                    log_action("credits_add", entity_id=user_id, details={"amount": amount}, ip=_admin_ip())
                    flash(f"Начислено {amount} CR")
            except (ValueError, TypeError):
                flash("Неверное количество", "error")
        elif action == "sub_credits":
            amount = request.form.get("amount")
            try:
                amount = int(amount)
                if amount > 0:
                    cur.execute("SELECT credits_bought FROM users WHERE id = %s", (user_id,))
                    row = cur.fetchone()
                    new_bought = max(0, (row["credits_bought"] or 0) - amount)
                    cur.execute("UPDATE users SET credits_bought = %s WHERE id = %s", (new_bought, user_id))
                    cur.execute(
                        "INSERT INTO credit_transactions (user_id, amount, credits_bought_after, credits_free_after, type, description) SELECT %s, %s, %s, credits_free_today, 'admin_sub', 'Списано из веб-админки' FROM users WHERE id = %s",
                        (user_id, -amount, new_bought, user_id),
                    )
                    conn.commit()
                    log_action("credits_sub", entity_id=user_id, details={"amount": amount}, ip=_admin_ip())
                    flash(f"Списано {amount} CR")
            except (ValueError, TypeError):
                flash("Неверное количество", "error")
        elif action == "set_unlimited":
            days = request.form.get("days")
            try:
                days = int(days or 0)
                if days > 0:
                    cur.execute("UPDATE users SET unlimited_ends_at = NOW() + (%s || ' days')::INTERVAL WHERE id = %s", (days, user_id))
                    conn.commit()
                    log_action("unlimited_set", entity_id=user_id, details={"days": days}, ip=_admin_ip())
                    flash(f"Безлимит на {days} дн.")
            except (ValueError, TypeError):
                flash("Укажите число дней", "error")
        elif action == "remove_unlimited":
            cur.execute("UPDATE users SET unlimited_ends_at = NULL WHERE id = %s", (user_id,))
            conn.commit()
            log_action("unlimited_remove", entity_id=user_id, ip=_admin_ip())
            flash("Безлимит отключён")
        elif action == "note":
            note = (request.form.get("note") or "").strip()[:1000]
            if note:
                admin_id = int(os.environ.get("ADMIN_PANEL_NOTE_AS_USER_ID", "0"))
                try:
                    cur.execute("INSERT INTO user_notes (user_id, admin_id, note) VALUES (%s, %s, %s)", (user_id, admin_id, note))
                    conn.commit()
                    log_action("note_add", entity_id=user_id, details={"len": len(note)}, ip=_admin_ip())
                    flash("Заметка добавлена")
                except Exception:
                    flash("Не удалось сохранить заметку", "error")
    finally:
        conn.close()
    return redirect(request.referrer or url_for("user_detail", user_id=user_id))
