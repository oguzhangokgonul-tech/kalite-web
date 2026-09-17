"""add work permits

Revision ID: 202609170001
Revises: 202609160008
"""
from alembic import op
import sqlalchemy as sa


revision = "202609170001"
down_revision = "202609160008"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "work_permits" not in tables:
        op.create_table(
            "work_permits",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("permit_no", sa.String(40), nullable=False),
            sa.Column("permit_type", sa.String(80), nullable=False),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("location", sa.String(200), nullable=False),
            sa.Column("department", sa.String(160)),
            sa.Column("contractor", sa.String(200)),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("hazards", sa.Text(), nullable=False),
            sa.Column("precautions", sa.Text(), nullable=False),
            sa.Column("ppe_requirements", sa.Text(), nullable=False),
            sa.Column("emergency_plan", sa.Text()),
            sa.Column("requester_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("responsible_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("approver_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("requested_start_at", sa.DateTime(), nullable=False),
            sa.Column("requested_end_at", sa.DateTime(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="Taslak"),
            sa.Column("review_note", sa.Text()),
            sa.Column("closure_note", sa.Text()),
            sa.Column("submitted_at", sa.DateTime()),
            sa.Column("approved_at", sa.DateTime()),
            sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("activated_at", sa.DateTime()),
            sa.Column("closed_at", sa.DateTime()),
            sa.Column("cancelled_at", sa.DateTime()),
            sa.Column("archived_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "permit_no", name="uq_work_permits_company_no"),
        )
        for column in ("company_id", "permit_no", "permit_type", "location", "department", "requester_user_id", "responsible_user_id", "approver_user_id", "requested_start_at", "requested_end_at", "status"):
            op.create_index(f"ix_work_permits_{column}", "work_permits", [column])
    if "work_permit_controls" not in tables:
        op.create_table(
            "work_permit_controls",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("permit_id", sa.Integer(), sa.ForeignKey("work_permits.id"), nullable=False),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("is_required", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("note", sa.Text()),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("confirmed_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("confirmed_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        for column in ("company_id", "permit_id"):
            op.create_index(f"ix_work_permit_controls_{column}", "work_permit_controls", [column])
    if "work_permit_files" not in tables:
        op.create_table(
            "work_permit_files",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("permit_id", sa.Integer(), sa.ForeignKey("work_permits.id"), nullable=False),
            sa.Column("original_name", sa.String(255), nullable=False),
            sa.Column("stored_path", sa.String(500), nullable=False),
            sa.Column("mime_type", sa.String(160)),
            sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sha256_hash", sa.String(64), nullable=False),
            sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        for column in ("company_id", "permit_id"):
            op.create_index(f"ix_work_permit_files_{column}", "work_permit_files", [column])
    if "app_settings" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.execute(sa.text("INSERT OR IGNORE INTO app_settings (key,value) VALUES ('sales_readiness:competitor_work_permits','1')"))


def downgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("work_permit_files", "work_permit_controls", "work_permits"):
        if table in tables:
            op.drop_table(table)
    if "app_settings" in tables:
        op.execute(sa.text("DELETE FROM app_settings WHERE key='sales_readiness:competitor_work_permits'"))
