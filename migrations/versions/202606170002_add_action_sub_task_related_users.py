"""add action sub task related users

Revision ID: 202606170002
Revises: 202606170001
Create Date: 2026-06-17 00:02:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606170002"
down_revision = "202606170001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "action_sub_tasks" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("action_sub_tasks")}
    with op.batch_alter_table("action_sub_tasks") as batch_op:
        if "related_user_1_id" not in columns:
            batch_op.add_column(sa.Column("related_user_1_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_action_sub_tasks_related_user_1_id_users",
                "users",
                ["related_user_1_id"],
                ["id"],
            )
        if "related_user_2_id" not in columns:
            batch_op.add_column(sa.Column("related_user_2_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_action_sub_tasks_related_user_2_id_users",
                "users",
                ["related_user_2_id"],
                ["id"],
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "action_sub_tasks" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("action_sub_tasks")}
    with op.batch_alter_table("action_sub_tasks") as batch_op:
        if "related_user_2_id" in columns:
            batch_op.drop_constraint(
                "fk_action_sub_tasks_related_user_2_id_users",
                type_="foreignkey",
            )
            batch_op.drop_column("related_user_2_id")
        if "related_user_1_id" in columns:
            batch_op.drop_constraint(
                "fk_action_sub_tasks_related_user_1_id_users",
                type_="foreignkey",
            )
            batch_op.drop_column("related_user_1_id")
