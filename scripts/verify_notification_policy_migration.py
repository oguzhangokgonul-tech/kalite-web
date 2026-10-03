"""Rehearse only on disposable SQLite copies; never run application startup.

Run with venv/Scripts/python.exe -B scripts/verify_notification_policy_migration.py.
Override the latest meeting-actions ZIP with --backup or NOTIFICATION_POLICY_BACKUP_ZIP.
"""

import argparse
from contextlib import contextmanager
from datetime import date
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
import zipfile

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
import sqlalchemy as sa


ROOT = Path(__file__).resolve().parents[1]
BASE, HEAD = "202610020001", "202610020002"
BATCH, EVENT = "notification_email_batches", "notification_email_events"
TABLES = {BATCH, EVENT}
BACKUPS = Path("C:/Users/Asus/VolkaPortalBackups/20261002-meeting-actions")
MODEL = ROOT / "app/notification_models.py"
MIGRATION = ROOT / "migrations/versions/202610020002_notification_email_policy.py"


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def snapshot(connection, exclude=()):
    excluded = set(exclude) | {"alembic_version"}
    schema = [row for row in connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
    ) if row[2] not in excluded]
    tables = {}
    for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        if name in excluded:
            continue
        rows = connection.execute(f"SELECT * FROM {quote(name)}").fetchall()
        hashes = sorted(hashlib.sha256(repr(row).encode()).hexdigest() for row in rows)
        tables[name] = {"rows": len(rows), "sha256": hashlib.sha256("".join(hashes).encode()).hexdigest()}
    return {"schema": schema, "tables": tables}


@contextmanager
def isolated_models(db):
    # The initial migration imports app models. Substitute only these modules,
    # without executing app/__init__.py; restore any caller modules afterwards.
    names = ("app", "app.extensions", "app.notification_models")
    saved = {name: sys.modules.get(name) for name in names}
    package = types.ModuleType("app")
    package.__path__ = []
    extension = types.ModuleType("app.extensions")
    extension.db = db
    sys.modules.update({"app": package, "app.extensions": extension})
    try:
        for name in ("companies", "users", "notifications"):
            sa.Table(name, db.metadata, sa.Column("id", sa.Integer, primary_key=True))
        spec = importlib.util.spec_from_file_location("app.notification_models", MODEL)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        yield module
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def rehearse(path, evidence):
    path = path.resolve(strict=True)
    app = Flask("isolated_notification_migration", instance_path=str(path.parent))
    app.config.update(SQLALCHEMY_DATABASE_URI=f"sqlite:///{path.as_posix()}")
    db = SQLAlchemy(app)
    Migrate(app, db, directory=str(ROOT / "migrations"))
    with app.app_context():
        @sa.event.listens_for(db.engine, "connect")
        def enable_foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")
    runner = app.test_cli_runner()
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys=ON")
    evidence.update(stages=[], commands=[], metadata=[], constraints=[], observations=[])
    before = {str(p.relative_to(ROOT)): digest(p) for p in (MODEL, MIGRATION)}
    evidence["source_sha256"] = before
    original = snapshot(connection)
    original_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    evidence["backup_baseline"] = original
    evidence["preexisting_foreign_key_errors"] = original_errors
    revision = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    evidence["backup_revision"] = revision

    def migrate(direction, target):
        result = runner.invoke(args=["db", direction, target])
        evidence["commands"].append({"direction": direction, "revision": target,
                                     "exit_code": result.exit_code, "output": result.output})
        print(f"db {direction} {target}: exit={result.exit_code}", flush=True)
        check(result.exit_code == 0, repr(result.exception) + result.output)

    def verify(stage, target, baseline, exclude=()):
        check(connection.execute("SELECT version_num FROM alembic_version").fetchall() == [(target,)], stage + ": revision")
        check(snapshot(connection, exclude) == baseline, stage + ": preexisting schema/data changed")
        check(connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)], stage + ": integrity")
        check(connection.execute("PRAGMA foreign_key_check").fetchall() == original_errors, stage + ": foreign keys changed")
        evidence["stages"].append({"stage": stage, "revision": target,
                                   "prior_schema_and_rows": "unchanged", "integrity_check": "ok",
                                   "foreign_key_check": "unchanged"})

    def metadata_check(stage):
        with app.app_context(), db.engine.connect() as sql_connection:
            context = MigrationContext.configure(sql_connection, opts={
                "compare_type": True, "compare_server_default": True,
                "include_object": lambda obj, name, kind, reflected, compare_to: name in TABLES if kind == "table" else True,
            })
            differences = compare_metadata(context, db.metadata)
            check(not differences, f"{stage}: model metadata differs: {differences!r}")
            inspector = sa.inspect(sql_connection)
            details = {}
            for name in sorted(TABLES):
                details[name] = {
                    "columns": [{**c, "type": str(c["type"])} for c in inspector.get_columns(name)],
                    "indexes": inspector.get_indexes(name),
                    "unique_constraints": inspector.get_unique_constraints(name),
                    "foreign_keys": inspector.get_foreign_keys(name),
                    "primary_key": inspector.get_pk_constraint(name),
                }
            check({tuple(x["column_names"]) for x in details[BATCH]["unique_constraints"]} == {("company_id", "user_id", "send_date")}, "Daily batch uniqueness missing")
            check({tuple(x["column_names"]) for x in details[EVENT]["unique_constraints"]} == {("dedupe_key",)}, "Event deduplication missing")
            check(len(details[BATCH]["foreign_keys"]) == 2 and len(details[EVENT]["foreign_keys"]) == 4, "Foreign key count mismatch")
            check({tuple(x["column_names"]) for x in details[BATCH]["indexes"]} == {("company_id",)}, "Batch index mismatch")
            check({tuple(x["column_names"]) for x in details[EVENT]["indexes"]} == {("company_id",), ("user_id",), ("status",)}, "Event indexes mismatch")
            evidence["metadata"].append({"stage": stage, "diff": differences, "tables": details})

    def populate():
        company, user = connection.execute("SELECT company_id,id FROM users WHERE company_id IS NOT NULL ORDER BY id LIMIT 1").fetchone()
        notification = connection.execute("SELECT id FROM notifications ORDER BY id LIMIT 1").fetchone()
        with app.app_context(), db.engine.begin() as sql_connection:
            batch = sql_connection.execute(db.metadata.tables[BATCH].insert().values(
                company_id=company, user_id=user, send_date=date(2026, 10, 2),
            )).inserted_primary_key[0]
            event = sql_connection.execute(db.metadata.tables[EVENT].insert().values(
                company_id=company, user_id=user, dedupe_key="d" * 64, kind="action", record_id=42,
                phase="due", title="Disposable probe", message="Migration probe", target_url="/actions/42",
                batch_id=batch, notification_id=notification[0] if notification else None,
            )).inserted_primary_key[0]
        check(connection.execute(f"SELECT status,item_count,created_at IS NOT NULL FROM {BATCH} WHERE id=?", (batch,)).fetchone() == ("claimed", 0, 1), "Batch defaults")
        check(connection.execute(f"SELECT status,attempts,created_at IS NOT NULL FROM {EVENT} WHERE id=?", (event,)).fetchone() == ("pending", 0, 1), "Event defaults")
        return company, user, batch, event

    def rejected(label, sql, params=(), expected=""):
        connection.execute("SAVEPOINT probe")
        try:
            try:
                connection.execute(sql, params)
            except sqlite3.IntegrityError as error:
                check(expected in str(error), f"{label}: wrong rejection: {error}")
                evidence["constraints"].append({"check": label, "result": "rejected", "error": str(error)})
            else:
                raise AssertionError(label + ": unexpectedly accepted")
        finally:
            connection.execute("ROLLBACK TO probe")
            connection.execute("RELEASE probe")

    try:
        check(revision in [[("202610010001",)], [(BASE,)]], "Unexpected backup revision; refusing migration")
        check(not TABLES.intersection(original["tables"]), "Backup already contains policy tables")
        with isolated_models(db):
            if revision != [(BASE,)]:
                migrate("upgrade", BASE)
                verify("prepare_predecessor", BASE, original, {"meeting_decision_actions"})
            predecessor = snapshot(connection)
            evidence["predecessor_baseline"] = predecessor
            migrate("upgrade", HEAD)
            verify("upgrade", HEAD, predecessor, TABLES)
            metadata_check("upgrade")
            migrate("downgrade", BASE)
            verify("downgrade_empty", BASE, predecessor)
            migrate("upgrade", HEAD)
            verify("reupgrade", HEAD, predecessor, TABLES)
            metadata_check("reupgrade")

            company, user, batch, event = populate()
            evidence["constraints"].append({"check": "valid_rows_and_defaults", "result": "accepted"})
            populated = snapshot(connection)
            rejected("daily_batch_unique", f"INSERT INTO {BATCH} (company_id,user_id,send_date,status,item_count) VALUES (?,?,'2026-10-02','claimed',0)", (company, user), "UNIQUE")
            rejected("dedupe_key_unique", f"INSERT INTO {EVENT} (company_id,user_id,dedupe_key,kind,record_id,phase,title,message,target_url,status,attempts) SELECT company_id,user_id,dedupe_key,kind,record_id,phase,title,message,target_url,status,attempts FROM {EVENT} WHERE id=?", (event,), "UNIQUE")
            for name, row_id in ((BATCH, batch), (EVENT, event)):
                for column in db.metadata.tables[name].columns:
                    if not column.nullable and not column.primary_key:
                        rejected(name + "_not_null_" + column.name, f"UPDATE {name} SET {quote(column.name)}=NULL WHERE id=?", (row_id,), "NOT NULL")
                for fk in db.metadata.tables[name].foreign_keys:
                    missing = connection.execute(f"SELECT COALESCE(MAX(id),0)+1000000 FROM {quote(fk.column.table.name)}").fetchone()[0]
                    rejected(name + "_missing_" + fk.parent.name, f"UPDATE {name} SET {quote(fk.parent.name)}=? WHERE id=?", (missing, row_id), "FOREIGN KEY")
            rejected("delete_referenced_batch", f"DELETE FROM {BATCH} WHERE id=?", (batch,), "FOREIGN KEY")
            notification_id = connection.execute(f"SELECT notification_id FROM {EVENT} WHERE id=?", (event,)).fetchone()[0]
            if notification_id is not None:
                connection.execute("BEGIN")
                try:
                    connection.execute("DELETE FROM notifications WHERE id=?", (notification_id,))
                    check(connection.execute(f"SELECT notification_id FROM {EVENT} WHERE id=?", (event,)).fetchone() == (None,), "Notification deletion must retain event and clear its notification_id")
                    evidence["constraints"].append({"check": "delete_notification_sets_null_preserves_event", "result": "accepted"})
                finally:
                    connection.rollback()
            other = connection.execute("SELECT id FROM companies WHERE id<>? ORDER BY id LIMIT 1", (company,)).fetchone()
            if other:
                connection.execute("BEGIN")
                try:
                    connection.execute(f"UPDATE {EVENT} SET company_id=? WHERE id=?", (other[0], event))
                    check(connection.execute("PRAGMA foreign_key_check").fetchall() == original_errors, "Tenant probe FK errors")
                    evidence["observations"].append({"check": "cross_company_event", "result": "accepted_with_foreign_keys_on", "detail": "Independent FKs do not enforce event tenant matching user, batch or notification tenant; application checks are required."})
                finally:
                    connection.rollback()
            verify("constraints_rolled_back", HEAD, populated)
            migrate("upgrade", HEAD)
            verify("repeat_upgrade_populated", HEAD, populated)
            evidence["populated_policy_rows"] = {name: populated["tables"][name] for name in sorted(TABLES)}
            migrate("downgrade", BASE)
            verify("downgrade_populated", BASE, predecessor)
            migrate("upgrade", HEAD)
            verify("reupgrade_after_populated_downgrade", HEAD, predecessor, TABLES)
            check(all(connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone() == (0,) for name in TABLES), "Downgraded policy rows unexpectedly recovered")
            metadata_check("reupgrade_after_populated_downgrade")

            migrate("downgrade", BASE)
            with app.app_context():
                for name in (BATCH, EVENT):
                    db.metadata.tables[name].create(db.engine, checkfirst=True)
            populate()
            runtime = snapshot(connection)
            migrate("upgrade", HEAD)
            verify("runtime_precreated_populated_tables", HEAD, runtime)
            metadata_check("runtime_precreated_populated_tables")
        after = {str(p.relative_to(ROOT)): digest(p) for p in (MODEL, MIGRATION)}
        evidence["source_sha256_after"] = after
        evidence["reviewed_sources_stable_during_rehearsal"] = before == after
        check(before == after, "Sources changed during rehearsal; rerun required")
        evidence["factory_or_seed_executed"] = False
        evidence["migration_model_import_isolation"] = "Only app.notification_models executed against isolated db; app and app.extensions temporarily substituted. No factory or seed called."
        evidence["rollback_warning"] = "Downgrade drops all email events and batches, including pending deliveries, deduplication keys and daily send claims. Re-upgrade recreates empty tables and may allow repeat email. Export/restore these tables and coordinate application rollback first. All predecessor data remains unchanged."
        evidence["result"] = "PASS_WITH_OBSERVATIONS"
    finally:
        connection.close()
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, default=os.environ.get("NOTIFICATION_POLICY_BACKUP_ZIP"))
    args = parser.parse_args()
    archive_path = args.backup
    if archive_path is None:
        candidates = sorted(BACKUPS.glob("volkaportal-backup-*.zip"), key=lambda p: p.name)
        check(bool(candidates), "No backup ZIP found")
        archive_path = candidates[-1]
    archive_path = archive_path.resolve(strict=True)
    directory = Path(tempfile.mkdtemp(prefix=".tmp-notification-policy-migration-", dir=ROOT))
    path = directory / "migration.db"
    before = digest(archive_path)
    evidence = {"directory": str(directory), "backup_path": str(archive_path), "backup_sha256": before}
    try:
        with zipfile.ZipFile(archive_path) as archive:
            check(archive.namelist().count("database/actions.db") == 1, "Ambiguous database archive member")
            with archive.open("database/actions.db") as source, path.open("xb") as target:
                shutil.copyfileobj(source, target)
        evidence["extracted_database_sha256"] = digest(path)
        rehearse(path, evidence)
    except BaseException as error:
        evidence.update(result="FAILED", failure=repr(error))
        raise
    finally:
        evidence["backup_sha256_after"] = digest(archive_path)
        evidence["backup_unchanged"] = before == evidence["backup_sha256_after"]
        if not evidence["backup_unchanged"]:
            evidence.update(result="FAILED", failure="Original backup changed")
        output = directory / "evidence.json"
        output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(f"EVIDENCE={output}", flush=True)
        print(f"RESULT={evidence.get('result')}; STAGES={len(evidence.get('stages', []))}; CONSTRAINTS={len(evidence.get('constraints', []))}", flush=True)
    check(evidence["backup_unchanged"], "Original backup changed")


if __name__ == "__main__":
    main()
