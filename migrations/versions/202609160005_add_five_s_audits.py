"""add five s audits

Revision ID: 202609160005
Revises: 202609160004
"""
from alembic import op
import sqlalchemy as sa

revision = "202609160005"
down_revision = "202609160004"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "five_s_audits" not in tables:
        op.create_table("five_s_audits",
            sa.Column("id", sa.Integer(), primary_key=True), sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("audit_no", sa.String(40), nullable=False), sa.Column("title", sa.String(220), nullable=False), sa.Column("area", sa.String(180), nullable=False), sa.Column("department", sa.String(160)),
            sa.Column("auditor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("planned_date", sa.Date(), nullable=False), sa.Column("due_date", sa.Date()), sa.Column("status", sa.String(30), nullable=False, server_default="planned"),
            sa.Column("score_percent", sa.Float()), sa.Column("summary", sa.Text()), sa.Column("review_note", sa.Text()), sa.Column("submitted_at", sa.DateTime()), sa.Column("reviewed_at", sa.DateTime()), sa.Column("completed_at", sa.DateTime()), sa.Column("archived_at", sa.DateTime()),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "audit_no", name="uq_five_s_audits_company_no"))
        for column in ("company_id","audit_no","area","department","auditor_user_id","reviewer_user_id","planned_date","due_date","status"): op.create_index(f"ix_five_s_audits_{column}", "five_s_audits", [column])
    if "five_s_audit_items" not in tables:
        op.create_table("five_s_audit_items",
            sa.Column("id", sa.Integer(), primary_key=True), sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False), sa.Column("audit_id", sa.Integer(), sa.ForeignKey("five_s_audits.id"), nullable=False),
            sa.Column("category", sa.String(40), nullable=False), sa.Column("criterion", sa.String(300), nullable=False), sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"), sa.Column("score", sa.Integer()), sa.Column("observation", sa.Text()),
            sa.Column("responsible_user_id", sa.Integer(), sa.ForeignKey("users.id")), sa.Column("due_date", sa.Date()), sa.Column("action_id", sa.Integer(), sa.ForeignKey("actions.id")),
            sa.Column("is_resolved", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("resolution_note", sa.Text()), sa.Column("resolved_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
        for column in ("company_id","audit_id","category","responsible_user_id","due_date","action_id"): op.create_index(f"ix_five_s_audit_items_{column}", "five_s_audit_items", [column])
    if "five_s_audit_files" not in tables:
        op.create_table("five_s_audit_files",
            sa.Column("id", sa.Integer(), primary_key=True), sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False), sa.Column("audit_id", sa.Integer(), sa.ForeignKey("five_s_audits.id"), nullable=False), sa.Column("item_id", sa.Integer(), sa.ForeignKey("five_s_audit_items.id")),
            sa.Column("original_name", sa.String(255), nullable=False), sa.Column("stored_path", sa.String(500), nullable=False), sa.Column("mime_type", sa.String(160)), sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"), sa.Column("sha256_hash", sa.String(64), nullable=False), sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
        for column in ("company_id","audit_id","item_id"): op.create_index(f"ix_five_s_audit_files_{column}", "five_s_audit_files", [column])
    if "app_settings" in set(sa.inspect(op.get_bind()).get_table_names()): op.execute(sa.text("INSERT OR IGNORE INTO app_settings (key,value) VALUES ('sales_readiness:competitor_five_s_audit','1')"))


def downgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("five_s_audit_files", "five_s_audit_items", "five_s_audits"):
        if table in tables: op.drop_table(table)
    if "app_settings" in tables: op.execute(sa.text("DELETE FROM app_settings WHERE key='sales_readiness:competitor_five_s_audit'"))
