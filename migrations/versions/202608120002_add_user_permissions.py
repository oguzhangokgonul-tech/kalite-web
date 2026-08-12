"""add user specific permissions

Revision ID: 202608120002
Revises: 202608120001
Create Date: 2026-08-12 00:02:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202608120002"
down_revision = "202608120001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "user_permissions" in set(inspector.get_table_names()):
        return

    op.create_table(
        "user_permissions",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("permission_key", sa.String(length=120), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "permission_key"),
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "user_permissions" in set(inspector.get_table_names()):
        op.drop_table("user_permissions")
