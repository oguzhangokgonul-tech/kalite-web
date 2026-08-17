"""add vehicle management

Revision ID: 202608170001
Revises: 202608130005
Create Date: 2026-08-17 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202608170001"
down_revision = "202608130005"
branch_labels = None
depends_on = None


def _table_names(bind):
    return set(sa.inspect(bind).get_table_names())


def upgrade():
    bind = op.get_bind()
    tables = _table_names(bind)

    if "vehicles" not in tables:
        op.create_table(
            "vehicles",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=True),
            sa.Column("plate", sa.String(length=40), nullable=False),
            sa.Column("brand", sa.String(length=120), nullable=False),
            sa.Column("model", sa.String(length=120), nullable=False),
            sa.Column("owner", sa.String(length=160), nullable=False),
            sa.Column("traffic_insurance_due_date", sa.Date(), nullable=True),
            sa.Column("casco_insurance_due_date", sa.Date(), nullable=True),
            sa.Column("last_inspection_date", sa.Date(), nullable=True),
            sa.Column("next_inspection_due_date", sa.Date(), nullable=True),
            sa.Column("traffic_insurance_reminder_sent_at", sa.DateTime(), nullable=True),
            sa.Column("casco_insurance_reminder_sent_at", sa.DateTime(), nullable=True),
            sa.Column("next_inspection_reminder_sent_at", sa.DateTime(), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("company_id", "plate", name="uq_vehicles_company_plate"),
        )
        op.create_index("ix_vehicles_company_id", "vehicles", ["company_id"], unique=False)

    if "vehicle_operations" not in tables:
        op.create_table(
            "vehicle_operations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=True),
            sa.Column("vehicle_id", sa.Integer(), nullable=False),
            sa.Column("operation_date", sa.Date(), nullable=False),
            sa.Column("description", sa.String(length=255), nullable=False),
            sa.Column("amount_tl", sa.Numeric(12, 2), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_vehicle_operations_company_id", "vehicle_operations", ["company_id"], unique=False)
        op.create_index("ix_vehicle_operations_vehicle_id", "vehicle_operations", ["vehicle_id"], unique=False)

    if "vehicle_fuel_entries" not in tables:
        op.create_table(
            "vehicle_fuel_entries",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=True),
            sa.Column("vehicle_id", sa.Integer(), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("month", sa.Integer(), nullable=False),
            sa.Column("amount_tl", sa.Numeric(12, 2), nullable=True),
            sa.Column("fuel_liter", sa.Numeric(12, 2), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
            sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "company_id",
                "vehicle_id",
                "year",
                "month",
                name="uq_vehicle_fuel_entries_company_vehicle_month",
            ),
        )
        op.create_index("ix_vehicle_fuel_entries_company_id", "vehicle_fuel_entries", ["company_id"], unique=False)
        op.create_index("ix_vehicle_fuel_entries_vehicle_id", "vehicle_fuel_entries", ["vehicle_id"], unique=False)


def downgrade():
    bind = op.get_bind()
    tables = _table_names(bind)

    if "vehicle_fuel_entries" in tables:
        op.drop_index("ix_vehicle_fuel_entries_vehicle_id", table_name="vehicle_fuel_entries")
        op.drop_index("ix_vehicle_fuel_entries_company_id", table_name="vehicle_fuel_entries")
        op.drop_table("vehicle_fuel_entries")
    if "vehicle_operations" in tables:
        op.drop_index("ix_vehicle_operations_vehicle_id", table_name="vehicle_operations")
        op.drop_index("ix_vehicle_operations_company_id", table_name="vehicle_operations")
        op.drop_table("vehicle_operations")
    if "vehicles" in tables:
        op.drop_index("ix_vehicles_company_id", table_name="vehicles")
        op.drop_table("vehicles")
