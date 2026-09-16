"""add supplier quality audits and surveys

Revision ID: 202609160001
Revises: 202609150002
"""

from alembic import op
import sqlalchemy as sa


revision = "202609160001"
down_revision = "202609150002"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    tables = _tables()
    if "supplier_quality_audits" not in tables:
        op.create_table(
            "supplier_quality_audits",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("supplier_records.id"), nullable=False),
            sa.Column("audit_date", sa.Date(), nullable=False),
            sa.Column("next_audit_date", sa.Date()),
            sa.Column("auditor_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("scope", sa.String(240), nullable=False),
            sa.Column("status", sa.String(40), nullable=False, server_default="Planlandı"),
            sa.Column("score", sa.Integer()),
            sa.Column("findings", sa.Text()),
            sa.Column("corrective_action", sa.Text()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        for column in ("company_id", "supplier_id", "next_audit_date", "auditor_user_id", "status"):
            op.create_index(f"ix_supplier_quality_audits_{column}", "supplier_quality_audits", [column])

    if "supplier_surveys" not in tables:
        op.create_table(
            "supplier_surveys",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("supplier_records.id"), nullable=False),
            sa.Column("survey_date", sa.Date(), nullable=False),
            sa.Column("respondent_name", sa.String(160), nullable=False),
            sa.Column("quality_score", sa.Integer(), nullable=False),
            sa.Column("delivery_score", sa.Integer(), nullable=False),
            sa.Column("communication_score", sa.Integer(), nullable=False),
            sa.Column("total_score", sa.Integer(), nullable=False),
            sa.Column("comments", sa.Text()),
            sa.Column("recorded_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        for column in ("company_id", "supplier_id", "recorded_by_user_id"):
            op.create_index(f"ix_supplier_surveys_{column}", "supplier_surveys", [column])

    if "app_settings" in _tables():
        op.execute(sa.text(
            "INSERT OR IGNORE INTO app_settings (key, value) "
            "VALUES ('sales_readiness:competitor_advanced_supplier_quality', '1')"
        ))


def downgrade():
    for table in ("supplier_surveys", "supplier_quality_audits"):
        if table in _tables():
            op.drop_table(table)
    if "app_settings" in _tables():
        op.execute(sa.text(
            "DELETE FROM app_settings WHERE key='sales_readiness:competitor_advanced_supplier_quality'"
        ))
