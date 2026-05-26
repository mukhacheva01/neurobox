"""Shared helpers for admin Flask routes."""
from __future__ import annotations

from flask import request

from services.admin.access import current_admin
from shared.config import settings
from shared.domain.admin_runtime import DEFAULT_ADMIN_TEXTS
from shared.domain.credits import DEFAULT_CREDIT_PACKS, UNLIMITED_DAYS


def delta_str(curr, prev):
    """Return a compact percentage delta string."""
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
    if pct < 0:
        return f"{pct:.1f}%"
    return "0%"


def get_period_sql(period):
    """Return (days, interval literal) for supported dashboard periods."""
    if period == "day":
        return 1, "1 day"
    if period == "week":
        return 7, "7 days"
    return 30, "30 days"


def period_days(period: str) -> int:
    if period == "day":
        return 1
    if period == "week":
        return 7
    if period == "month":
        return 30
    return 365


def admin_user_id() -> int | None:
    value = current_admin().get("id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def infra_cost_rub_for_days(days: int) -> float:
    monthly_usd = float(getattr(settings, "infra_monthly_cost_usd", 25.0) or 25.0)
    usd_to_rub = float(getattr(settings, "usd_to_rub", 95.0) or 95.0)
    return round((monthly_usd * usd_to_rub) * (days / 30.0), 2)


def sync_default_content_and_plans(cur, admin_id: int | None = None):
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


def admin_ip() -> str:
    return request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr


USER_SEGMENT_SQL = """
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
