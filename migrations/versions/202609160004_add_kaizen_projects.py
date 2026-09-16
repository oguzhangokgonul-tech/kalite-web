"""add kaizen project management

Revision ID: 202609160004
Revises: 202609160003
"""
from alembic import op
import sqlalchemy as sa

revision = "202609160004"
down_revision = "202609160003"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "kaizen_projects" not in tables:
        op.create_table(
            "kaizen_projects",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("project_no", sa.String(40), nullable=False), sa.Column("title", sa.String(240), nullable=False),
            sa.Column("department", sa.String(160)), sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("stage", sa.String(40), nullable=False, server_default="Fikir"),
            sa.Column("status", sa.String(40), nullable=False, server_default="Açık"),
            sa.Column("priority", sa.String(20), nullable=False, server_default="Orta"),
            sa.Column("start_date", sa.Date(), nullable=False), sa.Column("target_date", sa.Date()), sa.Column("completed_at", sa.DateTime()),
            sa.Column("problem_statement", sa.Text(), nullable=False), sa.Column("current_state", sa.Text()), sa.Column("target_state", sa.Text()),
            sa.Column("root_cause", sa.Text()), sa.Column("solution", sa.Text()), sa.Column("verification_method", sa.Text()), sa.Column("standardization_plan", sa.Text()),
            sa.Column("metric_name", sa.String(160)), sa.Column("baseline_value", sa.Float()), sa.Column("target_value", sa.Float()), sa.Column("actual_value", sa.Float()),
            sa.Column("estimated_cost", sa.Float()), sa.Column("realized_cost", sa.Float()), sa.Column("estimated_benefit", sa.Float()), sa.Column("realized_benefit", sa.Float()),
            sa.Column("suggestion_id", sa.Integer(), sa.ForeignKey("suggestions.id")), sa.Column("action_id", sa.Integer(), sa.ForeignKey("actions.id")),
            sa.Column("quality_objective_id", sa.Integer(), sa.ForeignKey("quality_objectives.id")),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("archived_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "project_no", name="uq_kaizen_projects_company_no"),
        )
        for column in ("company_id", "project_no", "title", "department", "owner_user_id", "stage", "status", "target_date", "suggestion_id", "action_id", "quality_objective_id"):
            op.create_index(f"ix_kaizen_projects_{column}", "kaizen_projects", [column])
    if "kaizen_team_members" not in tables:
        op.create_table("kaizen_team_members", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False), sa.Column("project_id", sa.Integer(), sa.ForeignKey("kaizen_projects.id"), nullable=False), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("role_name", sa.String(80), nullable=False, server_default="Ekip Üyesi"), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("project_id", "user_id", name="uq_kaizen_team_project_user"))
        for column in ("company_id", "project_id", "user_id"): op.create_index(f"ix_kaizen_team_members_{column}", "kaizen_team_members", [column])
    if "kaizen_project_updates" not in tables:
        op.create_table("kaizen_project_updates", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False), sa.Column("project_id", sa.Integer(), sa.ForeignKey("kaizen_projects.id"), nullable=False), sa.Column("stage", sa.String(40), nullable=False), sa.Column("status", sa.String(40), nullable=False), sa.Column("note", sa.Text(), nullable=False), sa.Column("actual_value", sa.Float()), sa.Column("realized_cost", sa.Float()), sa.Column("realized_benefit", sa.Float()), sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
        for column in ("company_id", "project_id"): op.create_index(f"ix_kaizen_project_updates_{column}", "kaizen_project_updates", [column])
    if "kaizen_project_files" not in tables:
        op.create_table("kaizen_project_files", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False), sa.Column("project_id", sa.Integer(), sa.ForeignKey("kaizen_projects.id"), nullable=False), sa.Column("original_name", sa.String(255), nullable=False), sa.Column("stored_path", sa.String(500), nullable=False), sa.Column("mime_type", sa.String(160)), sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"), sa.Column("sha256_hash", sa.String(64), nullable=False), sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
        for column in ("company_id", "project_id"): op.create_index(f"ix_kaizen_project_files_{column}", "kaizen_project_files", [column])
    if "app_settings" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.execute(sa.text("INSERT OR IGNORE INTO app_settings (key,value) VALUES ('sales_readiness:competitor_kaizen_projects','1')"))


def downgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("kaizen_project_files", "kaizen_project_updates", "kaizen_team_members", "kaizen_projects"):
        if table in tables: op.drop_table(table)
    if "app_settings" in tables: op.execute(sa.text("DELETE FROM app_settings WHERE key='sales_readiness:competitor_kaizen_projects'"))
