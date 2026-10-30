import sqlite3

from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy


BASE = "202610300001"
HEAD = "202610300002"


def migration_runner(database):
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{database.as_posix()}"
    db = SQLAlchemy(app)
    Migrate(app, db, directory="migrations")
    return app.test_cli_runner()


def test_dof_cleanup_migration_round_trip(tmp_path):
    database = tmp_path / "migration.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(f"""
            CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY);
            INSERT INTO alembic_version VALUES ('{BASE}');
            CREATE TABLE dofs(id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL);
            INSERT INTO dofs VALUES (1, 10);
        """)
    runner = migration_runner(database)

    for command, revision in (
        ("upgrade", HEAD), ("upgrade", HEAD),
        ("downgrade", BASE), ("upgrade", HEAD),
    ):
        result = runner.invoke(args=["db", command, revision])
        assert result.exit_code == 0, result.output + repr(result.exception)
        with sqlite3.connect(database) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (revision,)
            assert connection.execute("SELECT * FROM dofs").fetchall() == [(1, 10)]

    with sqlite3.connect(database) as connection:
        connection.execute("""
            INSERT INTO dof_file_cleanup
                (company_id, dof_id, stored_name, file_type, sha256, size_bytes)
            VALUES (10, 1, 'dof-opening-test.jpg', 'opening', ?, 5)
        """, ("a" * 64,))
        connection.commit()
    result = runner.invoke(args=["db", "downgrade", BASE])
    assert result.exit_code != 0
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM dof_file_cleanup").fetchone() == (1,)


def test_dof_cleanup_migration_rejects_incomplete_runtime_table(tmp_path):
    database = tmp_path / "incomplete.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(f"""
            CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY);
            INSERT INTO alembic_version VALUES ('{BASE}');
            CREATE TABLE dof_file_cleanup(id INTEGER PRIMARY KEY);
        """)
    result = migration_runner(database).invoke(args=["db", "upgrade", HEAD])
    assert result.exit_code != 0
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (BASE,)
