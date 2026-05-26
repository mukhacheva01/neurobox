"""User model."""
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user ID
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    referral_code: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    referred_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    referral_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    credits_bought: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    credits_free_today: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    credits_free_reset: Mapped[date | None] = mapped_column(Date, nullable=True)
    credits_total_spent: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    unlimited_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    full_access_48h_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    text_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    image_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tts_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tts_voice: Mapped[str | None] = mapped_column(String(128), nullable=True)
    video_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    music_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_daily_bonus_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    login_streak: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_payments_rub: Mapped[float] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    first_paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
