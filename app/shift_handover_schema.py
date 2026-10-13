"""Explicit seed hook and SQLite guards, including legacy FK-disabled databases."""
from sqlalchemy import inspect, text


GUARDS = ('tenant_insert', 'tenant_update', 'identity', 'transition', 'content',
          'sent_identity', 'received_identity', 'archived', 'version', 'delete',
          'user_delete', 'user_update', 'department_delete', 'department_update',
          'company_delete', 'company_update', 'initial', 'cancelled_identity')


def ensure_shift_handover_schema():
    from .extensions import db
    from .shift_handover_models import ShiftHandover
    with db.engine.begin() as connection:
        ShiftHandover.__table__.create(bind=connection, checkfirst=True)
        ensure_shift_handover_guards(connection)


def ensure_shift_handover_guards(connection):
    if connection.dialect.name != 'sqlite' or not inspect(connection).has_table('shift_handovers'):
        return

    def actor(column):
        return (f'EXISTS(SELECT 1 FROM users u WHERE u.id=NEW.{column} AND '
                '(u.company_id=NEW.company_id OR EXISTS(SELECT 1 FROM user_roles ur '
                "JOIN roles r ON r.id=ur.role_id WHERE ur.user_id=u.id AND r.key='super_admin')))")

    valid = ('EXISTS(SELECT 1 FROM companies WHERE id=NEW.company_id) AND '
             'EXISTS(SELECT 1 FROM company_departments WHERE id=NEW.department_id AND company_id=NEW.company_id) AND '
             'EXISTS(SELECT 1 FROM users WHERE id=NEW.receiver_user_id AND company_id=NEW.company_id)')
    insert_valid = f'{valid} AND {actor("sender_user_id")}'
    # Do not re-authorize historical actors after their roles change.
    update_valid = valid + ''.join(
        f' AND (NEW.{column} IS OLD.{column} OR NEW.{column} IS NULL OR {actor(column)})'
        for column in ('sent_by_user_id', 'archived_by_user_id', 'cancelled_by_user_id'))
    content_columns = ('handover_date', 'shift_name', 'department_id', 'area', 'title', 'summary',
                       'pending_work', 'safety_notes', 'quality_notes', 'equipment_notes', 'receiver_user_id')
    changed_content = ' OR '.join(f'NEW.{column} IS NOT OLD.{column}' for column in content_columns)
    user_refs = ('EXISTS(SELECT 1 FROM shift_handovers WHERE sender_user_id=OLD.id OR receiver_user_id=OLD.id '
                 'OR sent_by_user_id=OLD.id OR received_by_user_id=OLD.id OR archived_by_user_id=OLD.id OR cancelled_by_user_id=OLD.id)')
    department_refs = 'EXISTS(SELECT 1 FROM shift_handovers WHERE department_id=OLD.id)'
    company_refs = 'EXISTS(SELECT 1 FROM shift_handovers WHERE company_id=OLD.id)'
    definitions = (
        ('tenant_insert', 'BEFORE INSERT ON shift_handovers', f'NOT ({insert_valid})'),
        ('tenant_update', 'BEFORE UPDATE ON shift_handovers', f'NOT ({update_valid})'),
        ('initial', 'BEFORE INSERT ON shift_handovers', "NEW.status != 'draft' OR NEW.archived_at IS NOT NULL OR NEW.version_id != 1"),
        ('identity', 'BEFORE UPDATE ON shift_handovers', 'NEW.id IS NOT OLD.id OR NEW.company_id IS NOT OLD.company_id OR NEW.sender_user_id IS NOT OLD.sender_user_id OR NEW.request_token IS NOT OLD.request_token OR NEW.created_at IS NOT OLD.created_at'),
        ('transition', 'BEFORE UPDATE ON shift_handovers', "NOT (NEW.status = OLD.status OR (OLD.status='draft' AND NEW.status IN ('sent','cancelled')) OR (OLD.status='sent' AND NEW.status IN ('received','cancelled')))"),
        ('content', 'BEFORE UPDATE ON shift_handovers', f"OLD.status != 'draft' AND ({changed_content})"),
        ('sent_identity', 'BEFORE UPDATE ON shift_handovers', "OLD.status != 'draft' AND (NEW.sent_at IS NOT OLD.sent_at OR NEW.sent_by_user_id IS NOT OLD.sent_by_user_id)"),
        ('received_identity', 'BEFORE UPDATE ON shift_handovers', "OLD.status = 'received' AND (NEW.received_at IS NOT OLD.received_at OR NEW.received_by_user_id IS NOT OLD.received_by_user_id)"),
        ('cancelled_identity', 'BEFORE UPDATE ON shift_handovers', "OLD.status = 'cancelled' AND (NEW.cancelled_at IS NOT OLD.cancelled_at OR NEW.cancelled_by_user_id IS NOT OLD.cancelled_by_user_id OR NEW.cancel_reason IS NOT OLD.cancel_reason)"),
        ('archived', 'BEFORE UPDATE ON shift_handovers', "OLD.archived_at IS NOT NULL OR (NEW.archived_at IS NOT NULL AND NEW.status NOT IN ('received','cancelled'))"),
        ('version', 'BEFORE UPDATE ON shift_handovers', 'NEW.version_id != OLD.version_id + 1'),
        ('delete', 'BEFORE DELETE ON shift_handovers', '1'),
        ('user_delete', 'BEFORE DELETE ON users', user_refs),
        ('user_update', 'BEFORE UPDATE OF id,company_id ON users', f'(NEW.id IS NOT OLD.id OR NEW.company_id IS NOT OLD.company_id) AND {user_refs}'),
        ('department_delete', 'BEFORE DELETE ON company_departments', department_refs),
        ('department_update', 'BEFORE UPDATE OF id,company_id ON company_departments', f'(NEW.id IS NOT OLD.id OR NEW.company_id IS NOT OLD.company_id) AND {department_refs}'),
        ('company_delete', 'BEFORE DELETE ON companies', company_refs),
        ('company_update', 'BEFORE UPDATE OF id ON companies', f'NEW.id IS NOT OLD.id AND {company_refs}'),
    )
    with connection.begin_nested():
        for name, event, predicate in definitions:
            trigger_name = f'trg_shift_handover_{name}'
            statement = f"CREATE TRIGGER {trigger_name} {event} WHEN {predicate} BEGIN SELECT RAISE(ABORT, 'shift handover integrity guard'); END"
            previous = connection.execute(text("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=:name"), {'name': trigger_name}).scalar()
            if previous == statement:
                continue
            if previous:
                connection.execute(text(f'DROP TRIGGER {trigger_name}'))
            connection.execute(text(statement))


def drop_shift_handover_guards(connection):
    if connection.dialect.name == 'sqlite':
        for name in GUARDS:
            connection.execute(text(f'DROP TRIGGER IF EXISTS trg_shift_handover_{name}'))
