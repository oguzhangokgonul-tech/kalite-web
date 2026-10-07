"""Tenant-scoped organization contexts.

Revision ID: 202610050004
Revises: 202610050003
"""
from alembic import op
import sqlalchemy as sa

revision = "202610050004"
down_revision = "202610050003"
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
            f"CREATE TRIGGER IF NOT EXISTS trg_organization_contexts_tenant_{operation.lower()} "
            f"BEFORE {operation} ON organization_contexts WHEN NOT ({predicate}) "
            "BEGIN SELECT RAISE(ABORT, 'context tenant mismatch'); END"
        ))
    whitespace = "char(9,10,11,12,13,28,29,30,31,32,133,160,5760,8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288)"
    required = " AND ".join(
        f"length(trim(coalesce(NEW.{field}, ''), {whitespace})) > 0"
        for field in ("scope", "internal_issues", "external_issues", "climate_reason",
                      "evidence_sources", "strategy", "review_note")
    )
    invalid = (
        f"length(trim(NEW.title, {whitespace})) = 0 OR "
        f"(NEW.status = 'reviewed' AND NOT ({required})) OR "
        f"(NEW.status = 'archived' AND length(trim(coalesce(NEW.archive_note, ''), {whitespace})) = 0)"
    )
    for operation in ("INSERT", "UPDATE"):
        op.execute(sa.text(
            f"CREATE TRIGGER IF NOT EXISTS trg_context_required_{operation.lower()} "
            f"BEFORE {operation} ON organization_contexts WHEN {invalid} "
            "BEGIN SELECT RAISE(ABORT, 'context required text missing'); END"
        ))
    references = (
        "EXISTS (SELECT 1 FROM organization_contexts a WHERE a.owner_user_id=OLD.id "
        "OR a.created_by_user_id=OLD.id OR a.reviewed_by_user_id=OLD.id)"
    )
    guards = (
        ("context_user_delete", "BEFORE DELETE ON users", references),
        ("context_user_update", "BEFORE UPDATE OF id,company_id ON users",
         f"(NEW.id IS NOT OLD.id OR NEW.company_id IS NOT OLD.company_id) AND {references}"),
        ("context_company_delete", "BEFORE DELETE ON companies",
         "EXISTS (SELECT 1 FROM organization_contexts a WHERE a.company_id=OLD.id)"),
        ("context_company_update", "BEFORE UPDATE OF id ON companies",
         "NEW.id IS NOT OLD.id AND EXISTS (SELECT 1 FROM organization_contexts a WHERE a.company_id=OLD.id)"),
        ("context_company_immutable", "BEFORE UPDATE OF company_id ON organization_contexts",
         "NEW.company_id IS NOT OLD.company_id"),
    )
    for name, event, condition in guards:
        op.execute(sa.text(f"CREATE TRIGGER IF NOT EXISTS trg_{name} {event} WHEN {condition} "
                           "BEGIN SELECT RAISE(ABORT, 'context referenced record'); END"))


def upgrade():
    connection = op.get_bind()
    if not sa.inspect(connection).has_table("organization_contexts"):
        op.create_table("organization_contexts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("scope", sa.Text()),
            sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("analysis_date", sa.Date(), nullable=False),
            sa.Column("review_date", sa.Date(), nullable=False),
            sa.Column("internal_issues", sa.Text()),
            sa.Column("external_issues", sa.Text()),
            sa.Column("climate_relevance", sa.String(20), nullable=False, server_default="under_review"),
            sa.Column("climate_reason", sa.Text()),
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
            sa.CheckConstraint("climate_relevance IN ('under_review', 'relevant', 'not_relevant')",
                name="ck_organization_contexts_climate_relevance"),
            sa.CheckConstraint("status IN ('draft', 'reviewed', 'archived')", name="ck_organization_contexts_status"),
            sa.CheckConstraint("review_date > analysis_date", name="ck_organization_contexts_dates"),
            sa.CheckConstraint("length(trim(title)) BETWEEN 1 AND 240", name="ck_organization_contexts_title"),
            sa.CheckConstraint("version_id > 0", name="ck_organization_contexts_version"),
            sa.CheckConstraint(
                "status != 'reviewed' OR ("
                "length(trim(coalesce(scope, ''))) > 0 AND "
                "length(trim(coalesce(internal_issues, ''))) > 0 AND "
                "length(trim(coalesce(external_issues, ''))) > 0 AND "
                "length(trim(coalesce(climate_reason, ''))) > 0 AND "
                "climate_relevance IN ('relevant', 'not_relevant') AND "
                "length(trim(coalesce(evidence_sources, ''))) > 0 AND "
                "length(trim(coalesce(strategy, ''))) > 0 AND "
                "length(trim(coalesce(review_note, ''))) > 0 AND "
                "reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL)",
                name="ck_organization_contexts_reviewed"),
            sa.CheckConstraint(
                "status != 'draft' OR (review_note IS NULL AND reviewed_by_user_id IS NULL AND reviewed_at IS NULL)",
                name="ck_organization_contexts_draft"),
            sa.CheckConstraint("status != 'archived' OR length(trim(coalesce(archive_note, ''))) > 0",
                name="ck_organization_contexts_archive"),
        )
    indexes = {item["name"] for item in sa.inspect(connection).get_indexes("organization_contexts")}
    for column in ("company_id", "owner_user_id", "analysis_date", "review_date", "status"):
        name = f"ix_organization_contexts_{column}"
        if name not in indexes:
            op.create_index(name, "organization_contexts", [column])
    install_sqlite_guards()


def downgrade():
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        for name in ("context_required_insert", "context_required_update", "organization_contexts_tenant_insert", "organization_contexts_tenant_update", "context_user_delete",
                     "context_user_update", "context_company_delete", "context_company_update", "context_company_immutable"):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{name}"))
    if sa.inspect(connection).has_table("organization_contexts"):
        op.drop_table("organization_contexts")
