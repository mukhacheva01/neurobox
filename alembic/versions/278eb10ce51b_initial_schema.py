"""initial schema

Revision ID: 278eb10ce51b
Revises:
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "278eb10ce51b"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("first_name", sa.String(255), nullable=True),
        sa.Column("referral_code", sa.String(64), nullable=True),
        sa.Column("referred_by", sa.BigInteger(), nullable=True),
        sa.Column("referral_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("credits_bought", sa.Integer(), server_default="0", nullable=False),
        sa.Column("credits_free_today", sa.Integer(), server_default="0", nullable=False),
        sa.Column("credits_free_reset", sa.Date(), nullable=True),
        sa.Column("credits_total_spent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unlimited_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("full_access_48h_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("onboarded", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_blocked", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("text_model", sa.String(128), nullable=True),
        sa.Column("image_model", sa.String(128), nullable=True),
        sa.Column("tts_model", sa.String(128), nullable=True),
        sa.Column("tts_voice", sa.String(128), nullable=True),
        sa.Column("video_model", sa.String(128), nullable=True),
        sa.Column("music_model", sa.String(128), nullable=True),
        sa.Column("last_daily_bonus_date", sa.Date(), nullable=True),
        sa.Column("login_streak", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_payments_rub", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("first_paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("referral_code"),
    )

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("payment_id", sa.String(128), nullable=False),
        sa.Column("amount_rub", sa.Numeric(12, 2), nullable=False),
        sa.Column("credits_amount", sa.Integer(), nullable=False),
        sa.Column("pack_name", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_method", sa.String(64), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])

    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("credits_bought_after", sa.Integer(), nullable=True),
        sa.Column("credits_free_after", sa.Integer(), nullable=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("task_type", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_credit_transactions_user_id", "credit_transactions", ["user_id"])

    op.create_table(
        "ai_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("prompt", sa.String(200), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("credits_charged", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("cost_usd", sa.Numeric(16, 6), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_requests_user_id", "ai_requests", ["user_id"])

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_name", sa.String(128), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("properties", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_event_name", "events", ["event_name"])
    op.create_index("ix_events_user_id", "events", ["user_id"])

    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("action", sa.String(256), nullable=False),
        sa.Column("admin_user", sa.String(128), nullable=True),
        sa.Column("target", sa.String(256), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "error_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("level", sa.String(32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_error_logs_level", "error_logs", ["level"])

    op.create_table(
        "response_ratings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("rating", sa.String(16), nullable=True),
        sa.Column("task_type", sa.String(64), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_response_ratings_user_id", "response_ratings", ["user_id"])

    op.create_table(
        "promocodes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("used_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "promo_uses",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "code"),
    )

    op.create_table(
        "billing_plans",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("plan_key", sa.String(128), nullable=False),
        sa.Column("label", sa.String(256), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("price_rub", sa.Numeric(12, 2), nullable=True),
        sa.Column("price_stars", sa.Integer(), nullable=True),
        sa.Column("price_usd", sa.Numeric(12, 2), nullable=True),
        sa.Column("discount", sa.String(32), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_one_time", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_unlimited", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("period_days", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_key"),
    )

    op.create_table(
        "daily_stats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("metric", sa.String(128), nullable=False),
        sa.Column("value", sa.Numeric(16, 4), server_default="0", nullable=False),
        sa.Column("meta", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", "metric", name="uq_daily_stats_date_metric"),
    )

    op.create_table(
        "user_notes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("admin_user", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_notes_user_id", "user_notes", ["user_id"])


def downgrade() -> None:
    op.drop_table("user_notes")
    op.drop_table("daily_stats")
    op.drop_table("billing_plans")
    op.drop_table("promo_uses")
    op.drop_table("promocodes")
    op.drop_table("response_ratings")
    op.drop_table("error_logs")
    op.drop_table("admin_audit_log")
    op.drop_table("events")
    op.drop_table("ai_requests")
    op.drop_table("credit_transactions")
    op.drop_table("payments")
    op.drop_table("users")
