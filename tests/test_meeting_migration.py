"""Standalone migration checks; never import the application factory or run seed.

Run with python -B tests/test_meeting_migration.py. Set MEETING_BACKUP_ZIP to
rehearse on a copied backup as well. Artifacts remain in unique .tmp directories.
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
BASE = "202609300001"
HEAD = "202610010001"
TABLES = {"meeting_records", "meeting_participants", "meeting_decisions"}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def snapshot(connection):
    schema = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
    ).fetchall()
    schema = [row for row in schema if row[2] not in TABLES | {"alembic_version"}]
    tables = {}
    for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        if name in TABLES | {"alembic_version"}:
            continue
        rows = connection.execute(f"SELECT * FROM {quote(name)}").fetchall()
        hashes = sorted(hashlib.sha256(repr(row).encode()).hexdigest() for row in rows)
        tables[name] = {"rows": len(rows), "sha256": hashlib.sha256("".join(hashes).encode()).hexdigest()}
    return {"schema": schema, "tables": tables}


class MeetingMigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix=".tmp-meeting-migration-", dir=ROOT))
        self.path = self.directory / "migration.db"
        self.addCleanup(lambda: print(f"ARTIFACTS={self.directory}", flush=True))

    def run_rehearsal(self):
        source_hashes = {
            str(path.relative_to(ROOT)): digest(path)
            for path in (ROOT / "app/meeting_models.py", ROOT / "migrations/versions/202610010001_add_meetings.py")
        }
        app = Flask("meeting_migration_probe", instance_path=str(self.directory))
        app.config.update(SQLALCHEMY_DATABASE_URI=f"sqlite:///{self.path.as_posix()}")
        db = SQLAlchemy(app)
        Migrate(app, db, directory=str(ROOT / "migrations"))

        with app.app_context():
            @sa.event.listens_for(db.engine, "connect")
            def enable_foreign_keys(connection, record):
                connection.execute("PRAGMA foreign_keys=ON")

        runner = app.test_cli_runner()
        stages = []
        connection = sqlite3.connect(self.path)
        self.addCleanup(connection.close)
        connection.execute("PRAGMA foreign_keys=ON")
        baseline = snapshot(connection)
        self.assertEqual(connection.execute("SELECT version_num FROM alembic_version").fetchall(), [(BASE,)])
        self.assertFalse(TABLES & {row[0] for row in connection.execute("SELECT name FROM sqlite_master")})
        original_fk_errors = connection.execute("PRAGMA foreign_key_check").fetchall()

        def verify(stage, version):
            self.assertEqual(connection.execute("SELECT version_num FROM alembic_version").fetchall(), [(version,)])
            self.assertEqual(snapshot(connection), baseline, stage)
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), original_fk_errors)
            stages.append({"stage": stage, "revision": version, "existing_schema_data": "unchanged", "integrity_check": "ok"})

        def migrate(direction, revision):
            result = runner.invoke(args=["db", direction, revision])
            print(f"db {direction} {revision}: exit={result.exit_code}\n{result.output}", flush=True)
            self.assertEqual(result.exit_code, 0, repr(result.exception) + result.output)

        try:
            migrate("upgrade", HEAD)
            verify("upgrade", HEAD)
            with app.app_context():
                inspector = sa.inspect(db.engine)
                self.assertTrue(TABLES <= set(inspector.get_table_names()))
                self.assertEqual(sum(len(inspector.get_indexes(name)) for name in TABLES), 12)
                self.assertEqual(sum(len(inspector.get_check_constraints(name)) for name in TABLES), 2)
                self.assertEqual(sum(len(inspector.get_unique_constraints(name)) for name in TABLES), 2)
                self.assertEqual(sum(len(inspector.get_foreign_keys(name)) for name in TABLES), 8)
                self.check_model_schema(db)

            company, user = connection.execute(
                "SELECT company_id, id FROM users WHERE company_id IS NOT NULL ORDER BY id LIMIT 1"
            ).fetchone()
            connection.execute(
                "INSERT INTO meeting_records (id, company_id, title, meeting_at, created_by_user_id) VALUES (1, ?, 'Migration probe', '2026-10-01 12:00:00', ?)",
                (company, user),
            )
            connection.execute("INSERT INTO meeting_participants (company_id, meeting_id, user_id) VALUES (?, 1, ?)", (company, user))
            connection.execute(
                "INSERT INTO meeting_decisions (company_id, meeting_id, owner_user_id, title, due_date) VALUES (?, 1, ?, 'Probe decision', '2026-10-02')",
                (company, user),
            )
            self.assertEqual(connection.execute("SELECT status, version_id FROM meeting_records").fetchone(), ("draft", 1))
            self.assertEqual(connection.execute("SELECT status, version_id FROM meeting_decisions").fetchone(), ("open", 1))
            for sql, params in (
                ("UPDATE meeting_records SET status='invalid'", ()),
                ("UPDATE meeting_decisions SET status='invalid'", ()),
                ("INSERT INTO meeting_participants (company_id, meeting_id, user_id) VALUES (?, 1, ?)", (company, user)),
                ("UPDATE meeting_participants SET meeting_id=99999999", ()),
                ("UPDATE meeting_decisions SET meeting_id=99999999", ()),
                ("UPDATE meeting_records SET company_id=NULL", ()),
            ):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(sql, params)
            connection.commit()
            migrate("upgrade", HEAD)
            verify("repeat_upgrade_with_meeting_data", HEAD)
            self.assertTrue(all(connection.execute(f"SELECT COUNT(*) FROM {quote(name)}").fetchone()[0] == 1 for name in TABLES))
            migrate("downgrade", BASE)
            verify("downgrade", BASE)
            self.assertFalse(TABLES & {row[0] for row in connection.execute("SELECT name FROM sqlite_master")})
            migrate("upgrade", HEAD)
            verify("reupgrade", HEAD)
            self.assertTrue(all(connection.execute(f"SELECT COUNT(*) FROM {quote(name)}").fetchone()[0] == 0 for name in TABLES))
            self.assertEqual(source_hashes, {name: digest(ROOT / name) for name in source_hashes})
            evidence = {
                "source_sha256": source_hashes,
                "baseline": baseline,
                "stages": stages,
                "preexisting_foreign_key_errors": len(original_fk_errors),
                "checklist": "all preexisting rows preserved; no seed or mark invoked",
                "rollback_warning": "Downgrade deletes all meeting records, participants and decisions.",
            }
            (self.directory / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            print(f"PASS: {len(baseline['tables'])} existing tables, {sum(item['rows'] for item in baseline['tables'].values())} rows preserved; model diff=[]", flush=True)
        finally:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()

    def check_model_schema(self, db):
        # Load only this model module under a private package; avoid app startup.
        package_name = "_meeting_migration_models"
        package = types.ModuleType(package_name)
        package.__path__ = []
        extensions = types.ModuleType(package_name + ".extensions")
        extensions.db = db
        sys.modules[package_name] = package
        sys.modules[extensions.__name__] = extensions
        try:
            for name in ("companies", "users", "actions"):
                sa.Table(name, db.metadata, sa.Column("id", sa.Integer, primary_key=True))
            spec = importlib.util.spec_from_file_location(package_name + ".meeting_models", ROOT / "app/meeting_models.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with db.engine.connect() as connection:
                context = MigrationContext.configure(connection, opts={
                    "compare_type": True,
                    "compare_server_default": True,
                    "include_object": lambda obj, name, kind, reflected, compare_to: name in TABLES if kind == "table" else True,
                })
                self.assertEqual(compare_metadata(context, db.metadata), [])
        finally:
            sys.modules.pop(extensions.__name__, None)
            sys.modules.pop(package_name, None)

    def test_minimal_predecessor_roundtrip(self):
        with sqlite3.connect(self.path) as connection:
            connection.executescript("""
                CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
                INSERT INTO alembic_version VALUES ('202609300001');
                CREATE TABLE companies (id INTEGER PRIMARY KEY);
                INSERT INTO companies VALUES (1);
                CREATE TABLE users (id INTEGER PRIMARY KEY, company_id INTEGER REFERENCES companies(id));
                INSERT INTO users VALUES (1, 1);
                CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT);
                INSERT INTO app_settings VALUES ('sales_readiness:competitor_meetings', '0');
            """)
        self.run_rehearsal()

    @unittest.skipUnless(os.environ.get("MEETING_BACKUP_ZIP"), "MEETING_BACKUP_ZIP not supplied")
    def test_backup_copy_roundtrip(self):
        archive_path = Path(os.environ["MEETING_BACKUP_ZIP"]).resolve(strict=True)
        before = digest(archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            self.assertEqual(archive.namelist().count("database/actions.db"), 1)
            with archive.open("database/actions.db") as source, self.path.open("xb") as target:
                shutil.copyfileobj(source, target)
        self.run_rehearsal()
        self.assertEqual(digest(archive_path), before)
        print(f"BACKUP_UNCHANGED_SHA256={before}", flush=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
