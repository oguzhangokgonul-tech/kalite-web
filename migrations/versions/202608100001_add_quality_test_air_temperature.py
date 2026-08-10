"""add quality test air temperature

Revision ID: 202608100001
Revises: 202607210001
Create Date: 2026-08-10 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202608100001"
down_revision = "202607210001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "quality_test_records" not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns("quality_test_records")}
    if "air_temperature" not in columns:
        op.add_column(
            "quality_test_records",
            sa.Column("air_temperature", sa.Float(), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "quality_test_records" not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns("quality_test_records")}
    if "air_temperature" in columns:
        op.drop_column("quality_test_records", "air_temperature")
