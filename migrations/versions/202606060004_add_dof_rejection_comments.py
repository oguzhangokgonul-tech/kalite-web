"""add dof rejection comments

Revision ID: 202606060004
Revises: 202606060003
Create Date: 2026-06-06 00:04:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606060004"
down_revision = "202606060003"
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

    if "dofs" in tables:
        columns = {column["name"] for column in inspector.get_columns("dofs")}
        add_column_if_missing(
            "dofs",
            columns,
            sa.Column("rejection_reason", sa.Text(), nullable=True),
        )
        add_column_if_missing(
            "dofs",
            columns,
            sa.Column("rejected_by_user_id", sa.Integer(), nullable=True),
        )
        add_column_if_missing(
            "dofs",
            columns,
            sa.Column("rejected_at", sa.DateTime(), nullable=True),
        )
        add_column_if_missing(
            "dofs",
            columns,
            sa.Column("rejected_step", sa.String(length=40), nullable=True),
        )

    if "dof_comments" not in tables:
        op.create_table(
            "dof_comments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("dof_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("comment", sa.Text(), nullable=False),
            sa.Column("comment_type", sa.String(length=40), nullable=False, server_default="note"),
            sa.Column(
                "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.ForeignKeyConstraint(["dof_id"], ["dofs.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "dof_comments" in tables:
        op.drop_table("dof_comments")

    if "dofs" in tables:
        columns = {column["name"] for column in inspector.get_columns("dofs")}
        for column_name in (
            "rejected_step",
            "rejected_at",
            "rejected_by_user_id",
            "rejection_reason",
        ):
            if column_name in columns:
                op.drop_column("dofs", column_name)
