"""add dofs

Revision ID: 202606060001
Revises: 202606040004
Create Date: 2026-06-06 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606060001"
down_revision = "202606040004"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "dofs" not in tables:
        op.create_table(
            "dofs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("dof_no", sa.String(length=30), nullable=False),
            sa.Column("title", sa.String(length=160), nullable=True),
            sa.Column("department", sa.String(length=80), nullable=True),
            sa.Column("responsible_id", sa.Integer(), nullable=True),
            sa.Column("opening_date", sa.Date(), nullable=True),
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column("priority", sa.String(length=40), nullable=True),
            sa.Column("source", sa.String(length=120), nullable=True),
            sa.Column("nonconformity_description", sa.Text(), nullable=True),
            sa.Column("root_cause_analysis", sa.Text(), nullable=True),
            sa.Column("corrective_action", sa.Text(), nullable=True),
            sa.Column("preventive_action", sa.Text(), nullable=True),
            sa.Column("closing_evidence", sa.Text(), nullable=True),
            sa.Column("evidence_original_name", sa.String(length=255), nullable=True),
            sa.Column("evidence_stored_name", sa.String(length=255), nullable=True),
            sa.Column("evidence_mime_type", sa.String(length=120), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="Taslak"),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["responsible_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("dof_no"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "dofs" in tables:
        op.drop_table("dofs")
