"""add internal audit scope fields

Revision ID: 202606090001
Revises: 202606080005
Create Date: 2026-06-09 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606090001"
down_revision = "202606080005"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "internal_audits" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("internal_audits")}
    if "evaluated_department" not in columns:
        op.add_column(
            "internal_audits",
            sa.Column("evaluated_department", sa.String(length=80), nullable=True),
        )
    if "audited_user_id" not in columns:
        op.add_column(
            "internal_audits",
            sa.Column("audited_user_id", sa.Integer(), nullable=True),
        )

    if "internal_audit_questions" in tables:
        bind.execute(
            sa.text(
                """
                UPDATE internal_audits
                SET evaluated_department = (
                    SELECT q.evaluated_department
                    FROM internal_audit_questions q
                    WHERE q.audit_id = internal_audits.id
                      AND q.evaluated_department IS NOT NULL
                      AND q.evaluated_department != ''
                    ORDER BY q.order_no ASC, q.id ASC
                    LIMIT 1
                )
                WHERE (evaluated_department IS NULL OR evaluated_department = '')
                """
            )
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "internal_audits" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("internal_audits")}
    if "audited_user_id" in columns:
        op.drop_column("internal_audits", "audited_user_id")
    if "evaluated_department" in columns:
        op.drop_column("internal_audits", "evaluated_department")
