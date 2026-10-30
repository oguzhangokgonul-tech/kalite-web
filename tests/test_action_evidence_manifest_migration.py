import sqlite3

from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy


BASE = "202610270001"
HEAD = "202610300001"


def test_action_manifest_migration_round_trip_preserves_existing_schema(tmp_path):
    database = tmp_path / "migration.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(f"""
            CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY);
            INSERT INTO alembic_version VALUES ('{BASE}');
            CREATE TABLE actions(id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL);
            CREATE TRIGGER actions_audit AFTER INSERT ON actions
                BEGIN SELECT NEW.id; END;
            INSERT INTO actions VALUES (1, 10);
        """)
        original_schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='actions_audit'"
        ).fetchone()[0]

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{database.as_posix()}"
    db = SQLAlchemy(app)
    Migrate(app, db, directory="migrations")
    runner = app.test_cli_runner()

    for command, revision in (
        ("upgrade", HEAD), ("upgrade", HEAD),
        ("downgrade", BASE), ("upgrade", HEAD),
    ):
        result = runner.invoke(args=["db", command, revision])
        assert result.exit_code == 0, result.output + repr(result.exception)
        with sqlite3.connect(database) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (revision,)
            assert connection.execute("SELECT * FROM actions").fetchall() == [(1, 10)]
            assert connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='actions_audit'"
            ).fetchone()[0] == original_schema

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE alembic_version SET version_num=?", (BASE,))
        connection.commit()
    result = runner.invoke(args=["db", "upgrade", HEAD])
    assert result.exit_code == 0, result.output + repr(result.exception)

    with sqlite3.connect(database) as connection:
        connection.execute("""
            INSERT INTO action_evidence_manifest
                (stored_name, company_id, action_id, kind, sha256, size_bytes)
            VALUES ('company-010/actions/files/1/proof.pdf', 10, 1, 'files', ?, 5)
        """, ("a" * 64,))
        connection.commit()

    result = runner.invoke(args=["db", "downgrade", BASE])
    assert result.exit_code != 0
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM action_evidence_manifest").fetchone() == (1,)


def test_action_manifest_migration_refuses_unverified_existing_file(tmp_path):
    database = tmp_path / "existing-file.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(f"""
            CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY);
            INSERT INTO alembic_version VALUES ('{BASE}');
            CREATE TABLE actions(id INTEGER PRIMARY KEY, file_stored_name TEXT);
            INSERT INTO actions VALUES (1, 'company-001/actions/files/1/old.pdf');
        """)

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{database.as_posix()}"
    db = SQLAlchemy(app)
    Migrate(app, db, directory="migrations")
    result = app.test_cli_runner().invoke(args=["db", "upgrade", HEAD])
    assert result.exit_code != 0
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (BASE,)
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name='action_evidence_manifest'"
        ).fetchone() is None


def test_action_manifest_migration_refuses_incomplete_runtime_table(tmp_path):
    database = tmp_path / "incomplete.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(f"""
            CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY);
            INSERT INTO alembic_version VALUES ('{BASE}');
            CREATE TABLE action_evidence_manifest(id INTEGER PRIMARY KEY);
        """)

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{database.as_posix()}"
    db = SQLAlchemy(app)
    Migrate(app, db, directory="migrations")
    result = app.test_cli_runner().invoke(args=["db", "upgrade", HEAD])
    assert result.exit_code != 0
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (BASE,)
