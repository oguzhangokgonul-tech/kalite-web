"""SQLite integrity even when legacy connections have foreign_keys disabled."""
from sqlalchemy import inspect, text


PARENTS = (
    ('objective', 'quality_objectives', 'objective_id'),
    ('project', 'project_records', 'project_id'),
    ('action', 'actions', 'action_id'),
    ('user', 'users', 'created_by_user_id'),
)
GUARDS = ('tenant_insert', 'duplicate_insert', 'immutable_update', 'immutable_delete') + tuple(
    f'{name}_{operation}' for name, _, _ in PARENTS for operation in ('delete', 'update', 'replace')
) + ('company_delete', 'company_update')


def ensure_objective_plan_schema(engine):
    """Run after legacy parent tables exist; do not create or alter those tables."""
    from .objective_plan_models import ObjectivePlanLink
    with engine.begin() as connection:
        ObjectivePlanLink.__table__.create(connection, checkfirst=True)
        # after_create does not fire when a previous runtime already created the table.
        ensure_objective_plan_sqlite_guards(connection)


def ensure_objective_plan_sqlite_guards(connection):
    if connection.dialect.name != 'sqlite' or not inspect(connection).has_table('objective_plan_links'):
        return
    valid = (
        "EXISTS(SELECT 1 FROM companies WHERE id=NEW.company_id) AND "
        "EXISTS(SELECT 1 FROM quality_objectives WHERE id=NEW.objective_id "
        "AND company_id=NEW.company_id AND status IN ('Taslak','Aktif')) AND "
        "EXISTS(SELECT 1 FROM users u WHERE u.id=NEW.created_by_user_id AND "
        "(u.company_id=NEW.company_id OR EXISTS(SELECT 1 FROM user_roles ur "
        "JOIN roles r ON r.id=ur.role_id WHERE ur.user_id=u.id AND r.key='super_admin'))) AND "
        "((NEW.kind='project' AND NEW.action_id IS NULL AND EXISTS(SELECT 1 FROM project_records "
        "WHERE id=NEW.project_id AND company_id=NEW.company_id)) OR "
        "(NEW.kind='action' AND NEW.project_id IS NULL AND EXISTS(SELECT 1 FROM actions "
        "WHERE id=NEW.action_id AND company_id=NEW.company_id)))"
    )
    # REPLACE can bypass DELETE triggers with recursive_triggers disabled.
    duplicate = (
        "EXISTS(SELECT 1 FROM objective_plan_links WHERE id=NEW.id OR "
        "(company_id=NEW.company_id AND objective_id=NEW.objective_id AND kind=NEW.kind) OR "
        "project_id=NEW.project_id OR action_id=NEW.action_id)"
    )
    definitions = [
        ('tenant_insert', 'BEFORE INSERT ON objective_plan_links', f'NOT ({valid})'),
        ('duplicate_insert', 'BEFORE INSERT ON objective_plan_links', duplicate),
        ('immutable_update', 'BEFORE UPDATE ON objective_plan_links', '1'),
        ('immutable_delete', 'BEFORE DELETE ON objective_plan_links', '1'),
    ]
    for name, table, column in PARENTS:
        refs = f'EXISTS(SELECT 1 FROM objective_plan_links WHERE {column}=OLD.id)'
        definitions.extend([
            (f'{name}_delete', f'BEFORE DELETE ON {table}', refs),
            (f'{name}_update', f'BEFORE UPDATE OF id,company_id ON {table}',
             f'((NEW.id IS NOT OLD.id OR NEW.company_id IS NOT OLD.company_id) AND {refs}) OR '
             f'(NEW.id IS NOT OLD.id AND EXISTS(SELECT 1 FROM objective_plan_links WHERE {column}=NEW.id))'),
            (f'{name}_replace', f'BEFORE INSERT ON {table}',
             f'EXISTS(SELECT 1 FROM {table} p JOIN objective_plan_links l ON l.{column}=p.id '
             'WHERE p.id=NEW.id AND NEW.company_id IS NOT p.company_id)'),
        ])
    company_refs = 'EXISTS(SELECT 1 FROM objective_plan_links WHERE company_id=OLD.id)'
    definitions.extend([
        ('company_delete', 'BEFORE DELETE ON companies', company_refs),
        ('company_update', 'BEFORE UPDATE OF id ON companies',
         f'NEW.id IS NOT OLD.id AND ({company_refs} OR '
         'EXISTS(SELECT 1 FROM objective_plan_links WHERE company_id=NEW.id))'),
    ])
    # Refresh stale definitions atomically, but leave already-correct guards alone.
    with connection.begin_nested():
        for name, event, predicate in definitions:
            trigger = f'trg_objective_plan_{name}'
            statement = (f'CREATE TRIGGER {trigger} {event} WHEN {predicate} '
                         "BEGIN SELECT RAISE(ABORT, 'objective plan integrity guard'); END")
            previous = connection.execute(text(
                "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=:name"
            ), {'name': trigger}).scalar()
            if previous == statement:
                continue
            if previous:
                connection.execute(text(f'DROP TRIGGER {trigger}'))
            connection.execute(text(statement))


def drop_objective_plan_sqlite_guards(connection):
    if connection.dialect.name == 'sqlite':
        for name in GUARDS:
            connection.execute(text(f'DROP TRIGGER IF EXISTS trg_objective_plan_{name}'))
