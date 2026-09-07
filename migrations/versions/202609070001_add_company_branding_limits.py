"""add company branding limits

Revision ID: 202609070001
Revises: 202608280002
Create Date: 2026-09-07
"""

from alembic import op
import sqlalchemy as sa


revision = "202609070001"
down_revision = "202608280002"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("companies") as batch_op:
        batch_op.add_column(sa.Column("logo_file_path", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("logo_original_name", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("brand_primary_color", sa.String(length=7), nullable=True))
        batch_op.add_column(sa.Column("brand_accent_color", sa.String(length=7), nullable=True))
        batch_op.add_column(sa.Column("user_limit", sa.Integer(), nullable=True, server_default="25"))
        batch_op.add_column(sa.Column("storage_quota_mb", sa.Integer(), nullable=True, server_default="1024"))


def downgrade():
    with op.batch_alter_table("companies") as batch_op:
        batch_op.drop_column("storage_quota_mb")
        batch_op.drop_column("user_limit")
        batch_op.drop_column("brand_accent_color")
        batch_op.drop_column("brand_primary_color")
        batch_op.drop_column("logo_original_name")
        batch_op.drop_column("logo_file_path")
