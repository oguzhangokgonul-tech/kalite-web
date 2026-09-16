"""add equipment lifecycle

Revision ID: 202609160003
Revises: 202609160002
"""
from alembic import op
import sqlalchemy as sa

revision = "202609160003"
down_revision = "202609160002"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "equipment_assets" not in tables:
        op.create_table(
            "equipment_assets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("asset_code", sa.String(50), nullable=False),
            sa.Column("name", sa.String(220), nullable=False),
            sa.Column("category", sa.String(120)), sa.Column("manufacturer", sa.String(160)),
            sa.Column("brand_model", sa.String(180)), sa.Column("serial_no", sa.String(160)),
            sa.Column("purchase_date", sa.Date()), sa.Column("commissioning_date", sa.Date()),
            sa.Column("warranty_end_date", sa.Date()), sa.Column("location", sa.String(160)),
            sa.Column("department", sa.String(160)),
            sa.Column("custodian_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("maintenance_machine_id", sa.Integer(), sa.ForeignKey("maintenance_machines.id")),
            sa.Column("calibration_record_id", sa.Integer(), sa.ForeignKey("calibration_records.id")),
            sa.Column("next_maintenance_date", sa.Date()), sa.Column("next_inspection_date", sa.Date()),
            sa.Column("criticality", sa.String(20), nullable=False, server_default="Orta"),
            sa.Column("status", sa.String(30), nullable=False, server_default="Aktif"),
            sa.Column("notes", sa.Text()),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("archived_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "asset_code", name="uq_equipment_assets_company_code"),
        )
        for column in ("company_id","asset_code","name","category","serial_no","warranty_end_date","location","department","custodian_user_id","maintenance_machine_id","calibration_record_id","next_maintenance_date","next_inspection_date","status"):
            op.create_index(f"ix_equipment_assets_{column}", "equipment_assets", [column])
    if "equipment_lifecycle_events" not in tables:
        op.create_table(
            "equipment_lifecycle_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("asset_id", sa.Integer(), sa.ForeignKey("equipment_assets.id"), nullable=False),
            sa.Column("event_type", sa.String(50), nullable=False),
            sa.Column("event_date", sa.Date(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("old_status", sa.String(30)), sa.Column("new_status", sa.String(30)),
            sa.Column("old_location", sa.String(160)), sa.Column("new_location", sa.String(160)),
            sa.Column("performed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        for column in ("company_id","asset_id","event_type","event_date"):
            op.create_index(f"ix_equipment_lifecycle_events_{column}", "equipment_lifecycle_events", [column])
    if "equipment_asset_files" not in tables:
        op.create_table(
            "equipment_asset_files",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("asset_id", sa.Integer(), sa.ForeignKey("equipment_assets.id"), nullable=False),
            sa.Column("original_name", sa.String(255), nullable=False),
            sa.Column("stored_path", sa.String(500), nullable=False),
            sa.Column("mime_type", sa.String(160)), sa.Column("file_size", sa.Integer(), nullable=False),
            sa.Column("sha256_hash", sa.String(64), nullable=False),
            sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_equipment_asset_files_company_id", "equipment_asset_files", ["company_id"])
        op.create_index("ix_equipment_asset_files_asset_id", "equipment_asset_files", ["asset_id"])
    if "app_settings" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.execute(sa.text("INSERT OR IGNORE INTO app_settings (key,value) VALUES ('sales_readiness:competitor_equipment_lifecycle','1')"))


def downgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("equipment_asset_files","equipment_lifecycle_events","equipment_assets"):
        if table in tables:
            op.drop_table(table)
    if "app_settings" in tables:
        op.execute(sa.text("DELETE FROM app_settings WHERE key='sales_readiness:competitor_equipment_lifecycle'"))
