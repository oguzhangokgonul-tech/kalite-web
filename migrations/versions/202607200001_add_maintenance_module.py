"""add maintenance module

Revision ID: 202607200001
Revises: 202606190003
Create Date: 2026-07-20 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202607200001"
down_revision = "202606190003"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "maintenance_machines" not in tables:
        op.create_table(
            "maintenance_machines",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("code", sa.String(length=80), nullable=False),
            sa.Column("machine_name", sa.String(length=180), nullable=False),
            sa.Column("brand_model", sa.String(length=180), nullable=True),
            sa.Column("serial_no", sa.String(length=120), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="ÇALIŞIYOR"),
            sa.Column("location", sa.String(length=160), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("code"),
        )

    if "maintenance_faults" not in tables:
        op.create_table(
            "maintenance_faults",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("fault_number", sa.Integer(), nullable=True),
            sa.Column("machine_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=180), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="Açık"),
            sa.Column("priority", sa.String(length=40), nullable=False, server_default="Orta"),
            sa.Column("reported_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("closing_note", sa.Text(), nullable=True),
            sa.Column("reported_by_user_id", sa.Integer(), nullable=True),
            sa.Column("responsible_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.ForeignKeyConstraint(["machine_id"], ["maintenance_machines.id"]),
            sa.ForeignKeyConstraint(["reported_by_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["responsible_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("fault_number"),
        )

    inspector = sa.inspect(bind)
    if "maintenance_faults" in set(inspector.get_table_names()):
        indexes = {index["name"] for index in inspector.get_indexes("maintenance_faults")}
        if "ix_maintenance_faults_machine_id" not in indexes:
            op.create_index(
                "ix_maintenance_faults_machine_id",
                "maintenance_faults",
                ["machine_id"],
                unique=False,
            )
        if "ix_maintenance_faults_status" not in indexes:
            op.create_index(
                "ix_maintenance_faults_status",
                "maintenance_faults",
                ["status"],
                unique=False,
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "maintenance_faults" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("maintenance_faults")}
        if "ix_maintenance_faults_status" in indexes:
            op.drop_index("ix_maintenance_faults_status", table_name="maintenance_faults")
        if "ix_maintenance_faults_machine_id" in indexes:
            op.drop_index("ix_maintenance_faults_machine_id", table_name="maintenance_faults")
        op.drop_table("maintenance_faults")

    if "maintenance_machines" in tables:
        op.drop_table("maintenance_machines")
