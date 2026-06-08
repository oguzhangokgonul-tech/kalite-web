"""add internal audit evaluator department

Revision ID: 202606080005
Revises: 202606080004
Create Date: 2026-06-08 00:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606080005"
down_revision = "202606080004"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "internal_audit_questions" in tables:
        columns = {column["name"] for column in inspector.get_columns("internal_audit_questions")}
        if "evaluator_department" not in columns:
            op.add_column(
                "internal_audit_questions",
                sa.Column("evaluator_department", sa.String(length=80), nullable=True),
            )

    if "internal_audit_answers" in tables:
        columns = {column["name"] for column in inspector.get_columns("internal_audit_answers")}
        if "evaluator_department" not in columns:
            op.add_column(
                "internal_audit_answers",
                sa.Column("evaluator_department", sa.String(length=80), nullable=True),
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "internal_audit_answers" in tables:
        columns = {column["name"] for column in inspector.get_columns("internal_audit_answers")}
        if "evaluator_department" in columns:
            op.drop_column("internal_audit_answers", "evaluator_department")

    if "internal_audit_questions" in tables:
        columns = {column["name"] for column in inspector.get_columns("internal_audit_questions")}
        if "evaluator_department" in columns:
            op.drop_column("internal_audit_questions", "evaluator_department")
