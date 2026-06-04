"""add closure rejection and evidence files

Revision ID: 202606040004
Revises: 202606040003
Create Date: 2026-06-04 00:04:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "202606040004"
down_revision = "202606040003"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "actions" in tables:
        columns = {column["name"] for column in inspector.get_columns("actions")}
        with op.batch_alter_table("actions", schema=None) as batch_op:
            if "closure_rejected_at" not in columns:
                batch_op.add_column(
                    sa.Column("closure_rejected_at", sa.DateTime(), nullable=True)
                )
            if "closure_rejected_by_user_id" not in columns:
                batch_op.add_column(
                    sa.Column("closure_rejected_by_user_id", sa.Integer(), nullable=True)
                )
            if "closure_rejection_reason" not in columns:
                batch_op.add_column(
                    sa.Column("closure_rejection_reason", sa.Text(), nullable=True)
                )

    if "action_closure_files" not in tables:
        op.create_table(
            "action_closure_files",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("action_id", sa.Integer(), nullable=False),
            sa.Column("original_name", sa.String(length=255), nullable=False),
            sa.Column("stored_name", sa.String(length=255), nullable=False),
            sa.Column("mime_type", sa.String(length=120), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["action_id"], ["actions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    tables = set(sa.inspect(bind).get_table_names())
    if "actions" in tables and "action_closure_files" in tables:
        action_columns = {
            column["name"] for column in sa.inspect(bind).get_columns("actions")
        }
        if {
            "closure_file_original_name",
            "closure_file_stored_name",
            "closure_file_mime_type",
        }.issubset(action_columns):
            bind.execute(
                sa.text(
                    """
                    INSERT INTO action_closure_files
                        (action_id, original_name, stored_name, mime_type, created_at)
                    SELECT
                        id,
                        closure_file_original_name,
                        closure_file_stored_name,
                        closure_file_mime_type,
                        CURRENT_TIMESTAMP
                    FROM actions
                    WHERE closure_file_stored_name IS NOT NULL
                      AND closure_file_original_name IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1
                          FROM action_closure_files
                          WHERE action_closure_files.action_id = actions.id
                            AND action_closure_files.stored_name = actions.closure_file_stored_name
                      )
                    """
                )
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "action_closure_files" in tables:
        op.drop_table("action_closure_files")

    tables = set(sa.inspect(bind).get_table_names())
    if "actions" in tables:
        columns = {column["name"] for column in sa.inspect(bind).get_columns("actions")}
        with op.batch_alter_table("actions", schema=None) as batch_op:
            for column_name in (
                "closure_rejection_reason",
                "closure_rejected_by_user_id",
                "closure_rejected_at",
            ):
                if column_name in columns:
                    batch_op.drop_column(column_name)
