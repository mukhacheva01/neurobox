"""НейроБокс — lightweight analytics helpers for funnel and payments."""

import structlog

log = structlog.get_logger()


async def track(event_name: str, user_id: int, **props) -> None:
    """Insert event. Never raises — analytics must not break the bot."""
    try:
        from shared.db.repositories.event import EventRepository
        from shared.db.session import get_session

        async with get_session() as session:
            repo = EventRepository(session)
            await repo.create(
                event_name=event_name,
                user_id=user_id,
                properties=props if props else None,
            )
    except Exception:
        log.info(
            "analytics_event",
            event_name=event_name,
            user_id=user_id,
            **{k: str(v)[:100] for k, v in props.items()},
        )


async def track_paywall_view(
    user_id: int,
    task_description: str,
    need_cr: int,
    balance_cr: int,
    recommended_packs: list[str] | None = None,
    source: str = "smart_paywall",
) -> None:
    await track(
        "paywall_view",
        user_id,
        task=task_description[:120],
        need_cr=int(need_cr or 0),
        balance_cr=int(balance_cr or 0),
        recommended_packs=list(recommended_packs or []),
        source=source,
    )


async def track_paywall_hit(user_id: int, task_description: str, need_cr: int, balance_cr: int) -> None:
    await track_paywall_view(user_id, task_description, need_cr, balance_cr)


async def track_plan_selected(
    user_id: int,
    pack_name: str,
    price_rub: float = 0.0,
    credits: int = 0,
    source: str = "checkout",
    **extra,
) -> None:
    props = {
        "pack_name": str(pack_name or ""),
        "price_rub": float(price_rub or 0),
        "credits": int(credits or 0),
        "source": str(source or "checkout"),
    }
    if extra:
        props.update(extra)
    await track("plan_selected", user_id, **props)


async def track_payment_started(
    user_id: int,
    payment_id: str,
    method: str,
    pack_name: str = "",
    amount_rub: float = 0.0,
    credits: int = 0,
    is_test: bool = False,
    **extra,
) -> None:
    props = {
        "payment_id": str(payment_id or ""),
        "method": str(method or ""),
        "pack_name": str(pack_name or ""),
        "amount_rub": float(amount_rub or 0),
        "credits": int(credits or 0),
        "is_test": bool(is_test),
    }
    if extra:
        props.update(extra)
    await track("payment_started", user_id, **props)


async def track_payment_success(
    user_id: int,
    payment_id: str,
    method: str,
    pack_name: str = "",
    amount_rub: float = 0.0,
    credits: int = 0,
    is_test: bool = False,
    **extra,
) -> None:
    props = {
        "payment_id": str(payment_id or ""),
        "method": str(method or ""),
        "pack_name": str(pack_name or ""),
        "amount_rub": float(amount_rub or 0),
        "credits": int(credits or 0),
        "is_test": bool(is_test),
    }
    if extra:
        props.update(extra)
    await track("payment_success", user_id, **props)


async def track_payment_failed(
    user_id: int,
    method: str,
    pack_name: str = "",
    amount_rub: float = 0.0,
    credits: int = 0,
    reason: str = "",
    payment_id: str = "",
    is_test: bool = False,
    **extra,
) -> None:
    props = {
        "payment_id": str(payment_id or ""),
        "method": str(method or ""),
        "pack_name": str(pack_name or ""),
        "amount_rub": float(amount_rub or 0),
        "credits": int(credits or 0),
        "reason": str(reason or "")[:200],
        "is_test": bool(is_test),
    }
    if extra:
        props.update(extra)
    await track("payment_failed", user_id, **props)


async def track_first_value(
    user_id: int,
    task_type: str,
    model: str,
    success_event: str = "",
    **extra,
) -> None:
    props = {
        "task_type": str(task_type or ""),
        "model": str(model or ""),
        "success_event": str(success_event or ""),
    }
    if extra:
        props.update(extra)
    await track("first_value", user_id, **props)


async def track_premium_action(
    user_id: int,
    task_type: str,
    model: str,
    cr_cost: int = 0,
    success_event: str = "",
    **extra,
) -> None:
    props = {
        "task_type": str(task_type or ""),
        "model": str(model or ""),
        "cr_cost": int(cr_cost or 0),
        "success_event": str(success_event or ""),
    }
    if extra:
        props.update(extra)
    await track("premium_action", user_id, **props)
