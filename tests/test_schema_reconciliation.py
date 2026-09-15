from pathlib import Path
import importlib.util

import pytest
from sqlalchemy import inspect, text
from sqlalchemy import create_engine
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app import create_app, db
from app.tenant_health import collect_tenant_health_checks


def migration_app(tmp_path):
    class TestConfig:
        SECRET_KEY = "migration-test"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = str(tmp_path / "uploads")

    return create_app(TestConfig)


def assert_model_schema_is_present():
    inspector = inspect(db.engine)
    actual_tables = set(inspector.get_table_names())
    assert set(db.metadata.tables) <= actual_tables
    for name, table in db.metadata.tables.items():
        actual_columns = {column["name"] for column in inspector.get_columns(name)}
        assert {column.name for column in table.columns} <= actual_columns, name


@pytest.mark.parametrize("runtime_schema_already_exists", (False, True))
def test_upgrade_reconciles_fresh_and_existing_runtime_databases(
    tmp_path, runtime_schema_already_exists
):
    app = migration_app(tmp_path)
    runner = app.test_cli_runner()
    directory = str(Path(__file__).parents[1] / "migrations")
    result = runner.invoke(args=["db", "upgrade", "-d", directory, "202609120004"])
    assert result.exit_code == 0, result.output

    with app.app_context():
        if runtime_schema_already_exists:
            # Simulate deployed tables created outside the Alembic chain.
            db.create_all()
        db.session.execute(text(
            "INSERT INTO companies (code, name, slug, is_active, created_at, updated_at) "
            "VALUES ('AUDIT', 'Preserved company', 'preserved', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))
        db.session.commit()

    for _ in range(2):
        result = runner.invoke(args=["db", "upgrade", "-d", directory])
        assert result.exit_code == 0, result.output

    with app.app_context():
        assert_model_schema_is_present()
        row = db.session.execute(text(
            "SELECT name, package_key, is_demo FROM companies WHERE code = 'AUDIT'"
        )).one()
        assert tuple(row) == ("Preserved company", "production_plus", 0)
        for table, column in (
            ("actions", "dof_id"), ("users", "personnel_contact_id"),
            ("notifications", "source_key"),
        ):
            indexes = inspect(db.engine).get_indexes(table)
            assert any(column in index["column_names"] for index in indexes)
        app.config.update(PASSWORD_MIN_LENGTH=10, PASSWORD_MAX_LENGTH=128)
        created = runner.invoke(args=["create-superadmin"], input="strong-migration-password\nstrong-migration-password\n")
        assert created.exit_code == 0, created.output
        checks = collect_tenant_health_checks()
        assert not [check for check in checks if check.status == "FAIL"]
        db.session.remove()
        db.engine.dispose()


def test_identity_upgrade_replaces_unnamed_legacy_evaluator_constraint():
    path = Path(__file__).parents[1] / "migrations/versions/202609150002_identity_security.py"
    spec = importlib.util.spec_from_file_location("identity_security", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE login_attempts (id INTEGER PRIMARY KEY)"))
        connection.execute(text(
            "CREATE TABLE suggestion_evaluations (id INTEGER PRIMARY KEY, suggestion_id INTEGER, "
            "parameter_id INTEGER, evaluator_user_id INTEGER, evaluator_department VARCHAR(80), "
            "UNIQUE(suggestion_id, parameter_id, evaluator_department))"
        ))
        connection.execute(text("INSERT INTO suggestion_evaluations VALUES (1, 1, 1, 1, 'Same Name')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
        connection.execute(text("INSERT INTO suggestion_evaluations VALUES (2, 1, 1, 2, 'Same Name')"))
        assert connection.execute(text("SELECT COUNT(*) FROM suggestion_evaluations")).scalar() == 2
        constraints = inspect(connection).get_unique_constraints("suggestion_evaluations")
        assert all("evaluator_department" not in row["column_names"] for row in constraints)
    engine.dispose()
