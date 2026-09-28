"""add tenant and user language preferences

Revision ID: 202609280001
Revises: 202609270001
"""

from alembic import op
import sqlalchemy as sa


revision = "202609280001"
down_revision = "202609270001"
branch_labels = None
depends_on = None


def _has_column(bind, table_name, column_name):
    return column_name in {
        column["name"] for column in sa.inspect(bind).get_columns(table_name)
    }


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "companies" in tables and not _has_column(bind, "companies", "default_locale"):
        op.add_column(
            "companies",
            sa.Column("default_locale", sa.String(10), nullable=False, server_default="tr"),
        )
    if "users" in tables and not _has_column(bind, "users", "preferred_locale"):
        op.add_column(
            "users",
            sa.Column("preferred_locale", sa.String(10), nullable=True),
        )

    if "app_settings" in tables:
        key = "sales_readiness:competitor_multilanguage"
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
    tables = set(sa.inspect(bind).get_table_names())
    if "app_settings" in tables:
        bind.execute(
            sa.text(
                "DELETE FROM app_settings "
                "WHERE key = 'sales_readiness:competitor_multilanguage'"
            )
        )
    if "users" in tables and _has_column(bind, "users", "preferred_locale"):
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_column("preferred_locale")
    if "companies" in tables and _has_column(bind, "companies", "default_locale"):
        with op.batch_alter_table("companies") as batch_op:
            batch_op.drop_column("default_locale")
