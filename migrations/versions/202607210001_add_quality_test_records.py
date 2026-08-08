"""add quality test records

Revision ID: 202607210001
Revises: 202607200002
Create Date: 2026-07-21 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202607210001"
down_revision = "202607200002"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "quality_test_records" not in tables:
        op.create_table(
            "quality_test_records",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("test_type", sa.String(length=80), nullable=False),
            sa.Column("record_number", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(length=180), nullable=False),
            sa.Column("record_date", sa.Date(), nullable=True),
            sa.Column("customer", sa.String(length=180), nullable=True),
            sa.Column("sample_name", sa.String(length=180), nullable=True),
            sa.Column("concrete_class", sa.String(length=40), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="Kayıtlı"),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    if "quality_test_records" in set(inspector.get_table_names()):
        indexes = {index["name"] for index in inspector.get_indexes("quality_test_records")}
        if "ix_quality_test_records_test_type" not in indexes:
            op.create_index(
                "ix_quality_test_records_test_type",
                "quality_test_records",
                ["test_type"],
                unique=False,
            )
        if "ix_quality_test_records_status" not in indexes:
            op.create_index(
                "ix_quality_test_records_status",
                "quality_test_records",
                ["status"],
                unique=False,
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "quality_test_records" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("quality_test_records")}
        if "ix_quality_test_records_status" in indexes:
            op.drop_index("ix_quality_test_records_status", table_name="quality_test_records")
        if "ix_quality_test_records_test_type" in indexes:
            op.drop_index("ix_quality_test_records_test_type", table_name="quality_test_records")
        op.drop_table("quality_test_records")
