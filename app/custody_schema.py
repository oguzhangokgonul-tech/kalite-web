from sqlalchemy import text

GUARDS = ('tenant_insert', 'tenant_update', 'identity', 'closed', 'person_delete', 'person_update',
          'user_delete', 'user_update', 'company_delete')


def ensure_custody_guards(connection):
    if connection.dialect.name != 'sqlite':
        return
    valid = ("EXISTS(SELECT 1 FROM companies WHERE id=NEW.company_id) AND "
             "EXISTS(SELECT 1 FROM personnel_contacts WHERE id=NEW.personnel_contact_id AND company_id=NEW.company_id)")
    def actor(column):
        return (f"EXISTS(SELECT 1 FROM users u WHERE u.id=NEW.{column} AND "
                "(u.company_id=NEW.company_id OR EXISTS(SELECT 1 FROM user_roles ur "
                "JOIN roles r ON r.id=ur.role_id WHERE ur.user_id=u.id AND r.key='super_admin')))")
    returned_actor = f"(NEW.returned_by_user_id IS NULL OR {actor('returned_by_user_id')})"
    insert_valid = f"{valid} AND {actor('created_by_user_id')} AND {returned_actor}"
    # Historical creator authorization is not re-evaluated after a role change.
    update_valid = f"{valid} AND (NEW.returned_by_user_id IS OLD.returned_by_user_id OR {returned_actor})"
    definitions = [
        ('tenant_insert', 'BEFORE INSERT ON custody_records', f'NOT ({insert_valid})'),
        ('tenant_update', 'BEFORE UPDATE ON custody_records', f'NOT ({update_valid})'),
        ('identity', 'BEFORE UPDATE ON custody_records', 'NEW.company_id IS NOT OLD.company_id OR NEW.created_by_user_id IS NOT OLD.created_by_user_id OR NEW.request_token IS NOT OLD.request_token OR NEW.created_at IS NOT OLD.created_at'),
        ('closed', 'BEFORE UPDATE ON custody_records', 'OLD.returned_date IS NOT NULL'),
        ('person_delete', 'BEFORE DELETE ON personnel_contacts', 'EXISTS(SELECT 1 FROM custody_records WHERE personnel_contact_id=OLD.id)'),
        ('person_update', 'BEFORE UPDATE OF id,company_id ON personnel_contacts', '(NEW.id IS NOT OLD.id OR NEW.company_id IS NOT OLD.company_id) AND EXISTS(SELECT 1 FROM custody_records WHERE personnel_contact_id=OLD.id)'),
        ('user_delete', 'BEFORE DELETE ON users', 'EXISTS(SELECT 1 FROM custody_records WHERE created_by_user_id=OLD.id OR returned_by_user_id=OLD.id)'),
        ('user_update', 'BEFORE UPDATE OF id,company_id ON users', '(NEW.id IS NOT OLD.id OR NEW.company_id IS NOT OLD.company_id) AND EXISTS(SELECT 1 FROM custody_records WHERE created_by_user_id=OLD.id OR returned_by_user_id=OLD.id)'),
        ('company_delete', 'BEFORE DELETE ON companies', 'EXISTS(SELECT 1 FROM custody_records WHERE company_id=OLD.id)'),
    ]
    with connection.begin_nested():
        for name, event, predicate in definitions:
            trigger_name = f'trg_custody_{name}'
            statement = f"CREATE TRIGGER {trigger_name} {event} WHEN {predicate} BEGIN SELECT RAISE(ABORT, 'custody integrity guard'); END"
            previous = connection.execute(text("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=:name"), {'name': trigger_name}).scalar()
            if previous == statement:
                continue
            if previous:
                connection.execute(text(f'DROP TRIGGER {trigger_name}'))
            connection.execute(text(statement))


def drop_custody_guards(connection):
    if connection.dialect.name == 'sqlite':
        for name in GUARDS:
            connection.execute(text(f'DROP TRIGGER IF EXISTS trg_custody_{name}'))
