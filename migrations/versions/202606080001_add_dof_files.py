"""add dof files

Revision ID: 202606080001
Revises: 202606060004
Create Date: 2026-06-08 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606080001"
down_revision = "202606060004"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "dof_files" not in tables:
        op.create_table(
            "dof_files",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("dof_id", sa.Integer(), nullable=False),
            sa.Column("original_name", sa.String(length=255), nullable=False),
            sa.Column("stored_name", sa.String(length=255), nullable=False),
            sa.Column("mime_type", sa.String(length=120), nullable=True),
            sa.Column("file_type", sa.String(length=40), nullable=False, server_default="opening"),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["dof_id"], ["dofs.id"]),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "dof_files" in tables:
        op.drop_table("dof_files")
