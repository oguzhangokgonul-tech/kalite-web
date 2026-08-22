"""add company modules

Revision ID: 202608210001
Revises: 202608170001
Create Date: 2026-08-21 16:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "202608210001"
down_revision = "202608170001"
branch_labels = None
depends_on = None


MODULE_KEYS = (
    "organization",
    "maintenance",
    "vehicles",
    "quality_tests",
    "quality_test_concrete",
    "quality_test_methylene",
    "quality_test_water_absorption",
    "quality_test_sieve_analysis",
    "quality_test_rebar_tensile",
    "if_management",
    "internal_audit",
    "documents",
)


def _table_names(bind):
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table_name):
    if table_name not in _table_names(bind):
        return set()
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade():
    bind = op.get_bind()
    tables = _table_names(bind)
    if "company_modules" not in tables:
        op.create_table(
            "company_modules",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("module_key", sa.String(length=80), nullable=False),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "company_id",
                "module_key",
                name="uq_company_modules_company_module",
            ),
        )
        op.create_index("ix_company_modules_company_id", "company_modules", ["company_id"])
        op.create_index("ix_company_modules_module_key", "company_modules", ["module_key"])

    if "companies" not in tables and "companies" not in _table_names(bind):
        return
    if not {"id"}.issubset(_column_names(bind, "companies")):
        return

    company_ids = [
        row[0]
        for row in bind.execute(sa.text("SELECT id FROM companies")).fetchall()
    ]
    for company_id in company_ids:
        for module_key in MODULE_KEYS:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO company_modules (company_id, module_key, is_enabled)
                    SELECT :company_id, :module_key, 1
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM company_modules
                        WHERE company_id = :company_id
                          AND module_key = :module_key
                    )
                    """
                ),
                {"company_id": company_id, "module_key": module_key},
            )


def downgrade():
    bind = op.get_bind()
    if "company_modules" not in _table_names(bind):
        return
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("company_modules")}
    if "ix_company_modules_module_key" in indexes:
        op.drop_index("ix_company_modules_module_key", table_name="company_modules")
    if "ix_company_modules_company_id" in indexes:
        op.drop_index("ix_company_modules_company_id", table_name="company_modules")
    op.drop_table("company_modules")
