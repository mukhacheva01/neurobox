"""Worker job: collect and persist daily statistics."""
from typing import Any

import structlog
from sqlalchemy import text

log = structlog.get_logger()


def _pct(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return round(100.0 * float(part) / float(whole), 1)


async def _compute_funnel_window(session, window_hours: int, offset_hours: int = 0) -> dict[str, Any]:
    """KPI funnel for a sliding window.

    window_hours: window size in hours (e.g. 24)
    offset_hours: shift window back from now in hours
      - 0   -> [now-24h, now)
      - 24  -> [now-48h, now-24h)
    """
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


async def _compute_funnel_24h(session) -> dict[str, Any]:
    """KPI funnel for last 24h: start -> first_generation -> paywall_hit -> purchase -> repeat."""
    return await _compute_funnel_window(session, window_hours=24, offset_hours=0)


async def handle(payload: dict, bot=None) -> None:
    """Collect daily metrics and upsert into daily_stats table."""
    try:
        from shared.db.session import get_session

        async with get_session() as session:
            today_users = (
                await session.execute(
                    text("SELECT COUNT(DISTINCT user_id) FROM credit_transactions WHERE created_at >= CURRENT_DATE")
                )
            ).scalar()
            today_revenue = (
                await session.execute(
                    text(
                        "SELECT COALESCE(SUM(amount_rub), 0) FROM payments"
                        " WHERE status = 'confirmed' AND confirmed_at >= CURRENT_DATE"
                    )
                )
            ).scalar()
            today_requests = (
                await session.execute(
                    text("SELECT COUNT(*) FROM ai_requests WHERE started_at >= CURRENT_DATE")
                )
            ).scalar()
            funnel = await _compute_funnel_24h(session)

            for metric, val in (
                ("active_users", float(today_users or 0)),
                ("revenue_rub", float(today_revenue or 0)),
                ("ai_requests", float(today_requests or 0)),
                ("funnel_start_users_24h", float(funnel["start"])),
                ("funnel_first_generation_users_24h", float(funnel["first_generation"])),
                ("funnel_paywall_hit_users_24h", float(funnel["paywall_hit"])),
                ("funnel_purchase_users_24h", float(funnel["purchase"])),
                ("funnel_repeat_users_24h", float(funnel["repeat"])),
                ("funnel_cr_start_to_first_pct_24h", float(funnel["cr_start_to_first_pct"])),
                ("funnel_cr_first_to_paywall_pct_24h", float(funnel["cr_first_to_paywall_pct"])),
                ("funnel_cr_paywall_to_purchase_pct_24h", float(funnel["cr_paywall_to_purchase_pct"])),
                ("funnel_cr_purchase_to_repeat_pct_24h", float(funnel["cr_purchase_to_repeat_pct"])),
            ):
                await session.execute(
                    text(
                        "INSERT INTO daily_stats (date, metric, value, meta)"
                        " VALUES (CURRENT_DATE, :metric, :value, NULL)"
                        " ON CONFLICT (date, metric) DO UPDATE SET value = :value"
                    ),
                    {"metric": metric, "value": val},
                )
        log.info(
            "daily_stats_collected",
            users=today_users,
            revenue=float(today_revenue or 0),
            requests=today_requests,
            funnel=funnel,
        )
    except Exception as e:
        log.error("daily_stats_error", error=str(e))
