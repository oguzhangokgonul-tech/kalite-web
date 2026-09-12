"""add stakeholder and expectation management

Revision ID: 202609120002
Revises: 202609120001
"""

from alembic import op
import sqlalchemy as sa


revision = "202609120002"
down_revision = "202609120001"
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
        "stakeholder_parties",
        sa.Column("id", sa.Integer(), primary_key=True),
        company_column(),
        sa.Column("party_no", sa.String(30), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("internal_external", sa.String(20), nullable=False, server_default="external"),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("relevance_status", sa.String(30), nullable=False, server_default="relevant"),
        sa.Column("relevance_reason", sa.Text()),
        sa.Column("department", sa.String(160)),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("influence_score", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("importance_score", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("review_interval_months", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("last_review_date", sa.Date()),
        sa.Column("next_review_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("activated_at", sa.DateTime()),
        sa.Column("archived_at", sa.DateTime()),
        *timestamps(),
        sa.UniqueConstraint("company_id", "party_no", name="uq_stakeholder_parties_company_no"),
    )
    create_indexes(
        "stakeholder_parties",
        ("company_id", "department", "owner_user_id", "next_review_date", "status", "created_by_user_id"),
    )

    op.create_table(
        "stakeholder_requirements",
        sa.Column("id", sa.Integer(), primary_key=True),
        company_column(),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("stakeholder_parties.id"), nullable=False),
        sa.Column("requirement_type", sa.String(40), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("source", sa.String(255)),
        sa.Column("climate_related", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("process", sa.String(160)),
        sa.Column("fulfillment_status", sa.String(30), nullable=False, server_default="not_assessed"),
        sa.Column("responsible_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("due_date", sa.Date()),
        sa.Column("risk_id", sa.Integer(), sa.ForeignKey("risk_records.id")),
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("actions.id")),
        sa.Column("improvement_plan", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("archived_at", sa.DateTime()),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        *timestamps(),
    )
    create_indexes(
        "stakeholder_requirements",
        ("company_id", "party_id", "fulfillment_status", "responsible_user_id", "due_date", "risk_id", "action_id", "is_active"),
    )

    op.create_table(
        "stakeholder_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        company_column(),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("stakeholder_parties.id"), nullable=False),
        sa.Column("requirement_id", sa.Integer(), sa.ForeignKey("stakeholder_requirements.id")),
        sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("party_name_snapshot", sa.String(180), nullable=False),
        sa.Column("requirement_title_snapshot", sa.String(180)),
        sa.Column("requirement_source_snapshot", sa.String(255)),
        sa.Column("fulfillment_status_before", sa.String(30)),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence_note", sa.Text()),
        sa.Column("next_review_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    create_indexes(
        "stakeholder_reviews",
        ("company_id", "party_id", "requirement_id", "reviewer_user_id", "reviewed_at", "outcome", "next_review_date"),
    )
    company_columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("companies")
    }
    enabled_expression = (
        "CASE WHEN package_key = 'custom' THEN 0 ELSE 1 END"
        if "package_key" in company_columns
        else "1"
    )
    op.execute(
        sa.text(
            "INSERT INTO company_modules (company_id, module_key, is_enabled) "
            f"SELECT id, 'stakeholder_management', {enabled_expression} FROM companies "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM company_modules cm WHERE cm.company_id = companies.id "
            "AND cm.module_key = 'stakeholder_management'"
            ")"
        )
    )


def downgrade():
    op.execute("DELETE FROM company_modules WHERE module_key = 'stakeholder_management'")
    op.drop_table("stakeholder_reviews")
    op.drop_table("stakeholder_requirements")
    op.drop_table("stakeholder_parties")
