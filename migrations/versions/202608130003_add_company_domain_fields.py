"""add company domain fields

Revision ID: 202608130003
Revises: 202608130002
Create Date: 2026-08-13 03:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202608130003"
down_revision = "202608130002"
branch_labels = None
depends_on = None


def _table_names(bind):
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table_name):
    return {
        column["name"]
        for column in sa.inspect(bind).get_columns(table_name)
    }


def _index_names(bind, table_name):
    return {
        index["name"]
        for index in sa.inspect(bind).get_indexes(table_name)
    }


def _ensure_column(bind, table_name, column):
    if column.name in _column_names(bind, table_name):
        return

    with op.batch_alter_table(table_name) as batch_op:
        batch_op.add_column(column)


def _ensure_unique_index(bind, table_name, index_name, columns):
    if index_name in _index_names(bind, table_name):
        return

    op.create_index(index_name, table_name, columns, unique=True)


def upgrade():
    bind = op.get_bind()
    if "companies" not in _table_names(bind):
        return

    _ensure_column(bind, "companies", sa.Column("slug", sa.String(length=80), nullable=True))
    _ensure_column(bind, "companies", sa.Column("primary_domain", sa.String(length=255), nullable=True))
    _ensure_column(bind, "companies", sa.Column("custom_domain", sa.String(length=255), nullable=True))

    bind.execute(
        sa.text(
            """
            UPDATE companies
            SET slug = 'deneme',
                primary_domain = 'deneme.volkaportal.com'
            WHERE code = '000'
              AND (slug IS NULL OR slug = '')
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE companies
            SET slug = 'erprefabrik',
                primary_domain = 'erprefabrik.volkaportal.com'
            WHERE code = '001'
              AND (slug IS NULL OR slug = '')
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE companies
            SET slug = 'firma-' || code
            WHERE slug IS NULL OR slug = ''
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE companies
            SET primary_domain = slug || '.volkaportal.com'
            WHERE primary_domain IS NULL OR primary_domain = ''
            """
        )
    )

    _ensure_unique_index(bind, "companies", "ix_companies_slug_unique", ["slug"])
    _ensure_unique_index(bind, "companies", "ix_companies_primary_domain_unique", ["primary_domain"])
    _ensure_unique_index(bind, "companies", "ix_companies_custom_domain_unique", ["custom_domain"])


def downgrade():
    bind = op.get_bind()
    if "companies" not in _table_names(bind):
        return

    for index_name in (
        "ix_companies_custom_domain_unique",
        "ix_companies_primary_domain_unique",
        "ix_companies_slug_unique",
    ):
        if index_name in _index_names(bind, "companies"):
            op.drop_index(index_name, table_name="companies")

    existing_columns = _column_names(bind, "companies")
    with op.batch_alter_table("companies") as batch_op:
        if "custom_domain" in existing_columns:
            batch_op.drop_column("custom_domain")
        if "primary_domain" in existing_columns:
            batch_op.drop_column("primary_domain")
        if "slug" in existing_columns:
            batch_op.drop_column("slug")
