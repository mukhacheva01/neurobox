#!/usr/bin/env python3
"""НейроБокс — Daily stats report to Telegram admin channel.

Install:
  crontab -e → add:
  0 9 * * * cd /opt/neurobox && python3 scripts/daily_report.py

Sends a summary to the admin (or channel) via Telegram Bot API.
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta

import httpx


def load_env():
    """Load .env from standard locations."""
    for d in [os.getcwd(), "/opt/neurobox", os.path.dirname(os.path.abspath(__file__))]:
        env_path = os.path.join(d, ".env")
        if os.path.isfile(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


load_env()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = os.environ.get("ADMIN_IDS", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")


async def get_stats(conn) -> dict:
    """Query daily stats from DB."""
    yesterday = datetime.utcnow().date() - timedelta(days=1)
    today = datetime.utcnow().date()

    stats = {}

    # DAU (unique users who sent messages yesterday)
    row = await conn.fetchrow(
        "SELECT COUNT(DISTINCT user_id) AS dau FROM events "
        "WHERE event_name = 'message_sent' AND created_at >= $1 AND created_at < $2",
        yesterday, today,
    )
    stats["dau"] = row["dau"] if row else 0

    # New users (is_new: JSON boolean or string 'true'/'t'/'1')
    row = await conn.fetchrow(
        "SELECT COUNT(*) AS cnt FROM events "
        "WHERE event_name = 'bot_start' AND created_at >= $1 AND created_at < $2 "
        "AND ( (properties->'is_new')::text IN ('true', 't') "
        "   OR LOWER(TRIM(COALESCE(properties->>'is_new', ''))) IN ('true', 't', '1') )",
        yesterday, today,
    )
    stats["new_users"] = row["cnt"] if row else 0

    # Total messages
    row = await conn.fetchrow(
        "SELECT COUNT(*) AS cnt FROM events "
        "WHERE event_name = 'message_sent' AND created_at >= $1 AND created_at < $2",
        yesterday, today,
    )
    stats["messages"] = row["cnt"] if row else 0

    # Errors
    row = await conn.fetchrow(
        "SELECT COUNT(*) AS cnt FROM events "
        "WHERE event_name = 'message_error' AND created_at >= $1 AND created_at < $2",
        yesterday, today,
    )
    stats["errors"] = row["cnt"] if row else 0

    # Payments
    row = await conn.fetchrow(
        "SELECT COUNT(*) AS cnt, COALESCE(SUM((properties->>'amount_rub')::float), 0) AS rev "
        "FROM events "
        "WHERE event_name = 'payment_success' AND created_at >= $1 AND created_at < $2",
        yesterday, today,
    )
    stats["payments"] = row["cnt"] if row else 0
    stats["revenue"] = round(row["rev"], 2) if row else 0

    # Error rate
    if stats["messages"] > 0:
        stats["error_rate"] = round(stats["errors"] / stats["messages"] * 100, 1)
    else:
        stats["error_rate"] = 0

    # Avg latency
    row = await conn.fetchrow(
        "SELECT AVG((properties->>'latency_ms')::int) AS avg_lat "
        "FROM events "
        "WHERE event_name = 'message_sent' AND created_at >= $1 AND created_at < $2 "
        "AND properties->>'latency_ms' IS NOT NULL",
        yesterday, today,
    )
    stats["avg_latency_ms"] = int(row["avg_lat"]) if row and row["avg_lat"] else 0

    # Top models
    rows = await conn.fetch(
        "SELECT properties->>'model' AS model, COUNT(*) AS cnt "
        "FROM events "
        "WHERE event_name = 'message_sent' AND created_at >= $1 AND created_at < $2 "
        "GROUP BY model ORDER BY cnt DESC LIMIT 5",
        yesterday, today,
    )
    stats["top_models"] = [(r["model"], r["cnt"]) for r in rows]

    return stats


async def send_report(stats: dict):
    """Send formatted report to Telegram."""
    date_str = (datetime.utcnow().date() - timedelta(days=1)).strftime("%d.%m.%Y")

    top_models_str = "\n".join(
        f"  {m}: {c}" for m, c in stats.get("top_models", [])
    ) or "  —"

    text = (
        f"📊 <b>НейроБокс — отчёт за {date_str}</b>\n\n"
        f"👥 DAU: <b>{stats['dau']}</b>\n"
        f"🆕 Новых: <b>{stats['new_users']}</b>\n"
        f"💬 Сообщений: <b>{stats['messages']}</b>\n"
        f"❌ Ошибок: <b>{stats['errors']}</b> ({stats['error_rate']}%)\n"
        f"⏱ Средний отклик: <b>{stats['avg_latency_ms']}ms</b>\n"
        f"💳 Платежей: <b>{stats['payments']}</b>\n"
        f"💰 Выручка: <b>{stats['revenue']}₽</b>\n\n"
        f"🏆 Топ моделей:\n{top_models_str}"
    )

    admin_ids = [int(x.strip()) for x in ADMIN_IDS.split(",") if x.strip()]

    async with httpx.AsyncClient() as client:
        for admin_id in admin_ids:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": admin_id,
                        "text": text,
                        "parse_mode": "HTML",
                    },
                )
                print(f"Report sent to {admin_id}")
            except Exception as e:
                print(f"Failed to send to {admin_id}: {e}", file=sys.stderr)


async def main():
    if not BOT_TOKEN or not ADMIN_IDS:
        print("BOT_TOKEN or ADMIN_IDS not set", file=sys.stderr)
        sys.exit(1)

    import asyncpg
    db_url = DATABASE_URL.replace("+asyncpg", "")
    conn = await asyncpg.connect(db_url)

    try:
        stats = await get_stats(conn)
        await send_report(stats)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
