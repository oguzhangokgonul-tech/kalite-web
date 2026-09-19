"""add hazardous substance management

Revision ID: 202609190001
Revises: 202609170001
"""
from alembic import op
import sqlalchemy as sa


revision = "202609190001"
down_revision = "202609170001"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "hazardous_substances" not in tables:
        op.create_table(
            "hazardous_substances",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("inventory_no", sa.String(40), nullable=False),
            sa.Column("name", sa.String(240), nullable=False),
            sa.Column("product_code", sa.String(100)), sa.Column("manufacturer", sa.String(200)),
            sa.Column("supplier", sa.String(200)), sa.Column("cas_no", sa.String(80)),
            sa.Column("ec_no", sa.String(80)), sa.Column("un_no", sa.String(40)),
            sa.Column("physical_state", sa.String(40), nullable=False),
            sa.Column("signal_word", sa.String(20), nullable=False),
            sa.Column("hazard_classes", sa.Text(), nullable=False),
            sa.Column("pictogram_codes", sa.String(120), nullable=False),
            sa.Column("department", sa.String(160)), sa.Column("usage_area", sa.String(200), nullable=False),
            sa.Column("storage_location", sa.String(200), nullable=False),
            sa.Column("storage_group", sa.String(100), nullable=False),
            sa.Column("incompatible_materials", sa.Text()),
            sa.Column("precautions", sa.Text(), nullable=False),
            sa.Column("ppe_requirements", sa.Text(), nullable=False),
            sa.Column("first_aid", sa.Text(), nullable=False),
            sa.Column("spill_response", sa.Text(), nullable=False),
            sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
            sa.Column("unit", sa.String(20), nullable=False),
            sa.Column("minimum_stock", sa.Float()), sa.Column("maximum_stock", sa.Float()),
            sa.Column("expiry_date", sa.Date()),
            sa.Column("sds_revision_date", sa.Date(), nullable=False),
            sa.Column("sds_review_due_date", sa.Date(), nullable=False),
            sa.Column("responsible_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="Taslak"),
            sa.Column("review_note", sa.Text()), sa.Column("submitted_at", sa.DateTime()),
            sa.Column("approved_at", sa.DateTime()),
            sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("quarantined_at", sa.DateTime()), sa.Column("disposed_at", sa.DateTime()),
            sa.Column("archived_at", sa.DateTime()),
            sa.Column("risk_id", sa.Integer(), sa.ForeignKey("risk_records.id")),
            sa.Column("action_id", sa.Integer(), sa.ForeignKey("actions.id")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "inventory_no", name="uq_hazardous_substances_company_no"),
        )
        for column in ("company_id", "inventory_no", "name", "cas_no", "department", "storage_location", "storage_group", "expiry_date", "sds_review_due_date", "responsible_user_id", "reviewer_user_id", "status", "risk_id", "action_id"):
            op.create_index(f"ix_hazardous_substances_{column}", "hazardous_substances", [column])
    if "hazardous_substance_transactions" not in tables:
        op.create_table(
            "hazardous_substance_transactions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("substance_id", sa.Integer(), sa.ForeignKey("hazardous_substances.id"), nullable=False),
            sa.Column("movement_type", sa.String(30), nullable=False),
            sa.Column("quantity", sa.Float(), nullable=False), sa.Column("balance_after", sa.Float(), nullable=False),
            sa.Column("note", sa.Text(), nullable=False),
            sa.Column("performed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        for column in ("company_id", "substance_id", "movement_type"):
            op.create_index(f"ix_hazardous_substance_transactions_{column}", "hazardous_substance_transactions", [column])
    if "hazardous_substance_files" not in tables:
        op.create_table(
            "hazardous_substance_files",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("substance_id", sa.Integer(), sa.ForeignKey("hazardous_substances.id"), nullable=False),
            sa.Column("file_type", sa.String(30), nullable=False, server_default="Diğer"),
            sa.Column("revision_no", sa.String(80)), sa.Column("document_date", sa.Date()),
            sa.Column("language", sa.String(40)),
            sa.Column("is_current", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("archived_at", sa.DateTime()),
            sa.Column("original_name", sa.String(255), nullable=False),
            sa.Column("stored_path", sa.String(500), nullable=False),
            sa.Column("mime_type", sa.String(160)), sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sha256_hash", sa.String(64), nullable=False),
            sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        for column in ("company_id", "substance_id", "file_type", "is_current"):
            op.create_index(f"ix_hazardous_substance_files_{column}", "hazardous_substance_files", [column])
    if "app_settings" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.execute(sa.text("INSERT OR IGNORE INTO app_settings (key,value) VALUES ('sales_readiness:competitor_hazardous_substances','1')"))


def downgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("hazardous_substance_files", "hazardous_substance_transactions", "hazardous_substances"):
        if table in tables:
            op.drop_table(table)
    if "app_settings" in tables:
        op.execute(sa.text("DELETE FROM app_settings WHERE key='sales_readiness:competitor_hazardous_substances'"))
