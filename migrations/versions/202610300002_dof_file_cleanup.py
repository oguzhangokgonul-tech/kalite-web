"""Persist IF evidence cleanup jobs.

Revision ID: 202610300002
Revises: 202610300001
"""

from alembic import op
import sqlalchemy as sa


revision = "202610300002"
down_revision = "202610300001"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "dof_file_cleanup" in inspector.get_table_names():
        columns = {item["name"] for item in inspector.get_columns("dof_file_cleanup")}
        expected = {
            "id", "company_id", "dof_id", "stored_name", "file_type", "sha256",
            "size_bytes", "created_at", "cleaned_at", "last_error",
        }
        if columns != expected:
            raise RuntimeError("Existing IF file cleanup schema is incomplete")
        indexes = {item["name"] for item in inspector.get_indexes("dof_file_cleanup")}
        if not {"ix_dof_file_cleanup_company_id", "ix_dof_file_cleanup_dof_id"}.issubset(indexes):
            raise RuntimeError("Existing IF file cleanup indexes are incomplete")
        return
    op.create_table(
        "dof_file_cleanup",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("company_id", sa.Integer, nullable=False),
        sa.Column("dof_id", sa.Integer, nullable=False),
        sa.Column("stored_name", sa.String(255), nullable=False),
        sa.Column("file_type", sa.String(20), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("cleaned_at", sa.DateTime),
        sa.Column("last_error", sa.String(120)),
    )
    op.create_index("ix_dof_file_cleanup_company_id", "dof_file_cleanup", ["company_id"])
    op.create_index("ix_dof_file_cleanup_dof_id", "dof_file_cleanup", ["dof_id"])


def downgrade():
    connection = op.get_bind()
    if "dof_file_cleanup" not in sa.inspect(connection).get_table_names():
        return
    if connection.execute(sa.text("SELECT 1 FROM dof_file_cleanup LIMIT 1")).first():
        raise RuntimeError("IF file cleanup history exists; use a code-only rollback.")
    op.drop_index("ix_dof_file_cleanup_dof_id", table_name="dof_file_cleanup")
    op.drop_index("ix_dof_file_cleanup_company_id", table_name="dof_file_cleanup")
    op.drop_table("dof_file_cleanup")
