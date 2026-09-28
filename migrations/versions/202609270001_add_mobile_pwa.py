"""mark tenant PWA and QR mobile center ready

Revision ID: 202609270001
Revises: 202609240001
"""

from alembic import op
import sqlalchemy as sa


revision = "202609270001"
down_revision = "202609240001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "app_settings" not in tables:
        return
    key = "sales_readiness:competitor_mobile_pwa"
    exists = bind.execute(
        sa.text("SELECT 1 FROM app_settings WHERE key = :key"),
        {"key": key},
    ).scalar()
    if not exists:
        bind.execute(
            sa.text("INSERT INTO app_settings (key, value) VALUES (:key, '1')"),
            {"key": key},
        )

    if {"roles", "role_permissions"}.issubset(tables):
        role_permissions = {
            "management_representative": (
                "helpdesk.view", "helpdesk.view_all", "helpdesk.create",
                "helpdesk.assign", "helpdesk.work", "helpdesk.comment",
                "helpdesk.manage", "helpdesk.archive", "helpdesk.file_download",
            ),
            "management": (
                "helpdesk.view", "helpdesk.view_all", "helpdesk.create",
                "helpdesk.comment", "helpdesk.file_download",
            ),
            "department_manager": (
                "helpdesk.view", "helpdesk.create", "helpdesk.work",
                "helpdesk.comment", "helpdesk.file_download",
            ),
            "department_staff": (
                "helpdesk.view", "helpdesk.create", "helpdesk.work",
                "helpdesk.comment", "helpdesk.file_download",
            ),
            "viewer": ("helpdesk.view", "helpdesk.file_download"),
        }
        for role_key, permission_keys in role_permissions.items():
            for permission_key in permission_keys:
                bind.execute(
                    sa.text(
                        """
                        INSERT INTO role_permissions (role_id, permission_key)
                        SELECT roles.id, :permission_key
                        FROM roles
                        WHERE roles.key = :role_key
                          AND NOT EXISTS (
                            SELECT 1 FROM role_permissions
                            WHERE role_id = roles.id
                              AND permission_key = :permission_key
                          )
                        """
                    ),
                    {"role_key": role_key, "permission_key": permission_key},
                )


def downgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "app_settings" in tables:
        bind.execute(
            sa.text(
                "DELETE FROM app_settings "
                "WHERE key = 'sales_readiness:competitor_mobile_pwa'"
            )
        )
    if {"roles", "role_permissions"}.issubset(tables):
        bind.execute(
            sa.text(
                """
                DELETE FROM role_permissions
                WHERE permission_key LIKE 'helpdesk.%'
                  AND role_id IN (
                    SELECT id FROM roles
                    WHERE key IN (
                      'management_representative', 'management',
                      'department_manager', 'department_staff', 'viewer'
                    )
                  )
                """
            )
        )
