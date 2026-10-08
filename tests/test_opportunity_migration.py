"""Disposable SQLite rehearsal. OPPORTUNITY_BACKUP_ZIP enables a production-copy test."""
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
BASE, HEAD = '202610050004', '202610070001'
TABLE = 'opportunities'


def snapshot(connection):
    result = {'schema': connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE type IN ('index','trigger','view') "
        "AND tbl_name NOT IN ('opportunities','alembic_version') AND name NOT LIKE 'trg_opportunit%' ORDER BY type,name").fetchall()}
    for name, sql in connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"):
        if name in (TABLE, 'alembic_version'):
            continue
        quoted = '"' + name.replace('"', '""') + '"'
        rows = sorted(hashlib.sha256(repr(row).encode()).hexdigest() for row in connection.execute('SELECT * FROM ' + quoted))
        result[name] = (sql, len(rows), hashlib.sha256(''.join(rows).encode()).hexdigest())
    return result


class OpportunityMigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix='.tmp-opportunity-migration-', dir=ROOT))
        self.path = self.directory / 'rehearsal.db'
        self.app = Flask('opportunity_rehearsal', instance_path=str(self.directory))
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + self.path.as_posix()
        self.db = SQLAlchemy(self.app)
        Migrate(self.app, self.db, directory=str(ROOT / 'migrations'))

    def minimal(self):
        with sqlite3.connect(self.path) as c:
            c.executescript("""
                CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY);
                INSERT INTO alembic_version VALUES('202610050004');
                CREATE TABLE companies(id INTEGER PRIMARY KEY);
                INSERT INTO companies VALUES(1),(2);
                CREATE TABLE users(id INTEGER PRIMARY KEY,company_id INTEGER REFERENCES companies(id));
                INSERT INTO users VALUES(1,1),(2,2);
                CREATE TABLE actions(id INTEGER PRIMARY KEY,company_id INTEGER REFERENCES companies(id));
                INSERT INTO actions VALUES(1,1),(2,2);
            """)

    def load_model(self):
        package = types.ModuleType('_opportunity_probe')
        package.__path__ = []
        extensions = types.ModuleType(package.__name__ + '.extensions')
        extensions.db = self.db
        sys.modules[package.__name__], sys.modules[extensions.__name__] = package, extensions
        for name in ('companies', 'users', 'actions'):
            sa.Table(name, self.db.metadata, sa.Column('id', sa.Integer, primary_key=True))
        for name in ('opportunity_schema', 'opportunity_models'):
            spec = importlib.util.spec_from_file_location(package.__name__ + '.' + name, ROOT / f'app/{name}.py')
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)

    def upgrade(self):
        result = self.app.test_cli_runner().invoke(args=['db', 'upgrade', HEAD])
        self.assertEqual(result.exit_code, 0, result.output + repr(result.exception))

    def rehearse(self):
        with sqlite3.connect(self.path) as c:
            baseline = snapshot(c)
            before_fk = c.execute('PRAGMA foreign_key_check').fetchall()
            self.assertEqual(c.execute('SELECT version_num FROM alembic_version').fetchone(), (BASE,))
            for direction, revision in [('upgrade', HEAD), ('upgrade', HEAD), ('downgrade', BASE), ('upgrade', HEAD)]:
                result = self.app.test_cli_runner().invoke(args=['db', direction, revision])
                self.assertEqual(result.exit_code, 0, result.output + repr(result.exception))
                self.assertEqual(snapshot(c), baseline)
                self.assertEqual(c.execute('SELECT version_num FROM alembic_version').fetchone(), (revision,))
                self.assertEqual(c.execute('PRAGMA integrity_check').fetchone(), ('ok',))
                self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), before_fk)
            company, user = c.execute('SELECT company_id,id FROM users WHERE company_id IS NOT NULL LIMIT 1').fetchone()
            c.execute("INSERT INTO opportunities(company_id,title,owner_user_id,created_by_user_id,analysis_date,due_date) VALUES(?,'Probe',?,?,'2026-10-07','2026-12-01')", (company, user, user))
            c.commit()
            c.execute('PRAGMA foreign_keys=OFF')
            for sql in ("UPDATE opportunities SET likelihood=0", "UPDATE opportunities SET benefit=6",
                        "UPDATE opportunities SET owner_user_id=999999999", "UPDATE opportunities SET action_id=999999999",
                        "UPDATE opportunities SET status='active'", "UPDATE opportunities SET title=char(9,160)",
                        f'DELETE FROM users WHERE id={user}', f'DELETE FROM companies WHERE id={company}'):
                with self.assertRaises(sqlite3.IntegrityError, msg=sql):
                    c.execute(sql)
            c.execute('DELETE FROM opportunities')
            c.commit()
            self.assertEqual(snapshot(c), baseline)
        with self.app.app_context():
            self.load_model()
            with self.db.engine.connect() as connection:
                context = MigrationContext.configure(connection, opts={
                    'compare_type': True, 'compare_server_default': True,
                    'include_object': lambda obj, name, kind, reflected, compare_to: name == TABLE if kind == 'table' else True,
                })
                self.assertEqual(compare_metadata(context, self.db.metadata), [])

    def test_minimal_roundtrip(self):
        self.minimal()
        self.rehearse()

    def test_runtime_table_preserves_rows(self):
        self.minimal()
        with self.app.app_context():
            self.load_model()
            self.db.metadata.tables[TABLE].create(self.db.engine)
        with sqlite3.connect(self.path) as c:
            c.execute("INSERT INTO opportunities(company_id,title,owner_user_id,created_by_user_id,analysis_date,due_date,source_reference,success_criteria) VALUES(1,'Runtime',1,1,'2026-10-07','2026-12-01','SWOT','Fayda')")
            c.commit()
            before = c.execute('SELECT * FROM opportunities').fetchall()
            baseline = snapshot(c)
            for _ in range(2):
                self.upgrade()
                self.assertEqual(c.execute('SELECT * FROM opportunities').fetchall(), before)
                self.assertEqual(snapshot(c), baseline)

    @unittest.skipUnless(os.environ.get('OPPORTUNITY_BACKUP_ZIP'), 'No production backup provided')
    def test_backup_roundtrip(self):
        path = Path(os.environ['OPPORTUNITY_BACKUP_ZIP'])
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        with zipfile.ZipFile(path) as archive, archive.open('database/actions.db') as source, self.path.open('xb') as target:
            shutil.copyfileobj(source, target)
        self.rehearse()
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def tearDown(self):
        with self.app.app_context():
            self.db.session.remove()
            self.db.engine.dispose()
        for name in list(sys.modules):
            if name == '_opportunity_probe' or name.startswith('_opportunity_probe.'):
                sys.modules.pop(name)


if __name__ == '__main__':
    unittest.main(verbosity=2)
