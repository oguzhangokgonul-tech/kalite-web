"""Add company-scoped standard headings and live document links."""

from alembic import op
import sqlalchemy as sa


revision = "202611050001"
down_revision = "202611040004"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "standard_documentation_headings" not in tables:
        op.create_table(
            "standard_documentation_headings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("related_standard", sa.String(200)),
            sa.Column("technical_heading_no", sa.String(80)),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_standard_documentation_headings_company_id", "standard_documentation_headings", ["company_id"])
    if "standard_documentation_links" not in tables:
        op.create_table(
            "standard_documentation_links",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("heading_id", sa.Integer(), sa.ForeignKey("standard_documentation_headings.id"), nullable=False),
            sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id"), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("heading_id", "document_id", name="uq_standard_documentation_heading_document"),
        )
        for column in ("company_id", "heading_id", "document_id"):
            op.create_index(f"ix_standard_documentation_links_{column}", "standard_documentation_links", [column])


def downgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("standard_documentation_links", "standard_documentation_headings"):
        if table in tables and op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Standart dokümantasyon kayıtları varken önce doğrulanmış yedeği geri yükleyin.")
    if "standard_documentation_links" in tables:
        for column in ("company_id", "heading_id", "document_id"):
            op.drop_index(f"ix_standard_documentation_links_{column}", table_name="standard_documentation_links")
        op.drop_table("standard_documentation_links")
    if "standard_documentation_headings" in tables:
        op.drop_index("ix_standard_documentation_headings_company_id", table_name="standard_documentation_headings")
        op.drop_table("standard_documentation_headings")
