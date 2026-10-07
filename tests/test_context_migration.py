"""Standalone rehearsal; CONTEXT_BACKUP_ZIP optionally supplies a verified backup copy."""
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
import zipfile

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[1]
BASE, HEAD = '202610050003', '202610050004'
TABLE = 'organization_contexts'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def snapshot(connection):
    result = {}
    result['__schema_objects__'] = connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE type IN ('index','trigger','view') "
        "AND tbl_name NOT IN (?, 'alembic_version') AND name NOT LIKE 'trg_context_%' ORDER BY type,name",
        (TABLE,),
    ).fetchall()
    for name, sql in connection.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"):
        if name in {TABLE, 'alembic_version'}:
            continue
        quoted = '"' + name.replace('"', '""') + '"'
        rows = sorted(hashlib.sha256(repr(row).encode()).hexdigest() for row in connection.execute(f'SELECT * FROM {quoted}'))
        result[name] = (sql, len(rows), hashlib.sha256(''.join(rows).encode()).hexdigest())
    return result


class ContextMigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix='.tmp-context-migration-', dir=ROOT))
        self.path = self.directory / 'rehearsal.db'

    def rehearse(self):
        app = Flask('context_rehearsal', instance_path=str(self.directory))
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + self.path.as_posix()
        db = SQLAlchemy(app)
        Migrate(app, db, directory=str(ROOT / 'migrations'))
        runner = app.test_cli_runner()
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute('SELECT version_num FROM alembic_version').fetchone(), (BASE,))
            baseline, old_fk = snapshot(connection), connection.execute('PRAGMA foreign_key_check').fetchall()
            existing = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone()
            original_rows = connection.execute(f'SELECT * FROM {TABLE} ORDER BY id').fetchall() if existing else []
            probe = None
            for step, (direction, revision) in enumerate([('upgrade', HEAD), ('upgrade', HEAD), ('downgrade', BASE), ('upgrade', HEAD)]):
                result = runner.invoke(args=['db', direction, revision])
                self.assertEqual(result.exit_code, 0, result.output + repr(result.exception))
                self.assertEqual(connection.execute('SELECT version_num FROM alembic_version').fetchone(), (revision,))
                self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone(), ('ok',))
                self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), old_fk)
                self.assertEqual(snapshot(connection), baseline)
                present = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone()
                self.assertEqual(bool(present), revision == HEAD)
                if step == 0:
                    self.assertEqual(connection.execute(f'SELECT * FROM {TABLE} ORDER BY id').fetchall(), original_rows)
                    probe = original_rows
                if (step == 0 and not original_rows) or step == 3:
                    self.assertEqual(connection.execute(f'SELECT COUNT(*) FROM {TABLE}').fetchone(), (0,))
                    company, user = connection.execute('SELECT company_id,id FROM users WHERE company_id IS NOT NULL LIMIT 1').fetchone()
                    connection.execute(f"INSERT INTO {TABLE}(company_id,title,scope,owner_user_id,created_by_user_id,analysis_date,review_date) VALUES(?,'Preservation probe','Scope',?,?,'2026-10-05','2027-01-05')", (company, user, user))
                    connection.commit()
                    probe = connection.execute(f'SELECT * FROM {TABLE} ORDER BY id').fetchall()
                if direction == 'upgrade':
                    self.assertEqual(connection.execute(f'SELECT * FROM {TABLE} ORDER BY id').fetchall(), probe)
            connection.execute(f'DELETE FROM {TABLE}')
            connection.commit()
            company, user = connection.execute('SELECT company_id,id FROM users WHERE company_id IS NOT NULL LIMIT 1').fetchone()
            other = connection.execute('SELECT id FROM companies WHERE id != ? LIMIT 1', (company,)).fetchone()[0]
            connection.execute(f"INSERT INTO {TABLE}(company_id,title,scope,owner_user_id,created_by_user_id,analysis_date,review_date) VALUES(?,'Probe','Scope',?,?,'2026-10-05','2027-01-05')", (company, user, user))
            connection.commit()
            connection.execute('PRAGMA foreign_keys=OFF')
            self.assertEqual(connection.execute('PRAGMA foreign_keys').fetchone(), (0,))
            for sql, params in [
                (f'UPDATE {TABLE} SET company_id=?', (other,)),
                (f"UPDATE {TABLE} SET status='invalid'", ()),
                (f"UPDATE {TABLE} SET review_date='2026-10-01'", ()),
                (f'UPDATE {TABLE} SET owner_user_id=999999999', ()),
                ('DELETE FROM users WHERE id=?', (user,)),
                ('UPDATE users SET company_id=? WHERE id=?', (other, user)),
                ('DELETE FROM companies WHERE id=?', (company,)),
            ]:
                with self.assertRaises(sqlite3.IntegrityError, msg=sql):
                    connection.execute(sql, params)
            connection.execute(f'DELETE FROM {TABLE}')
            connection.commit()
            self.assertEqual(snapshot(connection), baseline)
        with app.app_context():
            package = types.ModuleType('_context_probe')
            package.__path__ = []
            extensions = types.ModuleType('_context_probe.extensions')
            extensions.db = db
            sys.modules[package.__name__], sys.modules[extensions.__name__] = package, extensions
            try:
                for name in ('companies', 'users'):
                    sa.Table(name, db.metadata, sa.Column('id', sa.Integer, primary_key=True))
                spec = importlib.util.spec_from_file_location('_context_probe.context_models', ROOT / 'app/context_models.py')
                spec.loader.exec_module(importlib.util.module_from_spec(spec))
                with db.engine.connect() as conn:
                    context = MigrationContext.configure(conn, opts={
                        'compare_type': True, 'compare_server_default': True,
                        'include_object': lambda obj, name, kind, reflected, compare_to: name == TABLE if kind == 'table' else True,
                    })
                    self.assertEqual(compare_metadata(context, db.metadata), [])
            finally:
                sys.modules.pop(package.__name__, None)
                sys.modules.pop(extensions.__name__, None)
                db.session.remove()
                db.engine.dispose()
        print(f'PASS: existing data/schema preserved, constraints and model parity verified. {self.directory}')

    def create_minimal_database(self):
        with sqlite3.connect(self.path) as connection:
            connection.executescript("""
                CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY);
                INSERT INTO alembic_version VALUES('202610050003');
                CREATE TABLE companies(id INTEGER PRIMARY KEY);
                INSERT INTO companies VALUES(1),(2);
                CREATE TABLE users(id INTEGER PRIMARY KEY, company_id INTEGER REFERENCES companies(id));
                INSERT INTO users VALUES(1,1);
                CREATE TABLE app_settings(key TEXT PRIMARY KEY,value TEXT);
                INSERT INTO app_settings VALUES('sales_readiness:module_context_stakeholders','0');
            """)

    def test_minimal_roundtrip(self):
        self.create_minimal_database()
        self.rehearse()

    def test_runtime_created_table_preserves_all_data_during_upgrade(self):
        self.create_minimal_database()
        app = Flask('context_runtime', instance_path=str(self.directory))
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + self.path.as_posix()
        db = SQLAlchemy(app)
        Migrate(app, db, directory=str(ROOT / 'migrations'))
        package = types.ModuleType('_context_runtime_probe')
        package.__path__ = []
        extensions = types.ModuleType('_context_runtime_probe.extensions')
        extensions.db = db
        sys.modules[package.__name__], sys.modules[extensions.__name__] = package, extensions
        with app.app_context():
            try:
                for name in ('companies', 'users'):
                    sa.Table(name, db.metadata, sa.Column('id', sa.Integer, primary_key=True))
                for name in ('context_models', 'context_schema'):
                    spec = importlib.util.spec_from_file_location(f'{package.__name__}.{name}', ROOT / f'app/{name}.py')
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[spec.name] = module
                    spec.loader.exec_module(module)
                    if name == 'context_schema':
                        guards = module.ensure_context_sqlite_guards
                db.metadata.tables[TABLE].create(db.engine)
                with db.engine.begin() as connection:
                    guards(connection)
                with sqlite3.connect(self.path) as connection:
                    connection.execute(f"INSERT INTO {TABLE}(company_id,title,scope,owner_user_id,created_by_user_id,analysis_date,review_date,internal_issues,evidence_sources,strategy) VALUES(1,'Runtime probe','Scope',1,1,'2026-10-05','2027-01-05','Policy','Evidence','Strategy')")
                    connection.commit()
                    before = connection.execute(f'SELECT * FROM {TABLE} ORDER BY id').fetchall()
                    baseline = snapshot(connection)
                    for _ in range(2):
                        result = app.test_cli_runner().invoke(args=['db', 'upgrade', HEAD])
                        self.assertEqual(result.exit_code, 0, result.output + repr(result.exception))
                        self.assertEqual(connection.execute(f'SELECT * FROM {TABLE} ORDER BY id').fetchall(), before)
                        self.assertEqual(snapshot(connection), baseline)
                        self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone(), ('ok',))
            finally:
                for name in ('context_models', 'context_schema'):
                    sys.modules.pop(f'{package.__name__}.{name}', None)
                sys.modules.pop(package.__name__, None)
                sys.modules.pop(extensions.__name__, None)
                db.session.remove()
                db.engine.dispose()

    @unittest.skipUnless(os.environ.get('CONTEXT_BACKUP_ZIP'), 'No backup supplied')
    def test_backup_roundtrip(self):
        archive_path = Path(os.environ['CONTEXT_BACKUP_ZIP'])
        before = digest(archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            with archive.open('database/actions.db') as source, self.path.open('xb') as target:
                shutil.copyfileobj(source, target)
        self.rehearse()
        self.assertEqual(digest(archive_path), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
