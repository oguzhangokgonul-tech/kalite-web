"""add internal help desk

Revision ID: 202609160008
Revises: 202609160007
"""
from alembic import op
import sqlalchemy as sa

revision = "202609160008"
down_revision = "202609160007"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "help_desk_tickets" not in tables:
        op.create_table("help_desk_tickets", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False), sa.Column("ticket_no", sa.String(40), nullable=False), sa.Column("title", sa.String(240), nullable=False), sa.Column("description", sa.Text(), nullable=False), sa.Column("category", sa.String(100), nullable=False, server_default="Diğer"), sa.Column("department", sa.String(160), nullable=False), sa.Column("priority", sa.String(20), nullable=False, server_default="Orta"), sa.Column("status", sa.String(30), nullable=False, server_default="Yeni"), sa.Column("requester_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("assignee_user_id", sa.Integer(), sa.ForeignKey("users.id")), sa.Column("sla_due_at", sa.DateTime(), nullable=False), sa.Column("resolution", sa.Text()), sa.Column("resolved_at", sa.DateTime()), sa.Column("closed_at", sa.DateTime()), sa.Column("reopened_at", sa.DateTime()), sa.Column("archived_at", sa.DateTime()), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("company_id", "ticket_no", name="uq_help_desk_tickets_company_no"))
        for column in ("company_id", "ticket_no", "category", "department", "priority", "status", "requester_user_id", "assignee_user_id", "sla_due_at"):
            op.create_index(f"ix_help_desk_tickets_{column}", "help_desk_tickets", [column])
    if "help_desk_comments" not in tables:
        op.create_table("help_desk_comments", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False), sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("help_desk_tickets.id"), nullable=False), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("body", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
        for column in ("company_id", "ticket_id", "user_id"):
            op.create_index(f"ix_help_desk_comments_{column}", "help_desk_comments", [column])
    if "help_desk_files" not in tables:
        op.create_table("help_desk_files", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False), sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("help_desk_tickets.id"), nullable=False), sa.Column("comment_id", sa.Integer(), sa.ForeignKey("help_desk_comments.id")), sa.Column("original_name", sa.String(255), nullable=False), sa.Column("stored_path", sa.String(500), nullable=False), sa.Column("mime_type", sa.String(160)), sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"), sa.Column("sha256_hash", sa.String(64), nullable=False), sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
        for column in ("company_id", "ticket_id", "comment_id"):
            op.create_index(f"ix_help_desk_files_{column}", "help_desk_files", [column])
    if "app_settings" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.execute(sa.text("INSERT OR IGNORE INTO app_settings (key,value) VALUES ('sales_readiness:competitor_help_desk','1')"))


def downgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("help_desk_files", "help_desk_comments", "help_desk_tickets"):
        if table in tables:
            op.drop_table(table)
    if "app_settings" in tables:
        op.execute(sa.text("DELETE FROM app_settings WHERE key='sales_readiness:competitor_help_desk'"))
