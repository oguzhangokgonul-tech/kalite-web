"""add orientation nodes

Revision ID: 202606010001
Revises: 202605250001
Create Date: 2026-06-01 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606010001"
down_revision = "202605250001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "orientation_nodes" not in tables:
        op.create_table(
            "orientation_nodes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("parent_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("title", sa.String(length=160), nullable=True),
            sa.Column("x", sa.Integer(), nullable=False, server_default="120"),
            sa.Column("y", sa.Integer(), nullable=False, server_default="80"),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["parent_id"], ["orientation_nodes.id"]),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "orientation_nodes" in tables:
        op.drop_table("orientation_nodes")
