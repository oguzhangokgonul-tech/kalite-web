"""add lessons learned knowledge base

Revision ID: 202609160007
Revises: 202609160006
"""
from alembic import op
import sqlalchemy as sa

revision = "202609160007"
down_revision = "202609160006"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "lessons_learned" not in tables:
        op.create_table(
            "lessons_learned",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("lesson_no", sa.String(40), nullable=False),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("department", sa.String(160)),
            sa.Column("category", sa.String(120), nullable=False, server_default="Genel"),
            sa.Column("tags", sa.String(500)),
            sa.Column("situation", sa.Text(), nullable=False),
            sa.Column("lesson", sa.Text(), nullable=False),
            sa.Column("recommendation", sa.Text(), nullable=False),
            sa.Column("applicability", sa.Text()),
            sa.Column("status", sa.String(30), nullable=False, server_default="Taslak"),
            sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("problem_solving_case_id", sa.Integer(), sa.ForeignKey("problem_solving_cases.id")),
            sa.Column("dof_id", sa.Integer(), sa.ForeignKey("dofs.id")),
            sa.Column("action_id", sa.Integer(), sa.ForeignKey("actions.id")),
            sa.Column("risk_id", sa.Integer(), sa.ForeignKey("risk_records.id")),
            sa.Column("kaizen_project_id", sa.Integer(), sa.ForeignKey("kaizen_projects.id")),
            sa.Column("review_note", sa.Text()),
            sa.Column("submitted_at", sa.DateTime()),
            sa.Column("published_at", sa.DateTime()),
            sa.Column("published_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("archived_at", sa.DateTime()),
            sa.Column("reuse_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "lesson_no", name="uq_lessons_learned_company_no"),
        )
        for column in ("company_id", "lesson_no", "department", "category", "status", "owner_user_id", "reviewer_user_id", "problem_solving_case_id", "dof_id", "action_id", "risk_id", "kaizen_project_id"):
            op.create_index(f"ix_lessons_learned_{column}", "lessons_learned", [column])
    if "lesson_learned_files" not in tables:
        op.create_table(
            "lesson_learned_files",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("lesson_id", sa.Integer(), sa.ForeignKey("lessons_learned.id"), nullable=False),
            sa.Column("original_name", sa.String(255), nullable=False),
            sa.Column("stored_path", sa.String(500), nullable=False),
            sa.Column("mime_type", sa.String(160)),
            sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sha256_hash", sa.String(64), nullable=False),
            sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_lesson_learned_files_company_id", "lesson_learned_files", ["company_id"])
        op.create_index("ix_lesson_learned_files_lesson_id", "lesson_learned_files", ["lesson_id"])
    if "app_settings" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.execute(sa.text("INSERT OR IGNORE INTO app_settings (key,value) VALUES ('sales_readiness:competitor_lessons_learned','1')"))


def downgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("lesson_learned_files", "lessons_learned"):
        if table in tables:
            op.drop_table(table)
    if "app_settings" in tables:
        op.execute(sa.text("DELETE FROM app_settings WHERE key='sales_readiness:competitor_lessons_learned'"))
