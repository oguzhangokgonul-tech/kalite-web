"""add login attempts audit table

Revision ID: 202608120003
Revises: 202608120002
Create Date: 2026-08-12 00:03:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202608120003"
down_revision = "202608120002"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "login_attempts" in set(inspector.get_table_names()):
        return

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=160), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_login_attempts_username_created_at",
        "login_attempts",
        ["username", "created_at"],
    )
    op.create_index(
        "ix_login_attempts_ip_created_at",
        "login_attempts",
        ["ip_address", "created_at"],
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "login_attempts" not in set(inspector.get_table_names()):
        return

    indexes = {index["name"] for index in inspector.get_indexes("login_attempts")}
    if "ix_login_attempts_ip_created_at" in indexes:
        op.drop_index("ix_login_attempts_ip_created_at", table_name="login_attempts")
    if "ix_login_attempts_username_created_at" in indexes:
        op.drop_index("ix_login_attempts_username_created_at", table_name="login_attempts")
    op.drop_table("login_attempts")
