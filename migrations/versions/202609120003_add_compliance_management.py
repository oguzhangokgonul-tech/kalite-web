"""add legal obligations and compliance tracking

Revision ID: 202609120003
Revises: 202609120002
"""

from alembic import op
import sqlalchemy as sa


revision = "202609120003"
down_revision = "202609120002"
branch_labels = None
depends_on = None


def company_column():
    return sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False)


def timestamps():
    return (
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def create_indexes(table_name, columns):
    for column in columns:
        op.create_index(f"ix_{table_name}_{column}", table_name, [column])


def upgrade():
    op.create_table(
        "compliance_obligations",
        sa.Column("id", sa.Integer(), primary_key=True),
        company_column(),
        sa.Column("obligation_no", sa.String(30), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("authority", sa.String(180)),
        sa.Column("region", sa.String(100)),
        sa.Column("obligation_type", sa.String(80), nullable=False),
        sa.Column("legal_reference", sa.String(255)),
        sa.Column("applicability_status", sa.String(30), nullable=False, server_default="applicable"),
        sa.Column("applicability_reason", sa.Text()),
        sa.Column("department", sa.String(160), nullable=False),
        sa.Column("process", sa.String(160)),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("criticality", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("review_interval_months", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("last_review_date", sa.Date()),
        sa.Column("next_review_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("activated_at", sa.DateTime()),
        sa.Column("repealed_at", sa.DateTime()),
        sa.Column("archived_at", sa.DateTime()),
        *timestamps(),
        sa.UniqueConstraint("company_id", "obligation_no", name="uq_compliance_obligations_company_no"),
    )
    create_indexes(
        "compliance_obligations",
        ("company_id", "department", "owner_user_id", "criticality", "next_review_date", "status", "created_by_user_id"),
    )

    op.create_table(
        "compliance_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        company_column(),
        sa.Column("obligation_id", sa.Integer(), sa.ForeignKey("compliance_obligations.id"), nullable=False),
        sa.Column("revision_no", sa.String(40), nullable=False),
        sa.Column("publication_date", sa.Date()),
        sa.Column("effective_date", sa.Date()),
        sa.Column("repeal_date", sa.Date()),
        sa.Column("official_source_url", sa.String(1000), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="verification_pending"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("verified_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("verified_at", sa.DateTime()),
        sa.Column("verification_note", sa.Text()),
        *timestamps(),
        sa.UniqueConstraint("obligation_id", "revision_no", name="uq_compliance_revisions_obligation_no"),
    )
    create_indexes(
        "compliance_revisions",
        ("company_id", "obligation_id", "status", "created_by_user_id", "verified_by_user_id"),
    )

    op.create_table(
        "compliance_evaluations",
        sa.Column("id", sa.Integer(), primary_key=True),
        company_column(),
        sa.Column("obligation_id", sa.Integer(), sa.ForeignKey("compliance_obligations.id"), nullable=False),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("compliance_revisions.id"), nullable=False),
        sa.Column("evaluator_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence_note", sa.Text()),
        sa.Column("next_review_date", sa.Date(), nullable=False),
        sa.Column("risk_id", sa.Integer(), sa.ForeignKey("risk_records.id")),
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("actions.id")),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id")),
        sa.Column("improvement_plan", sa.Text()),
        sa.Column("obligation_no_snapshot", sa.String(30), nullable=False),
        sa.Column("obligation_title_snapshot", sa.String(240), nullable=False),
        sa.Column("legal_reference_snapshot", sa.String(255)),
        sa.Column("revision_no_snapshot", sa.String(40), nullable=False),
        sa.Column("official_source_url_snapshot", sa.String(1000), nullable=False),
        sa.Column("owner_name_snapshot", sa.String(180), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    create_indexes(
        "compliance_evaluations",
        ("company_id", "obligation_id", "revision_id", "evaluator_user_id", "evaluated_at", "outcome", "next_review_date", "risk_id", "action_id", "document_id"),
    )

    op.create_table(
        "compliance_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        company_column(),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("compliance_revisions.id")),
        sa.Column("evaluation_id", sa.Integer(), sa.ForeignKey("compliance_evaluations.id")),
        sa.Column("file_kind", sa.String(30), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("stored_path", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(160)),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256_hash", sa.String(64), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "(revision_id IS NOT NULL AND evaluation_id IS NULL) OR "
            "(revision_id IS NULL AND evaluation_id IS NOT NULL)",
            name="ck_compliance_files_single_parent",
        ),
    )
    create_indexes(
        "compliance_files",
        ("company_id", "revision_id", "evaluation_id", "is_active"),
    )

    company_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("companies")}
    enabled_expression = (
        "CASE WHEN package_key = 'custom' THEN 0 ELSE 1 END"
        if "package_key" in company_columns else "1"
    )
    op.execute(sa.text(
        "INSERT INTO company_modules (company_id, module_key, is_enabled) "
        f"SELECT id, 'compliance_management', {enabled_expression} FROM companies "
        "WHERE NOT EXISTS (SELECT 1 FROM company_modules cm "
        "WHERE cm.company_id = companies.id AND cm.module_key = 'compliance_management')"
    ))


def downgrade():
    op.execute("DELETE FROM company_modules WHERE module_key = 'compliance_management'")
    op.drop_table("compliance_files")
    op.drop_table("compliance_evaluations")
    op.drop_table("compliance_revisions")
    op.drop_table("compliance_obligations")
