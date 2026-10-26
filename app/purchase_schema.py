"""Runtime schema hook and SQLite integrity guards for purchase requests."""
from sqlalchemy import inspect, text


GUARDS = ('request_insert', 'request_update', 'request_identity', 'request_transition',
          'request_version', 'request_delete', 'decision_insert', 'decision_update',
          'decision_delete', 'item_insert', 'item_update', 'item_delete')


def ensure_purchase_schema():
    from .extensions import db
    from .purchase_models import PurchaseDecision, PurchaseRequest, PurchaseRequestItem
    with db.engine.begin() as connection:
        PurchaseRequest.__table__.create(bind=connection, checkfirst=True)
        PurchaseRequestItem.__table__.create(bind=connection, checkfirst=True)
        PurchaseDecision.__table__.create(bind=connection, checkfirst=True)
        ensure_purchase_guards(connection)


def ensure_purchase_guards(connection):
    if connection.dialect.name != 'sqlite':
        return
    inspector = inspect(connection)
    if not all(inspector.has_table(name) for name in ('purchase_requests', 'purchase_request_items', 'purchase_decisions')):
        return
    def actor(column):
        return (f'EXISTS(SELECT 1 FROM users u WHERE u.id=NEW.{column} AND '
                '(u.company_id=NEW.company_id OR (u.company_id IS NULL AND '
                'EXISTS(SELECT 1 FROM user_roles ur JOIN roles r ON r.id=ur.role_id '
                "WHERE ur.user_id=u.id AND r.key='super_admin'))))")

    definitions = (
        ('request_insert', 'BEFORE INSERT ON purchase_requests',
         "NEW.status != 'draft' OR NEW.version_id != 1 OR "
         'NOT EXISTS(SELECT 1 FROM companies WHERE id=NEW.company_id) OR '
         f'NOT {actor("requester_id")} OR '
         '(NEW.purchasing_approver_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.purchasing_approver_id AND company_id=NEW.company_id)) OR '
         '(NEW.admin_approver_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.admin_approver_id AND company_id=NEW.company_id))'),
        ('request_update', 'BEFORE UPDATE ON purchase_requests',
         'NEW.requester_id IS NOT OLD.requester_id OR '
         '(NEW.purchasing_approver_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.purchasing_approver_id AND company_id=NEW.company_id)) OR '
         '(NEW.admin_approver_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.admin_approver_id AND company_id=NEW.company_id))'),
        ('request_identity', 'BEFORE UPDATE ON purchase_requests',
         'NEW.id IS NOT OLD.id OR NEW.company_id IS NOT OLD.company_id OR '
         'NEW.requester_id IS NOT OLD.requester_id OR NEW.request_token IS NOT OLD.request_token OR '
         'NEW.created_at IS NOT OLD.created_at'),
        ('request_transition', 'BEFORE UPDATE ON purchase_requests',
         "NOT (NEW.status = OLD.status OR "
         "(OLD.status='draft' AND NEW.status='pending_purchase') OR "
         "(OLD.status='returned' AND NEW.status='pending_purchase') OR "
         "(OLD.status='pending_purchase' AND NEW.status IN ('pending_admin','returned','rejected')) OR "
         "(OLD.status='pending_admin' AND NEW.status IN ('closed','returned','rejected')))"),
        ('request_version', 'BEFORE UPDATE ON purchase_requests',
         'NEW.version_id != OLD.version_id + 1'),
        ('request_delete', 'BEFORE DELETE ON purchase_requests', '1'),
        ('decision_insert', 'BEFORE INSERT ON purchase_decisions',
         'NOT EXISTS(SELECT 1 FROM purchase_requests p WHERE p.id=NEW.request_id AND p.company_id=NEW.company_id) OR '
         f'NOT {actor("actor_id")}'),
        ('decision_update', 'BEFORE UPDATE ON purchase_decisions', '1'),
        ('decision_delete', 'BEFORE DELETE ON purchase_decisions', '1'),
        ('item_insert', 'BEFORE INSERT ON purchase_request_items',
         "NOT EXISTS(SELECT 1 FROM purchase_requests p WHERE p.id=NEW.request_id AND p.company_id=NEW.company_id AND p.status IN ('draft','returned'))"),
        ('item_update', 'BEFORE UPDATE ON purchase_request_items',
         'NEW.id IS NOT OLD.id OR NEW.company_id IS NOT OLD.company_id OR '
         'NEW.request_id IS NOT OLD.request_id OR NEW.line_no IS NOT OLD.line_no OR '
         "NOT EXISTS(SELECT 1 FROM purchase_requests p WHERE p.id=NEW.request_id AND p.company_id=NEW.company_id AND p.status IN ('draft','returned'))"),
        ('item_delete', 'BEFORE DELETE ON purchase_request_items', '1'),
    )
    for name, event, predicate in definitions:
        trigger = f'trg_purchase_{name}'
        statement = f"CREATE TRIGGER {trigger} {event} WHEN {predicate} BEGIN SELECT RAISE(ABORT, 'purchase integrity guard'); END"
        previous = connection.execute(text("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=:name"), {'name': trigger}).scalar()
        if previous == statement:
            continue
        if previous:
            connection.execute(text(f'DROP TRIGGER {trigger}'))
        connection.execute(text(statement))


def drop_purchase_guards(connection):
    if connection.dialect.name == 'sqlite':
        for name in GUARDS:
            connection.execute(text(f'DROP TRIGGER IF EXISTS trg_purchase_{name}'))
