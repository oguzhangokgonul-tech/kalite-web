"""Disposable backup rehearsal. Never imports app or opens the current instance."""

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
ARCHIVE = Path(os.environ["MEETING_ACTION_BACKUP_ZIP"]).resolve(strict=True)
BASE, HEAD = "202610010001", "202610020001"
LINK = "meeting_decision_actions"
MEETINGS = {"meeting_records", "meeting_participants", "meeting_decisions"}
DIRECTORY = Path(tempfile.mkdtemp(prefix=".tmp-meeting-action-migration-", dir=ROOT))
PATH = DIRECTORY / "migration.db"
EVIDENCE = {"directory": str(DIRECTORY), "stages": [], "constraints": [], "observations": []}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def snapshot(connection, exclude=()):
    exclude = set(exclude) | {"alembic_version"}
    schema = [row for row in connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
    ) if row[2] not in exclude]
    tables = {}
    for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        if name in exclude:
            continue
        rows = connection.execute(f"SELECT * FROM {quote(name)}").fetchall()
        hashes = sorted(hashlib.sha256(repr(row).encode()).hexdigest() for row in rows)
        tables[name] = {"rows": len(rows), "sha256": hashlib.sha256(''.join(hashes).encode()).hexdigest()}
    return {"schema": schema, "tables": tables}


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def run():
    before_archive = digest(ARCHIVE)
    source_paths = [ROOT / "app/meeting_models.py", ROOT / "migrations/versions/202610020001_link_meeting_decision_actions.py"]
    source_before = {str(p.relative_to(ROOT)): digest(p) for p in source_paths}
    EVIDENCE["source_sha256"] = source_before
    EVIDENCE["backup_sha256"] = before_archive
    with zipfile.ZipFile(ARCHIVE) as archive:
        check(archive.namelist().count("database/actions.db") == 1, "Ambiguous database member")
        with archive.open("database/actions.db") as source, PATH.open("xb") as target:
            shutil.copyfileobj(source, target)
    EVIDENCE["extracted_database_sha256"] = digest(PATH)
    app = Flask("isolated_decision_action_migration", instance_path=str(DIRECTORY))
    app.config.update(SQLALCHEMY_DATABASE_URI=f"sqlite:///{PATH.as_posix()}")
    db = SQLAlchemy(app)
    Migrate(app, db, directory=str(ROOT / "migrations"))
    with app.app_context():
        @sa.event.listens_for(db.engine, "connect")
        def enable_foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")
    runner = app.test_cli_runner()
    connection = sqlite3.connect(PATH)
    connection.execute("PRAGMA foreign_keys=ON")
    check(connection.execute("PRAGMA foreign_keys").fetchone() == (1,), "FK enforcement disabled")
    original_fk_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    EVIDENCE["preexisting_foreign_key_errors"] = original_fk_errors
    original = snapshot(connection)
    EVIDENCE["backup_baseline"] = original
    revision = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    EVIDENCE["backup_revision"] = revision
    print(f"BACKUP_REVISION={revision}; TABLES={len(original['tables'])}; ROWS={sum(t['rows'] for t in original['tables'].values())}", flush=True)

    def migrate(direction, revision):
        result = runner.invoke(args=["db", direction, revision])
        EVIDENCE.setdefault("commands", []).append({"direction": direction, "revision": revision, "exit_code": result.exit_code, "output": result.output})
        print(f"db {direction} {revision}: exit={result.exit_code}", flush=True)
        check(result.exit_code == 0, repr(result.exception) + result.output)

    def verify(stage, revision, baseline, exclude=()):
        check(connection.execute("SELECT version_num FROM alembic_version").fetchall() == [(revision,)], f"{stage}: revision")
        check(snapshot(connection, exclude) == baseline, f"{stage}: preexisting schema/data changed")
        check(connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)], f"{stage}: integrity")
        check(connection.execute("PRAGMA foreign_key_check").fetchall() == original_fk_errors, f"{stage}: foreign keys")
        EVIDENCE["stages"].append({"stage": stage, "revision": revision, "prior_schema_and_rows": "unchanged", "integrity_check": "ok", "foreign_key_check": "unchanged"})

    package_name = "_isolated_decision_action_models"
    package = types.ModuleType(package_name)
    package.__path__ = []
    extension = types.ModuleType(package_name + ".extensions")
    extension.db = db
    sys.modules[package_name] = package
    sys.modules[extension.__name__] = extension
    for name in ("companies", "users", "actions"):
        sa.Table(name, db.metadata, sa.Column("id", sa.Integer, primary_key=True))
    spec = importlib.util.spec_from_file_location(package_name + ".meeting_models", ROOT / "app/meeting_models.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def metadata_check(stage):
        with app.app_context(), db.engine.connect() as sql_connection:
            context = MigrationContext.configure(sql_connection, opts={
                "compare_type": True, "compare_server_default": True,
                "include_object": lambda obj, name, kind, reflected, compare_to: name in MEETINGS | {LINK} if kind == "table" else True,
            })
            diff = compare_metadata(context, db.metadata)
            check(diff == [], f"{stage}: model metadata differs: {diff!r}")
            inspector = sa.inspect(sql_connection)
            indexes = inspector.get_indexes(LINK)
            uniques = inspector.get_unique_constraints(LINK)
            fks = inspector.get_foreign_keys(LINK)
            columns = inspector.get_columns(LINK)
            check([(x["name"], x["column_names"]) for x in indexes] == [("ix_meeting_decision_actions_company_id", ["company_id"])], "Company index mismatch")
            check({tuple(x["column_names"]) for x in uniques} == {("decision_id",), ("action_id",)}, "Unique keys mismatch")
            check(len(fks) == 4, "Expected four foreign keys")
            check({(tuple(fk["constrained_columns"]), fk["options"].get("ondelete")) for fk in fks if fk["referred_table"] in {"actions", "meeting_decisions"}} == {(("decision_id",), "RESTRICT"), (("action_id",), "RESTRICT")}, "Delete restrictions mismatch")
            check(all(not c["nullable"] for c in columns), "Unexpected nullable column")
            check(inspector.get_pk_constraint(LINK)["constrained_columns"] == ["id"], "Primary key mismatch")
            EVIDENCE.setdefault("metadata", []).append({"stage": stage, "diff": diff, "indexes": indexes, "unique_constraints": uniques, "foreign_keys": fks, "columns": [{**c, "type": str(c["type"])} for c in columns]})

    def fixture():
        company, user = connection.execute("SELECT company_id,id FROM users WHERE company_id IS NOT NULL ORDER BY id LIMIT 1").fetchone()
        meeting = connection.execute("INSERT INTO meeting_records (company_id,title,meeting_at,created_by_user_id) VALUES (?, 'Disposable probe', '2026-10-02 12:00:00', ?)", (company, user)).lastrowid
        connection.execute("INSERT INTO meeting_participants (company_id,meeting_id,user_id) VALUES (?,?,?)", (company, meeting, user))
        decisions = [connection.execute("INSERT INTO meeting_decisions (company_id,meeting_id,owner_user_id,title,due_date) VALUES (?,?,?,'Disposable decision','2026-10-03')", (company, meeting, user)).lastrowid for _ in range(2)]
        actions = [connection.execute("INSERT INTO actions (company_id,title,responsible_owner,department,termin_date,is_completed,delay_days,closure_approval_requested,effectiveness_required) VALUES (?,'Disposable action','Probe','Probe','2026-10-03',0,0,0,0)", (company,)).lastrowid for _ in range(2)]
        return company, user, meeting, decisions, actions

    def insert_link(company, user, decision, action):
        return connection.execute(f"INSERT INTO {LINK} (company_id,decision_id,action_id,created_by_user_id) VALUES (?,?,?,?)", (company, decision, action, user)).lastrowid

    def rejected(label, sql, args=(), expected=None):
        connection.execute("SAVEPOINT constraint_probe")
        try:
            try:
                connection.execute(sql, args)
            except sqlite3.IntegrityError as error:
                message = str(error)
                check(expected is None or expected in message, f"{label}: wrong rejection {message}")
                EVIDENCE["constraints"].append({"check": label, "result": "rejected", "error": message})
            else:
                raise AssertionError(f"{label}: unexpectedly accepted")
        finally:
            connection.execute("ROLLBACK TO constraint_probe")
            connection.execute("RELEASE constraint_probe")

    try:
        check(revision in [[("202609300001",)], [(BASE,)]], "Unexpected backup revision")
        if revision != [(BASE,)]:
            check(not (MEETINGS & original["tables"].keys()), "Predecessor tables unexpectedly exist")
            migrate("upgrade", BASE)
            verify("prepare_meeting_predecessor", BASE, original, MEETINGS)
        predecessor = snapshot(connection)
        EVIDENCE["predecessor_baseline"] = predecessor
        migrate("upgrade", HEAD)
        verify("upgrade", HEAD, predecessor, {LINK})
        metadata_check("upgrade")
        migrate("downgrade", BASE)
        verify("downgrade_empty", BASE, predecessor)
        migrate("upgrade", HEAD)
        verify("reupgrade", HEAD, predecessor, {LINK})
        metadata_check("reupgrade")

        connection.execute("BEGIN")
        company, user, meeting, decisions, actions = fixture()
        link = insert_link(company, user, decisions[0], actions[0])
        check(connection.execute(f"SELECT created_at FROM {LINK} WHERE id=?", (link,)).fetchone()[0] is not None, "Timestamp default missing")
        EVIDENCE["constraints"].append({"check": "valid_link_and_created_at_default", "result": "accepted"})
        rejected("unique_decision", f"INSERT INTO {LINK} (company_id,decision_id,action_id,created_by_user_id) VALUES (?,?,?,?)", (company, decisions[0], actions[1], user), "UNIQUE")
        rejected("unique_action", f"INSERT INTO {LINK} (company_id,decision_id,action_id,created_by_user_id) VALUES (?,?,?,?)", (company, decisions[1], actions[0], user), "UNIQUE")
        rejected("duplicate_primary_key", f"INSERT INTO {LINK} (id,company_id,decision_id,action_id,created_by_user_id) VALUES (?,?,?,?,?)", (link, company, decisions[1], actions[1], user), "UNIQUE")
        for column in ("company_id", "decision_id", "action_id", "created_by_user_id", "created_at"):
            rejected("not_null_" + column, f"UPDATE {LINK} SET {column}=NULL WHERE id=?", (link,), "NOT NULL")
        for column, target in (("company_id", "companies"), ("decision_id", "meeting_decisions"), ("action_id", "actions"), ("created_by_user_id", "users")):
            missing = connection.execute(f"SELECT COALESCE(MAX(id),0)+1000000 FROM {target}").fetchone()[0]
            rejected("missing_parent_" + column, f"UPDATE {LINK} SET {column}=? WHERE id=?", (missing, link), "FOREIGN KEY")
        rejected("delete_linked_decision", "DELETE FROM meeting_decisions WHERE id=?", (decisions[0],), "FOREIGN KEY")
        rejected("delete_linked_action", "DELETE FROM actions WHERE id=?", (actions[0],), "FOREIGN KEY")
        other_company = connection.execute("SELECT id FROM companies WHERE id != ? ORDER BY id LIMIT 1", (company,)).fetchone()
        check(other_company is not None, "Need two tenants for cross-company constraint probe")
        connection.execute(f"UPDATE {LINK} SET company_id=? WHERE id=?", (other_company[0], link))
        check(connection.execute("PRAGMA foreign_key_check").fetchall() == original_fk_errors, "Cross-company probe unexpectedly changed FK errors")
        EVIDENCE["observations"].append({"check": "cross_company_link", "result": "accepted_with_foreign_keys_on", "detail": "Independent FKs do not enforce link.company_id == decision.company_id == action.company_id or creator.company_id."})
        connection.rollback()
        verify("constraints_rolled_back", HEAD, predecessor, {LINK})

        connection.execute("BEGIN")
        company, user, meeting, decisions, actions = fixture()
        link = insert_link(company, user, decisions[0], actions[0])
        connection.commit()
        populated = snapshot(connection, {LINK})
        populated_all = snapshot(connection)
        EVIDENCE["populated_baseline"] = populated
        migrate("upgrade", HEAD)
        verify("repeat_upgrade_populated", HEAD, populated_all)
        migrate("downgrade", BASE)
        verify("downgrade_populated", BASE, populated)
        check(LINK not in snapshot(connection)["tables"], "Link table retained after downgrade")
        migrate("upgrade", HEAD)
        verify("reupgrade_after_populated_downgrade", HEAD, populated, {LINK})
        check(connection.execute(f"SELECT COUNT(*) FROM {LINK}").fetchone() == (0,), "Links unexpectedly recovered")
        metadata_check("reupgrade_after_populated_downgrade")

        migrate("downgrade", BASE)
        with app.app_context():
            module.MeetingDecisionAction.__table__.create(bind=db.engine, checkfirst=True)
        insert_link(company, user, decisions[0], actions[0])
        connection.commit()
        runtime_baseline = snapshot(connection)
        migrate("upgrade", HEAD)
        verify("precreated_model_table_with_link", HEAD, runtime_baseline)
        metadata_check("precreated_model_table_with_link")

        check("app" not in sys.modules, "Application package was imported")
        check(not any(name.startswith("app.") for name in sys.modules), "Application startup/seed module imported")
        check(digest(ARCHIVE) == before_archive, "Original ZIP changed")
        EVIDENCE["backup_unchanged"] = True
        source_after = {str(p.relative_to(ROOT)): digest(p) for p in source_paths}
        EVIDENCE["source_sha256_after"] = source_after
        EVIDENCE["reviewed_sources_stable_during_rehearsal"] = source_after == source_before
        EVIDENCE["factory_or_seed_imported"] = False
        EVIDENCE["rollback_warning"] = "Downgrade to 202610010001 deletes every decision-action link and its creator/timestamp. Meetings, decisions, actions remain, but re-upgrade does not reconstruct links; synchronization/duplicate prevention lose that history. Export/restore links and coordinate application rollback before downgrade. Downgrading further to 202609300001 also deletes meeting records/participants/decisions."
        EVIDENCE["result"] = "PASS_WITH_TENANT_CONSTRAINT_OBSERVATION"
    finally:
        connection.close()
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        sys.modules.pop(extension.__name__, None)
        sys.modules.pop(package_name, None)


try:
    run()
except BaseException as error:
    EVIDENCE["result"] = "FAILED"
    EVIDENCE["failure"] = repr(error)
    raise
finally:
    (DIRECTORY / "evidence.json").write_text(json.dumps(EVIDENCE, indent=2), encoding="utf-8")
    print(f"EVIDENCE={DIRECTORY / 'evidence.json'}", flush=True)
    print(f"RESULT={EVIDENCE.get('result')}; STAGES={len(EVIDENCE['stages'])}; CONSTRAINTS={len(EVIDENCE['constraints'])}", flush=True)
