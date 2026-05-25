"""add action numbers

Revision ID: 202605250001
Revises: 202605210001
Create Date: 2026-05-25 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202605250001"
down_revision = "202605210001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "actions" in tables:
        columns = {column["name"] for column in inspector.get_columns("actions")}
        if "action_number" not in columns:
            with op.batch_alter_table("actions", schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column("action_number", sa.Integer(), nullable=True)
                )

        op.execute("UPDATE actions SET action_number = id WHERE action_number IS NULL")

    if "app_settings" not in tables:
        op.create_table(
            "app_settings",
            sa.Column("key", sa.String(length=80), nullable=False),
            sa.Column("value", sa.String(length=255), nullable=False),
            sa.PrimaryKeyConstraint("key"),
        )

    max_number = bind.execute(
        sa.text("SELECT COALESCE(MAX(COALESCE(action_number, id)), 0) FROM actions")
    ).scalar()
    next_number = max_number + 1
    current_value = bind.execute(
        sa.text("SELECT value FROM app_settings WHERE key = 'next_action_number'")
    ).scalar()

    if current_value is None:
        bind.execute(
            sa.text(
                "INSERT INTO app_settings (key, value) "
                "VALUES ('next_action_number', :value)"
            ),
            {"value": str(next_number)},
        )
    elif int(current_value) <= max_number:
        bind.execute(
            sa.text(
                "UPDATE app_settings SET value = :value "
                "WHERE key = 'next_action_number'"
            ),
            {"value": str(next_number)},
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "app_settings" in tables:
        op.drop_table("app_settings")

    if "actions" in tables:
        columns = {column["name"] for column in inspector.get_columns("actions")}
        if "action_number" in columns:
            with op.batch_alter_table("actions", schema=None) as batch_op:
                batch_op.drop_column("action_number")
