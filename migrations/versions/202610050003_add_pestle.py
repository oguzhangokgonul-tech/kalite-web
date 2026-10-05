"""Tenant-scoped PESTLE analyses.

Revision ID: 202610050003
Revises: 202610050002
"""
from alembic import op
import sqlalchemy as sa

revision = "202610050003"
down_revision = "202610050002"
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
            f"CREATE TRIGGER IF NOT EXISTS trg_pestle_analyses_tenant_{operation.lower()} "
            f"BEFORE {operation} ON pestle_analyses WHEN NOT ({predicate}) "
            "BEGIN SELECT RAISE(ABORT, 'pestle tenant mismatch'); END"
        ))
    references = (
        "EXISTS (SELECT 1 FROM pestle_analyses a WHERE a.owner_user_id=OLD.id "
        "OR a.created_by_user_id=OLD.id OR a.reviewed_by_user_id=OLD.id)"
    )
    guards = (
        ("pestle_user_delete", "BEFORE DELETE ON users", references),
        ("pestle_user_update", "BEFORE UPDATE OF id,company_id ON users",
         f"(NEW.id IS NOT OLD.id OR NEW.company_id IS NOT OLD.company_id) AND {references}"),
        ("pestle_company_delete", "BEFORE DELETE ON companies",
         "EXISTS (SELECT 1 FROM pestle_analyses a WHERE a.company_id=OLD.id)"),
        ("pestle_company_update", "BEFORE UPDATE OF id ON companies",
         "NEW.id IS NOT OLD.id AND EXISTS (SELECT 1 FROM pestle_analyses a WHERE a.company_id=OLD.id)"),
        ("pestle_company_immutable", "BEFORE UPDATE OF company_id ON pestle_analyses",
         "NEW.company_id IS NOT OLD.company_id"),
    )
    for name, event, condition in guards:
        op.execute(sa.text(f"CREATE TRIGGER IF NOT EXISTS trg_{name} {event} WHEN {condition} "
                           "BEGIN SELECT RAISE(ABORT, 'pestle referenced record'); END"))


def upgrade():
    connection = op.get_bind()
    if not sa.inspect(connection).has_table("pestle_analyses"):
        op.create_table("pestle_analyses",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("scope", sa.Text()),
            sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("analysis_date", sa.Date(), nullable=False),
            sa.Column("review_date", sa.Date(), nullable=False),
            sa.Column("political", sa.Text()),
            sa.Column("economic", sa.Text()),
            sa.Column("social", sa.Text()),
            sa.Column("technological", sa.Text()),
            sa.Column("legal", sa.Text()),
            sa.Column("environmental", sa.Text()),
            sa.Column("evidence_sources", sa.Text()),
            sa.Column("strategy", sa.Text()),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("review_note", sa.Text()),
            sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("reviewed_at", sa.DateTime()),
            sa.Column("archive_note", sa.Text()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
            sa.CheckConstraint("status IN ('draft', 'reviewed', 'archived')", name="ck_pestle_analyses_status"),
            sa.CheckConstraint("review_date > analysis_date", name="ck_pestle_analyses_dates"),
            sa.CheckConstraint("length(trim(title)) BETWEEN 1 AND 240", name="ck_pestle_analyses_title"),
            sa.CheckConstraint("version_id > 0", name="ck_pestle_analyses_version"),
            sa.CheckConstraint(
                "status != 'reviewed' OR ("
                "length(trim(coalesce(political, ''))) > 0 AND "
                "length(trim(coalesce(economic, ''))) > 0 AND "
                "length(trim(coalesce(social, ''))) > 0 AND "
                "length(trim(coalesce(technological, ''))) > 0 AND "
                "length(trim(coalesce(legal, ''))) > 0 AND "
                "length(trim(coalesce(environmental, ''))) > 0 AND "
                "length(trim(coalesce(evidence_sources, ''))) > 0 AND "
                "length(trim(coalesce(strategy, ''))) > 0 AND "
                "length(trim(coalesce(review_note, ''))) > 0 AND "
                "reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL)",
                name="ck_pestle_analyses_reviewed"),
            sa.CheckConstraint(
                "status != 'draft' OR (review_note IS NULL AND reviewed_by_user_id IS NULL AND reviewed_at IS NULL)",
                name="ck_pestle_analyses_draft"),
            sa.CheckConstraint("status != 'archived' OR length(trim(coalesce(archive_note, ''))) > 0",
                name="ck_pestle_analyses_archive"),
        )
    indexes = {item["name"] for item in sa.inspect(connection).get_indexes("pestle_analyses")}
    for column in ("company_id", "owner_user_id", "analysis_date", "review_date", "status"):
        name = f"ix_pestle_analyses_{column}"
        if name not in indexes:
            op.create_index(name, "pestle_analyses", [column])
    install_sqlite_guards()


def downgrade():
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        for name in ("pestle_analyses_tenant_insert", "pestle_analyses_tenant_update", "pestle_user_delete",
                     "pestle_user_update", "pestle_company_delete", "pestle_company_update", "pestle_company_immutable"):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{name}"))
    if sa.inspect(connection).has_table("pestle_analyses"):
        op.drop_table("pestle_analyses")
