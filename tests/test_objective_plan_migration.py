"""Disposable migration checks; OBJECTIVE_PLAN_BACKUP_ZIP opts into copy rehearsal."""
from contextlib import closing
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import zipfile

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
import pytest
import sqlalchemy as sa

from app.extensions import db
from app.objective_plan_models import ObjectivePlanLink
from app.objective_plan_schema import (
    GUARDS, drop_objective_plan_sqlite_guards, ensure_objective_plan_schema,
)


ROOT = Path(__file__).resolve().parents[1]
BASE, HEAD = '202610080001', '202610090001'
TABLE = 'objective_plan_links'
PREFIX = 'trg_objective_plan_'


def legacy_snapshot(connection):
    """Keep customer values out of test failures while checking all legacy rows."""
    digest = hashlib.sha256()
    for kind, name, table, sql in connection.execute(
        'SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name'
    ).fetchall():
        if table in (TABLE, 'alembic_version') or (kind == 'trigger' and name.startswith(PREFIX)):
            continue
        digest.update(repr((kind, name, table, sql)).encode())
        if kind == 'table':
            quoted = '"' + name.replace('"', '""') + '"'
            rows = sorted(hashlib.sha256(repr(row).encode()).digest()
                          for row in connection.execute('SELECT * FROM ' + quoted))
            digest.update(str(len(rows)).encode())
            for row in rows:
                digest.update(row)
    return digest.hexdigest()


def fk_snapshot(connection):
    return hashlib.sha256(repr(sorted(connection.execute('PRAGMA foreign_key_check').fetchall())).encode()).hexdigest()


def guard_snapshot(connection):
    return dict(connection.execute(
        "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND substr(name,1,:length)=:prefix",
        {'length': len(PREFIX), 'prefix': PREFIX},
    ).fetchall())


def seed_minimal(path):
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript("""
            CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY);
            INSERT INTO alembic_version VALUES('202610080001');
            CREATE TABLE companies(id INTEGER PRIMARY KEY);
            INSERT INTO companies VALUES(1),(2),(3);
            CREATE TABLE users(id INTEGER PRIMARY KEY, company_id INTEGER);
            INSERT INTO users VALUES(1,1),(2,2),(3,NULL),(4,NULL),(5,2),(6,1);
            CREATE TABLE roles(id INTEGER PRIMARY KEY, key VARCHAR(80));
            INSERT INTO roles VALUES(1,'super_admin'),(2,'admin');
            CREATE TABLE user_roles(user_id INTEGER,role_id INTEGER);
            INSERT INTO user_roles VALUES(3,1),(4,2),(5,1);
            CREATE TABLE quality_objectives(id INTEGER PRIMARY KEY, company_id INTEGER, status VARCHAR(40));
            INSERT INTO quality_objectives VALUES
                (1,1,'Taslak'),(2,2,'Aktif'),(3,NULL,'Taslak'),(4,1,'Aktif'),
                (5,1,'Kapali'),(6,1,'Arsiv'),(7,1,NULL),(8,99,'Taslak');
            CREATE TABLE project_records(id INTEGER PRIMARY KEY, company_id INTEGER);
            INSERT INTO project_records VALUES(1,1),(2,2),(3,NULL),(4,1),(5,99);
            CREATE TABLE actions(id INTEGER PRIMARY KEY, company_id INTEGER);
            INSERT INTO actions VALUES(1,1),(2,2),(3,NULL),(4,1),(5,99);
        """)


def make_app(path):
    app = Flask('objective_plan_migration')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + path.as_posix()
    database = SQLAlchemy(app)
    Migrate(app, database, directory=str(ROOT / 'migrations'))
    return app, database


def migrate(app, direction, revision, private=False):
    result = app.test_cli_runner().invoke(args=['db', direction, revision])
    message = f'Objective plan {direction} failed' if private else result.output + repr(result.exception)
    assert result.exit_code == 0, message


def assert_metadata_parity(engine):
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={
            'compare_type': True, 'compare_server_default': True,
            'include_object': lambda obj, name, kind, reflected, compare_to: name == TABLE if kind == 'table' else True,
        })
        assert compare_metadata(context, ObjectivePlanLink.metadata) == []
        inspector = sa.inspect(connection)
        # Alembic's comparison does not compare CHECK constraints.
        assert {(item['name'], item['sqltext']) for item in inspector.get_check_constraints(TABLE)} == {
            (item.name, str(item.sqltext)) for item in ObjectivePlanLink.__table__.constraints
            if isinstance(item, sa.CheckConstraint)
        }


@pytest.fixture()
def rehearsal(tmp_path):
    path = tmp_path / 'objective-plans.db'
    seed_minimal(path)
    app, database = make_app(path)
    with app.app_context():
        try:
            yield path, app, database.engine
        finally:
            database.session.remove()
            database.engine.dispose()


def insert_link(connection, **values):
    data = dict(company_id=1, objective_id=1, kind='project', project_id=1,
                action_id=None, created_by_user_id=1)
    data.update(values)
    columns = ','.join(data)
    connection.execute(f'INSERT INTO {TABLE} ({columns}) VALUES ({",".join("?" for _ in data)})', tuple(data.values()))


def test_upgrade_downgrade_upgrade_and_metadata_parity(rehearsal):
    path, app, engine = rehearsal
    with closing(sqlite3.connect(path)) as connection:
        baseline = legacy_snapshot(connection)
        before_fk = fk_snapshot(connection)
        guards = None
        for direction, revision in [('upgrade', HEAD), ('upgrade', HEAD), ('downgrade', BASE), ('upgrade', HEAD)]:
            migrate(app, direction, revision)
            assert legacy_snapshot(connection) == baseline
            assert fk_snapshot(connection) == before_fk
            assert connection.execute('PRAGMA integrity_check').fetchone() == ('ok',)
            assert connection.execute('SELECT version_num FROM alembic_version').fetchone() == (revision,)
            if direction == 'downgrade':
                assert guard_snapshot(connection) == {}
                assert not sa.inspect(engine).has_table(TABLE)
                # No dangling parent triggers remain after removing only this module.
                connection.execute('UPDATE quality_objectives SET company_id=company_id')
                connection.commit()
            else:
                assert_metadata_parity(engine)
                current = guard_snapshot(connection)
                assert set(current) == {PREFIX + name for name in GUARDS}
                if guards is not None:
                    assert current == guards
                guards = current


@pytest.mark.parametrize('creation', ['migration', 'runtime', 'table_event'])
def test_runtime_upgrade_preserves_links_and_repairs_guards(rehearsal, creation):
    path, app, engine = rehearsal
    if creation == 'migration':
        migrate(app, 'upgrade', HEAD)
    elif creation == 'runtime':
        ensure_objective_plan_schema(engine)
    else:
        ObjectivePlanLink.__table__.create(engine)
    with closing(sqlite3.connect(path)) as connection:
        baseline = legacy_snapshot(connection)
        expected_guards = guard_snapshot(connection)
        assert len(expected_guards) == len(GUARDS)
        insert_link(connection)
        connection.commit()
        rows = connection.execute(f'SELECT * FROM {TABLE}').fetchall()
        connection.executescript(f"""
            DROP TRIGGER {PREFIX}tenant_insert;
            CREATE TRIGGER {PREFIX}tenant_insert BEFORE INSERT ON {TABLE}
            BEGIN SELECT RAISE(ABORT, 'obsolete'); END;
            DROP TRIGGER {PREFIX}action_delete;
        """)
        ensure_objective_plan_schema(engine)
        assert guard_snapshot(connection) == expected_guards
        # Execute upgrade twice, not just Alembic's already-at-head no-op.
        spec = importlib.util.spec_from_file_location('objective_plan_revision',
            ROOT / 'migrations/versions/202610090001_objective_plans.py')
        revision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(revision)
        for _ in range(2):
            connection.execute(f'DROP TRIGGER {PREFIX}action_delete')
            connection.commit()
            with engine.begin() as target:
                with Operations.context(MigrationContext.configure(target)):
                    revision.upgrade()
            assert connection.execute(f'SELECT * FROM {TABLE}').fetchall() == rows
            assert guard_snapshot(connection) == expected_guards
            assert legacy_snapshot(connection) == baseline
        assert_metadata_parity(engine)
        # A populated table can still be explicitly downgraded/dropped.
        with engine.begin() as target:
            ObjectivePlanLink.__table__.drop(target)
        assert guard_snapshot(connection) == {}
        assert legacy_snapshot(connection) == baseline


@pytest.mark.parametrize('foreign_keys', [False, True])
def test_populated_downgrade_cleans_guards_and_preserves_parents(rehearsal, foreign_keys):
    path, app, engine = rehearsal
    migrate(app, 'upgrade', HEAD)
    with closing(sqlite3.connect(path)) as connection:
        baseline = legacy_snapshot(connection)
        insert_link(connection)
        insert_link(connection, kind='action', project_id=None, action_id=1)
        connection.commit()
        spec = importlib.util.spec_from_file_location('objective_plan_downgrade',
            ROOT / 'migrations/versions/202610090001_objective_plans.py')
        revision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(revision)
        with engine.connect() as target:
            target.exec_driver_sql(f'PRAGMA foreign_keys={int(foreign_keys)}')
            target.commit()
            for _ in range(2):
                with target.begin(), Operations.context(MigrationContext.configure(target)):
                    revision.downgrade()
            assert not sa.inspect(target).has_table(TABLE)
        assert guard_snapshot(connection) == {}
        assert legacy_snapshot(connection) == baseline
        ensure_objective_plan_schema(engine)
        assert_metadata_parity(engine)
        assert len(guard_snapshot(connection)) == len(GUARDS)


@pytest.mark.parametrize('foreign_keys', [False, True])
def test_valid_targets_and_creator_authorization(rehearsal, foreign_keys):
    path, _, engine = rehearsal
    ensure_objective_plan_schema(engine)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(f'PRAGMA foreign_keys={int(foreign_keys)}')
        insert_link(connection)
        insert_link(connection, kind='action', project_id=None, action_id=1, created_by_user_id=3)
        insert_link(connection, objective_id=4, project_id=4, created_by_user_id=5)
        insert_link(connection, company_id=2, objective_id=2, project_id=2, created_by_user_id=2)
        assert connection.execute(f'SELECT COUNT(*) FROM {TABLE}').fetchone() == (4,)
        assert all(row[0] for row in connection.execute(f'SELECT created_at FROM {TABLE}'))
        # Creation-time authorization/status must not freeze later business lifecycle.
        connection.execute("UPDATE quality_objectives SET status='Kapali' WHERE id=1")
        connection.execute('DELETE FROM user_roles WHERE user_id=3')
        connection.execute('UPDATE users SET company_id=company_id WHERE id=3')
        connection.execute('DELETE FROM actions WHERE id=4')
        connection.execute('DELETE FROM users WHERE id=6')
        connection.execute('DELETE FROM companies WHERE id=3')
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []


@pytest.mark.parametrize('values', [
    {'company_id': None}, {'company_id': 2}, {'company_id': 99, 'objective_id': 8, 'project_id': 5, 'created_by_user_id': 3},
    {'objective_id': None}, {'objective_id': 999}, {'objective_id': 2}, {'objective_id': 3},
    {'objective_id': 5}, {'objective_id': 6}, {'objective_id': 7},
    {'kind': None}, {'kind': 'other'}, {'kind': 'action'},
    {'project_id': None}, {'project_id': 2}, {'project_id': 3}, {'project_id': 999},
    {'action_id': 1}, {'kind': 'action', 'project_id': None},
    {'kind': 'action', 'project_id': None, 'action_id': 2},
    {'kind': 'action', 'project_id': None, 'action_id': 3},
    {'kind': 'action', 'project_id': None, 'action_id': 999},
    {'created_by_user_id': None}, {'created_by_user_id': 999},
    {'created_by_user_id': 2}, {'created_by_user_id': 4}, {'created_at': None},
])
def test_invalid_links_rejected_with_foreign_keys_off(rehearsal, values):
    path, _, engine = rehearsal
    ensure_objective_plan_schema(engine)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute('PRAGMA foreign_keys=OFF')
        with pytest.raises(sqlite3.IntegrityError):
            insert_link(connection, **values)
        assert connection.execute(f'SELECT COUNT(*) FROM {TABLE}').fetchone() == (0,)


def test_uniqueness_and_xor_are_table_constraints(rehearsal):
    path, _, engine = rehearsal
    ensure_objective_plan_schema(engine)
    with engine.begin() as connection:
        drop_objective_plan_sqlite_guards(connection)
    with closing(sqlite3.connect(path)) as connection:
        insert_link(connection)
        insert_link(connection, kind='action', project_id=None, action_id=1)
        for values in (
            {'project_id': 4}, {'objective_id': 4},
            {'kind': 'action', 'project_id': None, 'action_id': 4},
            {'objective_id': 4, 'kind': 'action', 'project_id': None, 'action_id': 1},
            {'objective_id': 4, 'project_id': None},
            {'objective_id': 4, 'project_id': 4, 'action_id': 4},
            {'objective_id': 4, 'kind': 'other', 'project_id': 4},
            {'objective_id': 4, 'kind': 'project', 'project_id': None, 'action_id': 4},
            {'objective_id': 4, 'kind': 'action', 'project_id': 4, 'action_id': None},
        ):
            with pytest.raises(sqlite3.IntegrityError):
                insert_link(connection, **values)


@pytest.mark.parametrize('recursive_triggers', [False, True])
def test_immutable_links_and_parent_blockers(rehearsal, recursive_triggers):
    path, _, engine = rehearsal
    ensure_objective_plan_schema(engine)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute('PRAGMA foreign_keys=OFF')
        connection.execute(f'PRAGMA recursive_triggers={int(recursive_triggers)}')
        insert_link(connection, id=10)
        insert_link(connection, id=11, kind='action', project_id=None, action_id=1)
        connection.commit()
        baseline = legacy_snapshot(connection)
        links = connection.execute(f'SELECT * FROM {TABLE}').fetchall()
        statements = [f'DELETE FROM {TABLE}', f'UPDATE {TABLE} SET id=id']
        for column, value in (
            ('id', '20'), ('company_id', '2'), ('objective_id', '4'), ('kind', "'action'"),
            ('project_id', '4'), ('action_id', '4'), ('created_by_user_id', '3'),
            ('created_at', "'2026-01-01'"),
        ):
            statements.append(f'UPDATE {TABLE} SET {column}={value} WHERE id=10')
        for table in ('quality_objectives', 'project_records', 'actions', 'users'):
            statements.extend([
                f'DELETE FROM {table} WHERE id=1',
                f'UPDATE {table} SET id=99 WHERE id=1',
                f'UPDATE {table} SET company_id=2 WHERE id=1',
                f'UPDATE {table} SET company_id=NULL WHERE id=1',
                f'INSERT OR REPLACE INTO {table}(id,company_id) VALUES(1,2)',
                f'UPDATE OR REPLACE {table} SET id=1 WHERE id=2',
            ])
        statements.extend([
            'DELETE FROM companies WHERE id=1',
            'UPDATE companies SET id=99 WHERE id=1',
            'UPDATE OR REPLACE companies SET id=1 WHERE id=2',
        ])
        for values in ("10,1,4,'project',4,NULL,1", "20,1,1,'project',4,NULL,1",
                       "20,1,4,'project',1,NULL,1", "20,1,4,'action',NULL,1,1"):
            statements.append(f'INSERT OR REPLACE INTO {TABLE}'
                              '(id,company_id,objective_id,kind,project_id,action_id,created_by_user_id) '
                              f'VALUES({values})')
        for statement in statements:
            with pytest.raises(sqlite3.IntegrityError, match='objective plan integrity guard'):
                connection.execute(statement)
            assert legacy_snapshot(connection) == baseline
            assert connection.execute(f'SELECT * FROM {TABLE}').fetchall() == links


def test_create_all_and_drop_all_install_and_remove_guards(tmp_path):
    app = Flask('objective_plan_create_all')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + (tmp_path / 'all.db').as_posix()
    db.init_app(app)
    with app.app_context():
        try:
            db.create_all()
            with db.engine.connect() as connection:
                actual = connection.execute(sa.text(
                    "SELECT name FROM sqlite_master WHERE type='trigger' AND substr(name,1,:length)=:prefix"
                ), {'length': len(PREFIX), 'prefix': PREFIX}).scalars().all()
                assert set(actual) == {PREFIX + name for name in GUARDS}
            db.drop_all()
            assert sa.inspect(db.engine).get_table_names() == []
            db.create_all()
            assert_metadata_parity(db.engine)
        finally:
            db.session.remove()
            db.engine.dispose()


def backup_digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def rehearse_backup(backup, tmp_path):
    before = backup_digest(backup)
    try:
        with tempfile.TemporaryDirectory(prefix='objective-plan-copy-', dir=tmp_path) as directory:
            path = Path(directory) / 'rehearsal.db'
            with zipfile.ZipFile(backup) as archive, archive.open('database/actions.db') as source, path.open('xb') as target:
                shutil.copyfileobj(source, target)
            app, database = make_app(path)
            with app.app_context():
                try:
                    with closing(sqlite3.connect(path)) as connection:
                        assert connection.execute('SELECT version_num FROM alembic_version').fetchall() == [(BASE,)], 'Unexpected backup revision'
                        assert connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'Backup integrity check failed'
                        baseline, before_fk = legacy_snapshot(connection), fk_snapshot(connection)
                        for direction, revision in [('upgrade', HEAD), ('upgrade', HEAD), ('downgrade', BASE), ('upgrade', HEAD)]:
                            migrate(app, direction, revision, private=True)
                            assert legacy_snapshot(connection) == baseline, 'Legacy schema/data changed'
                            assert fk_snapshot(connection) == before_fk, 'Foreign-key baseline changed'
                            assert connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
                            assert connection.execute('SELECT version_num FROM alembic_version').fetchall() == [(revision,)]
                            assert len(guard_snapshot(connection)) == (0 if direction == 'downgrade' else len(GUARDS))
                            assert sa.inspect(database.engine).has_table(TABLE) == (direction != 'downgrade')
                        assert_metadata_parity(database.engine)
                finally:
                    database.session.remove()
                    database.engine.dispose()
    finally:
        assert backup_digest(backup) == before, 'Source backup changed'


def test_zip_rehearsal_on_synthetic_backup(tmp_path):
    source = tmp_path / 'source.db'
    backup = tmp_path / 'synthetic.zip'
    seed_minimal(source)
    before = backup_digest(source)
    with zipfile.ZipFile(backup, 'w') as archive:
        archive.write(source, 'database/actions.db')
    rehearse_backup(backup, tmp_path)
    assert backup_digest(source) == before
    assert not list(tmp_path.glob('objective-plan-copy-*'))


@pytest.mark.skipif(not os.environ.get('OBJECTIVE_PLAN_BACKUP_ZIP'), reason='No production backup provided')
def test_production_zip_roundtrip(tmp_path):
    rehearse_backup(Path(os.environ['OBJECTIVE_PLAN_BACKUP_ZIP']), tmp_path)
