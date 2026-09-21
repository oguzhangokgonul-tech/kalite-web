"""add ohs risk matrix

Revision ID: 202609210001
Revises: 202609200001
"""

from alembic import op
import sqlalchemy as sa


revision = "202609210001"
down_revision = "202609200001"
branch_labels = None
depends_on = None


def _index(table, column, unique=False):
    op.create_index(f"ix_{table}_{column}", table, [column], unique=unique)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "risk_records" in tables:
        columns = {column["name"] for column in inspector.get_columns("risk_records")}
        if "archived_at" not in columns:
            with op.batch_alter_table("risk_records") as batch:
                batch.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))
            _index("risk_records", "archived_at")

    if "ohs_risk_assessments" not in tables:
        op.create_table(
            "ohs_risk_assessments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("assessment_no", sa.String(40), nullable=False),
            sa.Column("department_id", sa.Integer(), sa.ForeignKey("company_departments.id"), nullable=False),
            sa.Column("activity", sa.String(240), nullable=False),
            sa.Column("location", sa.String(240), nullable=False),
            sa.Column("hazard", sa.Text(), nullable=False),
            sa.Column("risk_description", sa.Text(), nullable=False),
            sa.Column("exposed_people", sa.Text(), nullable=False),
            sa.Column("existing_controls", sa.Text(), nullable=False),
            sa.Column("initial_likelihood", sa.Integer(), nullable=False),
            sa.Column("initial_severity", sa.Integer(), nullable=False),
            sa.Column("control_hierarchy", sa.String(40), nullable=False),
            sa.Column("planned_controls", sa.Text(), nullable=False),
            sa.Column("responsible_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("risk_record_id", sa.Integer(), sa.ForeignKey("risk_records.id"), nullable=False),
            sa.Column("due_date", sa.Date(), nullable=False),
            sa.Column("review_date", sa.Date(), nullable=True),
            sa.Column("status", sa.String(40), nullable=False, server_default="Taslak"),
            sa.Column("review_note", sa.Text(), nullable=True),
            sa.Column("residual_likelihood", sa.Integer(), nullable=True),
            sa.Column("residual_severity", sa.Integer(), nullable=True),
            sa.Column("completion_note", sa.Text(), nullable=True),
            sa.Column("evidence_name", sa.String(255), nullable=True),
            sa.Column("evidence_path", sa.String(500), nullable=True),
            sa.Column("evidence_hash", sa.String(64), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("residual_submitted_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("archived_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "assessment_no", name="uq_ohs_risk_assessments_company_no"),
            sa.UniqueConstraint("risk_record_id", name="uq_ohs_risk_assessments_risk_record"),
        )
        for column in (
            "company_id", "assessment_no", "department_id", "responsible_user_id",
            "reviewer_user_id", "created_by_user_id", "risk_record_id", "due_date",
            "review_date", "status",
        ):
            _index("ohs_risk_assessments", column)

    if "ohs_risk_evaluations" not in tables:
        op.create_table(
            "ohs_risk_evaluations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("ohs_risk_assessments.id"), nullable=False),
            sa.Column("version_no", sa.Integer(), nullable=False),
            sa.Column("phase", sa.String(30), nullable=False),
            sa.Column("likelihood", sa.Integer(), nullable=False),
            sa.Column("severity", sa.Integer(), nullable=False),
            sa.Column("score", sa.Integer(), nullable=False),
            sa.Column("level", sa.String(30), nullable=False),
            sa.Column("existing_controls", sa.Text(), nullable=True),
            sa.Column("planned_controls", sa.Text(), nullable=True),
            sa.Column("control_hierarchy", sa.String(40), nullable=True),
            sa.Column("decision", sa.String(20), nullable=False),
            sa.Column("note", sa.Text(), nullable=False),
            sa.Column("evidence_name", sa.String(255), nullable=True),
            sa.Column("evidence_path", sa.String(500), nullable=True),
            sa.Column("evidence_hash", sa.String(64), nullable=True),
            sa.Column("evaluator_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("assessment_id", "version_no", name="uq_ohs_risk_evaluations_version"),
        )
        for column in ("company_id", "assessment_id", "evaluator_user_id"):
            _index("ohs_risk_evaluations", column)

    if "app_settings" in tables:
        op.execute(sa.text(
            "INSERT OR IGNORE INTO app_settings (key,value) "
            "VALUES ('sales_readiness:competitor_ohs_risk_matrix','1')"
        ))


def downgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "ohs_risk_evaluations" in tables:
        op.drop_table("ohs_risk_evaluations")
    if "ohs_risk_assessments" in tables:
        op.drop_table("ohs_risk_assessments")
    if "risk_records" in tables:
        columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("risk_records")}
        if "archived_at" in columns:
            indexes = {
                index["name"]
                for index in sa.inspect(op.get_bind()).get_indexes("risk_records")
            }
            if "ix_risk_records_archived_at" in indexes:
                op.drop_index("ix_risk_records_archived_at", table_name="risk_records")
            with op.batch_alter_table("risk_records") as batch:
                batch.drop_column("archived_at")
    if "app_settings" in tables:
        op.execute(sa.text(
            "DELETE FROM app_settings WHERE key='sales_readiness:competitor_ohs_risk_matrix'"
        ))
