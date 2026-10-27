"""Allow explicit per-user permission decisions.

Revision ID: 202610270001
Revises: 202610260002
"""

from alembic import op
import sqlalchemy as sa


revision = "202610270001"
down_revision = "202610260002"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if "roles" in sa.inspect(connection).get_table_names() and "permissions_customized" not in {
        column["name"] for column in sa.inspect(connection).get_columns("roles")
    }:
        op.add_column("roles", sa.Column(
            "permissions_customized", sa.Boolean, nullable=False, server_default="0",
        ))
    if "user_permissions" not in sa.inspect(connection).get_table_names():
        op.create_table(
            "user_permissions",
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("permission_key", sa.String(120), primary_key=True),
            sa.Column("is_allowed", sa.Boolean, nullable=False, server_default="1"),
        )
    elif "is_allowed" not in {column["name"] for column in sa.inspect(connection).get_columns("user_permissions")}:
        op.add_column(
            "user_permissions",
            sa.Column("is_allowed", sa.Boolean, nullable=False, server_default="1"),
        )
    if {"roles", "role_permissions"} <= set(sa.inspect(connection).get_table_names()):
        defaults = (
            ("management_representative", "suggestions.evaluate"),
            ("management_representative", "suggestions.manage_evaluators"),
            ("management", "customer_portal.view_all"),
            ("company_admin", "suggestions.evaluate"),
            ("company_admin", "suggestions.manage_evaluators"),
            ("company_admin", "customer_portal.view_all"),
            ("super_admin", "suggestions.evaluate"),
            ("super_admin", "suggestions.manage_evaluators"),
            ("super_admin", "customer_portal.view_all"),
        )
        for role_key, permission_key in defaults:
            connection.execute(sa.text("""
                INSERT INTO role_permissions (role_id, permission_key)
                SELECT roles.id, :permission_key FROM roles
                WHERE roles.key = :role_key
                AND NOT EXISTS (
                    SELECT 1 FROM role_permissions
                    WHERE role_permissions.role_id = roles.id
                      AND role_permissions.permission_key = :permission_key
                )
            """), {"role_key": role_key, "permission_key": permission_key})


def downgrade():
    connection = op.get_bind()
    if "roles" in sa.inspect(connection).get_table_names() and "permissions_customized" in {
        column["name"] for column in sa.inspect(connection).get_columns("roles")
    }:
        customized = connection.execute(sa.text(
            "SELECT 1 FROM roles WHERE permissions_customized = 1 LIMIT 1"
        )).scalar()
        if customized:
            raise RuntimeError("Customized role templates exist; back them up before downgrade.")
    has_decisions = "user_permissions" in sa.inspect(connection).get_table_names() and "is_allowed" in {
        column["name"] for column in sa.inspect(connection).get_columns("user_permissions")
    }
    if has_decisions:
        denied = connection.execute(
            sa.text("SELECT 1 FROM user_permissions WHERE is_allowed = 0 LIMIT 1")
        ).scalar()
        if denied:
            raise RuntimeError("Explicit permission denials exist; back them up and remove them before downgrade.")
        with op.batch_alter_table("user_permissions") as batch:
            batch.drop_column("is_allowed")
    if "roles" in sa.inspect(connection).get_table_names() and "permissions_customized" in {
        column["name"] for column in sa.inspect(connection).get_columns("roles")
    }:
        with op.batch_alter_table("roles") as batch:
            batch.drop_column("permissions_customized")
