"""Durable notification digests and delivery ledger.

Revision ID: 202610020002
Revises: 202610020001
"""
from alembic import op
import sqlalchemy as sa

revision = "202610020002"
down_revision = "202610020001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "notification_email_batches" not in existing:
        op.create_table(
            "notification_email_batches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("send_date", sa.Date(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("item_count", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("finished_at", sa.DateTime()),
            sa.Column("error_code", sa.String(80)),
            sa.UniqueConstraint("company_id", "user_id", "send_date", name="uq_notification_batch_day"),
        )
        op.create_index("ix_notification_email_batches_company_id", "notification_email_batches", ["company_id"])
    if "notification_email_events" not in existing:
        op.create_table(
            "notification_email_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("dedupe_key", sa.String(64), nullable=False, unique=True),
            sa.Column("kind", sa.String(80), nullable=False),
            sa.Column("record_id", sa.Integer(), nullable=False),
            sa.Column("phase", sa.String(100), nullable=False),
            sa.Column("due_date", sa.Date()),
            sa.Column("notification_id", sa.Integer(), sa.ForeignKey("notifications.id", ondelete="SET NULL")),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("target_url", sa.String(500), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("batch_id", sa.Integer(), sa.ForeignKey("notification_email_batches.id")),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("accepted_at", sa.DateTime()),
        )
        for column in ("company_id", "user_id", "status"):
            op.create_index(f"ix_notification_email_events_{column}", "notification_email_events", [column])


def downgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for name in ("notification_email_events", "notification_email_batches"):
        if name in existing:
            op.drop_table(name)
