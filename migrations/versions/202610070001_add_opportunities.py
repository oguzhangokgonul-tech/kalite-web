"""Tenant-scoped opportunities, independent of existing risk records.

Revision ID: 202610070001
Revises: 202610050004
"""
from alembic import op
import sqlalchemy as sa

revision = "202610070001"
down_revision = "202610050004"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if not sa.inspect(connection).has_table("opportunities"):
        op.create_table("opportunities",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("expected_benefit", sa.Text()),
            sa.Column("planned_action", sa.Text()),
            sa.Column("success_criteria", sa.Text()),
            sa.Column("source_reference", sa.Text()),
            sa.Column("likelihood", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("benefit", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("analysis_date", sa.Date(), nullable=False),
            sa.Column("due_date", sa.Date(), nullable=False),
            sa.Column("review_date", sa.Date()),
            sa.Column("action_id", sa.Integer(), sa.ForeignKey("actions.id")),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("result_note", sa.Text()),
            sa.Column("evidence_sources", sa.Text()),
            sa.Column("reviewed_at", sa.DateTime()),
            sa.Column("archive_note", sa.Text()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
            sa.CheckConstraint("status IN ('draft','active','realized','not_realized','archived')", name="ck_opportunities_status"),
            sa.CheckConstraint("length(trim(title)) BETWEEN 1 AND 240", name="ck_opportunities_title"),
            sa.CheckConstraint("likelihood IN (1,2,3,4,5) AND benefit IN (1,2,3,4,5)", name="ck_opportunities_scores"),
            sa.CheckConstraint("due_date >= analysis_date AND (review_date IS NULL OR review_date >= analysis_date)", name="ck_opportunities_dates"),
            sa.CheckConstraint("version_id > 0", name="ck_opportunities_version"),
            sa.CheckConstraint(
                "status NOT IN ('active','realized','not_realized') OR ("
                "length(trim(coalesce(description,''))) > 0 AND "
                "length(trim(coalesce(expected_benefit,''))) > 0 AND "
                "length(trim(coalesce(planned_action,''))) > 0 AND "
                "length(trim(coalesce(success_criteria,''))) > 0 AND review_date IS NOT NULL)", name="ck_opportunities_active"),
            sa.CheckConstraint(
                "status NOT IN ('realized','not_realized') OR ("
                "length(trim(coalesce(result_note,''))) > 0 AND "
                "length(trim(coalesce(evidence_sources,''))) > 0 AND "
                "reviewed_at IS NOT NULL AND reviewed_by_user_id IS NOT NULL)", name="ck_opportunities_closed"),
            sa.CheckConstraint(
                "status NOT IN ('draft','active') OR (result_note IS NULL AND evidence_sources IS NULL "
                "AND reviewed_at IS NULL AND reviewed_by_user_id IS NULL)", name="ck_opportunities_open"),
            sa.CheckConstraint("status != 'archived' OR length(trim(coalesce(archive_note,''))) > 0", name="ck_opportunities_archive"),
        )
    indexes = {item["name"] for item in sa.inspect(connection).get_indexes("opportunities")}
    for column in ("company_id", "owner_user_id", "analysis_date", "due_date", "review_date", "action_id", "status"):
        name = f"ix_opportunities_{column}"
        if name not in indexes:
            op.create_index(name, "opportunities", [column])
    from app.opportunity_schema import ensure_opportunity_sqlite_guards
    ensure_opportunity_sqlite_guards(connection)


def downgrade():
    from app.opportunity_schema import drop_opportunity_sqlite_guards
    connection = op.get_bind()
    drop_opportunity_sqlite_guards(connection)
    if sa.inspect(connection).has_table("opportunities"):
        op.drop_table("opportunities")
