"""add action department

Revision ID: 202605140004
Revises: 202605140003
Create Date: 2026-05-14 00:04:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202605140004"
down_revision = "202605140003"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("actions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "department",
                sa.String(length=80),
                nullable=False,
                server_default="Kalite",
            )
        )


def downgrade():
    with op.batch_alter_table("actions", schema=None) as batch_op:
        batch_op.drop_column("department")
