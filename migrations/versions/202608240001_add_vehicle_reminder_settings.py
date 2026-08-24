"""add vehicle reminder settings

Revision ID: 202608240001
Revises: 202608210001
Create Date: 2026-08-24 15:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "202608240001"
down_revision = "202608210001"
branch_labels = None
depends_on = None


def _table_names(bind):
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table_name):
    if table_name not in _table_names(bind):
        return set()
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade():
    bind = op.get_bind()
    tables = _table_names(bind)

    if "vehicles" in tables and "reminder_days_before" not in _column_names(bind, "vehicles"):
        op.add_column(
            "vehicles",
            sa.Column(
                "reminder_days_before",
                sa.Integer(),
                nullable=False,
                server_default="7",
            ),
        )

    if "vehicle_reminder_recipients" not in tables:
        op.create_table(
            "vehicle_reminder_recipients",
            sa.Column("vehicle_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"]),
            sa.PrimaryKeyConstraint("vehicle_id", "user_id"),
        )
        op.create_index(
            "ix_vehicle_reminder_recipients_user_id",
            "vehicle_reminder_recipients",
            ["user_id"],
            unique=False,
        )


def downgrade():
    bind = op.get_bind()
    tables = _table_names(bind)

    if "vehicle_reminder_recipients" in tables:
        indexes = {
            index["name"]
            for index in sa.inspect(bind).get_indexes("vehicle_reminder_recipients")
        }
        if "ix_vehicle_reminder_recipients_user_id" in indexes:
            op.drop_index(
                "ix_vehicle_reminder_recipients_user_id",
                table_name="vehicle_reminder_recipients",
            )
        op.drop_table("vehicle_reminder_recipients")

    if "vehicles" in tables and "reminder_days_before" in _column_names(bind, "vehicles"):
        op.drop_column("vehicles", "reminder_days_before")
