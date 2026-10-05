"""Tenant-scoped SWOT analyses.

Revision ID: 202610050002
Revises: 202610050001
"""
from alembic import op
import sqlalchemy as sa

revision = "202610050002"
down_revision = "202610050001"
branch_labels = None
depends_on = None


def install_sqlite_guards():
    if op.get_bind().dialect.name != "sqlite":
        return
    predicate = (
        "EXISTS (SELECT 1 FROM companies c WHERE c.id=NEW.company_id) "
        "AND EXISTS (SELECT 1 FROM users u WHERE u.id=NEW.owner_user_id AND u.company_id=NEW.company_id) "
        "AND EXISTS (SELECT 1 FROM users u WHERE u.id=NEW.created_by_user_id "
        "AND (u.company_id=NEW.company_id OR u.company_id IS NULL)) "
        "AND (NEW.reviewed_by_user_id IS NULL OR EXISTS (SELECT 1 FROM users u "
        "WHERE u.id=NEW.reviewed_by_user_id AND (u.company_id=NEW.company_id OR u.company_id IS NULL)))"
    )
    for operation in ("INSERT", "UPDATE"):
        op.execute(sa.text(
            f"CREATE TRIGGER IF NOT EXISTS trg_swot_analyses_tenant_{operation.lower()} "
            f"BEFORE {operation} ON swot_analyses WHEN NOT ({predicate}) "
            "BEGIN SELECT RAISE(ABORT, 'swot tenant mismatch'); END"
        ))
    references = (
        "EXISTS (SELECT 1 FROM swot_analyses a WHERE a.owner_user_id=OLD.id "
        "OR a.created_by_user_id=OLD.id OR a.reviewed_by_user_id=OLD.id)"
    )
    guards = (
        ("swot_user_delete", "BEFORE DELETE ON users", references),
        ("swot_user_update", "BEFORE UPDATE OF id,company_id ON users",
         f"(NEW.id IS NOT OLD.id OR NEW.company_id IS NOT OLD.company_id) AND {references}"),
        ("swot_company_delete", "BEFORE DELETE ON companies",
         "EXISTS (SELECT 1 FROM swot_analyses a WHERE a.company_id=OLD.id)"),
        ("swot_company_update", "BEFORE UPDATE OF id ON companies",
         "NEW.id IS NOT OLD.id AND EXISTS (SELECT 1 FROM swot_analyses a WHERE a.company_id=OLD.id)"),
        ("swot_company_immutable", "BEFORE UPDATE OF company_id ON swot_analyses",
         "NEW.company_id IS NOT OLD.company_id"),
    )
    for name, event, condition in guards:
        op.execute(sa.text(f"CREATE TRIGGER IF NOT EXISTS trg_{name} {event} WHEN {condition} "
                           "BEGIN SELECT RAISE(ABORT, 'swot referenced record'); END"))


def upgrade():
    connection = op.get_bind()
    if not sa.inspect(connection).has_table("swot_analyses"):
        op.create_table("swot_analyses",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("scope", sa.Text()),
            sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("analysis_date", sa.Date(), nullable=False),
            sa.Column("review_date", sa.Date(), nullable=False),
            sa.Column("strengths", sa.Text()),
            sa.Column("weaknesses", sa.Text()),
            sa.Column("opportunities", sa.Text()),
            sa.Column("threats", sa.Text()),
            sa.Column("strategy", sa.Text()),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("review_note", sa.Text()),
            sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("reviewed_at", sa.DateTime()),
            sa.Column("archive_note", sa.Text()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
            sa.CheckConstraint("status IN ('draft', 'reviewed', 'archived')", name="ck_swot_analyses_status"),
            sa.CheckConstraint("review_date > analysis_date", name="ck_swot_analyses_dates"),
            sa.CheckConstraint("length(trim(title)) BETWEEN 1 AND 240", name="ck_swot_analyses_title"),
            sa.CheckConstraint("version_id > 0", name="ck_swot_analyses_version"),
            sa.CheckConstraint(
                "status != 'reviewed' OR ("
                "length(trim(coalesce(strengths, ''))) > 0 AND "
                "length(trim(coalesce(weaknesses, ''))) > 0 AND "
                "length(trim(coalesce(opportunities, ''))) > 0 AND "
                "length(trim(coalesce(threats, ''))) > 0 AND "
                "length(trim(coalesce(strategy, ''))) > 0 AND "
                "length(trim(coalesce(review_note, ''))) > 0 AND "
                "reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL)",
                name="ck_swot_analyses_reviewed"),
            sa.CheckConstraint(
                "status != 'draft' OR (review_note IS NULL AND reviewed_by_user_id IS NULL AND reviewed_at IS NULL)",
                name="ck_swot_analyses_draft"),
            sa.CheckConstraint("status != 'archived' OR length(trim(coalesce(archive_note, ''))) > 0",
                name="ck_swot_analyses_archive"),
        )
    indexes = {item["name"] for item in sa.inspect(connection).get_indexes("swot_analyses")}
    for column in ("company_id", "owner_user_id", "analysis_date", "review_date", "status"):
        name = f"ix_swot_analyses_{column}"
        if name not in indexes:
            op.create_index(name, "swot_analyses", [column])
    install_sqlite_guards()


def downgrade():
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        for name in ("swot_analyses_tenant_insert", "swot_analyses_tenant_update", "swot_user_delete",
                     "swot_user_update", "swot_company_delete", "swot_company_update", "swot_company_immutable"):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{name}"))
    if sa.inspect(connection).has_table("swot_analyses"):
        op.drop_table("swot_analyses")
