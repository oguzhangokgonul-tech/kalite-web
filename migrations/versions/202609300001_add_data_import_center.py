"""Add controlled Excel and CSV data import center.

Revision ID: 202609300001
Revises: 202609280002
Create Date: 2026-09-30
"""

from alembic import op
import sqlalchemy as sa


revision = "202609300001"
down_revision = "202609280002"
branch_labels = None
depends_on = None


def upgrade():
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "data_import_batches" not in existing_tables:
        op.create_table(
            "data_import_batches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("module_key", sa.String(length=40), nullable=False),
            sa.Column("template_version", sa.String(length=20), nullable=False, server_default="1"),
            sa.Column("original_filename", sa.String(length=255), nullable=False),
            sa.Column("stored_file_path", sa.String(length=500), nullable=False),
            sa.Column("file_sha256", sa.String(length=64), nullable=False),
            sa.Column("file_size", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="validated"),
            sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("valid_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("applied_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("rolled_back_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("applied_at", sa.DateTime(), nullable=True),
            sa.Column("rolled_back_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("company_id", "id", name="uq_data_import_batches_company_id"),
            sa.UniqueConstraint(
                "company_id", "module_key", "file_sha256",
                name="uq_data_import_batches_company_module_hash",
            ),
        )
        for column in ("company_id", "module_key", "file_sha256", "status", "created_at"):
            op.create_index(f"ix_data_import_batches_{column}", "data_import_batches", [column])

    if "data_import_rows" not in existing_tables:
        op.create_table(
            "data_import_rows",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("batch_id", sa.Integer(), nullable=False),
            sa.Column("row_number", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("planned_action", sa.String(length=20), nullable=False, server_default="create"),
            sa.Column("source_json", sa.Text(), nullable=False),
            sa.Column("normalized_json", sa.Text(), nullable=False),
            sa.Column("messages_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("target_entity_type", sa.String(length=80), nullable=True),
            sa.Column("target_entity_id", sa.Integer(), nullable=True),
            sa.Column("after_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("batch_id", "row_number", name="uq_data_import_rows_batch_row"),
            sa.ForeignKeyConstraint(
                ("company_id", "batch_id"),
                ("data_import_batches.company_id", "data_import_batches.id"),
                name="fk_data_import_rows_company_batch",
                ondelete="CASCADE",
            ),
        )
        for column in ("company_id", "batch_id", "status", "target_entity_id"):
            op.create_index(f"ix_data_import_rows_{column}", "data_import_rows", [column])


def downgrade():
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "data_import_rows" in existing_tables:
        op.drop_table("data_import_rows")
    if "data_import_batches" in existing_tables:
        op.drop_table("data_import_batches")
