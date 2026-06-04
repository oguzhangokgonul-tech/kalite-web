"""add action closure approval

Revision ID: 202606040003
Revises: 202606040002
Create Date: 2026-06-04 00:03:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606040003"
down_revision = "202606040002"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "actions" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("actions")}
    with op.batch_alter_table("actions", schema=None) as batch_op:
        if "closure_approval_requested" not in columns:
            batch_op.add_column(
                sa.Column(
                    "closure_approval_requested",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )
        if "closure_requested_at" not in columns:
            batch_op.add_column(sa.Column("closure_requested_at", sa.DateTime(), nullable=True))
        if "closure_requested_by_user_id" not in columns:
            batch_op.add_column(
                sa.Column("closure_requested_by_user_id", sa.Integer(), nullable=True)
            )
        if "closure_evidence_note" not in columns:
            batch_op.add_column(sa.Column("closure_evidence_note", sa.Text(), nullable=True))
        if "closure_file_original_name" not in columns:
            batch_op.add_column(
                sa.Column("closure_file_original_name", sa.String(length=255), nullable=True)
            )
        if "closure_file_stored_name" not in columns:
            batch_op.add_column(
                sa.Column("closure_file_stored_name", sa.String(length=255), nullable=True)
            )
        if "closure_file_mime_type" not in columns:
            batch_op.add_column(
                sa.Column("closure_file_mime_type", sa.String(length=120), nullable=True)
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "actions" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("actions")}
    with op.batch_alter_table("actions", schema=None) as batch_op:
        for column_name in (
            "closure_file_mime_type",
            "closure_file_stored_name",
            "closure_file_original_name",
            "closure_evidence_note",
            "closure_requested_by_user_id",
            "closure_requested_at",
            "closure_approval_requested",
        ):
            if column_name in columns:
                batch_op.drop_column(column_name)
