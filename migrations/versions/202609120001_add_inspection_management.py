"""add company-scoped inspection management

Revision ID: 202609120001
Revises: 202609110001
"""

from alembic import op
import sqlalchemy as sa


revision = "202609120001"
down_revision = "202609110001"
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
        "inspection_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        company_column(),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("dynamic_form_versions.id"), nullable=False),
        sa.Column("inspection_no", sa.String(30), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("department", sa.String(160)),
        sa.Column("location", sa.String(255)),
        sa.Column("reference", sa.String(255)),
        sa.Column("inspector_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("planned_date", sa.Date()),
        sa.Column("due_date", sa.Date()),
        sa.Column("status", sa.String(30), nullable=False, server_default="planned"),
        sa.Column("overall_result", sa.String(30)),
        sa.Column("review_note", sa.Text()),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("submitted_at", sa.DateTime()),
        sa.Column("reviewed_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("archived_at", sa.DateTime()),
        *timestamps(),
        sa.UniqueConstraint("company_id", "inspection_no", name="uq_inspection_records_company_no"),
    )
    create_indexes(
        "inspection_records",
        (
            "company_id",
            "version_id",
            "department",
            "inspector_user_id",
            "reviewer_user_id",
            "created_by_user_id",
            "planned_date",
            "due_date",
            "status",
            "overall_result",
        ),
    )

    op.create_table(
        "inspection_item_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        company_column(),
        sa.Column("inspection_id", sa.Integer(), sa.ForeignKey("inspection_records.id"), nullable=False),
        sa.Column("field_id", sa.Integer(), sa.ForeignKey("dynamic_form_fields.id"), nullable=False),
        sa.Column("value_json", sa.Text()),
        sa.Column("compliance_result", sa.String(30)),
        sa.Column("explanation", sa.Text()),
        *timestamps(),
        sa.UniqueConstraint(
            "inspection_id",
            "field_id",
            name="uq_inspection_item_results_inspection_field",
        ),
    )
    create_indexes(
        "inspection_item_results",
        ("company_id", "inspection_id", "field_id", "compliance_result"),
    )

    op.create_table(
        "inspection_findings",
        sa.Column("id", sa.Integer(), primary_key=True),
        company_column(),
        sa.Column("inspection_id", sa.Integer(), sa.ForeignKey("inspection_records.id"), nullable=False),
        sa.Column("item_result_id", sa.Integer(), sa.ForeignKey("inspection_item_results.id")),
        sa.Column("item_label_snapshot", sa.String(180)),
        sa.Column("observed_value_json", sa.Text()),
        sa.Column("result_snapshot", sa.String(30)),
        sa.Column("explanation_snapshot", sa.Text()),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("severity", sa.String(20), nullable=False, server_default="Orta"),
        sa.Column("responsible_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("due_date", sa.Date()),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("resolution", sa.Text()),
        sa.Column("closed_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("closed_at", sa.DateTime()),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        *timestamps(),
    )
    create_indexes(
        "inspection_findings",
        (
            "company_id",
            "inspection_id",
            "item_result_id",
            "severity",
            "responsible_user_id",
            "due_date",
            "status",
        ),
    )


def downgrade():
    op.drop_table("inspection_findings")
    op.drop_table("inspection_item_results")
    op.drop_table("inspection_records")
