"""OHS classification schema checks using disposable local databases only."""
from pathlib import Path

from flask import Flask
from flask_migrate import Migrate
import pytest
import sqlalchemy as sa

from app.extensions import db
from app.ohs_actions_schema import ensure_ohs_actions_schema


PARENT = "202610120002"
REVISION = "202610140001"
INDEX = "ix_actions_action_category"


@pytest.fixture()
def schema_app(tmp_path):
    app = Flask("ohs_actions_schema")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + (tmp_path / "schema.db").as_posix()
    db.init_app(app)
    Migrate(app, db, directory=str(Path(__file__).resolve().parents[1] / "migrations"))
    with app.app_context():
        with db.engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
            connection.execute(sa.text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": PARENT})
            connection.execute(sa.text("CREATE TABLE companies (id INTEGER PRIMARY KEY)"))
            connection.execute(sa.text("INSERT INTO companies VALUES (1), (2)"))
            connection.execute(sa.text(
                "CREATE TABLE actions (id INTEGER PRIMARY KEY, company_id INTEGER REFERENCES companies(id), "
                "title VARCHAR(160) NOT NULL, updated_at TEXT NOT NULL DEFAULT 'legacy')"
            ))
            connection.execute(sa.text("CREATE INDEX ix_actions_company_id ON actions (company_id)"))
            connection.execute(sa.text("INSERT INTO actions (id, company_id, title) VALUES (1, 1, 'First'), (2, 2, 'Second')"))
            connection.execute(sa.text("CREATE TABLE action_links (id INTEGER PRIMARY KEY, action_id INTEGER REFERENCES actions(id))"))
            connection.execute(sa.text("INSERT INTO action_links VALUES (1, 1)"))
            connection.execute(sa.text(
                "CREATE TRIGGER action_identity BEFORE UPDATE OF id, company_id ON actions "
                "WHEN NEW.id IS NOT OLD.id OR NEW.company_id IS NOT OLD.company_id "
                "BEGIN SELECT RAISE(ABORT, 'immutable identity'); END"
            ))
        try:
            yield app
        finally:
            db.session.remove()
            db.engine.dispose()


def migrate(app, direction, revision):
    result = app.test_cli_runner().invoke(args=["db", direction, revision])
    assert result.exit_code == 0, result.output + repr(result.exception)


def legacy_snapshot(connection):
    return (
        connection.execute(sa.text("SELECT id, company_id, title, updated_at FROM actions ORDER BY id")).all(),
        connection.execute(sa.text("SELECT * FROM companies ORDER BY id")).all(),
        connection.execute(sa.text("SELECT * FROM action_links ORDER BY id")).all(),
        connection.execute(sa.text(
            "SELECT type, name, sql FROM sqlite_master WHERE type IN ('trigger', 'index') "
            "AND name != 'ix_actions_action_category' ORDER BY name"
        )).all(),
    )


def assert_category_schema(connection):
    inspector = sa.inspect(connection)
    column = next(column for column in inspector.get_columns("actions") if column["name"] == "action_category")
    assert isinstance(column["type"], sa.String)
    assert column["type"].length == 16
    assert column["nullable"] is False
    assert column["default"].strip("'\"") == "general"
    index = next(index for index in inspector.get_indexes("actions") if index["name"] == INDEX)
    assert index["column_names"] == ["action_category"]
    assert not index["unique"]


def test_runtime_adds_default_index_and_preserves_legacy_rows(schema_app):
    with db.engine.connect() as connection:
        before = legacy_snapshot(connection)
    ensure_ohs_actions_schema()
    ensure_ohs_actions_schema(db.engine)
    with db.engine.begin() as connection:
        assert_category_schema(connection)
        assert legacy_snapshot(connection) == before
        assert connection.execute(sa.text("SELECT action_category FROM actions ORDER BY id")).scalars().all() == ["general", "general"]
        connection.execute(sa.text("INSERT INTO actions (id, title) VALUES (3, 'Default')"))
        assert connection.execute(sa.text("SELECT action_category FROM actions WHERE id=3")).scalar_one() == "general"
        with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
            connection.execute(sa.text("INSERT INTO actions (id, title, action_category) VALUES (4, 'Null', NULL)"))


@pytest.mark.parametrize("use_migration", [False, True])
def test_backfill_missing_categories_preserves_ohs(schema_app, use_migration):
    with db.engine.begin() as connection:
        connection.execute(sa.text("ALTER TABLE actions ADD COLUMN action_category VARCHAR(16)"))
        connection.execute(sa.text("UPDATE actions SET action_category='ohs' WHERE id=2"))
        connection.execute(sa.text("INSERT INTO actions (id, title, action_category) VALUES (3, 'Blank', ''), (4, 'Spaces', '   '), (5, 'General', 'general')"))
        before = legacy_snapshot(connection)
    if use_migration:
        migrate(schema_app, "upgrade", REVISION)
    else:
        ensure_ohs_actions_schema()
        ensure_ohs_actions_schema()
    with db.engine.connect() as connection:
        assert legacy_snapshot(connection) == before
        assert connection.execute(sa.text("SELECT action_category FROM actions ORDER BY id")).scalars().all() == ["general", "ohs", "general", "general", "general"]
        assert INDEX in {index["name"] for index in sa.inspect(connection).get_indexes("actions")}


def test_upgrade_downgrade_upgrade_preserves_rows_and_guards(schema_app):
    with db.engine.connect() as connection:
        before = legacy_snapshot(connection)
    for direction, revision in (("upgrade", REVISION), ("downgrade", PARENT), ("upgrade", REVISION)):
        migrate(schema_app, direction, revision)
        with db.engine.begin() as connection:
            assert legacy_snapshot(connection) == before
            assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == revision
            assert connection.execute(sa.text("PRAGMA integrity_check")).scalar_one() == "ok"
            assert connection.execute(sa.text("PRAGMA foreign_key_check")).all() == []
            if direction == "upgrade":
                assert_category_schema(connection)
                assert connection.execute(sa.text("SELECT action_category FROM actions ORDER BY id")).scalars().all() == ["general", "general"]
                connection.execute(sa.text("UPDATE actions SET action_category='ohs' WHERE id=2"))
            else:
                assert "action_category" not in {column["name"] for column in sa.inspect(connection).get_columns("actions")}
                assert INDEX not in {index["name"] for index in sa.inspect(connection).get_indexes("actions")}
            with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
                connection.execute(sa.text("UPDATE actions SET company_id=2 WHERE id=1"))


def test_runtime_then_upgrade_preserves_categories_and_repairs_missing_index(schema_app):
    ensure_ohs_actions_schema()
    with db.engine.begin() as connection:
        connection.execute(sa.text("UPDATE actions SET action_category='ohs' WHERE id=2"))
        connection.execute(sa.text("DROP INDEX ix_actions_action_category"))
        before = connection.execute(sa.text("SELECT * FROM actions ORDER BY id")).all()
    migrate(schema_app, "upgrade", REVISION)
    migrate(schema_app, "upgrade", REVISION)
    ensure_ohs_actions_schema()
    with db.engine.connect() as connection:
        assert_category_schema(connection)
        assert connection.execute(sa.text("SELECT * FROM actions ORDER BY id")).all() == before


def test_missing_actions_table_is_noop(schema_app):
    with db.engine.begin() as connection:
        connection.execute(sa.text("DROP TABLE action_links"))
        connection.execute(sa.text("DROP TABLE actions"))
    ensure_ohs_actions_schema()
    for direction, revision in (("upgrade", REVISION), ("downgrade", PARENT), ("upgrade", REVISION)):
        migrate(schema_app, direction, revision)
        with db.engine.connect() as connection:
            assert not sa.inspect(connection).has_table("actions")
