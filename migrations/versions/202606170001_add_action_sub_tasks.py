"""add action sub tasks

Revision ID: 202606170001
Revises: 202606100002
Create Date: 2026-06-17 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606170001"
down_revision = "202606100002"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "action_sub_tasks" not in tables:
        op.create_table(
            "action_sub_tasks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("parent_action_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=160), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("responsible_id", sa.Integer(), nullable=True),
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column("priority", sa.String(length=40), nullable=False, server_default="Orta"),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="Beklemede"),
            sa.Column("evidence_required", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("evidence_original_name", sa.String(length=255), nullable=True),
            sa.Column("evidence_stored_name", sa.String(length=255), nullable=True),
            sa.Column("evidence_mime_type", sa.String(length=120), nullable=True),
            sa.Column("closing_note", sa.Text(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("completed_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["parent_action_id"], ["actions.id"]),
            sa.ForeignKeyConstraint(["responsible_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["completed_by_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "action_sub_tasks" in tables:
        op.drop_table("action_sub_tasks")
