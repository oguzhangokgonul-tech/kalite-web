"""add document file fields

Revision ID: 202605140001
Revises: 202605130001
Create Date: 2026-05-14 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202605140001"
down_revision = "202605130001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("file_original_name", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("file_stored_name", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("file_mime_type", sa.String(length=120), nullable=True))


def downgrade():
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_column("file_mime_type")
        batch_op.drop_column("file_stored_name")
        batch_op.drop_column("file_original_name")
