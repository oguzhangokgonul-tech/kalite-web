"""add document revision requests

Revision ID: 202608270001
Revises: 202608260001
Create Date: 2026-08-27
"""

from alembic import op
import sqlalchemy as sa


revision = "202608270001"
down_revision = "202608260001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "document_revision_requests" not in tables:
        op.create_table(
            "document_revision_requests",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), nullable=True),
            sa.Column("document_id", sa.Integer(), nullable=False),
            sa.Column("requested_by_user_id", sa.Integer(), nullable=False),
            sa.Column("approved_by_user_id", sa.Integer(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=60),
                nullable=False,
                server_default="Yönetim Temsilcisi Onayı Bekleniyor",
            ),
            sa.Column("explanation", sa.Text(), nullable=False),
            sa.Column("approval_note", sa.Text(), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
            sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"]),
        )
        op.create_index(
            "ix_document_revision_requests_company_id",
            "document_revision_requests",
            ["company_id"],
        )
        op.create_index(
            "ix_document_revision_requests_document_id",
            "document_revision_requests",
            ["document_id"],
        )

    if "document_revision_request_files" not in tables:
        op.create_table(
            "document_revision_request_files",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), nullable=True),
            sa.Column("revision_request_id", sa.Integer(), nullable=False),
            sa.Column("file_name", sa.String(length=255), nullable=False),
            sa.Column("original_file_name", sa.String(length=255), nullable=False),
            sa.Column("file_path", sa.String(length=500), nullable=False),
            sa.Column("file_type", sa.String(length=20), nullable=True),
            sa.Column("file_size", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
            sa.ForeignKeyConstraint(
                ["revision_request_id"], ["document_revision_requests.id"]
            ),
        )
        op.create_index(
            "ix_document_revision_request_files_company_id",
            "document_revision_request_files",
            ["company_id"],
        )
        op.create_index(
            "ix_document_revision_request_files_revision_request_id",
            "document_revision_request_files",
            ["revision_request_id"],
        )

    notification_columns = {
        column["name"] for column in inspector.get_columns("notifications")
    }
    if "document_revision_request_id" not in notification_columns:
        with op.batch_alter_table("notifications") as batch_op:
            batch_op.add_column(
                sa.Column("document_revision_request_id", sa.Integer(), nullable=True)
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    notification_columns = {
        column["name"] for column in inspector.get_columns("notifications")
    }
    if "document_revision_request_id" in notification_columns:
        with op.batch_alter_table("notifications") as batch_op:
            batch_op.drop_column("document_revision_request_id")

    tables = set(inspector.get_table_names())
    if "document_revision_request_files" in tables:
        op.drop_index(
            "ix_document_revision_request_files_revision_request_id",
            table_name="document_revision_request_files",
        )
        op.drop_index(
            "ix_document_revision_request_files_company_id",
            table_name="document_revision_request_files",
        )
        op.drop_table("document_revision_request_files")
    if "document_revision_requests" in tables:
        op.drop_index(
            "ix_document_revision_requests_document_id",
            table_name="document_revision_requests",
        )
        op.drop_index(
            "ix_document_revision_requests_company_id",
            table_name="document_revision_requests",
        )
        op.drop_table("document_revision_requests")
