"""add companies table

Revision ID: 202608120004
Revises: 202608120003
Create Date: 2026-08-12 00:04:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202608120004"
down_revision = "202608120003"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "companies" not in set(inspector.get_table_names()):
        op.create_table(
            "companies",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("code", sa.String(length=3), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("code"),
        )

    companies = sa.table(
        "companies",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("is_active", sa.Boolean),
    )
    existing_codes = {
        row[0]
        for row in bind.execute(sa.text("SELECT code FROM companies WHERE code IN ('000', '001')"))
    }
    rows = []
    if "000" not in existing_codes:
        rows.append({"code": "000", "name": "Deneme Hesabı", "is_active": True})
    if "001" not in existing_codes:
        rows.append({"code": "001", "name": "Er Prefabrik", "is_active": True})
    if rows:
        op.bulk_insert(companies, rows)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "companies" in set(inspector.get_table_names()):
        op.drop_table("companies")
