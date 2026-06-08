"""add internal audits

Revision ID: 202606080002
Revises: 202606080001
Create Date: 2026-06-08 00:02:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606080002"
down_revision = "202606080001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "internal_audits" not in tables:
        op.create_table(
            "internal_audits",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("audit_no", sa.String(length=30), nullable=False),
            sa.Column("title", sa.String(length=160), nullable=False),
            sa.Column("auditor_id", sa.Integer(), nullable=True),
            sa.Column("planned_date", sa.Date(), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="Devam Ediyor"),
            sa.Column("active_question_order", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["auditor_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("audit_no"),
        )

    if "internal_audit_questions" not in tables:
        op.create_table(
            "internal_audit_questions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("audit_id", sa.Integer(), nullable=False),
            sa.Column("order_no", sa.Integer(), nullable=False),
            sa.Column("standard", sa.String(length=160), nullable=False),
            sa.Column("audit_topic", sa.String(length=200), nullable=False),
            sa.Column("question_text", sa.Text(), nullable=False),
            sa.Column("evaluated_department", sa.String(length=80), nullable=True),
            sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["audit_id"], ["internal_audits.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if "internal_audit_answers" not in tables:
        op.create_table(
            "internal_audit_answers",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("audit_id", sa.Integer(), nullable=False),
            sa.Column("question_id", sa.Integer(), nullable=False),
            sa.Column("standard", sa.String(length=160), nullable=False),
            sa.Column("audit_topic", sa.String(length=200), nullable=False),
            sa.Column("question_text", sa.Text(), nullable=False),
            sa.Column("evaluated_department", sa.String(length=80), nullable=True),
            sa.Column("technical_findings", sa.Text(), nullable=True),
            sa.Column("result", sa.String(length=40), nullable=True),
            sa.Column("previous_nonconformity_id", sa.Integer(), nullable=True),
            sa.Column("dof_id", sa.Integer(), nullable=True),
            sa.Column("answered_by_user_id", sa.Integer(), nullable=True),
            sa.Column("answered_at", sa.DateTime(), nullable=True),
            sa.Column("is_draft", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["answered_by_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["audit_id"], ["internal_audits.id"]),
            sa.ForeignKeyConstraint(["dof_id"], ["dofs.id"]),
            sa.ForeignKeyConstraint(["previous_nonconformity_id"], ["dofs.id"]),
            sa.ForeignKeyConstraint(["question_id"], ["internal_audit_questions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    for table_name in (
        "internal_audit_answers",
        "internal_audit_questions",
        "internal_audits",
    ):
        if table_name in tables:
            op.drop_table(table_name)
