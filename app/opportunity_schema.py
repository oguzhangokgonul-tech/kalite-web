"""Opportunity integrity guards for legacy SQLite installations with FK checks off."""
from sqlalchemy import inspect, text


GUARD_NAMES = (
    "opportunity_tenant_insert", "opportunity_tenant_update",
    "opportunity_required_insert", "opportunity_required_update",
    "opportunity_user_delete", "opportunity_user_update",
    "opportunity_company_delete", "opportunity_company_update",
    "opportunity_action_delete", "opportunity_action_update", "opportunity_company_immutable",
)


def ensure_opportunity_sqlite_guards(connection):
    if connection.dialect.name != "sqlite" or not inspect(connection).has_table("opportunities"):
        return
    predicate = (
        "EXISTS (SELECT 1 FROM companies c WHERE c.id=NEW.company_id) "
        "AND EXISTS (SELECT 1 FROM users u WHERE u.id=NEW.owner_user_id AND u.company_id=NEW.company_id) "
        "AND EXISTS (SELECT 1 FROM users u WHERE u.id=NEW.created_by_user_id "
        "AND (u.company_id=NEW.company_id OR u.company_id IS NULL)) "
        "AND (NEW.reviewed_by_user_id IS NULL OR EXISTS (SELECT 1 FROM users u "
        "WHERE u.id=NEW.reviewed_by_user_id AND (u.company_id=NEW.company_id OR u.company_id IS NULL))) "
        "AND (NEW.action_id IS NULL OR EXISTS (SELECT 1 FROM actions a "
        "WHERE a.id=NEW.action_id AND a.company_id=NEW.company_id))"
    )
    whitespace = "char(9,10,11,12,13,28,29,30,31,32,133,160,5760,8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288)"
    def present(field):
        return f"length(trim(coalesce(NEW.{field},''), {whitespace})) > 0"
    active = " AND ".join(present(field) for field in ("description", "expected_benefit", "planned_action", "success_criteria"))
    closed = " AND ".join(present(field) for field in ("result_note", "evidence_sources"))
    invalid = (
        f"NOT ({present('title')}) OR "
        f"(NEW.status IN ('active','realized','not_realized') AND NOT ({active})) OR "
        f"(NEW.status IN ('realized','not_realized') AND NOT ({closed})) OR "
        f"(NEW.status='archived' AND NOT ({present('archive_note')}))"
    )
    for operation in ("INSERT", "UPDATE"):
        for kind, condition, message in (("tenant", f"NOT ({predicate})", "opportunity tenant mismatch"),
                                         ("required", invalid, "opportunity required text missing")):
            connection.execute(text(
                f"CREATE TRIGGER IF NOT EXISTS trg_opportunity_{kind}_{operation.lower()} "
                f"BEFORE {operation} ON opportunities WHEN {condition} "
                f"BEGIN SELECT RAISE(ABORT, '{message}'); END"))
    user_refs = "EXISTS (SELECT 1 FROM opportunities o WHERE o.owner_user_id=OLD.id OR o.created_by_user_id=OLD.id OR o.reviewed_by_user_id=OLD.id)"
    company_refs = "EXISTS (SELECT 1 FROM opportunities o WHERE o.company_id=OLD.id)"
    action_refs = "EXISTS (SELECT 1 FROM opportunities o WHERE o.action_id=OLD.id)"
    guards = (
        ("user_delete", "BEFORE DELETE ON users", user_refs),
        ("user_update", "BEFORE UPDATE OF id,company_id ON users", f"(NEW.id IS NOT OLD.id OR NEW.company_id IS NOT OLD.company_id) AND {user_refs}"),
        ("company_delete", "BEFORE DELETE ON companies", company_refs),
        ("company_update", "BEFORE UPDATE OF id ON companies", f"NEW.id IS NOT OLD.id AND {company_refs}"),
        ("action_delete", "BEFORE DELETE ON actions", action_refs),
        ("action_update", "BEFORE UPDATE OF id,company_id ON actions", f"(NEW.id IS NOT OLD.id OR NEW.company_id IS NOT OLD.company_id) AND {action_refs}"),
        ("company_immutable", "BEFORE UPDATE OF company_id ON opportunities", "NEW.company_id IS NOT OLD.company_id"),
    )
    for name, event, condition in guards:
        connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS trg_opportunity_{name} {event} WHEN {condition} "
                                "BEGIN SELECT RAISE(ABORT, 'opportunity referenced record'); END"))


def drop_opportunity_sqlite_guards(connection):
    if connection.dialect.name == "sqlite":
        for name in GUARD_NAMES:
            connection.execute(text(f"DROP TRIGGER IF EXISTS trg_{name}"))
