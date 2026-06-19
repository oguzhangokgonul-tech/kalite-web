"""add document preview fields

Revision ID: 202606190003
Revises: 202606190002
Create Date: 2026-06-19 00:03:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606190003"
down_revision = "202606190002"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "documents" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("documents")}
    new_columns = (
        ("preview_file_name", sa.Column("preview_file_name", sa.String(length=255), nullable=True)),
        ("preview_file_path", sa.Column("preview_file_path", sa.String(length=500), nullable=True)),
        ("preview_status", sa.Column("preview_status", sa.String(length=40), nullable=True)),
        ("preview_error", sa.Column("preview_error", sa.Text(), nullable=True)),
        ("preview_generated_at", sa.Column("preview_generated_at", sa.DateTime(), nullable=True)),
    )
    for name, column in new_columns:
        if name not in columns:
            op.add_column("documents", column)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "documents" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("documents")}
    with op.batch_alter_table("documents", schema=None) as batch_op:
        for name in (
            "preview_generated_at",
            "preview_error",
            "preview_status",
            "preview_file_path",
            "preview_file_name",
        ):
            if name in columns:
                batch_op.drop_column(name)
