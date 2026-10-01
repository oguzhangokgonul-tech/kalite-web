"""Add tenant-scoped meetings, participants and decisions.

Revision ID: 202610010001
Revises: 202609300001
Create Date: 2026-10-01
"""

from alembic import op
import sqlalchemy as sa


revision = "202610010001"
down_revision = "202609300001"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "meeting_records" not in existing:
        op.create_table(
            "meeting_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("meeting_at", sa.DateTime(), nullable=False),
            sa.Column("location", sa.String(240)),
            sa.Column("agenda", sa.Text()),
            sa.Column("minutes", sa.Text()),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
            sa.UniqueConstraint("company_id", "id", name="uq_meeting_records_company_id"),
            sa.CheckConstraint("status IN ('draft', 'open', 'completed', 'archived')", name="ck_meeting_records_status"),
        )
        for column in ("company_id", "meeting_at", "status", "created_by_user_id"):
            op.create_index(f"ix_meeting_records_{column}", "meeting_records", [column])

    if "meeting_participants" not in existing:
        op.create_table(
            "meeting_participants",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("meeting_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.UniqueConstraint("meeting_id", "user_id", name="uq_meeting_participants_meeting_user"),
            sa.ForeignKeyConstraint(
                ["company_id", "meeting_id"], ["meeting_records.company_id", "meeting_records.id"],
                name="fk_meeting_participants_company_meeting",
            ),
        )
        for column in ("company_id", "meeting_id", "user_id"):
            op.create_index(f"ix_meeting_participants_{column}", "meeting_participants", [column])

    if "meeting_decisions" not in existing:
        op.create_table(
            "meeting_decisions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("meeting_id", sa.Integer(), nullable=False),
            sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("due_date", sa.Date(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("completion_note", sa.Text()),
            sa.Column("completed_at", sa.DateTime()),
            sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
            sa.ForeignKeyConstraint(
                ["company_id", "meeting_id"], ["meeting_records.company_id", "meeting_records.id"],
                name="fk_meeting_decisions_company_meeting",
            ),
            sa.CheckConstraint("status IN ('open', 'completed')", name="ck_meeting_decisions_status"),
        )
        for column in ("company_id", "meeting_id", "owner_user_id", "due_date", "status"):
            op.create_index(f"ix_meeting_decisions_{column}", "meeting_decisions", [column])


def downgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("meeting_decisions", "meeting_participants", "meeting_records"):
        if table in existing:
            op.drop_table(table)
