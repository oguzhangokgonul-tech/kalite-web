"""add centralized roles and permissions

Revision ID: 202608120001
Revises: 202608100002
Create Date: 2026-08-12 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202608120001"
down_revision = "202608100002"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "roles" not in tables:
        op.create_table(
            "roles",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("key", sa.String(length=80), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("hierarchy_level", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("key"),
        )

    if "role_permissions" not in tables:
        op.create_table(
            "role_permissions",
            sa.Column("role_id", sa.Integer(), nullable=False),
            sa.Column("permission_key", sa.String(length=120), nullable=False),
            sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
            sa.PrimaryKeyConstraint("role_id", "permission_key"),
        )

    if "user_roles" not in tables:
        op.create_table(
            "user_roles",
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("role_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("user_id", "role_id"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "user_roles" in tables:
        op.drop_table("user_roles")
    if "role_permissions" in tables:
        op.drop_table("role_permissions")
    if "roles" in tables:
        op.drop_table("roles")
