"""add internal audit expected answer

Revision ID: 202606080004
Revises: 202606080003
Create Date: 2026-06-08 00:04:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606080004"
down_revision = "202606080003"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "internal_audit_questions" in tables:
        columns = {column["name"] for column in inspector.get_columns("internal_audit_questions")}
        if "expected_answer" not in columns:
            op.add_column(
                "internal_audit_questions",
                sa.Column("expected_answer", sa.Text(), nullable=True),
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "internal_audit_questions" in tables:
        columns = {column["name"] for column in inspector.get_columns("internal_audit_questions")}
        if "expected_answer" in columns:
            op.drop_column("internal_audit_questions", "expected_answer")
