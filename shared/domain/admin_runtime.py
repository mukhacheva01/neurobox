"""Runtime overrides for admin-editable texts and acquisition metadata."""
from __future__ import annotations

from urllib.parse import parse_qs

from shared.db.database import get_pool

DEFAULT_ADMIN_TEXTS: dict[str, dict[str, str]] = {
    "welcome_text": {
        "title": "Стартовое приветствие",
        "description": "Первый экран после /start для нового пользователя.",
        "value": (
            "👋 Добро пожаловать в НейроБокс, {first_name}!\n\n"
            "AI для текста, картинок, документов и транскрибации в одном боте.\n\n"
            "🎁 Тебе начислено {free} CR — попробуй прямо сейчас!\n\n"
            "Просто напиши задачу — бот поможет сразу."
        ),
    },
    "support_text": {
        "title": "Текст поддержки",
        "description": "Экран /paysupport и кнопки поддержки.",
        "value": (
            "💬 <b>Поддержка</b>\n\n"
            "Если у тебя есть вопросы, предложения или проблемы — напиши нам!\n\n"
            "🤖 Бот поддержки: @ai_xup_help_bot\n\n"
            "Обычно отвечаем в течение нескольких часов."
        ),
    },
    "paywall_trust_note": {
        "title": "Доверительный блок paywall",
        "description": "Короткая подпись под оффером оплаты.",
        "value": "💚 Если генерация не удалась — кредиты вернутся.",
    },
}


async def sync_admin_text_defaults() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            for key, meta in DEFAULT_ADMIN_TEXTS.items():
                await conn.execute(
                    """
                    INSERT INTO admin_texts (key, title, description, value, enabled)
                    VALUES ($1, $2, $3, $4, TRUE)
                    ON CONFLICT (key) DO NOTHING
                    """,
                    key,
                    meta["title"],
                    meta["description"],
                    meta["value"],
                )
        except Exception:
            return


async def get_admin_text(key: str, default: str | None = None) -> str:
    await sync_admin_text_defaults()
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                "SELECT value, enabled FROM admin_texts WHERE key = $1",
                key,
            )
        except Exception:
            row = None
    if row and row.get("enabled"):
        value = (row.get("value") or "").strip()
        if value:
            return value
    if default is not None:
        return default
    meta = DEFAULT_ADMIN_TEXTS.get(key) or {}
    return meta.get("value", "")


def parse_start_payload(payload: str | None) -> dict[str, str]:
    """Parse Telegram start payload into acquisition fields.

    Supported:
    - ref_CODE
    - utm_source=...&utm_campaign=...
    - source_campaign_content form via `src:...`
    """
    raw = (payload or "").strip()
    if not raw:
        return {}
    out: dict[str, str] = {"start_payload": raw[:255]}
    if raw.startswith("ref_"):
        out["acquisition_channel"] = "referral"
        return out
    if "=" in raw and "&" in raw:
        parsed = parse_qs(raw, keep_blank_values=False)
        for key in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"):
            if parsed.get(key):
                out[key] = parsed[key][0][:150]
        if out.get("utm_source"):
            out["acquisition_channel"] = out["utm_source"]
        return out
    if raw.startswith("src:"):
        parts = raw[4:].split(":")
        if len(parts) >= 1 and parts[0]:
            out["utm_source"] = parts[0][:100]
            out["acquisition_channel"] = parts[0][:100]
        if len(parts) >= 2 and parts[1]:
            out["utm_campaign"] = parts[1][:150]
        if len(parts) >= 3 and parts[2]:
            out["utm_content"] = parts[2][:150]
        return out
    out["acquisition_channel"] = raw[:100]
    return out


async def save_user_acquisition(user_id: int, payload: str | None) -> None:
    data = parse_start_payload(payload)
    if not data:
        return
    pool = await get_pool()
    fields = []
    values = []
    idx = 1
    for col in (
        "start_payload",
        "acquisition_channel",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
    ):
        if col in data:
            fields.append(f"{col} = COALESCE({col}, ${idx})")
            values.append(data[col])
            idx += 1
    if not fields:
        return
    values.append(user_id)
    sql = f"UPDATE users SET {', '.join(fields)}, updated_at = NOW() WHERE id = ${idx}"
    async with pool.acquire() as conn:
        try:
            await conn.execute(sql, *values)
        except Exception:
            return
