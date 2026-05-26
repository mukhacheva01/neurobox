"""НейроБокс — Credit service v5."""
import json
import secrets
from datetime import date, datetime, timedelta, timezone

import structlog

from shared.config.text_models import TEXT_CREDIT_PRICES, TEXT_FREE_MODELS
from shared.db.session import get_session

log = structlog.get_logger()
BALANCE_CACHE_TTL = 90


async def _balance_cache_get(user_id: int) -> dict | None:
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if not r:
            return None
        key = f"balance:{user_id}"
        val = await r.get(key)
        if val:
            return json.loads(val)
    except Exception:
        pass
    return None


async def _balance_cache_set(user_id: int, data: dict) -> None:
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if not r:
            return
        await r.set(f"balance:{user_id}", json.dumps(data), ex=BALANCE_CACHE_TTL)
    except Exception:
        pass


async def _balance_cache_invalidate(user_id: int) -> None:
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if not r:
            return
        await r.delete(f"balance:{user_id}")
    except Exception:
        pass

CREDIT_PRICES = {
    **TEXT_CREDIT_PRICES,
    "flux-2-turbo": 5, "flux-2-pro": 10, "flux-2-flex": 8, "flux-realism": 10,
    "grok-imagine-image": 10, "kling-image-v3": 10, "ideogram-v2": 10,
    "nano-banana": 12, "dall-e-3": 12, "gpt-image": 12, "midjourney": 20,
    "nano-banana-pro-2k": 40, "nano-banana-pro-4k": 75,
    "hailuo": 75, "freely-ai": 75, "wanx": 100, "luma": 150, "seedance": 150,
    "runway": 200, "grok-video": 300, "kling-2.6": 300, "sora2": 500,
    "veo-3.1": 600, "veo-3.1-audio": 900,
    "whisper": 5,
    "edge-tts": 0, "openai-tts-mini": 3, "openai-tts-hd": 8,
    "musicgen": 15, "suno-v4": 50,
    "rmbg": 5, "ocr": 3, "upscale": 5, "style": 8,
    "docgen_txt": 6, "docgen_md": 6, "docgen_csv": 6,
    "docgen_docx": 10, "docgen_pdf": 12, "docgen_xlsx": 10,
    "transcribe": 5, "transcribe_summary": 8, "transcribe_protocol": 12,
}

FREE_MODELS = TEXT_FREE_MODELS | {"edge-tts", "whisper"}

VIDEO_MODELS = {
    "kling-2.6":     {"label": "Kling 2.6",       "img": True,  "vid": True,  "audio": True,  "cr": 300, "endpoint": "fal-ai/kling-video/v2.1/master"},
    "veo-3.1":       {"label": "Veo 3.1",         "img": True,  "vid": True,  "audio": True,  "cr": 600, "endpoint": "fal-ai/veo3.1"},
    "veo-3.1-audio": {"label": "Veo 3.1 +Audio",  "img": True,  "vid": True,  "audio": True,  "cr": 900, "endpoint": "fal-ai/veo3.1"},
    "sora2":         {"label": "Sora 2",            "img": True,  "vid": True,  "audio": True,  "cr": 500, "endpoint": "fal-ai/sora-2/text-to-video"},
    "runway":        {"label": "Runway",           "img": True,  "vid": True,  "audio": False, "cr": 200, "endpoint": "fal-ai/runway-gen3/turbo/image-to-video"},
    "seedance":      {"label": "Seedance",         "img": True,  "vid": False, "audio": False, "cr": 150, "endpoint": "fal-ai/seedance-1-lite"},
    "grok-video":    {"label": "Grok",             "img": True,  "vid": True,  "audio": True,  "cr": 300, "endpoint": "fal-ai/grok-video"},
    "wanx":          {"label": "WanX - NSFW",      "img": True,  "vid": False, "audio": False, "cr": 100, "endpoint": "fal-ai/wan/v2.1/1.3b"},
    "luma":          {"label": "Luma",             "img": True,  "vid": False, "audio": False, "cr": 150, "endpoint": "fal-ai/luma-dream-machine"},
    "freely-ai":     {"label": "Freely AI Video",  "img": True,  "vid": False, "audio": False, "cr": 75,  "endpoint": "fal-ai/ltx-video/v0.9.5"},
    "hailuo":        {"label": "Hailuo",           "img": True,  "vid": False, "audio": False, "cr": 75,  "endpoint": "fal-ai/minimax-video/video-01"},
}

DEFAULT_CREDIT_PACKS = {
    "trial":    {"credits": 50,   "price_rub": 29,    "price_stars": 25,   "price_usd": 0.3,  "label": "🟢 Пробный",   "discount": ""},
    "welcome":  {"credits": 150,  "price_rub": 29,    "price_stars": 25,   "price_usd": 0.3,  "label": "🎉 Добро пожаловать!", "discount": "70%", "one_time": True},
    "start":    {"credits": 100,  "price_rub": 49,    "price_stars": 45,   "price_usd": 0.5,  "label": "🟢 Старт",     "discount": ""},
    "lite":     {"credits": 300,  "price_rub": 129,   "price_stars": 115,  "price_usd": 1.3,  "label": "🔵 Лайт",      "discount": "9%"},
    "basic":    {"credits": 700,  "price_rub": 249,   "price_stars": 225,  "price_usd": 2.5,  "label": "🔵 Базовый",   "discount": "14%"},
    "standard": {"credits": 1500, "price_rub": 449,   "price_stars": 400,  "price_usd": 4.5,  "label": "🟣 Стандарт", "discount": "22%"},
    "advanced": {"credits": 3000, "price_rub": 799,   "price_stars": 700,  "price_usd": 8.0,  "label": "🟣 Продвинутый", "discount": "28%"},
    "pro":      {"credits": 6000, "price_rub": 1490,  "price_stars": 1300, "price_usd": 15.0, "label": "🟡 Про",       "discount": "31%"},
    "proplus":  {"credits": 10000,"price_rub": 2290,  "price_stars": 2000, "price_usd": 23.0, "label": "🟡 Про+",      "discount": "38%"},
    "mega":     {"credits": 18000,"price_rub": 3990,  "price_stars": 3500, "price_usd": 40.0, "label": "🔴 Мега",      "discount": "45%"},
    "ultra":    {"credits": 40000,"price_rub": 8990,  "price_stars": 8000, "price_usd": 90.0, "label": "⚫ Ультра",    "discount": "54%"},
    "unlimited": {"credits": 0,   "price_rub": 2990,  "price_stars": 2500, "price_usd": 30.0, "label": "♾️ Безлимит 30 дн.", "discount": ""},
}

# Backward-compatible constant for legacy imports. Runtime should prefer get_credit_packs().
CREDIT_PACKS = DEFAULT_CREDIT_PACKS

TTS_VOICES = {
    "edge-tts": {
        "svetlana": {"id": "ru-RU-SvetlanaNeural", "label": "👩 Светлана"},
        "dmitry":   {"id": "ru-RU-DmitryNeural",   "label": "👨 Дмитрий"},
        "emma":     {"id": "en-US-EmmaNeural",      "label": "👩 Emma (EN)"},
        "guy":      {"id": "en-US-GuyNeural",       "label": "👨 Guy (EN)"},
    },
    "openai-tts-mini": {
        "alloy": {"id": "alloy", "label": "🔵 Alloy"}, "echo": {"id": "echo", "label": "🟣 Echo"},
        "nova": {"id": "nova", "label": "🟢 Nova"}, "onyx": {"id": "onyx", "label": "⚫ Onyx"},
        "shimmer": {"id": "shimmer", "label": "🟡 Shimmer"},
    },
    "openai-tts-hd": {
        "alloy": {"id": "alloy", "label": "🔵 Alloy HD"}, "echo": {"id": "echo", "label": "🟣 Echo HD"},
        "nova": {"id": "nova", "label": "🟢 Nova HD"}, "onyx": {"id": "onyx", "label": "⚫ Onyx HD"},
        "shimmer": {"id": "shimmer", "label": "🟡 Shimmer HD"},
    },
}

REFERRER_CR = 50
REFEREE_CR = 50
# Уровни: (мин. друзей, множитель бонуса, название)
REFERRAL_LEVELS = [(3, 1.5, "Бронза"), (10, 2.0, "Серебро"), (25, 2.5, "Золото"), (50, 3.0, "Бриллиант")]


def get_referral_level(referral_count: int) -> tuple[str, float]:
    """Возвращает (название уровня, множитель бонуса). referral_count — текущее число приведённых друзей (до начисления за нового)."""
    name, mult = "Старт", 1.0
    for min_ref, multiplier, level_name in REFERRAL_LEVELS:
        if referral_count >= min_ref:
            name, mult = level_name, multiplier
    return name, mult


UNLIMITED_DAYS = 30


async def sync_billing_plans_defaults() -> None:
    """Синхронизировать дефолтные тарифы в billing_plans, если таблица доступна."""
    try:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from shared.db.models.worker_task import BillingPlan

        async with get_session() as session:
            for idx, (plan_key, plan) in enumerate(DEFAULT_CREDIT_PACKS.items(), start=1):
                stmt = pg_insert(BillingPlan).values(
                    plan_key=plan_key,
                    label=plan.get("label", plan_key),
                    credits=int(plan.get("credits", 0) or 0),
                    price_rub=float(plan.get("price_rub", 0) or 0),
                    price_stars=int(plan.get("price_stars", 0) or 0),
                    price_usd=float(plan.get("price_usd", 0) or 0),
                    discount=str(plan.get("discount", "") or ""),
                    enabled=True,
                    sort_order=idx,
                    is_one_time=bool(plan.get("one_time", False)),
                    is_unlimited=plan_key == "unlimited",
                    period_days=UNLIMITED_DAYS if plan_key == "unlimited" else None,
                ).on_conflict_do_nothing(index_elements=["plan_key"])
                await session.execute(stmt)
    except Exception:
        return


async def get_credit_packs() -> dict[str, dict]:
    """Текущие тарифы с учётом billing_plans. Fallback — кодовые дефолты."""
    await sync_billing_plans_defaults()
    try:
        from sqlalchemy import select

        from shared.db.models.worker_task import BillingPlan

        async with get_session() as session:
            result = await session.execute(
                select(BillingPlan)
                .where(BillingPlan.enabled == True)  # noqa: E712
                .order_by(BillingPlan.sort_order.asc(), BillingPlan.plan_key.asc())
            )
            rows = result.scalars().all()
    except Exception:
        rows = []
    if not rows:
        return {k: dict(v) for k, v in DEFAULT_CREDIT_PACKS.items()}
    packs: dict[str, dict] = {}
    for row in rows:
        plan_key = row.plan_key
        base = dict(DEFAULT_CREDIT_PACKS.get(plan_key, {}))
        base.update(
            {
                "label": row.label,
                "credits": int(row.credits or 0),
                "price_rub": float(row.price_rub or 0),
                "price_stars": int(row.price_stars or 0),
                "price_usd": float(row.price_usd or 0),
                "discount": row.discount or "",
            }
        )
        if row.is_one_time is not None:
            base["one_time"] = bool(row.is_one_time)
        packs[plan_key] = base
    return packs


async def get_credit_pack(plan_key: str) -> dict | None:
    packs = await get_credit_packs()
    return packs.get(plan_key)

# Пробный период: 45 минут безлимита после активации по кнопке
TRIAL_DURATION_MINUTES = 45

# Пользователи с вечным безлимитом (username без @, lowercase). Для теста подписок — безлимит без прав админа.
# Безлимит только для владельца (админ 72916668). По username больше не даём.
# OWNER_TG_ID removed — using settings.admin_id_list
UNLIMITED_USERNAMES: set[str] = set()


async def is_trial_active(user_id: int) -> bool:
    """True если у пользователя активен пробный безлимит (в течение 45 мин после активации)."""
    from sqlalchemy import text

    async with get_session() as session:
        result = await session.execute(
            text(
                "SELECT 1 FROM users WHERE id = :uid"
                " AND trial_started_at IS NOT NULL"
                " AND trial_started_at + INTERVAL '1 minute' * :mins > NOW()"
            ),
            {"uid": user_id, "mins": TRIAL_DURATION_MINUTES},
        )
        return result.scalar_one_or_none() is not None


async def get_trial_status(user_id: int) -> dict:
    """Возвращает: can_activate (ещё не активировал), is_active, expires_at (datetime или None)."""
    from shared.db.models.user import User

    async with get_session() as session:
        user = await session.get(User, user_id)

    if not user:
        return {"can_activate": True, "is_active": False, "expires_at": None}
    started = user.trial_started_at
    if started is None:
        return {"can_activate": True, "is_active": False, "expires_at": None}
    expires = started + timedelta(minutes=TRIAL_DURATION_MINUTES)
    now = datetime.now(timezone.utc)
    if started.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    is_active = now < expires
    return {
        "can_activate": False,
        "is_active": is_active,
        "expires_at": expires,
    }


async def start_trial(user_id: int) -> bool:
    """Включить пробный период. Возвращает True если включён (впервые), False если уже был активирован."""
    from sqlalchemy import update

    from shared.db.models.user import User

    async with get_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return False
        if user.trial_started_at is not None:
            return False  # уже активировал раньше
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(trial_started_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
        )
    log.info("Trial started", user_id=user_id)
    return True


async def get_onboarded(user_id: int) -> bool:
    """Пройден ли онбординг (тур из 3 шагов). Если колонки нет — считаем пройденным."""
    try:
        from shared.db.models.user import User

        async with get_session() as session:
            user = await session.get(User, user_id)
            if not user:
                return True
            return bool(user.onboarded)
    except Exception:
        return True


async def set_onboarded(user_id: int) -> None:
    """Отметить онбординг как пройденный."""
    from sqlalchemy import update

    from shared.db.models.user import User

    async with get_session() as session:
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(onboarded=True, updated_at=datetime.now(timezone.utc))
        )


async def get_or_create_user(user_id, username=None, first_name=None, referral_code_from_start=None):
    from sqlalchemy import select, update

    from shared.config import settings
    from shared.db.models.user import User

    async with get_session() as session:
        user = await session.get(User, user_id)
        if user:
            now = datetime.now(timezone.utc)
            if user.credits_free_reset is None or user.credits_free_reset < date.today():
                update_vals: dict = {
                    "credits_free_today": settings.free_daily_credits,
                    "credits_free_reset": date.today(),
                    "updated_at": now,
                    "last_active_at": now,
                }
                if username is not None:
                    update_vals["username"] = username
                await session.execute(update(User).where(User.id == user_id).values(**update_vals))
                await session.flush()
                await session.refresh(user)
            else:
                await session.execute(
                    update(User)
                    .where(User.id == user_id)
                    .values(updated_at=now, last_active_at=now)
                )
                await session.flush()
                await session.refresh(user)
            return {c.key: getattr(user, c.key) for c in user.__table__.columns}

        # Создание нового пользователя
        ref_code = secrets.token_urlsafe(6)[:8]
        referred_by_id = None
        if referral_code_from_start:
            result = await session.execute(
                select(User.id).where(User.referral_code == referral_code_from_start)
            )
            referrer_id = result.scalar_one_or_none()
            if referrer_id and referrer_id != user_id:
                referred_by_id = referrer_id

        new_user = User(
            id=user_id,
            username=username,
            first_name=first_name,
            referral_code=ref_code,
            referred_by=referred_by_id,
            credits_free_today=settings.free_daily_credits,
            credits_free_reset=date.today(),
            credits_bought=REFEREE_CR if referred_by_id else 0,
        )
        session.add(new_user)
        await session.flush()

        if referred_by_id:
            # Lock referrer row for update
            ref_result = await session.execute(
                select(User).where(User.id == referred_by_id).with_for_update()
            )
            referrer = ref_result.scalar_one_or_none()
            if referrer:
                ref_count = (referrer.referral_count or 0) + 1
                _, multiplier = get_referral_level(ref_count)
                bonus = int(REFERRER_CR * multiplier)
                referrer.referral_count = ref_count
                referrer.credits_bought = (referrer.credits_bought or 0) + bonus
                await session.flush()

        await session.refresh(new_user)
        log.info("New user", user_id=user_id, referred_by=referred_by_id)
        return {c.key: getattr(new_user, c.key) for c in new_user.__table__.columns}


async def get_balance(user_id):
    cached = await _balance_cache_get(user_id)
    if cached is not None:
        return cached
    from sqlalchemy import select, update

    from shared.config import settings
    from shared.db.models.user import User

    async with get_session() as session:
        result = await session.execute(
            select(
                User.credits_bought,
                User.credits_free_today,
                User.credits_free_reset,
                User.credits_total_spent,
            ).where(User.id == user_id)
        )
        row = result.one_or_none()
        if not row:
            return {"bought": 0, "free": 0, "total": 0, "total_spent": 0}
        free = row.credits_free_today
        if row.credits_free_reset is None or row.credits_free_reset < date.today():
            free = settings.free_daily_credits
            await session.execute(
                update(User)
                .where(User.id == user_id)
                .values(credits_free_today=free, credits_free_reset=date.today())
            )
        out = {
            "bought": row.credits_bought,
            "free": free,
            "total": row.credits_bought + free,
            "total_spent": row.credits_total_spent,
        }
    await _balance_cache_set(user_id, out)
    return out


async def is_unlimited_active(user_id: int) -> bool:
    """True если у пользователя активен безлимит (unlimited_ends_at > сейчас)."""
    from sqlalchemy import select

    from shared.db.models.user import User

    async with get_session() as session:
        result = await session.execute(select(User.unlimited_ends_at).where(User.id == user_id))
        end = result.scalar_one_or_none()
    if not end:
        return False
    now = datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return now < end


async def get_unlimited_ends_at(user_id: int):
    """Дата окончания безлимита или None."""
    from sqlalchemy import select

    from shared.db.models.user import User

    async with get_session() as session:
        result = await session.execute(select(User.unlimited_ends_at).where(User.id == user_id))
        return result.scalar_one_or_none()


async def set_unlimited_until(user_id: int, days: int = 30) -> None:
    """Включить/продлить безлимит на days календарных дней. Если уже активен — продлеваем от текущей даты окончания."""
    from sqlalchemy import select, update

    from shared.db.models.user import User

    async with get_session() as session:
        result = await session.execute(select(User.unlimited_ends_at).where(User.id == user_id))
        end = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if end:
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            base = end if end > now else now
        else:
            base = now
        new_end = base + timedelta(days=days)
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(unlimited_ends_at=new_end, updated_at=datetime.now(timezone.utc))
        )
    await _balance_cache_invalidate(user_id)


# ── Полный доступ на 48 часов (одноразовая кнопка в меню) ──
FULL_ACCESS_48H_HOURS = 48


async def get_48h_status(user_id: int) -> dict:
    """Статус «Полный доступ на 48 часов»: can_activate, is_active, ends_at.

    Одноразовая активация: если full_access_48h_ends_at уже заполнен,
    кнопку повторно не показываем даже после истечения.
    """
    from shared.db.models.user import User

    async with get_session() as session:
        user = await session.get(User, user_id)

    if not user:
        return {"can_activate": False, "is_active": False, "ends_at": None}

    ends_at = user.full_access_48h_ends_at
    now = datetime.now(timezone.utc)
    if ends_at and ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=timezone.utc)
    is_active = ends_at is not None and now < ends_at
    can_activate = ends_at is None
    return {"can_activate": can_activate, "is_active": is_active, "ends_at": ends_at}


async def activate_48h_full_access(user_id: int) -> bool:
    """Включить полный доступ на 48 часов ровно один раз.

    Возвращает:
      True  — активация выполнена сейчас;
      False — уже активирован ранее (повтор запрещён).
    """
    from sqlalchemy import update

    from shared.db.models.user import User

    async with get_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return False
        if user.full_access_48h_ends_at is not None:
            return False
        now = datetime.now(timezone.utc)
        new_end = now + timedelta(hours=FULL_ACCESS_48H_HOURS)
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(full_access_48h_ends_at=new_end, updated_at=datetime.now(timezone.utc))
        )
    await _balance_cache_invalidate(user_id)
    return True


_admin_ids_cache: set[int] | None = None
_qa_tester_ids_cache: set[int] | None = None


def _is_admin_user(user_id: int) -> bool:
    """Проверка admin (cached set, parsed once)."""
    global _admin_ids_cache
    if _admin_ids_cache is None:
        from shared.config import settings
        if not settings.admin_ids:
            _admin_ids_cache = set()
        else:
            try:
                _admin_ids_cache = {int(x.strip()) for x in settings.admin_ids.split(",") if x.strip()}
            except (ValueError, AttributeError):
                _admin_ids_cache = set()
    return user_id in _admin_ids_cache


def _is_qa_tester_user(user_id: int) -> bool:
    """Пользователь может тестировать платный функционал без списания CR, но без admin-прав."""
    global _qa_tester_ids_cache
    if _qa_tester_ids_cache is None:
        from shared.config import settings
        if not getattr(settings, "qa_tester_ids", ""):
            _qa_tester_ids_cache = set()
        else:
            try:
                _qa_tester_ids_cache = {int(x.strip()) for x in settings.qa_tester_ids.split(",") if x.strip()}
            except (ValueError, AttributeError):
                _qa_tester_ids_cache = set()
    return user_id in _qa_tester_ids_cache


def _usage_bucket_for_model(model: str) -> str | None:
    """Map model_id to usage policy bucket."""
    if model in VIDEO_MODELS:
        return "video"
    if model in {"musicgen", "suno-v4"}:
        return "music"
    if model == "upscale":
        return "upscale"
    text_price = TEXT_CREDIT_PRICES.get(model)
    if text_price is not None and int(text_price) >= 15:
        return "elite_text"
    return None


def _seconds_until_utc_day_end() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).date()
    next_midnight = datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone.utc)
    return max(60, int((next_midnight - now).total_seconds()))


def _daily_limit_for_tier(tier: str, bucket: str) -> int:
    from shared.config import settings

    limits = {
        "trial": {
            "video": int(getattr(settings, "trial_video_daily_limit", 2) or 0),
            "music": int(getattr(settings, "trial_music_daily_limit", 5) or 0),
            "upscale": int(getattr(settings, "trial_upscale_daily_limit", 20) or 0),
            "elite_text": int(getattr(settings, "trial_elite_text_daily_limit", 60) or 0),
        },
        "full48h": {
            "video": int(getattr(settings, "full48_video_daily_limit", 4) or 0),
            "music": int(getattr(settings, "full48_music_daily_limit", 10) or 0),
            "upscale": int(getattr(settings, "full48_upscale_daily_limit", 40) or 0),
            "elite_text": int(getattr(settings, "full48_elite_text_daily_limit", 120) or 0),
        },
        "unlimited": {
            "video": int(getattr(settings, "unlimited_video_daily_limit", 6) or 0),
            "music": int(getattr(settings, "unlimited_music_daily_limit", 20) or 0),
            "upscale": int(getattr(settings, "unlimited_upscale_daily_limit", 80) or 0),
            "elite_text": int(getattr(settings, "unlimited_elite_text_daily_limit", 250) or 0),
        },
    }
    return int(limits.get(tier, {}).get(bucket, 0) or 0)


async def enforce_usage_policy(user_id: int, model: str) -> dict:
    """Enforce cooldown + daily caps for heavy features and zero-cost modes.

    Returns:
      {"ok": True, "tier": str, "bucket": str|None}
      {"ok": False, "reason": str, "message": str, ...}
    """
    bucket = _usage_bucket_for_model(model)
    if bucket is None:
        return {"ok": True, "tier": "paid", "bucket": None}

    from sqlalchemy import select

    from shared.db.models.user import User

    async with get_session() as session:
        result = await session.execute(
            select(
                User.username,
                User.trial_started_at,
                User.unlimited_ends_at,
                User.full_access_48h_ends_at,
            ).where(User.id == user_id)
        )
        row = result.one_or_none()

    if not row:
        return {"ok": False, "reason": "user_not_found", "message": "Пользователь не найден. Нажми /start."}

    now = datetime.now(timezone.utc)
    username = (row.username or "").lower()

    if _is_admin_user(user_id):
        tier = "admin"
    elif _is_qa_tester_user(user_id):
        tier = "qa"
    elif username and username in UNLIMITED_USERNAMES:
        tier = "admin"
    else:
        tier = "paid"
        trial_started = row.trial_started_at
        if trial_started is not None:
            trial_end = trial_started + timedelta(minutes=TRIAL_DURATION_MINUTES)
            if trial_started.tzinfo is None:
                trial_end = trial_end.replace(tzinfo=timezone.utc)
            if now < trial_end:
                tier = "trial"

        unlimited_end = row.unlimited_ends_at
        if tier == "paid" and unlimited_end is not None:
            if unlimited_end.tzinfo is None:
                unlimited_end = unlimited_end.replace(tzinfo=timezone.utc)
            if now < unlimited_end:
                tier = "unlimited"

        full_48h_end = row.full_access_48h_ends_at
        if tier == "paid" and full_48h_end is not None:
            if full_48h_end.tzinfo is None:
                full_48h_end = full_48h_end.replace(tzinfo=timezone.utc)
            if now < full_48h_end:
                tier = "full48h"

    try:
        from shared.redis.store import _get_redis

        r = await _get_redis()
    except Exception:
        r = None

    if not r:
        # Fail-open: если Redis недоступен, не блокируем основной сценарий.
        return {"ok": True, "tier": tier, "bucket": bucket}

    policy_usage: dict = {"tier": tier, "bucket": bucket}
    # Per-user cooldowns for heavy actions.
    if bucket in {"video", "music", "upscale"} and tier not in {"admin", "qa"}:
        from shared.config import settings

        cooldown_map = {
            "video": int(getattr(settings, "heavy_video_cooldown_sec", 45) or 0),
            "music": int(getattr(settings, "heavy_music_cooldown_sec", 30) or 0),
            "upscale": int(getattr(settings, "heavy_upscale_cooldown_sec", 15) or 0),
        }
        cooldown_sec = cooldown_map.get(bucket, 0)
        if cooldown_sec > 0:
            cd_key = f"policy:cooldown:{bucket}:{user_id}"
            set_ok = await r.set(cd_key, b"1", nx=True, ex=cooldown_sec)
            if set_ok:
                policy_usage["cooldown_key"] = cd_key
            if not set_ok:
                ttl = await r.ttl(cd_key)
                ttl = int(ttl if ttl and ttl > 0 else cooldown_sec)
                bucket_name = {"video": "видео", "music": "музыки", "upscale": "апскейла"}.get(bucket, bucket)
                return {
                    "ok": False,
                    "reason": "cooldown",
                    "retry_after_sec": ttl,
                    "message": f"⏳ Слишком часто для {bucket_name}. Повтори через {ttl} сек.",
                }

    # Daily hard-caps for zero-cost access tiers.
    if tier in {"trial", "full48h", "unlimited"}:
        daily_limit = _daily_limit_for_tier(tier, bucket)
        if daily_limit > 0:
            day_key = now.strftime("%Y%m%d")
            limit_key = f"policy:daily:{tier}:{bucket}:{user_id}:{day_key}"
            usage_count = await r.incr(limit_key)
            policy_usage["daily_limit_key"] = limit_key
            policy_usage["daily_incremented"] = True
            if usage_count == 1:
                await r.expire(limit_key, _seconds_until_utc_day_end() + 3600)
            if int(usage_count) > daily_limit:
                try:
                    rolled = await r.decr(limit_key)
                    if int(rolled or 0) <= 0:
                        await r.delete(limit_key)
                except Exception:
                    pass
                bucket_name = {
                    "video": "видео",
                    "music": "музыке",
                    "upscale": "апскейлу",
                    "elite_text": "дорогим текстовым моделям",
                }.get(bucket, bucket)
                tier_name = {"trial": "Trial", "full48h": "48h", "unlimited": "Unlimited"}.get(tier, tier)
                return {
                    "ok": False,
                    "reason": "daily_limit",
                    "message": (
                        f"⚠️ Достигнут дневной лимит по {bucket_name} для режима {tier_name} "
                        f"({daily_limit}/день). Пополни баланс или подожди до завтра."
                    ),
                    "daily_limit": daily_limit,
                }

    return {"ok": True, "tier": tier, "bucket": bucket, "policy_usage": policy_usage}


async def _rollback_policy_usage(policy_usage: dict | None) -> None:
    if not policy_usage or policy_usage.get("_rolled_back"):
        return
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
    except Exception:
        r = None
    if not r:
        return
    try:
        cooldown_key = policy_usage.get("cooldown_key")
        if cooldown_key:
            await r.delete(cooldown_key)
        if policy_usage.get("daily_incremented") and policy_usage.get("daily_limit_key"):
            limit_key = policy_usage["daily_limit_key"]
            try:
                new_val = await r.decr(limit_key)
                if int(new_val or 0) <= 0:
                    await r.delete(limit_key)
            except Exception:
                pass
    finally:
        policy_usage["_rolled_back"] = True


async def rollback_spend_usage_policy(spend: dict | None) -> None:
    if not spend:
        return
    await _rollback_policy_usage(spend.get("policy_usage"))


async def refund_spend_credits(user_id: int, spend: dict, reason: str = "ошибка генерации") -> bool:
    """Refund credits (if any) and release reserved policy counters/cooldown for failed attempts."""
    await rollback_spend_usage_policy(spend)
    amount = int(spend.get("cost", 0) or 0)
    if amount and not spend.get("trial") and not spend.get("unlimited"):
        await refund_credits(user_id, amount, reason)
        return True
    return False


async def spend_credits(user_id, model, description="", cost_override=None):
    cost = int(cost_override) if cost_override is not None else CREDIT_PRICES.get(model, 0)
    if cost == 0:
        return {"ok": True, "cost": 0}

    policy = await enforce_usage_policy(user_id, model)
    if not policy.get("ok", True):
        blocked = {
            "ok": False,
            "reason": policy.get("reason", "policy_block"),
            "cost": cost,
        }
        if policy.get("message"):
            blocked["message"] = policy["message"]
        if "retry_after_sec" in policy:
            blocked["retry_after_sec"] = policy["retry_after_sec"]
        if "daily_limit" in policy:
            blocked["daily_limit"] = policy["daily_limit"]
        return blocked

    # Single query to check all bypass conditions at once
    from sqlalchemy import select

    from shared.db.models.user import User

    async with get_session() as session:
        result = await session.execute(
            select(
                User.username,
                User.trial_started_at,
                User.unlimited_ends_at,
                User.full_access_48h_ends_at,
                User.credits_bought,
                User.credits_free_today,
            ).where(User.id == user_id)
        )
        bypass_row = result.one_or_none()

    if not bypass_row:
        await _rollback_policy_usage(policy.get("policy_usage"))
        return {"ok": False, "reason": "user_not_found", "policy_usage": policy.get("policy_usage")}

    # Check bypass: только владелец и админы из ADMIN_IDS
    uname = bypass_row.username
    if _is_admin_user(user_id) or (uname and uname.lower() in UNLIMITED_USERNAMES):
        return {"ok": True, "cost": 0, "unlimited": True,
                "bought": bypass_row.credits_bought,
                "free": bypass_row.credits_free_today,
                "policy_usage": policy.get("policy_usage")}
    if _is_qa_tester_user(user_id):
        return {"ok": True, "cost": 0, "qa_bypass": True,
                "bought": bypass_row.credits_bought,
                "free": bypass_row.credits_free_today,
                "policy_usage": policy.get("policy_usage")}

    # Trial check
    trial_started = bypass_row.trial_started_at
    if trial_started is not None:
        now = datetime.now(timezone.utc)
        exp = trial_started + timedelta(minutes=TRIAL_DURATION_MINUTES)
        if trial_started.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if now < exp:
            return {"ok": True, "cost": 0, "trial": True,
                    "bought": bypass_row.credits_bought,
                    "free": bypass_row.credits_free_today,
                    "policy_usage": policy.get("policy_usage")}

    # Unlimited subscription check
    unlimited_end = bypass_row.unlimited_ends_at
    if unlimited_end is not None:
        now = datetime.now(timezone.utc)
        if unlimited_end.tzinfo is None:
            unlimited_end = unlimited_end.replace(tzinfo=timezone.utc)
        if now < unlimited_end:
            return {"ok": True, "cost": 0, "unlimited": True,
                    "bought": bypass_row.credits_bought,
                    "free": bypass_row.credits_free_today,
                    "policy_usage": policy.get("policy_usage")}

    # Полный доступ на 48 часов (кнопка в меню)
    full_48h_end = bypass_row.full_access_48h_ends_at
    if full_48h_end is not None:
        now = datetime.now(timezone.utc)
        if full_48h_end.tzinfo is None:
            full_48h_end = full_48h_end.replace(tzinfo=timezone.utc)
        if now < full_48h_end:
            return {"ok": True, "cost": 0, "unlimited": True,
                    "bought": bypass_row.credits_bought,
                    "free": bypass_row.credits_free_today,
                    "policy_usage": policy.get("policy_usage")}

    # Actual credit deduction (atomic) — all in one session/transaction
    from sqlalchemy import update

    from shared.db.models.payment import CreditTransaction

    async with get_session() as session:
        result = await session.execute(
            select(
                User.credits_bought,
                User.credits_free_today,
                User.credits_free_reset,
            ).where(User.id == user_id).with_for_update()
        )
        user_row = result.one_or_none()
        if not user_row:
            await _rollback_policy_usage(policy.get("policy_usage"))
            return {"ok": False, "reason": "user_not_found", "policy_usage": policy.get("policy_usage")}
        free = user_row.credits_free_today
        bought = user_row.credits_bought
        if user_row.credits_free_reset is None or user_row.credits_free_reset < date.today():
            from shared.config import settings
            free = settings.free_daily_credits
        if model not in FREE_MODELS:
            if bought < cost:
                await _rollback_policy_usage(policy.get("policy_usage"))
                return {"ok": False, "reason": "need_bought_credits",
                        "cost": cost, "balance": bought, "policy_usage": policy.get("policy_usage")}
            bought -= cost
        else:
            if free >= cost:
                free -= cost
            elif free + bought >= cost:
                remainder = cost - free
                free = 0
                bought -= remainder
            else:
                await _rollback_policy_usage(policy.get("policy_usage"))
                return {"ok": False, "reason": "insufficient",
                        "cost": cost, "balance": free + bought, "policy_usage": policy.get("policy_usage")}
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                credits_bought=bought,
                credits_free_today=free,
                credits_free_reset=date.today(),
                credits_total_spent=User.credits_total_spent + cost,
                updated_at=datetime.now(timezone.utc),
            )
        )
        tx = CreditTransaction(
            user_id=user_id,
            amount=-cost,
            credits_bought_after=bought,
            credits_free_after=free,
            type="spend",
            description=description,
            model=model,
        )
        session.add(tx)
        await session.flush()

    await _balance_cache_invalidate(user_id)
    return {"ok": True, "cost": cost, "bought": bought, "free": free,
            "policy_usage": policy.get("policy_usage")}


async def add_credits(user_id, amount, tx_type="purchase", description=""):
    from sqlalchemy import select, update

    from shared.db.models.payment import CreditTransaction
    from shared.db.models.user import User

    async with get_session() as session:
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                credits_bought=User.credits_bought + amount,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.flush()
        result = await session.execute(
            select(User.credits_bought, User.credits_free_today).where(User.id == user_id)
        )
        user_row = result.one_or_none()
        tx = CreditTransaction(
            user_id=user_id,
            amount=amount,
            credits_bought_after=user_row.credits_bought if user_row else None,
            credits_free_after=user_row.credits_free_today if user_row else None,
            type=tx_type,
            description=description,
        )
        session.add(tx)
        await session.flush()

    await _balance_cache_invalidate(user_id)
    new_balance = user_row.credits_bought if user_row else None
    return {"ok": True, "new_balance": new_balance}


async def refund_credits(user_id: int, amount: int, reason: str = "ошибка генерации") -> None:
    """Вернуть кредиты пользователю (например, при сбое API после spend_credits)."""
    if amount <= 0:
        return
    await add_credits(user_id, amount, "refund", reason)


async def deduct_credits_refund(user_id: int, amount: int, description: str = "Возврат оплаты ЮKassa") -> dict:
    """Списать кредиты при refund.succeeded (возврат оплаты). Баланс не уходит в минус — списываем что есть."""
    if amount <= 0:
        return {"ok": True, "deducted": 0}
    from sqlalchemy import select, update

    from shared.db.models.payment import CreditTransaction
    from shared.db.models.user import User

    async with get_session() as session:
        result = await session.execute(
            select(User.credits_bought).where(User.id == user_id).with_for_update()
        )
        credits_bought = result.scalar_one_or_none()
        if credits_bought is None:
            return {"ok": False, "error": "user_not_found"}
        current = credits_bought or 0
        deduct = min(amount, current)
        if deduct <= 0:
            log.warning("Refund deduct: user has no credits", user_id=user_id, amount=amount)
            return {"ok": True, "deducted": 0}
        new_bought = current - deduct
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(credits_bought=new_bought, updated_at=datetime.now(timezone.utc))
        )
        tx = CreditTransaction(
            user_id=user_id,
            amount=-deduct,
            credits_bought_after=new_bought,
            credits_free_after=0,
            type="yookassa_refund",
            description=description[:200],
        )
        session.add(tx)
        await session.flush()

    await _balance_cache_invalidate(user_id)
    return {"ok": True, "deducted": deduct}


# Страйк-бонусы: (дней подряд, дополнительные CR)
STREAK_BONUSES = {3: 10, 7: 20, 14: 30, 30: 50}


async def try_grant_daily_login_bonus(user_id: int) -> dict | bool:
    """Выдать ежедневный бонус за вход (раз в сутки).
    Возвращает dict {granted, amount, streak} или False."""
    from shared.config import settings
    base_amount = getattr(settings, "daily_login_bonus_credits", 5)
    if base_amount <= 0:
        return False
    try:
        from sqlalchemy import select, update

        from shared.db.models.user import User

        async with get_session() as session:
            result = await session.execute(
                select(User.last_daily_bonus_date, User.login_streak).where(User.id == user_id)
            )
            row = result.one_or_none()
            if not row:
                return False
            last = row.last_daily_bonus_date
            streak = row.login_streak or 0
            if last is not None and last >= date.today():
                return False
            # Считаем страйк
            if last is not None and last == date.today() - timedelta(days=1):
                streak += 1
            else:
                streak = 1
            await session.execute(
                update(User)
                .where(User.id == user_id)
                .values(
                    last_daily_bonus_date=date.today(),
                    login_streak=streak,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        # Бонус за страйк
        streak_bonus = STREAK_BONUSES.get(streak, 0)
        total = base_amount + streak_bonus
        desc = f"Ежедневный бонус (+{base_amount})"
        if streak_bonus:
            desc += f" + страйк {streak} дн. (+{streak_bonus})"
        await add_credits(user_id, total, "daily_bonus", desc)
        log.info("Daily login bonus", user_id=user_id, amount=total, streak=streak)
        return {"granted": True, "amount": total, "streak": streak, "streak_bonus": streak_bonus}
    except Exception as e:
        log.warning("Daily bonus skip", user_id=user_id, error=str(e))
        return False

_MODEL_DEFAULTS = {
    "text": "gpt-5-nano", "image": "flux-2-turbo", "tts": "edge-tts",
    "tts_voice": "svetlana", "video": "kling-2.6", "music": "musicgen",
}
_MODEL_COLUMNS = {
    "text": "text_model", "image": "image_model", "tts": "tts_model",
    "tts_voice": "tts_voice", "video": "video_model", "music": "music_model",
}


async def get_all_user_models(user_id: int) -> dict[str, str]:
    """Fetch all model preferences in a single DB query (instead of 5 separate ones)."""
    from sqlalchemy import select

    from shared.db.models.user import User

    async with get_session() as session:
        result = await session.execute(
            select(
                User.text_model,
                User.image_model,
                User.tts_model,
                User.tts_voice,
                User.video_model,
                User.music_model,
            ).where(User.id == user_id)
        )
        row = result.one_or_none()
    if not row:
        return dict(_MODEL_DEFAULTS)
    return {
        task: (getattr(row, col) or default)
        for task, col, default in zip(
            _MODEL_DEFAULTS.keys(),
            _MODEL_COLUMNS.values(),
            _MODEL_DEFAULTS.values(),
        )
    }


async def get_user_model(user_id, task_type="text"):
    col = _MODEL_COLUMNS.get(task_type)
    default = _MODEL_DEFAULTS.get(task_type, "gpt-5-nano")
    if not col:
        return default
    from sqlalchemy import select

    from shared.db.models.user import User

    async with get_session() as session:
        result = await session.execute(
            select(getattr(User, col)).where(User.id == user_id)
        )
        val = result.scalar_one_or_none()
    return val or default


async def get_referral_code(user_id: int) -> str:
    from sqlalchemy import select

    from shared.db.models.user import User

    async with get_session() as session:
        result = await session.execute(select(User.referral_code).where(User.id == user_id))
        code = result.scalar_one_or_none()
        return code or ""


async def apply_promocode(user_id: int, code: str) -> dict:
    """Применить промокод. Возвращает {ok, credits?, error?}. Транзакция + FOR UPDATE — без гонки."""
    from sqlalchemy import select, update

    from shared.db.models.user import User
    from shared.db.models.worker_task import Promocode, PromoUse

    code = (code or "").strip().upper()
    if not code:
        return {"ok": False, "error": "Укажи код: /promo КОД"}

    async with get_session() as session:
        now_utc = datetime.now(timezone.utc)
        # Lock the promocode row
        promo_result = await session.execute(
            select(Promocode)
            .where(
                Promocode.code == code,
                (Promocode.expires_at.is_(None)) | (Promocode.expires_at > now_utc),
            )
            .with_for_update()
        )
        promo = promo_result.scalar_one_or_none()
        if not promo:
            return {"ok": False, "error": "Промокод не найден или истёк"}
        if promo.used_count >= promo.max_uses:
            return {"ok": False, "error": "Промокод исчерпан"}
        used_result = await session.execute(
            select(PromoUse).where(PromoUse.user_id == user_id, PromoUse.code == code)
        )
        used = used_result.scalar_one_or_none()
        if used:
            return {"ok": False, "error": "Ты уже использовал этот промокод"}

        credits = promo.credits
        promo.used_count = promo.used_count + 1
        session.add(PromoUse(user_id=user_id, code=code))
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(credits_bought=User.credits_bought + credits)
        )
        await session.flush()

    return {"ok": True, "credits": credits}


async def set_user_model(user_id, task_type, model):
    from sqlalchemy import update

    from shared.db.models.user import User

    col_map = {"text": "text_model", "image": "image_model",
               "tts": "tts_model", "tts_voice": "tts_voice", "video": "video_model", "music": "music_model"}
    col = col_map.get(task_type)
    if col:
        async with get_session() as session:
            await session.execute(
                update(User)
                .where(User.id == user_id)
                .values(**{col: model, "updated_at": datetime.now(timezone.utc)})
            )


async def create_payment_record(user_id: int, payment_id: str, amount_rub: float, credits_amount: int, pack_name: str) -> bool:
    """Записать платёж в БД (status=pending). Возвращает True если запись создана, False если дубликат."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from shared.db.models.payment import Payment

    async with get_session() as session:
        stmt = (
            pg_insert(Payment)
            .values(
                user_id=user_id,
                payment_id=payment_id,
                amount_rub=amount_rub,
                credits_amount=credits_amount,
                pack_name=pack_name,
                status="pending",
            )
            .on_conflict_do_nothing(index_elements=["payment_id"])
            .returning(Payment.id)
        )
        result = await session.execute(stmt)
        inserted_id = result.scalar_one_or_none()

    created = inserted_id is not None
    if not created:
        log.info("create_payment_record_duplicate", payment_id=payment_id, user_id=user_id)
    return created


async def get_payment_by_yookassa_id(payment_id: str):
    """Найти платёж по payment_id ЮKassa. Возвращает row или None."""
    from shared.db.repositories.payment import PaymentRepository

    async with get_session() as session:
        repo = PaymentRepository(session)
        payment = await repo.get_by_payment_id(payment_id)
        if payment is None:
            return None
        # Return dict-like object compatible with existing callers
        return {c.key: getattr(payment, c.key) for c in payment.__table__.columns}


async def get_last_pending_payment(user_id: int):
    """Последний ожидающий платёж пользователя (для проверки после return_url)."""
    from shared.db.repositories.payment import PaymentRepository

    async with get_session() as session:
        repo = PaymentRepository(session)
        payment = await repo.get_pending_for_user(user_id)
        if payment is None:
            return None
        return {c.key: getattr(payment, c.key) for c in payment.__table__.columns}


async def confirm_payment_record(payment_id: str):
    """Атомарно пометить pending-платёж подтверждённым и вернуть row, либо None если уже подтверждён/не найден."""
    from sqlalchemy import select, update

    from shared.db.models.payment import Payment
    from shared.db.models.user import User

    async with get_session() as session:
        result = await session.execute(
            select(Payment)
            .where(Payment.payment_id == payment_id, Payment.status == "pending")
            .with_for_update()
        )
        payment = result.scalar_one_or_none()
        if not payment:
            return None
        now = datetime.now(timezone.utc)
        payment.status = "confirmed"
        if payment.confirmed_at is None:
            payment.confirmed_at = now
        await session.flush()
        from sqlalchemy import func as sqlfunc

        await session.execute(
            update(User)
            .where(User.id == payment.user_id)
            .values(
                total_payments_rub=User.total_payments_rub + float(payment.amount_rub),
                first_paid_at=sqlfunc.coalesce(User.first_paid_at, now),
                last_paid_at=now,
            )
        )
        await session.flush()
        return {c.key: getattr(payment, c.key) for c in payment.__table__.columns}


_PROVIDER_KEYWORDS = {
    "gemini": "google", "veo": "google", "claude": "anthropic",
    "grok": "xai", "deepseek": "deepseek",
    "flux": "falai", "kling": "falai", "runway": "falai", "seedance": "falai",
    "luma": "falai", "hailuo": "falai", "wanx": "falai", "freely": "falai",
    "rmbg": "falai", "upscale": "falai", "musicgen": "falai", "suno": "falai",
    "edge-tts": "edge", "whisper": "openai",
}


def _detect_provider(model: str) -> str:
    for kw, prov in _PROVIDER_KEYWORDS.items():
        if kw in model:
            return prov
    return "openai"


async def log_ai_request(user_id: int, task_type: str, model: str, prompt: str = "",
                         status: str = "completed", credits_charged: int = 0,
                         duration_ms: int = 0, error_message: str = "") -> None:
    """Log an AI request to ai_requests for statistics."""
    try:
        from shared.db.models.ai_request import AIRequest

        async with get_session() as session:
            req = AIRequest(
                user_id=user_id,
                task_type=task_type,
                model=model,
                prompt=(prompt or "")[:200],
                status=status,
                credits_charged=credits_charged,
                duration_ms=duration_ms,
                error_message=(error_message or "")[:500],
            )
            session.add(req)
            await session.flush()
    except Exception:
        pass
