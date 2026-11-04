"""Keep extracted document text outside audited document rows."""

from alembic import op
import sqlalchemy as sa


revision = "202611040003"
down_revision = "202611040002"
branch_labels = None
depends_on = None


def upgrade():
    if "document_search_indexes" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "document_search_indexes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("source_file_path", sa.String(length=500), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("indexed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("document_id"),
    )
    op.create_index("ix_document_search_indexes_company_id", "document_search_indexes", ["company_id"])
    op.create_index("ix_document_search_indexes_document_id", "document_search_indexes", ["document_id"])


def downgrade():
    if "document_search_indexes" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_index("ix_document_search_indexes_document_id", table_name="document_search_indexes")
        op.drop_index("ix_document_search_indexes_company_id", table_name="document_search_indexes")
        op.drop_table("document_search_indexes")
