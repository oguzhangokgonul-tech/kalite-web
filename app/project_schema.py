"""Project-only SQLite guards for installations with legacy FK enforcement off."""
from sqlalchemy import inspect, text


def ensure_project_sqlite_guards(connection):
    if connection.dialect.name != "sqlite":
        return
    predicates = {
        "project_records": (
            "EXISTS (SELECT 1 FROM companies c WHERE c.id=NEW.company_id) "
            "AND EXISTS (SELECT 1 FROM users u WHERE u.id=NEW.owner_user_id AND u.company_id=NEW.company_id) "
            "AND EXISTS (SELECT 1 FROM users u WHERE u.id=NEW.created_by_user_id "
            "AND (u.company_id=NEW.company_id OR u.company_id IS NULL))"
        ),
        "project_tasks": (
            "EXISTS (SELECT 1 FROM project_records p WHERE p.id=NEW.project_id AND p.company_id=NEW.company_id) "
            "AND EXISTS (SELECT 1 FROM users u WHERE u.id=NEW.owner_user_id AND u.company_id=NEW.company_id)"
        ),
    }
    for table, predicate in predicates.items():
        for operation in ("INSERT", "UPDATE"):
            connection.execute(text(
                f"CREATE TRIGGER IF NOT EXISTS trg_{table}_tenant_{operation.lower()} "
                f"BEFORE {operation} ON {table} WHEN NOT ({predicate}) "
                "BEGIN SELECT RAISE(ABORT, 'project tenant mismatch'); END"
            ))
    guards = (
        ("project_parent_update", "BEFORE UPDATE OF id,company_id ON project_records",
         "(NEW.id != OLD.id OR NEW.company_id != OLD.company_id) AND EXISTS (SELECT 1 FROM project_tasks t WHERE t.project_id=OLD.id)"),
        ("project_parent_delete", "BEFORE DELETE ON project_records",
         "EXISTS (SELECT 1 FROM project_tasks t WHERE t.project_id=OLD.id)"),
        ("project_user_delete", "BEFORE DELETE ON users",
         "EXISTS (SELECT 1 FROM project_records p WHERE p.owner_user_id=OLD.id OR p.created_by_user_id=OLD.id) OR EXISTS (SELECT 1 FROM project_tasks t WHERE t.owner_user_id=OLD.id)"),
        ("project_user_update", "BEFORE UPDATE OF id,company_id ON users",
         "(NEW.id IS NOT OLD.id OR NEW.company_id IS NOT OLD.company_id) AND (EXISTS (SELECT 1 FROM project_records p WHERE p.owner_user_id=OLD.id OR p.created_by_user_id=OLD.id) OR EXISTS (SELECT 1 FROM project_tasks t WHERE t.owner_user_id=OLD.id))"),
        ("project_company_delete", "BEFORE DELETE ON companies",
         "EXISTS (SELECT 1 FROM project_records p WHERE p.company_id=OLD.id)"),
        ("project_company_update", "BEFORE UPDATE OF id ON companies",
         "NEW.id != OLD.id AND EXISTS (SELECT 1 FROM project_records p WHERE p.company_id=OLD.id)"),
    )
    for name, event, predicate in guards:
        connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS trg_{name} {event} WHEN {predicate} "
                                "BEGIN SELECT RAISE(ABORT, 'project referenced record'); END"))
    if not inspect(connection).has_table("project_milestones"):
        return
    milestone_predicate = (
        "EXISTS (SELECT 1 FROM project_records p WHERE p.id=NEW.project_id "
        "AND p.company_id=NEW.company_id AND NEW.target_date BETWEEN p.start_date AND p.due_date)"
    )
    for operation in ("INSERT", "UPDATE"):
        connection.execute(text(
            f"CREATE TRIGGER IF NOT EXISTS trg_project_milestones_tenant_{operation.lower()} "
            f"BEFORE {operation} ON project_milestones WHEN NOT ({milestone_predicate}) "
            "BEGIN SELECT RAISE(ABORT, 'project milestone tenant or date mismatch'); END"
        ))
    milestone_guards = (
        ("project_milestone_parent_update", "BEFORE UPDATE OF id,company_id,start_date,due_date ON project_records",
         "EXISTS (SELECT 1 FROM project_milestones m WHERE m.project_id=OLD.id "
         "AND ((NEW.id IS NOT OLD.id OR NEW.company_id IS NOT OLD.company_id) "
         "OR m.target_date < NEW.start_date OR m.target_date > NEW.due_date))"),
        ("project_milestone_parent_delete", "BEFORE DELETE ON project_records",
         "EXISTS (SELECT 1 FROM project_milestones m WHERE m.project_id=OLD.id)"),
    )
    for name, event, predicate in milestone_guards:
        connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS trg_{name} {event} WHEN {predicate} "
                                "BEGIN SELECT RAISE(ABORT, 'project referenced milestone'); END"))


def drop_project_sqlite_milestone_parent_guards(connection):
    if connection.dialect.name == "sqlite":
        for name in ("project_milestone_parent_update", "project_milestone_parent_delete"):
            connection.execute(text(f"DROP TRIGGER IF EXISTS trg_{name}"))


def drop_project_sqlite_guards(connection):
    if connection.dialect.name == "sqlite":
        drop_project_sqlite_milestone_parent_guards(connection)
        for name in ("project_user_delete", "project_user_update", "project_company_delete", "project_company_update"):
            connection.execute(text(f"DROP TRIGGER IF EXISTS trg_{name}"))
