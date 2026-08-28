"""add project number to quality test records

Revision ID: 202608280001
Revises: 202608270001
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa


revision = "202608280001"
down_revision = "202608270001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "quality_test_records" not in inspector.get_table_names():
        return

    columns = {
        column["name"]
        for column in inspector.get_columns("quality_test_records")
    }
    if "project_number" not in columns:
        op.add_column(
            "quality_test_records",
            sa.Column("project_number", sa.String(length=80), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "quality_test_records" not in inspector.get_table_names():
        return

    columns = {
        column["name"]
        for column in inspector.get_columns("quality_test_records")
    }
    if "project_number" in columns:
        op.drop_column("quality_test_records", "project_number")
