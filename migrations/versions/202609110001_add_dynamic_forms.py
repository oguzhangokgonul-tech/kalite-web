"""add company-scoped dynamic forms

Revision ID: 202609110001
Revises: 202609070002
"""

from alembic import op
import sqlalchemy as sa


revision = "202609110001"
down_revision = "202609070002"
branch_labels = None
depends_on = None


def company_column():
    return sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False)


def timestamps(include_updated=True):
    columns = [
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now())
    ]
    if include_updated:
        columns.append(sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
    return columns


def upgrade():
    op.create_table(
        "dynamic_form_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        company_column(),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("current_version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        *timestamps(),
        sa.UniqueConstraint("company_id", "code", name="uq_dynamic_form_templates_company_code"),
    )
    op.create_index("ix_dynamic_form_templates_company_id", "dynamic_form_templates", ["company_id"])
    op.create_index("ix_dynamic_form_templates_status", "dynamic_form_templates", ["status"])

    op.create_table(
        "dynamic_form_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        company_column(),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("dynamic_form_templates.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("name_snapshot", sa.String(180), nullable=False),
        sa.Column("description_snapshot", sa.Text()),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("published_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("published_at", sa.DateTime()),
        *timestamps(include_updated=False),
        sa.UniqueConstraint("template_id", "version_number", name="uq_dynamic_form_versions_template_version"),
    )
    op.create_index("ix_dynamic_form_versions_company_id", "dynamic_form_versions", ["company_id"])
    op.create_index("ix_dynamic_form_versions_template_id", "dynamic_form_versions", ["template_id"])
    op.create_index("ix_dynamic_form_versions_status", "dynamic_form_versions", ["status"])

    op.create_table(
        "dynamic_form_fields",
        sa.Column("id", sa.Integer(), primary_key=True),
        company_column(),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("dynamic_form_versions.id"), nullable=False),
        sa.Column("field_key", sa.String(80), nullable=False),
        sa.Column("label", sa.String(180), nullable=False),
        sa.Column("field_type", sa.String(30), nullable=False),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("options_json", sa.Text()),
        *timestamps(include_updated=False),
        sa.UniqueConstraint("version_id", "field_key", name="uq_dynamic_form_fields_version_key"),
    )
    op.create_index("ix_dynamic_form_fields_company_id", "dynamic_form_fields", ["company_id"])
    op.create_index("ix_dynamic_form_fields_version_id", "dynamic_form_fields", ["version_id"])

    op.create_table(
        "dynamic_form_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        company_column(),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("dynamic_form_versions.id"), nullable=False),
        sa.Column("assigned_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("assigned_department", sa.String(160)),
        sa.Column("due_date", sa.Date()),
        sa.Column("status", sa.String(20), nullable=False, server_default="assigned"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("completed_at", sa.DateTime()),
        *timestamps(),
    )
    for column in ("company_id", "version_id", "assigned_user_id", "assigned_department", "due_date", "status"):
        op.create_index(f"ix_dynamic_form_assignments_{column}", "dynamic_form_assignments", [column])

    op.create_table(
        "dynamic_form_assignment_recipients",
        sa.Column("id", sa.Integer(), primary_key=True),
        company_column(),
        sa.Column(
            "assignment_id",
            sa.Integer(),
            sa.ForeignKey("dynamic_form_assignments.id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        *timestamps(include_updated=False),
        sa.UniqueConstraint(
            "assignment_id",
            "user_id",
            name="uq_dynamic_form_assignment_recipients_assignment_user",
        ),
    )
    for column in ("company_id", "assignment_id", "user_id"):
        op.create_index(
            f"ix_dynamic_form_assignment_recipients_{column}",
            "dynamic_form_assignment_recipients",
            [column],
        )

    op.create_table(
        "dynamic_form_submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        company_column(),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("dynamic_form_assignments.id"), nullable=False),
        sa.Column("respondent_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("submitted_at", sa.DateTime()),
        *timestamps(),
        sa.UniqueConstraint("assignment_id", "respondent_user_id", name="uq_dynamic_form_submissions_assignment_respondent"),
    )
    for column in ("company_id", "assignment_id", "respondent_user_id", "status"):
        op.create_index(f"ix_dynamic_form_submissions_{column}", "dynamic_form_submissions", [column])

    op.create_table(
        "dynamic_form_answers",
        sa.Column("id", sa.Integer(), primary_key=True),
        company_column(),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("dynamic_form_submissions.id"), nullable=False),
        sa.Column("field_id", sa.Integer(), sa.ForeignKey("dynamic_form_fields.id"), nullable=False),
        sa.Column("value_json", sa.Text()),
        *timestamps(),
        sa.UniqueConstraint("submission_id", "field_id", name="uq_dynamic_form_answers_submission_field"),
    )
    for column in ("company_id", "submission_id", "field_id"):
        op.create_index(f"ix_dynamic_form_answers_{column}", "dynamic_form_answers", [column])


def downgrade():
    op.drop_table("dynamic_form_answers")
    op.drop_table("dynamic_form_submissions")
    op.drop_table("dynamic_form_assignment_recipients")
    op.drop_table("dynamic_form_assignments")
    op.drop_table("dynamic_form_fields")
    op.drop_table("dynamic_form_versions")
    op.drop_table("dynamic_form_templates")
