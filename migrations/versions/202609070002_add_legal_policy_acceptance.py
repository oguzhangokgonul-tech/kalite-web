"""add legal policy acceptance

Revision ID: 202609070002
Revises: 202609070001
Create Date: 2026-09-07
"""

from alembic import op
import sqlalchemy as sa


revision = "202609070002"
down_revision = "202609070001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "legal_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.String(length=40), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("published_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["published_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_type",
            "version",
            name="uq_legal_documents_type_version",
        ),
    )
    op.create_index("ix_legal_documents_document_type", "legal_documents", ["document_type"])
    op.create_index("ix_legal_documents_slug", "legal_documents", ["slug"])
    op.create_index("ix_legal_documents_status", "legal_documents", ["status"])

    op.create_table(
        "legal_acceptances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("legal_document_id", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.String(length=40), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("ip_address", sa.String(length=80), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["legal_document_id"], ["legal_documents.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "company_id",
            "legal_document_id",
            "version",
            name="uq_legal_acceptances_user_company_document_version",
        ),
    )
    op.create_index("ix_legal_acceptances_company_id", "legal_acceptances", ["company_id"])
    op.create_index("ix_legal_acceptances_legal_document_id", "legal_acceptances", ["legal_document_id"])
    op.create_index("ix_legal_acceptances_user_id", "legal_acceptances", ["user_id"])

    op.create_table(
        "company_legal_profiles",
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("legal_name", sa.String(length=255), nullable=True),
        sa.Column("legal_address", sa.Text(), nullable=True),
        sa.Column("tax_number", sa.String(length=80), nullable=True),
        sa.Column("mersis_number", sa.String(length=80), nullable=True),
        sa.Column("kvkk_contact_email", sa.String(length=255), nullable=True),
        sa.Column("data_controller_name", sa.String(length=255), nullable=True),
        sa.Column("dpo_contact", sa.String(length=255), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("company_id"),
    )


def downgrade():
    op.drop_table("company_legal_profiles")
    op.drop_index("ix_legal_acceptances_user_id", table_name="legal_acceptances")
    op.drop_index("ix_legal_acceptances_legal_document_id", table_name="legal_acceptances")
    op.drop_index("ix_legal_acceptances_company_id", table_name="legal_acceptances")
    op.drop_table("legal_acceptances")
    op.drop_index("ix_legal_documents_status", table_name="legal_documents")
    op.drop_index("ix_legal_documents_slug", table_name="legal_documents")
    op.drop_index("ix_legal_documents_document_type", table_name="legal_documents")
    op.drop_table("legal_documents")
