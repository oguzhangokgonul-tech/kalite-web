import sqlite3
from pathlib import Path
from uuid import uuid4

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.shift_handover_models import ShiftHandover
from app.shift_handover_schema import GUARDS, ensure_shift_handover_guards


REVISION = "202610120002"
PARENT = "202610120001"
TABLE = "shift_handovers"


@pytest.fixture()
def migration_db(tmp_path):
    path = tmp_path / "shift-handover.db"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY);
            INSERT INTO alembic_version VALUES('202610120001');
            CREATE TABLE companies(id INTEGER PRIMARY KEY, name VARCHAR(100));
            INSERT INTO companies VALUES(1,'Legacy company'),(2,'Other company');
            CREATE TABLE users(id INTEGER PRIMARY KEY, company_id INTEGER, is_active BOOLEAN);
            INSERT INTO users VALUES(1,1,1),(2,1,1),(3,2,1);
            CREATE TABLE company_departments(id INTEGER PRIMARY KEY, company_id INTEGER, name VARCHAR(160));
            INSERT INTO company_departments VALUES(1,1,'Production'),(2,2,'Foreign production');
            CREATE TABLE roles(id INTEGER PRIMARY KEY, key VARCHAR(80));
            INSERT INTO roles VALUES(1,'super_admin');
            CREATE TABLE user_roles(user_id INTEGER, role_id INTEGER);
            CREATE TABLE complaint_files(id INTEGER PRIMARY KEY, original_name VARCHAR(255), evidence_stage VARCHAR(20));
            INSERT INTO complaint_files VALUES(1,'legacy.png','general');
        """)
    app = Flask("shift_handover_migration")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + path.as_posix()
    database = SQLAlchemy(app)
    Migrate(app, database, directory=str(Path(__file__).resolve().parents[1] / "migrations"))
    try:
        yield app, database
    finally:
        with app.app_context():
            database.session.remove()
            database.engine.dispose()


def migrate(app, direction, revision):
    result = app.test_cli_runner().invoke(args=["db", direction, revision])
    assert result.exit_code == 0, result.output + repr(result.exception)


def legacy_snapshot(connection):
    tables = ("companies", "users", "company_departments", "roles", "user_roles", "complaint_files")
    return {name: connection.execute(text(f'SELECT * FROM "{name}" ORDER BY 1')).all() for name in tables}


def guard_names(connection):
    return set(connection.execute(text(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_shift_handover_%'"
    )).scalars())


def assert_schema_parity(connection):
    context = MigrationContext.configure(connection, opts={
        "compare_type": True, "compare_server_default": True,
        "include_object": lambda obj, name, kind, reflected, compare_to: name == TABLE if kind == "table" else True,
    })
    assert compare_metadata(context, ShiftHandover.metadata) == []
    expected_checks = {constraint.name: str(constraint.sqltext) for constraint in ShiftHandover.__table__.constraints
                       if hasattr(constraint, "sqltext")}
    actual_checks = {constraint["name"]: constraint["sqltext"] for constraint in inspect(connection).get_check_constraints(TABLE)}
    assert actual_checks == expected_checks
    assert guard_names(connection) == {"trg_shift_handover_" + name for name in GUARDS}


def insert_record(connection, **overrides):
    values = dict(company_id=1, handover_date="2026-10-12", shift_name="Morning", department_id=1,
                  title="Preserved handover", summary="Legacy-safe test", sender_user_id=1,
                  receiver_user_id=2, request_token=str(uuid4()))
    values.update(overrides)
    # Only test-owned column names are interpolated; all record data is bound.
    statement = f"INSERT INTO shift_handovers ({','.join(values)}) VALUES ({','.join(':' + name for name in values)})"
    return connection.execute(text(statement), values).lastrowid


def test_upgrade_downgrade_upgrade_preserves_legacy_data_and_schema(migration_db):
    app, database = migration_db
    with app.app_context(), database.engine.connect() as connection:
        baseline = legacy_snapshot(connection)
    for direction, revision in (("upgrade", REVISION), ("downgrade", PARENT), ("upgrade", REVISION)):
        migrate(app, direction, revision)
        with app.app_context(), database.engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == revision
            assert legacy_snapshot(connection) == baseline
            assert connection.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
            assert inspect(connection).has_table(TABLE) is (direction == "upgrade")
            if direction == "upgrade":
                assert_schema_parity(connection)
            else:
                assert guard_names(connection) == set()


def test_runtime_created_table_and_records_survive_upgrade_and_guard_refresh(migration_db):
    app, database = migration_db
    with app.app_context(), database.engine.begin() as connection:
        ShiftHandover.__table__.create(connection)
        record_id = insert_record(connection)
        before = connection.execute(text("SELECT * FROM shift_handovers")).all()
        connection.execute(text("DROP TRIGGER trg_shift_handover_tenant_insert"))
        connection.execute(text("CREATE TRIGGER trg_shift_handover_tenant_insert BEFORE INSERT ON shift_handovers "
                                "BEGIN SELECT RAISE(ABORT, 'obsolete guard'); END"))
    migrate(app, "upgrade", REVISION)
    migrate(app, "upgrade", REVISION)
    with app.app_context(), database.engine.begin() as connection:
        assert connection.execute(text("SELECT * FROM shift_handovers")).all() == before
        assert_schema_parity(connection)
        sql = connection.execute(text("SELECT sql FROM sqlite_master WHERE name='trg_shift_handover_tenant_insert'")).scalar_one()
        assert "obsolete guard" not in sql
        ensure_shift_handover_guards(connection)
        assert_schema_parity(connection)
        assert insert_record(connection) != record_id


def test_migrated_database_enforces_tenant_lifecycle_identity_and_versions(migration_db):
    app, database = migration_db
    migrate(app, "upgrade", REVISION)
    with app.app_context(), database.engine.begin() as connection:
        # Guards must protect existing SQLite deployments even with foreign_keys disabled.
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 0
        record_id = insert_record(connection)
        for overrides in ({"receiver_user_id": 3}, {"department_id": 2}, {"sender_user_id": 3},
                          {"company_id": 999}, {"receiver_user_id": 999}, {"version_id": 2},
                          {"status": "sent", "sent_at": "2026-10-12 08:00:00", "sent_by_user_id": 1}):
            with pytest.raises(IntegrityError), connection.begin_nested():
                insert_record(connection, **overrides)
        original = connection.execute(text("SELECT * FROM shift_handovers WHERE id=:id"), {"id": record_id}).one()
        forbidden = (
            "UPDATE shift_handovers SET title='No version bump' WHERE id=:id",
            "UPDATE shift_handovers SET sender_user_id=2,version_id=version_id+1 WHERE id=:id",
            "UPDATE shift_handovers SET company_id=2,version_id=version_id+1 WHERE id=:id",
            "UPDATE shift_handovers SET receiver_user_id=3,version_id=version_id+1 WHERE id=:id",
            "UPDATE shift_handovers SET department_id=2,version_id=version_id+1 WHERE id=:id",
            "UPDATE shift_handovers SET request_token='11111111-1111-1111-1111-111111111111',version_id=version_id+1 WHERE id=:id",
            "DELETE FROM shift_handovers WHERE id=:id",
            "DELETE FROM users WHERE id=2",
            "UPDATE users SET company_id=2 WHERE id=2",
            "DELETE FROM company_departments WHERE id=1",
            "UPDATE company_departments SET company_id=2 WHERE id=1",
            "DELETE FROM companies WHERE id=1",
        )
        for statement in forbidden:
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(text(statement), {"id": record_id})
            assert connection.execute(text("SELECT * FROM shift_handovers WHERE id=:id"), {"id": record_id}).one() == original
        connection.execute(text("UPDATE shift_handovers SET status='sent',sent_at='2026-10-12 08:00:00',"
                                "sent_by_user_id=1,version_id=2 WHERE id=:id"), {"id": record_id})
        for actor in (None, 1, 3):
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(text("UPDATE shift_handovers SET status='received',received_at='2026-10-12 09:00:00',"
                                        "received_by_user_id=:actor,version_id=3 WHERE id=:id"), {"id": record_id, "actor": actor})
        connection.execute(text("UPDATE shift_handovers SET status='received',received_at='2026-10-12 09:00:00',"
                                "received_by_user_id=2,version_id=3 WHERE id=:id"), {"id": record_id})
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(text("UPDATE shift_handovers SET title='Changed receipt',version_id=4 WHERE id=:id"), {"id": record_id})
        connection.execute(text("UPDATE shift_handovers SET archived_at='2026-10-12 10:00:00',"
                                "archived_by_user_id=1,version_id=4 WHERE id=:id"), {"id": record_id})
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(text("UPDATE shift_handovers SET archived_at=NULL,archived_by_user_id=NULL,version_id=5 WHERE id=:id"), {"id": record_id})
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []


@pytest.mark.parametrize("sent", [False, True])
def test_migrated_database_preserves_cancel_evidence_and_terminal_state(migration_db, sent):
    app, database = migration_db
    migrate(app, "upgrade", REVISION)
    with app.app_context(), database.engine.begin() as connection:
        record_id = insert_record(connection)
        if sent:
            connection.execute(text("UPDATE shift_handovers SET status='sent',sent_at='2026-10-12 08:00:00',"
                                    "sent_by_user_id=1,version_id=2 WHERE id=:id"), {"id": record_id})
        for reason, actor in ((None, 1), ("", 1), ("Reason", None), ("Reason", 3), ("x" * 1001, 1)):
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(text("UPDATE shift_handovers SET status='cancelled',cancel_reason=:reason,"
                                        "cancelled_at='2026-10-12 09:00:00',cancelled_by_user_id=:actor,"
                                        "version_id=version_id+1 WHERE id=:id"),
                                   {"id": record_id, "reason": reason, "actor": actor})
        connection.execute(text("UPDATE shift_handovers SET status='cancelled',cancel_reason='Superseded',"
                                "cancelled_at='2026-10-12 09:00:00',cancelled_by_user_id=1,"
                                "version_id=version_id+1 WHERE id=:id"), {"id": record_id})
        original = connection.execute(text("SELECT * FROM shift_handovers WHERE id=:id"), {"id": record_id}).one()
        for mutation in ("cancel_reason='Forged'", "cancelled_by_user_id=2", "cancelled_at='2026-10-12 10:00:00'",
                         "title='Altered cancellation'", "status='draft',cancel_reason=NULL,cancelled_at=NULL,cancelled_by_user_id=NULL",
                         "status='received',received_at='2026-10-12 10:00:00',received_by_user_id=2"):
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(text(f"UPDATE shift_handovers SET {mutation},version_id=version_id+1 WHERE id=:id"),
                                   {"id": record_id})
            assert connection.execute(text("SELECT * FROM shift_handovers WHERE id=:id"), {"id": record_id}).one() == original
        connection.execute(text("UPDATE shift_handovers SET archived_at='2026-10-12 10:00:00',"
                                "archived_by_user_id=1,version_id=version_id+1 WHERE id=:id"), {"id": record_id})
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
