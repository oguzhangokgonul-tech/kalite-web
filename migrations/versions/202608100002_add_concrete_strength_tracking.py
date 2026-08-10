"""add concrete strength tracking

Revision ID: 202608100002
Revises: 202608100001
Create Date: 2026-08-10 00:02:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202608100002"
down_revision = "202608100001"
branch_labels = None
depends_on = None


STRENGTH_COLUMNS = (
    ("strength_2_day", sa.Float()),
    ("strength_2_recorded_at", sa.DateTime()),
    ("strength_7_day", sa.Float()),
    ("strength_7_recorded_at", sa.DateTime()),
    ("strength_28_day", sa.Float()),
    ("strength_28_recorded_at", sa.DateTime()),
)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "quality_test_records" not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns("quality_test_records")}
    for column_name, column_type in STRENGTH_COLUMNS:
        if column_name not in columns:
            op.add_column(
                "quality_test_records",
                sa.Column(column_name, column_type, nullable=True),
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "quality_test_records" not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns("quality_test_records")}
    for column_name, _column_type in reversed(STRENGTH_COLUMNS):
        if column_name in columns:
            op.drop_column("quality_test_records", column_name)
