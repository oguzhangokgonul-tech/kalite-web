"""add organization node type

Revision ID: 202606040001
Revises: 202606010001
Create Date: 2026-06-04 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606040001"
down_revision = "202606010001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "orientation_nodes" in tables:
        columns = {column["name"] for column in inspector.get_columns("orientation_nodes")}
        if "node_type" not in columns:
            with op.batch_alter_table("orientation_nodes", schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "node_type",
                        sa.String(length=40),
                        nullable=False,
                        server_default="person",
                    )
                )
        op.execute(
            "UPDATE orientation_nodes SET node_type = 'person' "
            "WHERE node_type IS NULL OR node_type = ''"
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "orientation_nodes" in tables:
        columns = {column["name"] for column in inspector.get_columns("orientation_nodes")}
        if "node_type" in columns:
            with op.batch_alter_table("orientation_nodes", schema=None) as batch_op:
                batch_op.drop_column("node_type")
