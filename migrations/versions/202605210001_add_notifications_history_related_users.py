"""add notifications history related users

Revision ID: 202605210001
Revises: 202605160001
Create Date: 2026-05-21 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202605210001"
down_revision = "202605160001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "actions" in tables:
        columns = {column["name"] for column in inspector.get_columns("actions")}
        with op.batch_alter_table("actions", schema=None) as batch_op:
            if "related_user_1_id" not in columns:
                batch_op.add_column(
                    sa.Column("related_user_1_id", sa.Integer(), nullable=True)
                )
            if "related_user_2_id" not in columns:
                batch_op.add_column(
                    sa.Column("related_user_2_id", sa.Integer(), nullable=True)
                )

    if "action_histories" not in tables:
        op.create_table(
            "action_histories",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("action_id", sa.Integer(), nullable=False),
            sa.Column("actor_user_id", sa.Integer(), nullable=True),
            sa.Column("event_type", sa.String(length=40), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.ForeignKeyConstraint(["action_id"], ["actions.id"]),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if "notifications" not in tables:
        op.create_table(
            "notifications",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("action_id", sa.Integer(), nullable=True),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column(
                "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["action_id"], ["actions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "notifications" in tables:
        op.drop_table("notifications")
    if "action_histories" in tables:
        op.drop_table("action_histories")

    if "actions" in tables:
        columns = {column["name"] for column in inspector.get_columns("actions")}
        with op.batch_alter_table("actions", schema=None) as batch_op:
            if "related_user_2_id" in columns:
                batch_op.drop_column("related_user_2_id")
            if "related_user_1_id" in columns:
                batch_op.drop_column("related_user_1_id")
