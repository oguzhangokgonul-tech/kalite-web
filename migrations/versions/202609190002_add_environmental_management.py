"""add environmental aspect and waste management

Revision ID: 202609190002
Revises: 202609190001
"""

from alembic import op
import sqlalchemy as sa


revision = "202609190002"
down_revision = "202609190001"
branch_labels = None
depends_on = None


def _index(table, column):
    op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "environmental_aspects" not in tables:
        op.create_table(
            "environmental_aspects",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("aspect_no", sa.String(40), nullable=False),
            sa.Column("department_id", sa.Integer(), sa.ForeignKey("company_departments.id"), nullable=False),
            sa.Column("process", sa.String(180), nullable=False), sa.Column("activity", sa.String(240), nullable=False),
            sa.Column("aspect", sa.String(240), nullable=False), sa.Column("impact", sa.String(240), nullable=False),
            sa.Column("lifecycle_stage", sa.String(60), nullable=False), sa.Column("operating_condition", sa.String(30), nullable=False),
            sa.Column("influence_type", sa.String(30), nullable=False), sa.Column("existing_controls", sa.Text(), nullable=False),
            sa.Column("emergency_response", sa.Text()), sa.Column("matrix_version", sa.String(30), nullable=False, server_default="V1"),
            sa.Column("significance_threshold", sa.Integer(), nullable=False, server_default="40"),
            sa.Column("responsible_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("review_due_date", sa.Date(), nullable=False), sa.Column("status", sa.String(30), nullable=False, server_default="Taslak"),
            sa.Column("review_note", sa.Text()), sa.Column("submitted_at", sa.DateTime()), sa.Column("approved_at", sa.DateTime()),
            sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id")), sa.Column("archived_at", sa.DateTime()),
            sa.Column("risk_id", sa.Integer(), sa.ForeignKey("risk_records.id")), sa.Column("action_id", sa.Integer(), sa.ForeignKey("actions.id")),
            sa.Column("compliance_obligation_id", sa.Integer(), sa.ForeignKey("compliance_obligations.id")),
            sa.Column("quality_objective_id", sa.Integer(), sa.ForeignKey("quality_objectives.id")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "aspect_no", name="uq_environmental_aspects_company_no"),
        )
        for column in ("company_id", "aspect_no", "department_id", "aspect", "responsible_user_id", "reviewer_user_id", "review_due_date", "status", "risk_id", "action_id", "compliance_obligation_id", "quality_objective_id"):
            _index("environmental_aspects", column)
    if "environmental_aspect_assessments" not in tables:
        op.create_table(
            "environmental_aspect_assessments",
            sa.Column("id", sa.Integer(), primary_key=True), sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("aspect_id", sa.Integer(), sa.ForeignKey("environmental_aspects.id"), nullable=False), sa.Column("version_no", sa.Integer(), nullable=False),
            sa.Column("matrix_version", sa.String(30), nullable=False), sa.Column("significance_threshold", sa.Integer(), nullable=False),
            sa.Column("lifecycle_stage", sa.String(60), nullable=False), sa.Column("operating_condition", sa.String(30), nullable=False),
            sa.Column("influence_type", sa.String(30), nullable=False), sa.Column("controls_snapshot", sa.Text(), nullable=False),
            sa.Column("severity", sa.Integer(), nullable=False),
            sa.Column("frequency", sa.Integer(), nullable=False), sa.Column("legal_score", sa.Integer(), nullable=False),
            sa.Column("stakeholder_score", sa.Integer(), nullable=False), sa.Column("control_effectiveness", sa.Integer(), nullable=False),
            sa.Column("inherent_score", sa.Integer(), nullable=False), sa.Column("residual_score", sa.Integer(), nullable=False),
            sa.Column("is_significant", sa.Boolean(), nullable=False, server_default="0"), sa.Column("rationale", sa.Text(), nullable=False),
            sa.Column("assessed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("review_status", sa.String(30), nullable=False, server_default="Bekliyor"),
            sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("reviewed_at", sa.DateTime()), sa.Column("review_note", sa.Text()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("aspect_id", "version_no", name="uq_environmental_assessment_version"),
        )
        for column in ("company_id", "aspect_id", "is_significant"):
            _index("environmental_aspect_assessments", column)
    if "environmental_aspect_files" not in tables:
        op.create_table(
            "environmental_aspect_files",
            sa.Column("id", sa.Integer(), primary_key=True), sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("aspect_id", sa.Integer(), sa.ForeignKey("environmental_aspects.id"), nullable=False),
            sa.Column("original_name", sa.String(255), nullable=False), sa.Column("stored_path", sa.String(500), nullable=False),
            sa.Column("mime_type", sa.String(160)), sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sha256_hash", sa.String(64), nullable=False), sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        _index("environmental_aspect_files", "company_id"); _index("environmental_aspect_files", "aspect_id")
    if "waste_streams" not in tables:
        op.create_table(
            "waste_streams",
            sa.Column("id", sa.Integer(), primary_key=True), sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("waste_code", sa.String(40), nullable=False), sa.Column("name", sa.String(240), nullable=False),
            sa.Column("is_hazardous", sa.Boolean(), nullable=False, server_default="0"), sa.Column("department_id", sa.Integer(), sa.ForeignKey("company_departments.id"), nullable=False),
            sa.Column("source_process", sa.String(180), nullable=False), sa.Column("storage_location", sa.String(200), nullable=False),
            sa.Column("unit", sa.String(20), nullable=False), sa.Column("maximum_capacity", sa.Numeric(14, 3)),
            sa.Column("maximum_storage_days", sa.Integer(), nullable=False), sa.Column("responsible_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("aspect_id", sa.Integer(), sa.ForeignKey("environmental_aspects.id")),
            sa.Column("compliance_obligation_id", sa.Integer(), sa.ForeignKey("compliance_obligations.id")),
            sa.Column("status", sa.String(20), nullable=False, server_default="Aktif"), sa.Column("archived_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "waste_code", name="uq_waste_streams_company_code"),
        )
        for column in ("company_id", "waste_code", "is_hazardous", "department_id", "responsible_user_id", "aspect_id", "compliance_obligation_id", "status"):
            _index("waste_streams", column)
    if "waste_batches" not in tables:
        op.create_table(
            "waste_batches",
            sa.Column("id", sa.Integer(), primary_key=True), sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("batch_no", sa.String(40), nullable=False), sa.Column("stream_id", sa.Integer(), sa.ForeignKey("waste_streams.id"), nullable=False),
            sa.Column("generated_date", sa.Date(), nullable=False), sa.Column("storage_due_date", sa.Date(), nullable=False),
            sa.Column("initial_quantity", sa.Numeric(14, 3), nullable=False), sa.Column("remaining_quantity", sa.Numeric(14, 3), nullable=False),
            sa.Column("container_count", sa.Integer()), sa.Column("storage_location", sa.String(200), nullable=False),
            sa.Column("status", sa.String(40), nullable=False, server_default="Geçici Depoda"),
            sa.Column("responsible_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("carrier_name", sa.String(240)), sa.Column("carrier_license_no", sa.String(120)),
            sa.Column("receiving_facility", sa.String(240)), sa.Column("facility_license_no", sa.String(120)),
            sa.Column("motat_reference", sa.String(120)), sa.Column("abs_declaration_no", sa.String(120)),
            sa.Column("shipped_quantity", sa.Numeric(14, 3)), sa.Column("accepted_quantity", sa.Numeric(14, 3)),
            sa.Column("review_note", sa.Text()), sa.Column("completed_at", sa.DateTime()), sa.Column("archived_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "batch_no", name="uq_waste_batches_company_no"),
            sa.UniqueConstraint("company_id", "motat_reference", name="uq_waste_batches_company_motat"),
        )
        for column in ("company_id", "batch_no", "stream_id", "generated_date", "storage_due_date", "status", "responsible_user_id", "reviewer_user_id", "motat_reference"):
            _index("waste_batches", column)
    if "waste_movements" not in tables:
        op.create_table(
            "waste_movements",
            sa.Column("id", sa.Integer(), primary_key=True), sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("batch_id", sa.Integer(), sa.ForeignKey("waste_batches.id"), nullable=False), sa.Column("movement_type", sa.String(40), nullable=False),
            sa.Column("quantity", sa.Numeric(14, 3), nullable=False, server_default="0"), sa.Column("balance_after", sa.Numeric(14, 3), nullable=False),
            sa.Column("measured_quantity", sa.Numeric(14, 3)), sa.Column("location", sa.String(200)), sa.Column("note", sa.Text(), nullable=False),
            sa.Column("performed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        for column in ("company_id", "batch_id", "movement_type"):
            _index("waste_movements", column)
    if "waste_movement_files" not in tables:
        op.create_table(
            "waste_movement_files",
            sa.Column("id", sa.Integer(), primary_key=True), sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("movement_id", sa.Integer(), sa.ForeignKey("waste_movements.id"), nullable=False), sa.Column("document_type", sa.String(50), nullable=False),
            sa.Column("original_name", sa.String(255), nullable=False), sa.Column("stored_path", sa.String(500), nullable=False),
            sa.Column("mime_type", sa.String(160)), sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sha256_hash", sa.String(64), nullable=False), sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        _index("waste_movement_files", "company_id"); _index("waste_movement_files", "movement_id")
    if "app_settings" in tables:
        op.execute(sa.text("INSERT OR IGNORE INTO app_settings (key,value) VALUES ('sales_readiness:competitor_environmental_aspects','1')"))


def downgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("waste_movement_files", "waste_movements", "waste_batches", "waste_streams", "environmental_aspect_files", "environmental_aspect_assessments", "environmental_aspects"):
        if table in tables:
            op.drop_table(table)
    if "app_settings" in tables:
        op.execute(sa.text("DELETE FROM app_settings WHERE key='sales_readiness:competitor_environmental_aspects'"))
