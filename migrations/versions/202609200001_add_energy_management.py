"""add energy management

Revision ID: 202609200001
Revises: 202609190002
"""

from alembic import op
import sqlalchemy as sa


revision = "202609200001"
down_revision = "202609190002"
branch_labels = None
depends_on = None


def _index(table, column):
    op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "energy_meters" not in tables:
        op.create_table(
            "energy_meters",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("meter_code", sa.String(50), nullable=False), sa.Column("name", sa.String(240), nullable=False),
            sa.Column("energy_type", sa.String(40), nullable=False), sa.Column("unit", sa.String(20), nullable=False),
            sa.Column("department_id", sa.Integer(), sa.ForeignKey("company_departments.id"), nullable=False),
            sa.Column("location", sa.String(240), nullable=False), sa.Column("serial_no", sa.String(120)),
            sa.Column("multiplier", sa.Numeric(14, 4), nullable=False, server_default="1"),
            sa.Column("emission_factor", sa.Numeric(14, 6), nullable=False, server_default="0"),
            sa.Column("reading_due_day", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("responsible_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="Aktif"), sa.Column("archived_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "meter_code", name="uq_energy_meters_company_code"),
        )
        for column in ("company_id", "meter_code", "energy_type", "department_id", "responsible_user_id", "reviewer_user_id", "status"):
            _index("energy_meters", column)
    if "energy_readings" not in tables:
        op.create_table(
            "energy_readings",
            sa.Column("id", sa.Integer(), primary_key=True), sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("meter_id", sa.Integer(), sa.ForeignKey("energy_meters.id"), nullable=False), sa.Column("period", sa.Date(), nullable=False),
            sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("supersedes_id", sa.Integer(), sa.ForeignKey("energy_readings.id")),
            sa.Column("is_current", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("reading_method", sa.String(30), nullable=False, server_default="Sayaç"),
            sa.Column("previous_value", sa.Numeric(16, 3), nullable=False), sa.Column("current_value", sa.Numeric(16, 3), nullable=False),
            sa.Column("multiplier_snapshot", sa.Numeric(14, 4), nullable=False, server_default="1"),
            sa.Column("emission_factor_snapshot", sa.Numeric(14, 6), nullable=False, server_default="0"),
            sa.Column("consumption", sa.Numeric(16, 3), nullable=False), sa.Column("production_quantity", sa.Numeric(16, 3)),
            sa.Column("production_unit", sa.String(30)), sa.Column("normalized_consumption", sa.Numeric(16, 6)),
            sa.Column("unit_cost", sa.Numeric(14, 4)), sa.Column("total_cost", sa.Numeric(16, 2)),
            sa.Column("emission_kg", sa.Numeric(16, 3), nullable=False, server_default="0"), sa.Column("note", sa.Text()),
            sa.Column("status", sa.String(30), nullable=False, server_default="Onay Bekliyor"),
            sa.Column("entered_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id")), sa.Column("reviewed_at", sa.DateTime()), sa.Column("review_note", sa.Text()),
            sa.Column("evidence_name", sa.String(255)), sa.Column("evidence_path", sa.String(500)), sa.Column("evidence_hash", sa.String(64)),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("meter_id", "period", "version_no", name="uq_energy_readings_meter_period_version"),
        )
        for column in ("company_id", "meter_id", "period", "supersedes_id", "is_current", "status"):
            _index("energy_readings", column)
    if "energy_targets" not in tables:
        op.create_table(
            "energy_targets",
            sa.Column("id", sa.Integer(), primary_key=True), sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("target_no", sa.String(50), nullable=False), sa.Column("title", sa.String(240), nullable=False),
            sa.Column("meter_id", sa.Integer(), sa.ForeignKey("energy_meters.id")), sa.Column("baseline_year", sa.Integer(), nullable=False),
            sa.Column("baseline_consumption", sa.Numeric(16, 3), nullable=False), sa.Column("reduction_percent", sa.Numeric(6, 2), nullable=False),
            sa.Column("target_date", sa.Date(), nullable=False), sa.Column("responsible_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("approver_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("quality_objective_id", sa.Integer(), sa.ForeignKey("quality_objectives.id")), sa.Column("action_id", sa.Integer(), sa.ForeignKey("actions.id")),
            sa.Column("status", sa.String(30), nullable=False, server_default="Taslak"), sa.Column("review_note", sa.Text()),
            sa.Column("approved_at", sa.DateTime()), sa.Column("actual_consumption", sa.Numeric(16, 3)),
            sa.Column("completion_note", sa.Text()), sa.Column("completed_at", sa.DateTime()),
            sa.Column("completed_by_user_id", sa.Integer(), sa.ForeignKey("users.id")), sa.Column("archived_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "target_no", name="uq_energy_targets_company_no"),
        )
        for column in ("company_id", "target_no", "meter_id", "target_date", "responsible_user_id", "approver_user_id", "completed_by_user_id", "quality_objective_id", "action_id", "status"):
            _index("energy_targets", column)
    if "energy_saving_projects" not in tables:
        op.create_table(
            "energy_saving_projects",
            sa.Column("id", sa.Integer(), primary_key=True), sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("project_no", sa.String(50), nullable=False), sa.Column("title", sa.String(240), nullable=False), sa.Column("description", sa.Text(), nullable=False),
            sa.Column("meter_id", sa.Integer(), sa.ForeignKey("energy_meters.id")), sa.Column("planned_saving", sa.Numeric(16, 3), nullable=False),
            sa.Column("actual_saving", sa.Numeric(16, 3)), sa.Column("investment_cost", sa.Numeric(16, 2)),
            sa.Column("start_date", sa.Date(), nullable=False), sa.Column("due_date", sa.Date(), nullable=False),
            sa.Column("responsible_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("approver_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("action_id", sa.Integer(), sa.ForeignKey("actions.id")),
            sa.Column("status", sa.String(30), nullable=False, server_default="Planlandı"), sa.Column("completion_note", sa.Text()),
            sa.Column("evidence_name", sa.String(255)), sa.Column("evidence_path", sa.String(500)), sa.Column("evidence_hash", sa.String(64)),
            sa.Column("completed_at", sa.DateTime()), sa.Column("verified_at", sa.DateTime()), sa.Column("archived_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "project_no", name="uq_energy_saving_projects_company_no"),
        )
        for column in ("company_id", "project_no", "meter_id", "due_date", "responsible_user_id", "approver_user_id", "action_id", "status"):
            _index("energy_saving_projects", column)
    if "energy_saving_verifications" not in tables:
        op.create_table(
            "energy_saving_verifications",
            sa.Column("id", sa.Integer(), primary_key=True), sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("energy_saving_projects.id"), nullable=False), sa.Column("version_no", sa.Integer(), nullable=False),
            sa.Column("actual_saving", sa.Numeric(16, 3), nullable=False), sa.Column("financial_saving", sa.Numeric(16, 2)),
            sa.Column("decision", sa.String(20), nullable=False), sa.Column("verification_note", sa.Text(), nullable=False),
            sa.Column("evidence_name", sa.String(255), nullable=False), sa.Column("evidence_path", sa.String(500), nullable=False),
            sa.Column("evidence_hash", sa.String(64), nullable=False),
            sa.Column("verified_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("project_id", "version_no", name="uq_energy_saving_verification_version"),
        )
        _index("energy_saving_verifications", "company_id"); _index("energy_saving_verifications", "project_id")
    if "app_settings" in tables:
        op.execute(sa.text("INSERT OR IGNORE INTO app_settings (key,value) VALUES ('sales_readiness:competitor_energy_management','1')"))
        op.execute(sa.text("INSERT OR IGNORE INTO app_settings (key,value) VALUES ('sales_readiness:module_energy_consumption_tracking','1')"))


def downgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("energy_saving_verifications", "energy_saving_projects", "energy_targets", "energy_readings", "energy_meters"):
        if table in tables:
            op.drop_table(table)
    if "app_settings" in tables:
        op.execute(sa.text("DELETE FROM app_settings WHERE key IN ('sales_readiness:competitor_energy_management','sales_readiness:module_energy_consumption_tracking')"))
