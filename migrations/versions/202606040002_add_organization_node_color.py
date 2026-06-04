"""add organization node color

Revision ID: 202606040002
Revises: 202606040001
Create Date: 2026-06-04 00:02:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606040002"
down_revision = "202606040001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "orientation_nodes" in tables:
        columns = {column["name"] for column in inspector.get_columns("orientation_nodes")}
        if "color" not in columns:
            with op.batch_alter_table("orientation_nodes", schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "color",
                        sa.String(length=20),
                        nullable=False,
                        server_default="#198754",
                    )
                )
        op.execute(
            "UPDATE orientation_nodes SET color = '#198754' "
            "WHERE color IS NULL OR color = ''"
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "orientation_nodes" in tables:
        columns = {column["name"] for column in inspector.get_columns("orientation_nodes")}
        if "color" in columns:
            with op.batch_alter_table("orientation_nodes", schema=None) as batch_op:
                batch_op.drop_column("color")
