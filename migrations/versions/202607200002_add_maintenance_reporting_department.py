"""add maintenance reporting department

Revision ID: 202607200002
Revises: 202607200001
Create Date: 2026-07-20 00:02:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202607200002"
down_revision = "202607200001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "maintenance_faults" not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns("maintenance_faults")}
    if "reporting_department" not in columns:
        op.add_column(
            "maintenance_faults",
            sa.Column("reporting_department", sa.String(length=80), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "maintenance_faults" not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns("maintenance_faults")}
    if "reporting_department" in columns:
        with op.batch_alter_table("maintenance_faults", schema=None) as batch_op:
            batch_op.drop_column("reporting_department")
