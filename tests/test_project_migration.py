"""Standalone project migration rehearsal. PROJECT_BACKUP_ZIP is optional.

Run directly to avoid importing the application factory or runtime seed.
"""
import hashlib
import importlib.util
import json
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
BASE, HEAD = "202610020002", "202610030001"
TABLES = {"project_records", "project_tasks"}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def snapshot(connection):
    result = {}
    for name, sql in connection.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"):
        if name in TABLES | {"alembic_version"}:
            continue
        quoted = '"' + name.replace('"', '""') + '"'
        rows = sorted(hashlib.sha256(repr(row).encode()).hexdigest() for row in connection.execute(f"SELECT * FROM {quoted}"))
        result[name] = {"schema": sql, "rows": len(rows), "sha256": hashlib.sha256(''.join(rows).encode()).hexdigest()}
    return result


class ProjectMigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix=".tmp-project-migration-", dir=ROOT))
        self.path = self.directory / "migration.db"

    def rehearse(self):
        app = Flask("project_migration", instance_path=str(self.directory))
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + self.path.as_posix()
        db = SQLAlchemy(app)
        Migrate(app, db, directory=str(ROOT / 'migrations'))
        runner = app.test_cli_runner()
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            baseline = snapshot(connection)
            original_fk = connection.execute('PRAGMA foreign_key_check').fetchall()
            stages = []
            for direction, revision in (("upgrade", HEAD), ("upgrade", HEAD), ("downgrade", BASE), ("upgrade", HEAD)):
                result = runner.invoke(args=['db', direction, revision])
                self.assertEqual(result.exit_code, 0, result.output + repr(result.exception))
                self.assertEqual(snapshot(connection), baseline)
                self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone(), ('ok',))
                self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), original_fk)
                self.assertEqual(connection.execute('SELECT version_num FROM alembic_version').fetchone(), (revision,))
                tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertEqual(bool(TABLES & tables), revision == HEAD)
                stages.append(f"{direction}:{revision}")
            company, user = connection.execute('SELECT company_id,id FROM users WHERE company_id IS NOT NULL LIMIT 1').fetchone()
            other_company = connection.execute('SELECT id FROM companies WHERE id != ? LIMIT 1',(company,)).fetchone()[0]
            connection.execute("INSERT INTO project_records(id,company_id,title,owner_user_id,created_by_user_id,start_date,due_date) VALUES(1,?,'Probe',?,?,'2026-10-01','2026-10-31')", (company,user,user))
            connection.execute("INSERT INTO project_tasks(company_id,project_id,title,owner_user_id,start_date,due_date) VALUES(?,1,'Task',?,'2026-10-01','2026-10-02')", (company,user))
            for sql in ("UPDATE project_records SET status='bad'", "UPDATE project_tasks SET status='bad'",
                        "UPDATE project_records SET due_date='2026-09-01'", "UPDATE project_tasks SET due_date='2026-09-01'",
                        "UPDATE project_tasks SET project_id=999999999", "UPDATE project_tasks SET company_id=999999999"):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(sql)
            connection.commit()
            connection.execute("PRAGMA foreign_keys=OFF")
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone(), (0,))
            for sql, params in (
                ("UPDATE project_tasks SET company_id=?", (other_company,)),
                ("UPDATE project_tasks SET project_id=999999999", ()),
                ("UPDATE project_records SET company_id=?", (other_company,)),
                ("DELETE FROM project_records WHERE id=1", ()),
                ("UPDATE users SET company_id=? WHERE id=?", (other_company,user)),
                ("DELETE FROM users WHERE id=?", (user,)),
                ("DELETE FROM companies WHERE id=?", (company,)),
            ):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(sql, params)
            connection.execute('DELETE FROM project_tasks')
            connection.execute('DELETE FROM project_records')
            connection.commit()
            connection.rollback()
            self.assertEqual(snapshot(connection), baseline)
        with app.app_context():
            package = types.ModuleType('_project_probe')
            package.__path__ = []
            extensions = types.ModuleType('_project_probe.extensions')
            extensions.db = db
            sys.modules[package.__name__] = package
            sys.modules[extensions.__name__] = extensions
            try:
                for name in ('companies','users'):
                    sa.Table(name, db.metadata, sa.Column('id', sa.Integer, primary_key=True))
                spec = importlib.util.spec_from_file_location('_project_probe.project_models', ROOT/'app/project_models.py')
                spec.loader.exec_module(importlib.util.module_from_spec(spec))
                with db.engine.connect() as conn:
                    context = MigrationContext.configure(conn, opts={
                        'compare_type':True, 'compare_server_default':True,
                        'include_object': lambda obj,name,kind,reflected,compare_to: name in TABLES if kind == 'table' else True,
                    })
                    self.assertEqual(compare_metadata(context, db.metadata), [])
            finally:
                sys.modules.pop(package.__name__, None)
                sys.modules.pop(extensions.__name__, None)
                db.session.remove()
                db.engine.dispose()
        (self.directory/'evidence.json').write_text(json.dumps({'stages':stages,'baseline':baseline,
            'model_diff':[], 'constraints':6, 'sqlite_fk_off_guards':7, 'warning':'Downgrade deletes project data; never use on live.'}, indent=2), encoding='utf-8')
        print(f"PASS {len(baseline)} tables preserved. Evidence: {self.directory}")

    def test_minimal_roundtrip(self):
        with sqlite3.connect(self.path) as c:
            c.executescript("""
                CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY);
                INSERT INTO alembic_version VALUES('202610020002');
                CREATE TABLE companies(id INTEGER PRIMARY KEY);
                INSERT INTO companies VALUES(1);
                INSERT INTO companies VALUES(2);
                CREATE TABLE users(id INTEGER PRIMARY KEY, company_id INTEGER REFERENCES companies(id));
                INSERT INTO users VALUES(1,1);
                CREATE TABLE app_settings(key TEXT PRIMARY KEY,value TEXT);
                INSERT INTO app_settings VALUES('sales_readiness:module_project_planning','0');
            """)
        self.rehearse()

    @unittest.skipUnless(os.environ.get('PROJECT_BACKUP_ZIP'), 'No backup supplied')
    def test_backup_roundtrip(self):
        archive_path = Path(os.environ['PROJECT_BACKUP_ZIP'])
        before = digest(archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            with archive.open('database/actions.db') as source, self.path.open('xb') as target:
                shutil.copyfileobj(source,target)
        self.rehearse()
        self.assertEqual(digest(archive_path), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
