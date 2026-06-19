"""add document revision date

Revision ID: 202606190002
Revises: 202606190001
Create Date: 2026-06-19 00:02:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606190002"
down_revision = "202606190001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "documents" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("documents")}
    if "revision_date" not in columns:
        op.add_column("documents", sa.Column("revision_date", sa.Date(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "documents" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("documents")}
    if "revision_date" in columns:
        with op.batch_alter_table("documents", schema=None) as batch_op:
            batch_op.drop_column("revision_date")
