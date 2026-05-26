"""FastAPI router: все эндпоинты Admin API."""
import csv
import io
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from services.backend.schemas import admin as schemas
from services.backend.services import admin as service
from services.backend.deps import (
    issue_admin_token,
    require_api_key,
    require_role,
)

router = APIRouter()

_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_WINDOW_SEC = 900
_LOGIN_MAX_ATTEMPTS = 5


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    if forwarded:
        return forwarded
    client = getattr(request, "client", None)
    return getattr(client, "host", "unknown") or "unknown"


def _login_allowed(ip: str) -> bool:
    now = time.time()
    bucket = [ts for ts in _LOGIN_ATTEMPTS.get(ip, []) if now - ts <= _LOGIN_WINDOW_SEC]
    _LOGIN_ATTEMPTS[ip] = bucket
    return len(bucket) < _LOGIN_MAX_ATTEMPTS


def _login_failed(ip: str) -> None:
    now = time.time()
    bucket = [ts for ts in _LOGIN_ATTEMPTS.get(ip, []) if now - ts <= _LOGIN_WINDOW_SEC]
    bucket.append(now)
    _LOGIN_ATTEMPTS[ip] = bucket


def _login_succeeded(ip: str) -> None:
    _LOGIN_ATTEMPTS.pop(ip, None)


@router.post("/auth/login", response_model=schemas.LoginResponse)
async def login(body: schemas.LoginRequest, request: Request):
    from shared.config import settings
    ip = _client_ip(request)
    if not _login_allowed(ip):
        raise HTTPException(status_code=429, detail="Too many login attempts")

    expected_login = (settings.admin_login or "admin").strip()
    expected_password = (settings.admin_password or "").strip()
    if not expected_password or body.login.strip() != expected_login or body.password != expected_password:
        _login_failed(ip)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if body.otp:
        totp_secret = (getattr(settings, "admin_panel_totp_secret", "") or "").strip()
        if totp_secret:
            import pyotp
            if not pyotp.TOTP(totp_secret).verify(body.otp, valid_window=1):
                _login_failed(ip)
                raise HTTPException(status_code=401, detail="Invalid OTP")

    _login_succeeded(ip)
    admin_tg_id = (settings.admin_tg_id_list or [None])[0] if getattr(settings, "admin_tg_id_list", None) else None
    ttl = int(getattr(settings, "admin_api_token_ttl_sec", 3600) or 3600)
    return schemas.LoginResponse(
        token=issue_admin_token(
            admin_tg_id=admin_tg_id,
            ttl_sec=ttl,
            admin_user_id=None,
            admin_login=expected_login,
            admin_role="superadmin",
        ),
        admin_user_id=None,
        admin_login=expected_login,
        admin_role="superadmin",
        admin_tg_id=admin_tg_id,
    )


def _audit_meta(payload: dict) -> dict:
    return {
        "admin_tg_id": payload.get("admin_tg_id"),
        "admin_user_id": payload.get("admin_user_id"),
        "admin_login": payload.get("admin_login"),
        "admin_role": payload.get("admin_role"),
    }


@router.get("/stats", response_model=schemas.StatsResponse)
async def get_stats(period: str = Query("week", regex="^(day|week|month|year)$"), _: dict = Depends(require_api_key)):
    data = await service.get_stats(period)
    return schemas.StatsResponse(**data)


@router.get("/stats/chart", response_model=schemas.ChartResponse)
async def get_chart(period: str = Query("week", regex="^(day|week|month|year)$"), _: dict = Depends(require_api_key)):
    data = await service.get_chart(period)
    return schemas.ChartResponse(**data)


@router.get("/stats/models", response_model=schemas.StatsModelsResponse)
async def get_models(_: dict = Depends(require_api_key)):
    models = await service.get_models_stats()
    return schemas.StatsModelsResponse(models=[schemas.ModelStat(**m) for m in models])


@router.get("/stats/retention", response_model=schemas.RetentionResponse)
async def get_retention(_: dict = Depends(require_api_key)):
    cohorts = await service.get_retention()
    return schemas.RetentionResponse(cohorts=[schemas.CohortRow(**c) for c in cohorts])


@router.get("/stats/promos", response_model=schemas.PromosResponse)
async def get_promos(_: dict = Depends(require_api_key)):
    promos = await service.get_promos()
    return schemas.PromosResponse(promos=[schemas.PromoRow(**p) for p in promos])


@router.get("/stats/referrals", response_model=schemas.ReferralsResponse)
async def get_referrals(_: dict = Depends(require_api_key)):
    referrals = await service.get_referrals_top()
    return schemas.ReferralsResponse(referrals=[schemas.ReferralRow(**r) for r in referrals])


@router.get("/stats/hourly", response_model=schemas.HourlyResponse)
async def get_hourly(_: dict = Depends(require_api_key)):
    hours = await service.get_hourly_msk()
    return schemas.HourlyResponse(hours=hours)


@router.get("/stats/trends", response_model=schemas.TrendsResponse)
async def get_trends(_: dict = Depends(require_api_key)):
    data = await service.get_trends()
    return schemas.TrendsResponse(**data)


@router.get("/stats/bots", response_model=schemas.BotsStatsResponse)
async def get_bots_stats(_: dict = Depends(require_api_key)):
    from shared.config import settings
    bot_id = service._bot_id()
    name = getattr(settings, "bot_username", bot_id) or bot_id
    stats = await service.get_stats("month")
    users = await service.get_users_list(None, None, "created_at", "desc", 1, 1)
    bots = [{
        "id": bot_id,
        "name": name,
        "handle": f"@{name}" if not name.startswith("@") else name,
        "users": users["total"],
        "paying": stats.get("paying_users", 0),
        "revenue": stats.get("revenue", 0),
        "cr": stats.get("cr_trial_to_paid"),
        "generations": stats.get("total_generations", 0),
    }]
    return schemas.BotsStatsResponse(bots=[schemas.BotStat(**b) for b in bots])


@router.get("/users", response_model=schemas.UsersListResponse)
async def users_list(
    search: str | None = None,
    status: str | None = Query(None, alias="status"),
    sort: str = Query("created_at"),
    dir: str = Query("desc", regex="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    _: dict = Depends(require_api_key),
):
    data = await service.get_users_list(search, status, sort, dir, page, limit)
    return schemas.UsersListResponse(
        total=data["total"],
        page=data["page"],
        limit=data["limit"],
        users=[schemas.UserListItem(**u) for u in data["users"]],
    )


@router.get("/users/{telegram_id}", response_model=schemas.UserDetailResponse)
async def user_detail(telegram_id: int, _: dict = Depends(require_api_key)):
    user = await service.get_user_detail(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return schemas.UserDetailResponse(
        payments=[schemas.PaymentItem(**p) for p in user["payments"]],
        transactions=[schemas.TransactionItem(**t) for t in user["transactions"]],
        **{k: v for k, v in user.items() if k not in ("payments", "transactions")},
    )


@router.post("/users/{telegram_id}/block", response_model=schemas.BlockResponse)
async def block_user(telegram_id: int, request: Request, _: dict = Depends(require_role("admin", "owner"))):
    admin = _
    await service.block_user(telegram_id)
    meta = _audit_meta(admin)
    await service.log_admin_audit(meta["admin_tg_id"], "block", "user", str(telegram_id), None, meta["admin_user_id"], meta["admin_login"], meta["admin_role"])
    return schemas.BlockResponse(success=True, status="blocked")


@router.post("/users/{telegram_id}/unblock")
async def unblock_user(telegram_id: int, request: Request, _: dict = Depends(require_role("admin", "owner"))):
    admin = _
    await service.unblock_user(telegram_id)
    meta = _audit_meta(admin)
    await service.log_admin_audit(meta["admin_tg_id"], "unblock", "user", str(telegram_id), None, meta["admin_user_id"], meta["admin_login"], meta["admin_role"])
    return {"success": True, "status": "active"}


@router.post("/users/{telegram_id}/credits")
async def user_credits(telegram_id: int, body: schemas.CreditsRequest, request: Request, _: dict = Depends(require_role("admin", "owner"))):
    admin = _
    admin_tg_id = admin.get("admin_tg_id") or 0
    if body.amount > 0:
        await service.add_credits_to_user(telegram_id, body.amount, body.description, admin_tg_id)
    else:
        ok = await service.deduct_credits_from_user(telegram_id, abs(body.amount), body.description, admin_tg_id)
        if not ok:
            raise HTTPException(status_code=400, detail="Insufficient credits or user not found")
    await service.log_admin_audit(admin_tg_id, "credits", "user", str(telegram_id), {"amount": body.amount}, admin.get("admin_user_id"), admin.get("admin_login"), admin.get("admin_role"))
    return {"success": True}


@router.post("/users/{telegram_id}/unlimited")
async def user_unlimited(telegram_id: int, body: schemas.UnlimitedRequest, request: Request, _: dict = Depends(require_role("admin", "owner"))):
    admin = _
    admin_tg_id = admin.get("admin_tg_id") or 0
    await service.set_user_unlimited(telegram_id, body.is_unlimited, admin_tg_id)
    await service.log_admin_audit(admin_tg_id, "unlimited", "user", str(telegram_id), {"is_unlimited": body.is_unlimited}, admin.get("admin_user_id"), admin.get("admin_login"), admin.get("admin_role"))
    return {"success": True}


@router.post("/users/{telegram_id}/note")
async def user_note(telegram_id: int, body: schemas.NoteRequest, request: Request, _: dict = Depends(require_role("support", "admin", "owner"))):
    admin = _
    admin_tg_id = admin.get("admin_tg_id") or 0
    await service.add_user_note(telegram_id, body.text, admin_tg_id)
    await service.log_admin_audit(admin_tg_id, "note", "user", str(telegram_id), None, admin.get("admin_user_id"), admin.get("admin_login"), admin.get("admin_role"))
    return {"success": True}


@router.post("/users/{telegram_id}/message")
async def user_message(telegram_id: int, body: schemas.MessageRequest, request: Request, _: dict = Depends(require_role("support", "admin", "owner"))):
    admin = _
    ok = await service.send_message_to_user(telegram_id, body.text)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to send message")
    admin_tg_id = admin.get("admin_tg_id") or 0
    await service.log_admin_audit(admin_tg_id, "message", "user", str(telegram_id), None, admin.get("admin_user_id"), admin.get("admin_login"), admin.get("admin_role"))
    return {"success": True}


@router.get("/payments", response_model=schemas.PaymentsListResponse)
async def payments_list(
    status: str | None = None,
    bot: str | None = Query(None, alias="bot"),
    provider: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    _: dict = Depends(require_api_key),
):
    data = await service.get_payments_list(status, bot, provider, page, limit)
    return schemas.PaymentsListResponse(
        total=data["total"],
        total_revenue=data["total_revenue"],
        avg_check=data["avg_check"],
        refunds=data["refunds"],
        refunds_amount=data["refunds_amount"],
        confirmed_count=data["confirmed_count"],
        providers=[schemas.ProviderSplitRow(**p) for p in data["providers"]],
        payments=[schemas.PaymentListItem(**p) for p in data["payments"]],
    )


@router.get("/errors", response_model=schemas.ErrorsListResponse)
async def errors_list(
    level: str | None = None,
    bot: str | None = Query(None, alias="bot"),
    sort: str = Query("time"),
    dir: str = Query("desc", regex="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    _: dict = Depends(require_api_key),
):
    data = await service.get_errors_list(level, bot, sort, dir, page, limit)
    return schemas.ErrorsListResponse(
        total=data["total"],
        errors=[schemas.ErrorItem(**e) for e in data["errors"]],
    )


@router.get("/errors/top")
async def errors_top(_: dict = Depends(require_api_key)):
    items = await service.get_errors_top()
    return {"errors": [schemas.ErrorItem(**e) for e in items]}


def _csv_response(rows: list[dict], filename: str) -> Response:
    if not rows:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=[], extrasaction="ignore")
        w.writeheader()
        body = "\uFEFF" + buf.getvalue()
    else:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        body = "\uFEFF" + buf.getvalue()
    return Response(content=body.encode("utf-8-sig"), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename={filename}"})


@router.get("/export/{type}")
async def export_csv(type: str, _: dict = Depends(require_api_key)):
    if type == "users":
        data = await service.get_users_list(None, None, "created_at", "desc", 1, 10000)
        rows = []
        for u in data["users"]:
            rows.append({
                "telegram_id": u["telegram_id"],
                "first_name": u.get("first_name") or "",
                "username": u.get("username") or "",
                "status": u["status"],
                "ltv": u["ltv"],
                "credits": u["credits"],
                "created_at": str(u.get("created_at") or ""),
            })
        return _csv_response(rows, "users.csv")
    if type == "payments":
        data = await service.get_payments_list(None, None, None, 1, 10000)
        rows = []
        for p in data["payments"]:
            rows.append({
                "payment_id": p.get("payment_id") or "",
                "date": str(p.get("date") or ""),
                "user_id": p.get("user", {}).get("telegram_id") if isinstance(p.get("user"), dict) else "",
                "amount": p.get("amount"),
                "status": p.get("status") or "",
                "provider": p.get("provider") or "",
                "plan": p.get("plan") or "",
            })
        return _csv_response(rows, "payments.csv")
    if type == "errors":
        data = await service.get_errors_list(None, None, "time", "desc", 1, 10000)
        rows = [{"id": e["id"], "time": str(e.get("time") or ""), "level": e.get("level"), "message": (e.get("message") or "")[:500], "count": e.get("count", 1)} for e in data["errors"]]
        return _csv_response(rows, "errors.csv")
    raise HTTPException(status_code=404, detail="Unknown export type")
