"""add dof notifications

Revision ID: 202606060003
Revises: 202606060002
Create Date: 2026-06-06 00:03:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606060003"
down_revision = "202606060002"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "notifications" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("notifications")}
    if "dof_id" not in columns:
        with op.batch_alter_table("notifications", schema=None) as batch_op:
            batch_op.add_column(sa.Column("dof_id", sa.Integer(), nullable=True))
            if "dofs" in tables:
                batch_op.create_foreign_key(
                    "fk_notifications_dof_id_dofs",
                    "dofs",
                    ["dof_id"],
                    ["id"],
                )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "notifications" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("notifications")}
    if "dof_id" in columns:
        with op.batch_alter_table("notifications", schema=None) as batch_op:
            if "dofs" in tables:
                batch_op.drop_constraint(
                    "fk_notifications_dof_id_dofs",
                    type_="foreignkey",
                )
            batch_op.drop_column("dof_id")
