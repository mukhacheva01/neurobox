"""Worker job: KPI alerts (errors, revenue drop, 402, cost-per-paid-user, funnel drop)."""
import json
from typing import Any

import structlog
from sqlalchemy import text

log = structlog.get_logger()


def _pct(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return round(100.0 * float(part) / float(whole), 1)


async def _compute_funnel_window(session, window_hours: int, offset_hours: int = 0) -> dict[str, Any]:
    """KPI funnel for a sliding window."""
    start_offset_hours = int(window_hours) + int(offset_hours)
    end_offset_hours = int(offset_hours)

    result = await session.execute(
        text(
            """
            WITH
            starts AS (
                SELECT DISTINCT user_id
                FROM events
                WHERE event_name = 'bot_start'
                  AND created_at >= NOW() - (:p1::int * INTERVAL '1 hour')
                  AND created_at <  NOW() - (:p2::int * INTERVAL '1 hour')
            ),
            first_gen AS (
                SELECT DISTINCT user_id
                FROM events
                WHERE event_name IN ('message_sent', 'image_generated', 'video_generated', 'music_generated')
                  AND created_at >= NOW() - (:p1::int * INTERVAL '1 hour')
                  AND created_at <  NOW() - (:p2::int * INTERVAL '1 hour')
            ),
            paywall AS (
                SELECT DISTINCT user_id
                FROM events
                WHERE event_name = 'paywall_hit'
                  AND created_at >= NOW() - (:p1::int * INTERVAL '1 hour')
                  AND created_at <  NOW() - (:p2::int * INTERVAL '1 hour')
            ),
            purchases AS (
                SELECT DISTINCT user_id
                FROM events
                WHERE event_name = 'payment_success'
                  AND created_at >= NOW() - (:p1::int * INTERVAL '1 hour')
                  AND created_at <  NOW() - (:p2::int * INTERVAL '1 hour')
            ),
            repeats AS (
                SELECT user_id
                FROM events
                WHERE event_name = 'payment_success'
                  AND created_at >= NOW() - (:p1::int * INTERVAL '1 hour')
                  AND created_at <  NOW() - (:p2::int * INTERVAL '1 hour')
                GROUP BY user_id
                HAVING COUNT(*) >= 2
            ),
            s1 AS (
                SELECT user_id FROM first_gen WHERE user_id IN (SELECT user_id FROM starts)
            ),
            s2 AS (
                SELECT user_id FROM paywall WHERE user_id IN (SELECT user_id FROM s1)
            ),
            s3 AS (
                SELECT user_id FROM purchases WHERE user_id IN (SELECT user_id FROM s2)
            )
            SELECT
                (SELECT COUNT(*) FROM starts) AS start_users,
                (SELECT COUNT(*) FROM s1) AS first_generation_users,
                (SELECT COUNT(*) FROM s2) AS paywall_hit_users,
                (SELECT COUNT(*) FROM s3) AS purchase_users,
                (SELECT COUNT(*) FROM repeats WHERE user_id IN (SELECT user_id FROM s3)) AS repeat_users
            """
        ),
        {"p1": start_offset_hours, "p2": end_offset_hours},
    )
    row = result.mappings().first()

    start_users = int(row["start_users"] or 0)
    first_generation_users = int(row["first_generation_users"] or 0)
    paywall_hit_users = int(row["paywall_hit_users"] or 0)
    purchase_users = int(row["purchase_users"] or 0)
    repeat_users = int(row["repeat_users"] or 0)

    return {
        "start": start_users,
        "first_generation": first_generation_users,
        "paywall_hit": paywall_hit_users,
        "purchase": purchase_users,
        "repeat": repeat_users,
        "cr_start_to_first_pct": _pct(first_generation_users, start_users),
        "cr_first_to_paywall_pct": _pct(paywall_hit_users, first_generation_users),
        "cr_paywall_to_purchase_pct": _pct(purchase_users, paywall_hit_users),
        "cr_purchase_to_repeat_pct": _pct(repeat_users, purchase_users),
    }


async def _send_telegram_async(chat_id: int, text: str) -> None:
    import httpx

    from shared.config import settings

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(
                f"https://api.telegram.org/bot{settings.bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            )
    except Exception as e:
        log.warning("send_telegram_failed", chat_id=chat_id, error=str(e))


async def handle(payload: dict, bot=None) -> None:
    """Check KPI thresholds and send alerts to admin IDs if triggered."""
    try:
        from shared.db.session import get_session
        from shared.config import settings

        admin_ids = getattr(settings, "admin_id_list", None) or []
        if not admin_ids:
            return

        threshold_402 = int(getattr(settings, "metrics_402_alert_threshold_24h", 5) or 5)
        cppu_threshold = float(getattr(settings, "metrics_cost_per_paid_user_alert_24h", 2500.0) or 0)
        cppu_min_paid = int(getattr(settings, "metrics_cost_per_paid_user_min_paid_users", 3) or 0)
        funnel_drop_min_paywall = int(getattr(settings, "metrics_funnel_cr_drop_min_paywall_24h", 20) or 0)
        funnel_drop_ratio = float(getattr(settings, "metrics_funnel_cr_drop_ratio", 0.6) or 0)

        zero_purchase_alert_needed = False
        alert_402_needed = False
        alert_cppu_needed = False
        alert_funnel_drop_needed = False

        funnel: dict[str, Any] = {
            "start": 0,
            "first_generation": 0,
            "paywall_hit": 0,
            "purchase": 0,
            "repeat": 0,
            "cr_start_to_first_pct": 0.0,
            "cr_first_to_paywall_pct": 0.0,
            "cr_paywall_to_purchase_pct": 0.0,
            "cr_purchase_to_repeat_pct": 0.0,
        }
        prev_funnel = dict(funnel)

        openrouter_402_24h = 0
        paid_users_24h = 0
        spent_cr_24h = 0.0
        cost_per_paid_user_24h = 0.0
        current_paywall_cr = 0.0
        prev_paywall_cr = 0.0

        async with get_session() as session:
            pay_today = (
                await session.execute(
                    text(
                        "SELECT COALESCE(SUM(amount_rub), 0) FROM payments"
                        " WHERE status = 'confirmed' AND confirmed_at >= CURRENT_DATE"
                    )
                )
            ).scalar()
            pay_yesterday = (
                await session.execute(
                    text(
                        "SELECT COALESCE(SUM(amount_rub), 0) FROM payments"
                        " WHERE status = 'confirmed'"
                        " AND confirmed_at >= CURRENT_DATE - INTERVAL '1 day'"
                        " AND confirmed_at < CURRENT_DATE"
                    )
                )
            ).scalar()
            errors_week = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM ai_requests"
                        " WHERE started_at >= CURRENT_DATE - INTERVAL '7 days'"
                        " AND error_message IS NOT NULL"
                    )
                )
            ).scalar()
            total_week = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM ai_requests"
                        " WHERE started_at >= CURRENT_DATE - INTERVAL '7 days'"
                    )
                )
            ).scalar()

            funnel = await _compute_funnel_window(session, window_hours=24, offset_hours=0)
            prev_funnel = await _compute_funnel_window(session, window_hours=24, offset_hours=24)

            openrouter_402_24h = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM events"
                        " WHERE event_name = 'openrouter_402'"
                        " AND created_at >= NOW() - INTERVAL '24 hours'"
                    )
                )
            ).scalar()
            recent_402_alert = (
                await session.execute(
                    text(
                        "SELECT 1 FROM events"
                        " WHERE event_name = 'alert_openrouter_402_24h'"
                        " AND created_at >= NOW() - INTERVAL '6 hours'"
                        " LIMIT 1"
                    )
                )
            ).scalar()

            paid_users_24h = (
                await session.execute(
                    text(
                        "SELECT COUNT(DISTINCT user_id) FROM events"
                        " WHERE event_name = 'payment_success'"
                        " AND created_at >= NOW() - INTERVAL '24 hours'"
                    )
                )
            ).scalar()
            spent_cr_24h = (
                await session.execute(
                    text(
                        "SELECT COALESCE(SUM(-amount), 0) FROM credit_transactions"
                        " WHERE type = 'spend' AND created_at >= NOW() - INTERVAL '24 hours'"
                    )
                )
            ).scalar()
            recent_cppu_alert = (
                await session.execute(
                    text(
                        "SELECT 1 FROM events"
                        " WHERE event_name = 'alert_cost_per_paid_user_24h'"
                        " AND created_at >= NOW() - INTERVAL '6 hours'"
                        " LIMIT 1"
                    )
                )
            ).scalar()

            recent_zero_purchase_alert = (
                await session.execute(
                    text(
                        "SELECT 1 FROM events"
                        " WHERE event_name = 'alert_purchase_zero_24h'"
                        " AND created_at >= NOW() - INTERVAL '24 hours'"
                        " LIMIT 1"
                    )
                )
            ).scalar()
            recent_funnel_drop_alert = (
                await session.execute(
                    text(
                        "SELECT 1 FROM events"
                        " WHERE event_name = 'alert_funnel_cr_drop_24h'"
                        " AND created_at >= NOW() - INTERVAL '6 hours'"
                        " LIMIT 1"
                    )
                )
            ).scalar()

            if funnel["paywall_hit"] > 0 and funnel["purchase"] == 0 and not recent_zero_purchase_alert:
                zero_purchase_alert_needed = True

            openrouter_402_24h = int(openrouter_402_24h or 0)
            if openrouter_402_24h >= threshold_402 and not recent_402_alert:
                alert_402_needed = True

            paid_users_24h = int(paid_users_24h or 0)
            spent_cr_24h = float(spent_cr_24h or 0)
            if paid_users_24h > 0:
                cost_per_paid_user_24h = spent_cr_24h / paid_users_24h
            if (
                cppu_min_paid > 0
                and paid_users_24h >= cppu_min_paid
                and cost_per_paid_user_24h >= cppu_threshold
                and not recent_cppu_alert
            ):
                alert_cppu_needed = True

            current_paywall = int(funnel["paywall_hit"] or 0)
            current_purchase = int(funnel["purchase"] or 0)
            prev_paywall = int(prev_funnel["paywall_hit"] or 0)
            prev_purchase = int(prev_funnel["purchase"] or 0)
            current_paywall_cr = (current_purchase / current_paywall) if current_paywall > 0 else 0.0
            prev_paywall_cr = (prev_purchase / prev_paywall) if prev_paywall > 0 else 0.0

            if (
                current_paywall >= funnel_drop_min_paywall
                and prev_paywall >= funnel_drop_min_paywall
                and prev_paywall_cr > 0
                and current_paywall_cr < (prev_paywall_cr * funnel_drop_ratio)
                and not recent_funnel_drop_alert
            ):
                alert_funnel_drop_needed = True

        pay_today = float(pay_today or 0)
        pay_yesterday = float(pay_yesterday or 0)
        errors_week = int(errors_week or 0)
        total_week = int(total_week or 1)
        errors_pct = round(100 * errors_week / total_week, 1)

        alerts = []
        if total_week > 10 and errors_pct > 15:
            alerts.append(f"⚠️ Высокий % ошибок: {errors_pct}% за неделю ({errors_week}/{total_week})")
        if pay_yesterday > 0 and pay_today < 0.5 * pay_yesterday:
            alerts.append(f"⚠️ Выручка за сегодня {pay_today:.0f} ₽ vs вчера {pay_yesterday:.0f} ₽ (падение >50%)")
        if zero_purchase_alert_needed:
            alerts.append(
                "⚠️ За последние 24 часа нет покупок после paywall. "
                f"Funnel: start={funnel['start']} -> first_gen={funnel['first_generation']} "
                f"-> paywall={funnel['paywall_hit']} -> purchase={funnel['purchase']} -> repeat={funnel['repeat']}"
            )
        if alert_402_needed:
            alerts.append(
                f"⚠️ OpenRouter 402 за 24ч: {openrouter_402_24h} (порог {threshold_402}). "
                "Рекомендуется временно увести трафик с проблемных моделей."
            )
        if alert_cppu_needed:
            alerts.append(
                f"⚠️ Высокий cost-per-paid-user за 24ч: {cost_per_paid_user_24h:.1f} CR "
                f"(порог {cppu_threshold:.1f}, paid_users={paid_users_24h})."
            )
        if alert_funnel_drop_needed:
            alerts.append(
                "⚠️ Просадка конверсии paywall→purchase за 24ч: "
                f"{current_paywall_cr*100:.1f}% vs {prev_paywall_cr*100:.1f}% (пред. 24ч)."
            )

        for aid in admin_ids:
            for msg in alerts:
                await _send_telegram_async(aid, f"НейроБокс алерт:\n{msg}")

        async with get_session() as session:
            if zero_purchase_alert_needed:
                await session.execute(
                    text(
                        "INSERT INTO events (event_name, user_id, properties)"
                        " VALUES (:event_name, :user_id, :properties::jsonb)"
                    ),
                    {
                        "event_name": "alert_purchase_zero_24h",
                        "user_id": 0,
                        "properties": json.dumps(
                            {
                                "window": "24h",
                                "funnel": funnel,
                                "pay_today": pay_today,
                                "pay_yesterday": pay_yesterday,
                            },
                            ensure_ascii=False,
                        ),
                    },
                )
            if alert_402_needed:
                await session.execute(
                    text(
                        "INSERT INTO events (event_name, user_id, properties)"
                        " VALUES (:event_name, :user_id, :properties::jsonb)"
                    ),
                    {
                        "event_name": "alert_openrouter_402_24h",
                        "user_id": 0,
                        "properties": json.dumps(
                            {
                                "window": "24h",
                                "count": openrouter_402_24h,
                                "threshold": threshold_402,
                            },
                            ensure_ascii=False,
                        ),
                    },
                )
            if alert_cppu_needed:
                await session.execute(
                    text(
                        "INSERT INTO events (event_name, user_id, properties)"
                        " VALUES (:event_name, :user_id, :properties::jsonb)"
                    ),
                    {
                        "event_name": "alert_cost_per_paid_user_24h",
                        "user_id": 0,
                        "properties": json.dumps(
                            {
                                "window": "24h",
                                "cost_per_paid_user_cr": round(cost_per_paid_user_24h, 2),
                                "threshold": cppu_threshold,
                                "paid_users": paid_users_24h,
                                "spent_cr": round(spent_cr_24h, 2),
                            },
                            ensure_ascii=False,
                        ),
                    },
                )
            if alert_funnel_drop_needed:
                await session.execute(
                    text(
                        "INSERT INTO events (event_name, user_id, properties)"
                        " VALUES (:event_name, :user_id, :properties::jsonb)"
                    ),
                    {
                        "event_name": "alert_funnel_cr_drop_24h",
                        "user_id": 0,
                        "properties": json.dumps(
                            {
                                "window": "24h",
                                "current_paywall_to_purchase_cr": round(current_paywall_cr, 4),
                                "previous_paywall_to_purchase_cr": round(prev_paywall_cr, 4),
                                "ratio_threshold": funnel_drop_ratio,
                                "current_funnel": funnel,
                                "previous_funnel": prev_funnel,
                            },
                            ensure_ascii=False,
                        ),
                    },
                )
    except Exception as e:
        log.error("metrics_alert_error", error=str(e))
