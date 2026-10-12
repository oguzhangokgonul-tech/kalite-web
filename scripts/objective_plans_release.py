"""Read-only objective-plan smoke and explicitly authorized checklist marking.

Run from the repository with the service environment and PYTHONPATH=.:
  python -m scripts.objective_plans_release smoke
  python -m scripts.objective_plans_release mark-checklist --confirm module_quality_objective_projects

The coordinator owns backup, migration, QA, deployment and approval. This script
does not bootstrap schema, seed users, grant permissions or create business data.
SQLite is required: its integrity triggers are part of this release contract.
Authenticated GET checks run against a disposable database snapshot because legacy
startup hooks issue no-op writes. Live database reads are enforced read-only.
Missing live users/objectives are reported as partial coverage, never fabricated.
"""
import argparse
from contextlib import contextmanager
import json
import sqlite3
import hashlib
from pathlib import Path
import tempfile

from flask import g
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine

from app import create_app
from app.audit import record_audit_event
from app.config import Config
from app.extensions import db
from app.models import AppSetting, AuditLog, Company, QualityObjective, User
from app.objective_plan_models import ObjectivePlanLink
from app.objective_plan_schema import GUARDS
from app.tenant import company_primary_domain, tenant_base_domain, tenant_company_from_host


REVISION = '202610090001'
CHECKLIST_ID = 'module_quality_objective_projects'
CHECKLIST_KEY = 'sales_readiness:' + CHECKLIST_ID
ROLES = ('super_admin', 'management_representative', 'management',
         'department_manager', 'department_staff', 'viewer')
COUNT_TABLES = ('quality_objectives', 'objective_plan_links', 'project_records',
                'project_tasks', 'actions', 'action_histories', 'notifications', 'audit_logs')


class ReleaseConfig(Config):
    MAIL_ENABLED = False
    NOTIFICATION_AUTO_REMINDERS_ENABLED = False
    AUTO_BOOTSTRAP_DATABASE = False


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


@contextmanager
def read_only_database():
    """Protect every SQLAlchemy checkout, including application startup/hooks."""
    denied = []
    protected = {}
    writes = {getattr(sqlite3, 'SQLITE_' + name) for name in (
        'INSERT', 'UPDATE', 'DELETE', 'CREATE_INDEX', 'CREATE_TABLE',
        'CREATE_TEMP_INDEX', 'CREATE_TEMP_TABLE', 'CREATE_TEMP_TRIGGER',
        'CREATE_TEMP_VIEW', 'CREATE_TRIGGER', 'CREATE_VIEW', 'DROP_INDEX',
        'DROP_TABLE', 'DROP_TEMP_INDEX', 'DROP_TEMP_TABLE', 'DROP_TEMP_TRIGGER',
        'DROP_TEMP_VIEW', 'DROP_TRIGGER', 'DROP_VIEW', 'ALTER_TABLE',
        'REINDEX', 'ANALYZE', 'CREATE_VTABLE', 'DROP_VTABLE', 'ATTACH', 'DETACH')}

    def checkout(connection, record, proxy):
        require(isinstance(connection, sqlite3.Connection), 'SQLite is required for release smoke')
        if id(connection) in protected:
            return
        protected[id(connection)] = (connection, connection.execute('PRAGMA query_only').fetchone()[0])
        connection.execute('PRAGMA query_only=ON')
        indexes = set(connection.execute("SELECT name,tbl_name FROM sqlite_master WHERE type='index'"))

        def authorize(operation, first, second, database, source):
            # Legacy GET initialization issues CREATE INDEX IF NOT EXISTS.
            # Existing indexes are no-ops; query_only still forbids schema writes.
            if operation == sqlite3.SQLITE_CREATE_INDEX and (first, second) in indexes:
                return sqlite3.SQLITE_OK
            if operation in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE) and first == 'sqlite_master':
                return sqlite3.SQLITE_OK
            if operation in writes or (
                operation == sqlite3.SQLITE_PRAGMA and second is not None
                and first.lower() in {'query_only', 'writable_schema', 'journal_mode'}
            ):
                denied.append((operation, first))
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)

    event.listen(Engine, 'checkout', checkout)
    try:
        yield denied
        require(not denied, f'Smoke blocked database writes: {denied}')
    finally:
        event.remove(Engine, 'checkout', checkout)
        for connection, previous in protected.values():
            try:
                connection.set_authorizer(None)
                connection.execute('PRAGMA query_only=' + ('ON' if previous else 'OFF'))
            except sqlite3.ProgrammingError:
                pass  # A disposed connection cannot be reused for writes.


def schema_state():
    require(db.engine.dialect.name == 'sqlite', 'SQLite integrity guards are required')
    inspector = inspect(db.session.connection())
    tables = set(inspector.get_table_names())
    required = set(COUNT_TABLES) | {'alembic_version', 'app_settings', 'users', 'companies'}
    require(required <= tables, f'Missing tables: {sorted(required - tables)}; coordinator must migrate')
    versions = tuple(db.session.execute(text('SELECT version_num FROM alembic_version')).scalars())
    require(versions == (REVISION,), f'Expected revision {REVISION}, found {versions}')
    table = ObjectivePlanLink.__table__
    columns = {column['name']: column for column in inspector.get_columns(table.name)}
    for column in table.columns:
        require(column.name in columns, f'Missing plan column: {column.name}')
        if not column.nullable and not column.primary_key:
            require(not columns[column.name]['nullable'], f'Nullable plan column: {column.name}')
    unique = {tuple(item['column_names']) for item in inspector.get_unique_constraints(table.name)}
    require({('company_id', 'objective_id', 'kind'), ('project_id',), ('action_id',)} <= unique,
            'Missing objective-plan uniqueness constraints')
    checks = {item['name'] for item in inspector.get_check_constraints(table.name)}
    require({'ck_objective_plan_links_kind', 'ck_objective_plan_links_target'} <= checks,
            'Missing objective-plan check constraints')
    indexes = {tuple(item['column_names']) for item in inspector.get_indexes(table.name)}
    require({('company_id',), ('objective_id',)} <= indexes, 'Missing objective-plan indexes')
    foreign_keys = {(tuple(item['constrained_columns']), item['referred_table'],
                     tuple(item['referred_columns'])) for item in inspector.get_foreign_keys(table.name)}
    for column, parent in (('company_id', 'companies'), ('objective_id', 'quality_objectives'),
                           ('project_id', 'project_records'), ('action_id', 'actions'),
                           ('created_by_user_id', 'users')):
        require(((column,), parent, ('id',)) in foreign_keys, f'Missing foreign key: {column}')
    triggers = dict(db.session.execute(text(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger'"
    )).all())
    for guard in GUARDS:
        name = 'trg_objective_plan_' + guard
        require(name in triggers and 'RAISE(ABORT' in (triggers[name] or '').upper(),
                f'Missing integrity guard: {name}')
    return {'revision': versions[0], 'guards': {name: triggers[name] for name in sorted(triggers)
                                               if name.startswith('trg_objective_plan_')}}


def counts():
    return {name: db.session.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar_one()
            for name in COUNT_TABLES}


def checklist_values():
    return dict(db.session.query(AppSetting.key, AppSetting.value).filter(
        AppSetting.key.startswith('sales_readiness:', autoescape=True)).all())


def release_admin():
    admin = User.query.filter_by(username='superadmin', company_id=None, is_active=True).one()
    require(admin.has_role('super_admin'), 'Active global superadmin is required')
    return admin


def client_for(app, base, user=None, company=None):
    client = app.test_client()
    if user is not None:
        with client.session_transaction(base_url=base) as session:
            session['user_id'] = user.id
            if company is not None:
                session['company_id'] = company.id
    return client


def _smoke_snapshot(app):
    from app.objective_plans import can_generate
    from app.routes import can_view_quality_objectives, company_module_state

    require(not app.config.get('MAIL_ENABLED') and
            not app.config.get('NOTIFICATION_AUTO_REMINDERS_ENABLED'), 'Unsafe smoke configuration')
    expected_path = app.config.get('OBJECTIVE_PLANS_SNAPSHOT_PATH')
    require(expected_path and Path(db.engine.url.database).resolve() == Path(expected_path).resolve(),
            'Authenticated smoke requires an isolated snapshot')
    before_schema, before_counts, before_checklist = schema_state(), counts(), checklist_values()
    admin = release_admin()
    companies = Company.query.filter_by(is_active=True).order_by(Company.id).all()
    require(companies, 'No active companies available for smoke')
    checks, gaps, forms = 0, [], set()

    def get(client, base, path, expected, location=None):
        nonlocal checks
        response = client.get(path, base_url=base, follow_redirects=False)
        require(response.status_code == expected,
                f'GET {path}: expected {expected}, got {response.status_code}')
        if location:
            require(location in (response.location or ''), f'Unexpected redirect for {path}')
        checks += 1

    for company in companies:
        domain = company_primary_domain(company)
        resolved = tenant_company_from_host(domain) if domain else None
        require(resolved and resolved.id == company.id, f'Invalid domain for company {company.id}')
        base = 'https://' + domain
        modules = company_module_state(company)
        objectives = QualityObjective.query.filter_by(company_id=company.id).order_by(QualityObjective.id)
        samples = [objectives.filter(QualityObjective.status.in_(('Taslak', 'Aktif'))).first(),
                   objectives.filter(~QualityObjective.status.in_(('Taslak', 'Aktif'))).first()]
        samples = [objective for objective in samples if objective is not None]
        if not samples:
            gaps.append(f'{company.id}:no_existing_objectives')
        for role in ROLES:
            user = admin if role == 'super_admin' else User.query.filter(
                User.company_id == company.id, User.is_active.is_(True), User.roles.any(key=role)
            ).order_by(User.id).first()
            if user is None:
                gaps.append(f'{company.id}:no_user:{role}')
                continue
            client = client_for(app, base, user, company)
            with app.test_request_context(base_url=base):
                g.current_user, g.current_company = user, company
                g.current_user_is_super_admin = user.has_role('super_admin')
                g.company_module_enabled = lambda key: modules.get(key, False)
                readable = modules['quality_objectives'] and can_view_quality_objectives()
                expected_forms = {(objective.id, kind): can_generate(objective, kind)
                                  for objective in samples for kind in ('project', 'action')}
            get(client, base, '/kalite-hedefleri', 200 if readable else 403)
            for objective in samples:
                path = f'/kalite-hedefleri/{objective.id}'
                get(client, base, path, 200 if readable else 403)
                for kind in ('project', 'action'):
                    linked = ObjectivePlanLink.query.filter_by(
                        company_id=company.id, objective_id=objective.id, kind=kind).first() is not None
                    expected = (403 if not readable else 409 if objective.is_closed else
                                403 if not expected_forms[objective.id, kind] else 302 if linked else 200)
                    get(client, base, path + '/plan/' + kind, expected, path if expected == 302 else None)
                    if expected == 200:
                        forms.add((company.id, kind))
            foreign_objective = QualityObjective.query.filter(
                QualityObjective.company_id != company.id).order_by(QualityObjective.id).first()
            if foreign_objective:
                for kind in ('project', 'action'):
                    get(client, base, f'/kalite-hedefleri/{foreign_objective.id}/plan/{kind}',
                        404 if readable else 403)
        for kind in ('project', 'action'):
            if (company.id, kind) not in forms:
                gaps.append(f'{company.id}:no_accessible_unlinked_{kind}_form')
        foreign = User.query.filter(User.company_id.isnot(None), User.company_id != company.id,
                                    User.is_active.is_(True), ~User.roles.any(key='super_admin')).first()
        if foreign:
            client = client_for(app, base, foreign)
            get(client, base, '/kalite-hedefleri/1/plan/project', 302, '/login')
        else:
            gaps.append(f'{company.id}:no_foreign_tenant_user')
        get(client_for(app, base), base, '/kalite-hedefleri/1/plan/project', 302, '/login')

    base_domain = tenant_base_domain()
    require(base_domain and tenant_company_from_host(base_domain) is None, 'Invalid root tenant domain')
    base = 'https://' + base_domain
    get(client_for(app, base, admin), base, '/kalite-hedefleri/1/plan/project', 403)
    db.session.expire_all()
    require(schema_state() == before_schema, 'Schema/version changed during smoke')
    require(counts() == before_counts, 'Record counts changed during smoke; check concurrent traffic')
    require(checklist_values() == before_checklist, 'Checklist changed during smoke')
    return {'revision': REVISION, 'checks': checks, 'counts': before_counts,
            'coverage': 'partial' if gaps else 'complete', 'coverage_gaps': gaps,
            'scope': 'GET-only on isolated live snapshot; not POST or deployment acceptance'}


def business_digest(connection):
    digest = hashlib.sha256()
    for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        quoted = '"' + table.replace('"', '""') + '"'
        digest.update(table.encode())
        for row in sorted(hashlib.sha256(repr(row).encode()).digest()
                          for row in connection.execute('SELECT * FROM ' + quoted)):
            digest.update(row)
    return digest.hexdigest()


def smoke(app):
    require(not (db.session.new or db.session.dirty or db.session.deleted), 'Pending session changes')
    db.session.remove()
    with tempfile.TemporaryDirectory(prefix='objective-plans-smoke-') as directory:
        root = Path(directory)
        snapshot = root / 'snapshot.db'
        with read_only_database():
            try:
                schema_state()
                source = db.session.connection().connection.driver_connection
                target = sqlite3.connect(snapshot)
                try:
                    source.backup(target)
                    baseline = business_digest(target)
                finally:
                    target.close()
            finally:
                db.session.remove()

        class SnapshotConfig:
            pass

        for key, value in app.config.items():
            if key.isupper():
                setattr(SnapshotConfig, key, value)
        SnapshotConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + snapshot.as_posix()
        SnapshotConfig.OBJECTIVE_PLANS_SNAPSHOT_PATH = str(snapshot)
        SnapshotConfig.UPLOAD_FOLDER = str(root / 'uploads')
        SnapshotConfig.DATABASE_BACKUP_DIR = str(root / 'backups')
        SnapshotConfig.FULL_BACKUP_DIR = str(root / 'backups')
        SnapshotConfig.MAIL_ENABLED = False
        SnapshotConfig.NOTIFICATION_AUTO_REMINDERS_ENABLED = False
        snapshot_app = create_app(SnapshotConfig)
        with snapshot_app.app_context():
            try:
                result = _smoke_snapshot(snapshot_app)
                connection = db.session.connection().connection.driver_connection
                require(business_digest(connection) == baseline,
                        'GET smoke changed snapshot rows; investigate before deployment')
            finally:
                db.session.remove()
                db.engine.dispose()
        return result


def mark_checklist(app, *, confirmation):
    require(confirmation == CHECKLIST_ID, 'Explicit checklist confirmation is required')
    require(not (db.session.new or db.session.dirty or db.session.deleted), 'Pending session changes')
    require(db.engine.dialect.name == 'sqlite', 'SQLite is required for serialized checklist marking')
    db.session.rollback()
    try:
        # Serialize competing invocations before reading the checklist or audit log.
        db.session.execute(text('BEGIN IMMEDIATE'))
        schema_state()
        admin = release_admin()
        before = checklist_values()
        audit_query = AuditLog.query.filter_by(entity_type='ObjectivePlansRelease',
                                               action='checklist_completed', entity_id=CHECKLIST_ID)
        audit_before = audit_query.count()
        changed = before.get(CHECKLIST_KEY) != '1'
        with app.test_request_context():
            g.current_user = admin
            if changed:
                setting = db.session.get(AppSetting, CHECKLIST_KEY)
                if setting is None:
                    db.session.add(AppSetting(key=CHECKLIST_KEY, value='1'))
                else:
                    setting.value = '1'
                record_audit_event('ObjectivePlansRelease', 'checklist_completed',
                    'Quality objective execution plans release verified', entity_id=CHECKLIST_ID,
                    old_values={CHECKLIST_KEY: before.get(CHECKLIST_KEY)},
                    new_values={CHECKLIST_KEY: '1'}, commit=False)
                db.session.flush()
            expected = dict(before, **{CHECKLIST_KEY: '1'})
            require(checklist_values() == expected, 'Unrelated checklist changes; rolling back')
            require(audit_query.count() == audit_before + int(changed), 'Unexpected release audit count')
            db.session.commit()
        db.session.expire_all()
        require(checklist_values() == expected, 'Post-commit checklist mismatch; investigate concurrency')
        require(audit_query.count() == audit_before + int(changed), 'Post-commit audit mismatch')
        return {'checklist': CHECKLIST_ID, 'changed': changed, 'revision': REVISION}
    except Exception:
        db.session.rollback()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step', choices=('smoke', 'mark-checklist'))
    parser.add_argument('--confirm', choices=(CHECKLIST_ID,))
    args = parser.parse_args(argv)
    if (args.step == 'mark-checklist') != (args.confirm is not None):
        parser.error('--confirm is required only for mark-checklist, after coordinator approval')
    if args.step == 'smoke':
        app = create_app(ReleaseConfig)
        with app.app_context():
            result = smoke(app)
    else:
        app = create_app(ReleaseConfig)
        with app.app_context():
            result = mark_checklist(app, confirmation=args.confirm)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
