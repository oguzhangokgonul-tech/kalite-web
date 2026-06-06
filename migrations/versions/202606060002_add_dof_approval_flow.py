"""add dof approval flow

Revision ID: 202606060002
Revises: 202606060001
Create Date: 2026-06-06 00:02:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606060002"
down_revision = "202606060001"
branch_labels = None
depends_on = None


def add_column_if_missing(table_name, columns, column):
    if column.name not in columns:
        op.add_column(table_name, column)
        columns.add(column.name)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "dofs" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("dofs")}
    add_column_if_missing(
        "dofs",
        columns,
        sa.Column(
            "approval_step",
            sa.String(length=40),
            nullable=False,
            server_default="draft",
        ),
    )
    add_column_if_missing(
        "dofs",
        columns,
        sa.Column("management_approved_by_user_id", sa.Integer(), nullable=True),
    )
    add_column_if_missing(
        "dofs",
        columns,
        sa.Column("management_approved_at", sa.DateTime(), nullable=True),
    )
    add_column_if_missing(
        "dofs",
        columns,
        sa.Column("deputy_approved_by_user_id", sa.Integer(), nullable=True),
    )
    add_column_if_missing(
        "dofs",
        columns,
        sa.Column("deputy_approved_at", sa.DateTime(), nullable=True),
    )
    add_column_if_missing(
        "dofs",
        columns,
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )

    op.execute(
        """
        UPDATE dofs
        SET approval_step = 'management_representative',
            status = 'Onay Akışı Bekleniyor'
        WHERE status IS NOT NULL
          AND status != 'Taslak'
          AND (approval_step IS NULL OR approval_step = 'draft')
        """
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "dofs" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("dofs")}
    for column_name in (
        "completed_at",
        "deputy_approved_at",
        "deputy_approved_by_user_id",
        "management_approved_at",
        "management_approved_by_user_id",
        "approval_step",
    ):
        if column_name in columns:
            op.drop_column("dofs", column_name)
