"""add internal audit subject

Revision ID: 202606100002
Revises: 202606100001
Create Date: 2026-06-10 00:02:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606100002"
down_revision = "202606100001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "internal_audit_questions" in tables:
        columns = {column["name"] for column in inspector.get_columns("internal_audit_questions")}
        if "audit_subject" not in columns:
            op.add_column(
                "internal_audit_questions",
                sa.Column("audit_subject", sa.Text(), nullable=True),
            )

    if "internal_audit_answers" in tables:
        columns = {column["name"] for column in inspector.get_columns("internal_audit_answers")}
        if "audit_subject" not in columns:
            op.add_column(
                "internal_audit_answers",
                sa.Column("audit_subject", sa.Text(), nullable=True),
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "internal_audit_answers" in tables:
        columns = {column["name"] for column in inspector.get_columns("internal_audit_answers")}
        if "audit_subject" in columns:
            op.drop_column("internal_audit_answers", "audit_subject")

    if "internal_audit_questions" in tables:
        columns = {column["name"] for column in inspector.get_columns("internal_audit_questions")}
        if "audit_subject" in columns:
            op.drop_column("internal_audit_questions", "audit_subject")
