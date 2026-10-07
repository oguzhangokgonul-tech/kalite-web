"""Organization context SQLite guards for installations with legacy FK enforcement off."""
from sqlalchemy import inspect, text


def ensure_context_sqlite_guards(connection):
    if connection.dialect.name != "sqlite" or not inspect(connection).has_table("organization_contexts"):
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
        connection.execute(text(
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
        connection.execute(text(
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
        connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS trg_{name} {event} WHEN {condition} "
                                "BEGIN SELECT RAISE(ABORT, 'context referenced record'); END"))


def drop_context_sqlite_guards(connection):
    if connection.dialect.name == "sqlite":
        for name in ("context_required_insert", "context_required_update", "organization_contexts_tenant_insert", "organization_contexts_tenant_update", "context_user_delete",
                     "context_user_update", "context_company_delete", "context_company_update", "context_company_immutable"):
            connection.execute(text(f"DROP TRIGGER IF EXISTS trg_{name}"))
