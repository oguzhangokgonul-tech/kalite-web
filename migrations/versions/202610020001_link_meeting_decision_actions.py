"""Link meeting decisions to actions.

Revision ID: 202610020001
Revises: 202610010001
Create Date: 2026-10-02
"""

from alembic import op
import sqlalchemy as sa


revision = "202610020001"
down_revision = "202610010001"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "meeting_decision_actions" not in existing:
        op.create_table(
            "meeting_decision_actions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column(
                "decision_id", sa.Integer(), sa.ForeignKey("meeting_decisions.id", ondelete="RESTRICT"),
                nullable=False, unique=True,
            ),
            sa.Column(
                "action_id", sa.Integer(), sa.ForeignKey("actions.id", ondelete="RESTRICT"),
                nullable=False, unique=True,
            ),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_meeting_decision_actions_company_id", "meeting_decision_actions", ["company_id"])


def downgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "meeting_decision_actions" in existing:
        op.drop_table("meeting_decision_actions")
