"""The tri-state column must preserve existing grants and refuse lossy rollback."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def load_migration():
    path = Path(__file__).resolve().parents[1] / "migrations/versions/202610270001_personal_permission_decisions.py"
    spec = importlib.util.spec_from_file_location("personal_permission_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_personal_permission_upgrade_downgrade_upgrade(tmp_path):
    migration = load_migration()
    engine = sa.create_engine("sqlite:///" + (tmp_path / "permissions.db").as_posix())
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
            connection.execute(sa.text("INSERT INTO users (id) VALUES (1)"))
            connection.execute(sa.text("CREATE TABLE roles (id INTEGER PRIMARY KEY, key VARCHAR(80) NOT NULL)"))
            connection.execute(sa.text("INSERT INTO roles (id, key) VALUES (1, 'management_representative'), (2, 'company_admin')"))
            connection.execute(sa.text("CREATE TABLE role_permissions (role_id INTEGER, permission_key VARCHAR(120), PRIMARY KEY (role_id, permission_key))"))
            connection.execute(sa.text("""
                CREATE TABLE user_permissions (
                    user_id INTEGER NOT NULL, permission_key VARCHAR(120) NOT NULL,
                    PRIMARY KEY (user_id, permission_key),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
            """))
            connection.execute(sa.text("INSERT INTO user_permissions (user_id, permission_key) VALUES (1, 'quality.create')"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                migration.upgrade()
                assert "permissions_customized" in {
                    c["name"] for c in sa.inspect(connection).get_columns("roles")
                }
                assert connection.execute(sa.text(
                    "SELECT COUNT(*) FROM role_permissions WHERE permission_key = 'suggestions.evaluate'"
                )).scalar_one() == 2
                assert connection.execute(sa.text(
                    "SELECT is_allowed FROM user_permissions WHERE user_id = 1"
                )).scalar_one() == 1
                migration.downgrade()
                assert "is_allowed" not in {c["name"] for c in sa.inspect(connection).get_columns("user_permissions")}
                assert "permissions_customized" not in {c["name"] for c in sa.inspect(connection).get_columns("roles")}
                migration.upgrade()
                assert connection.execute(sa.text(
                    "SELECT is_allowed FROM user_permissions WHERE user_id = 1"
                )).scalar_one() == 1
                connection.execute(sa.text(
                    "UPDATE user_permissions SET is_allowed = 0 WHERE user_id = 1"
                ))
                with pytest.raises(RuntimeError, match="denials exist"):
                    migration.downgrade()
    finally:
        engine.dispose()


def test_downgrade_refuses_triggered_sqlite_schema_before_mutation(tmp_path):
    migration = load_migration()
    engine = sa.create_engine("sqlite:///" + (tmp_path / "triggered.db").as_posix())
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
            connection.execute(sa.text("CREATE TABLE roles (id INTEGER PRIMARY KEY, key VARCHAR(80))"))
            connection.execute(sa.text("CREATE TABLE role_permissions (role_id INTEGER, permission_key VARCHAR(120))"))
            connection.execute(sa.text(
                "CREATE TABLE user_permissions (user_id INTEGER, permission_key VARCHAR(120))"
            ))
            connection.execute(sa.text(
                "CREATE TRIGGER keep_roles AFTER INSERT ON users BEGIN "
                "SELECT COUNT(*) FROM roles; END"
            ))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                with pytest.raises(RuntimeError, match="trigger dependencies"):
                    migration.downgrade()
            assert "is_allowed" in {
                column["name"] for column in sa.inspect(connection).get_columns("user_permissions")
            }
            assert "permissions_customized" in {
                column["name"] for column in sa.inspect(connection).get_columns("roles")
            }
    finally:
        engine.dispose()
