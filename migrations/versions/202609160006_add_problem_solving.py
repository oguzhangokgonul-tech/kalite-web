"""add a3 and 8d problem solving

Revision ID: 202609160006
Revises: 202609160005
"""
from alembic import op
import sqlalchemy as sa
revision="202609160006"; down_revision="202609160005"; branch_labels=None; depends_on=None


def upgrade():
    tables=set(sa.inspect(op.get_bind()).get_table_names())
    if "problem_solving_cases" not in tables:
        op.create_table("problem_solving_cases",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("company_id",sa.Integer(),sa.ForeignKey("companies.id"),nullable=False),sa.Column("case_no",sa.String(40),nullable=False),sa.Column("method",sa.String(10),nullable=False),sa.Column("title",sa.String(240),nullable=False),sa.Column("department",sa.String(160)),sa.Column("leader_user_id",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),sa.Column("reviewer_user_id",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),sa.Column("priority",sa.String(20),nullable=False,server_default="Orta"),sa.Column("opened_date",sa.Date(),nullable=False),sa.Column("target_date",sa.Date()),sa.Column("status",sa.String(30),nullable=False,server_default="Açık"),sa.Column("current_step",sa.Integer(),nullable=False,server_default="1"),sa.Column("problem_statement",sa.Text(),nullable=False),sa.Column("impact",sa.Text()),sa.Column("containment_summary",sa.Text()),sa.Column("final_result",sa.Text()),sa.Column("dof_id",sa.Integer(),sa.ForeignKey("dofs.id")),sa.Column("action_id",sa.Integer(),sa.ForeignKey("actions.id")),sa.Column("risk_id",sa.Integer(),sa.ForeignKey("risk_records.id")),sa.Column("kaizen_project_id",sa.Integer(),sa.ForeignKey("kaizen_projects.id")),sa.Column("created_by_user_id",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),sa.Column("completed_at",sa.DateTime()),sa.Column("archived_at",sa.DateTime()),sa.Column("created_at",sa.DateTime(),nullable=False,server_default=sa.func.now()),sa.Column("updated_at",sa.DateTime(),nullable=False,server_default=sa.func.now()),sa.UniqueConstraint("company_id","case_no",name="uq_problem_solving_cases_company_no"))
        for c in ("company_id","case_no","method","department","leader_user_id","reviewer_user_id","target_date","status","dof_id","action_id","risk_id","kaizen_project_id"): op.create_index(f"ix_problem_solving_cases_{c}","problem_solving_cases",[c])
    if "problem_solving_team_members" not in tables:
        op.create_table("problem_solving_team_members",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("company_id",sa.Integer(),sa.ForeignKey("companies.id"),nullable=False),sa.Column("case_id",sa.Integer(),sa.ForeignKey("problem_solving_cases.id"),nullable=False),sa.Column("user_id",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),sa.Column("role_name",sa.String(80),nullable=False,server_default="Ekip Üyesi"),sa.Column("created_at",sa.DateTime(),nullable=False,server_default=sa.func.now()),sa.UniqueConstraint("case_id","user_id",name="uq_problem_solving_team_case_user"))
        for c in ("company_id","case_id","user_id"): op.create_index(f"ix_problem_solving_team_members_{c}","problem_solving_team_members",[c])
    if "problem_solving_steps" not in tables:
        op.create_table("problem_solving_steps",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("company_id",sa.Integer(),sa.ForeignKey("companies.id"),nullable=False),sa.Column("case_id",sa.Integer(),sa.ForeignKey("problem_solving_cases.id"),nullable=False),sa.Column("step_order",sa.Integer(),nullable=False),sa.Column("step_key",sa.String(20),nullable=False),sa.Column("title",sa.String(180),nullable=False),sa.Column("guidance",sa.Text()),sa.Column("content",sa.Text()),sa.Column("status",sa.String(30),nullable=False,server_default="Bekliyor"),sa.Column("owner_user_id",sa.Integer(),sa.ForeignKey("users.id")),sa.Column("due_date",sa.Date()),sa.Column("submitted_at",sa.DateTime()),sa.Column("approved_at",sa.DateTime()),sa.Column("approved_by_user_id",sa.Integer(),sa.ForeignKey("users.id")),sa.Column("review_note",sa.Text()),sa.Column("created_at",sa.DateTime(),nullable=False,server_default=sa.func.now()),sa.Column("updated_at",sa.DateTime(),nullable=False,server_default=sa.func.now()),sa.UniqueConstraint("case_id","step_order",name="uq_problem_solving_case_step"))
        for c in ("company_id","case_id","status","owner_user_id","due_date"): op.create_index(f"ix_problem_solving_steps_{c}","problem_solving_steps",[c])
    if "problem_solving_files" not in tables:
        op.create_table("problem_solving_files",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("company_id",sa.Integer(),sa.ForeignKey("companies.id"),nullable=False),sa.Column("case_id",sa.Integer(),sa.ForeignKey("problem_solving_cases.id"),nullable=False),sa.Column("step_id",sa.Integer(),sa.ForeignKey("problem_solving_steps.id")),sa.Column("original_name",sa.String(255),nullable=False),sa.Column("stored_path",sa.String(500),nullable=False),sa.Column("mime_type",sa.String(160)),sa.Column("file_size",sa.Integer(),nullable=False,server_default="0"),sa.Column("sha256_hash",sa.String(64),nullable=False),sa.Column("uploaded_by_user_id",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),sa.Column("created_at",sa.DateTime(),nullable=False,server_default=sa.func.now()))
        for c in ("company_id","case_id","step_id"): op.create_index(f"ix_problem_solving_files_{c}","problem_solving_files",[c])
    if "app_settings" in set(sa.inspect(op.get_bind()).get_table_names()): op.execute(sa.text("INSERT OR IGNORE INTO app_settings (key,value) VALUES ('sales_readiness:competitor_a3_problem_solving','1')"))


def downgrade():
    tables=set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("problem_solving_files","problem_solving_steps","problem_solving_team_members","problem_solving_cases"):
        if table in tables: op.drop_table(table)
    if "app_settings" in tables: op.execute(sa.text("DELETE FROM app_settings WHERE key='sales_readiness:competitor_a3_problem_solving'"))
