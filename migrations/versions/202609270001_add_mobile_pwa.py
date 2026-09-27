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
    if "app_settings" not in set(sa.inspect(bind).get_table_names()):
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


def downgrade():
    bind = op.get_bind()
    if "app_settings" in set(sa.inspect(bind).get_table_names()):
        bind.execute(
            sa.text(
                "DELETE FROM app_settings "
                "WHERE key = 'sales_readiness:competitor_mobile_pwa'"
            )
        )
