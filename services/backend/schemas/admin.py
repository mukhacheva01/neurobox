"""Pydantic-схемы request/response для Admin API."""
from datetime import datetime

from pydantic import BaseModel, Field


# --- Auth ---
class LoginRequest(BaseModel):
    login: str
    password: str
    otp: str | None = None


class LoginResponse(BaseModel):
    token: str | None = None
    admin_user_id: int | None = None
    admin_login: str | None = None
    admin_role: str | None = None
    admin_tg_id: int | None = None
    otp_required: bool = False


class AuditLogRequest(BaseModel):
    bot_identifier: str | None = None
    action: str
    entity_type: str | None = None
    entity_id: str | None = None
    details: dict | None = None
    ip: str | None = None


# --- Stats ---
class StatsResponse(BaseModel):
    period: str
    total_users: int
    new_users: int
    new_users_change_pct: float | None = None
    revenue: float
    revenue_change_pct: float | None = None
    paying_users: int
    total_generations: int
    cr_trial_to_paid: float | None = None
    arpu: float | None = None
    arppu: float | None = None
    churn_pct: float | None = None
    referrals: int
    likes: int
    dislikes: int
    rating_pct: float | None = None
    dau: int = 0
    wau: int = 0
    mau: int = 0
    stickiness_pct: float | None = None
    ai_cost_usd: float = 0.0
    ai_cost_rub: float = 0.0
    infra_cost_rub: float = 0.0
    margin_rub: float = 0.0
    segment_counts: dict[str, int] = Field(default_factory=dict)


class ChartResponse(BaseModel):
    labels: list[str]
    new_users: list[int]
    revenue: list[float]
    likes: list[int]
    dislikes: list[int]


class ModelStat(BaseModel):
    name: str
    count: int


class StatsModelsResponse(BaseModel):
    models: list[ModelStat]


class CohortRow(BaseModel):
    date: str
    total: int
    d1: float
    d3: float
    d7: float
    d14: float
    d30: float


class RetentionResponse(BaseModel):
    cohorts: list[CohortRow]


class PromoRow(BaseModel):
    code: str
    uses: int
    revenue: float
    cr: float | None = None


class PromosResponse(BaseModel):
    promos: list[PromoRow]


class ReferralRow(BaseModel):
    user_id: int
    name: str | None = None
    username: str | None = None
    count: int
    revenue: float


class ReferralsResponse(BaseModel):
    referrals: list[ReferralRow]


class HourlyResponse(BaseModel):
    hours: list[int]


class TrendsResponse(BaseModel):
    labels: list[str]
    users: list[int]
    revenue: list[float]


# --- Users ---
class UserListItem(BaseModel):
    telegram_id: int
    first_name: str | None = None
    username: str | None = None
    status: str
    ltv: float
    credits: int
    is_unlimited: bool
    generations: int
    referral_count: int
    created_at: datetime | None = None
    last_active_at: datetime | None = None
    source: str | None = None
    acquisition_channel: str | None = None
    utm_source: str | None = None
    bots: list[str] = Field(default_factory=list)


class UsersListResponse(BaseModel):
    total: int
    page: int
    limit: int
    users: list[UserListItem]


class PaymentItem(BaseModel):
    id: str | None = None
    date: datetime | None = None
    plan: str | None = None
    amount: float
    status: str
    promo: str | None = None


class TransactionItem(BaseModel):
    date: datetime | None = None
    type: str
    amount: int
    description: str | None = None


class UserDetailResponse(BaseModel):
    telegram_id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    status: str
    ltv: float
    credits: int
    is_unlimited: bool
    generations: int
    referral_count: int
    referrer_id: int | None = None
    created_at: datetime | None = None
    last_active_at: datetime | None = None
    acquisition_channel: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None
    start_payload: str | None = None
    first_paid_at: datetime | None = None
    last_paid_at: datetime | None = None
    notes: str = ""
    payments: list[PaymentItem] = Field(default_factory=list)
    transactions: list[TransactionItem] = Field(default_factory=list)


class BlockResponse(BaseModel):
    success: bool
    status: str


class CreditsRequest(BaseModel):
    amount: int
    description: str | None = None


class UnlimitedRequest(BaseModel):
    is_unlimited: bool


class NoteRequest(BaseModel):
    text: str


class MessageRequest(BaseModel):
    text: str


# --- Payments ---
class PaymentUserRef(BaseModel):
    telegram_id: int
    first_name: str | None = None
    username: str | None = None


class PaymentListItem(BaseModel):
    payment_id: str | None = None
    date: datetime | None = None
    user: PaymentUserRef | None = None
    bot: str
    plan: str | None = None
    amount: float
    status: str
    provider: str | None = None
    promo: str | None = None


class ProviderSplitRow(BaseModel):
    provider: str
    count: int
    revenue: float


class PaymentsListResponse(BaseModel):
    total: int
    total_revenue: float
    avg_check: float
    refunds: int
    refunds_amount: float = 0.0
    confirmed_count: int = 0
    providers: list[ProviderSplitRow] = Field(default_factory=list)
    payments: list[PaymentListItem]


# --- Errors ---
class ErrorItem(BaseModel):
    id: int
    time: datetime | None = None
    level: str
    source: str | None = None
    bot: str | None = None
    message: str
    user_id: int | None = None
    task_type: str | None = None
    model: str | None = None
    count: int = 1


class ErrorsListResponse(BaseModel):
    total: int
    errors: list[ErrorItem]


# --- Bots ---
class BotStat(BaseModel):
    id: str
    name: str
    handle: str
    users: int
    paying: int
    revenue: float
    cr: float | None = None
    generations: int


class BotsStatsResponse(BaseModel):
    bots: list[BotStat]
