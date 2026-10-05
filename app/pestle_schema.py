"""PESTLE SQLite guards for installations with legacy FK enforcement off."""
from sqlalchemy import inspect, text


def ensure_pestle_sqlite_guards(connection):
    if connection.dialect.name != "sqlite" or not inspect(connection).has_table("pestle_analyses"):
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
        connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS trg_{name} {event} WHEN {condition} "
                                "BEGIN SELECT RAISE(ABORT, 'pestle referenced record'); END"))


def drop_pestle_sqlite_guards(connection):
    if connection.dialect.name == "sqlite":
        for name in ("pestle_analyses_tenant_insert", "pestle_analyses_tenant_update", "pestle_user_delete",
                     "pestle_user_update", "pestle_company_delete", "pestle_company_update", "pestle_company_immutable"):
            connection.execute(text(f"DROP TRIGGER IF EXISTS trg_{name}"))
