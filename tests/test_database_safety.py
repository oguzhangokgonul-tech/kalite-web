from datetime import datetime
from pathlib import Path
import sqlite3

import pytest

from app import create_app
from app.database_ops import (
    DatabaseOperationError,
    create_sqlite_backup,
    sqlite_database_path,
    sqlite_health_check,
)
from app.extensions import db
from app.models import AppSetting, AuditLog
from app.seed import ensure_runtime_schema


def make_file_database_app(tmp_path):
    database_path = tmp_path / "actions.db"
    backup_dir = tmp_path / "backups"

    class TestConfig:
        SECRET_KEY = "test"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path.as_posix()}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = str(tmp_path / "uploads")
        DATA_DIR = str(tmp_path)
        DATABASE_BACKUP_DIR = str(backup_dir)
        DATABASE_BACKUP_KEEP_LAST = 2
        TENANT_BASE_DOMAIN = "volkaportal.com"

    return create_app(TestConfig)


def test_db_check_cli_validates_sqlite_and_writes_audit_log(tmp_path):
    app = make_file_database_app(tmp_path)
    with app.app_context():
        db.create_all()
        db.session.commit()

        result = app.test_cli_runner().invoke(args=["db-check"])

        assert result.exit_code == 0, result.output
        assert "quick_check: ok" in result.output
        assert "integrity_check: ok" in result.output
        audit_log = AuditLog.query.filter_by(
            entity_type="DatabaseSafety",
            action="integrity_checked",
        ).one()
        assert "quick_check" in audit_log.new_values


def test_db_backup_cli_creates_checked_sqlite_copy_and_audit_log(tmp_path):
    app = make_file_database_app(tmp_path)
    with app.app_context():
        db.create_all()
        db.session.add(AppSetting(key="sample", value="1"))
        db.session.commit()

        result = app.test_cli_runner().invoke(args=["db-backup"])

        assert result.exit_code == 0, result.output
        backups = list(Path(app.config["DATABASE_BACKUP_DIR"]).glob("actions-*.sqlite3"))
        assert len(backups) == 1
        with sqlite3.connect(backups[0]) as connection:
            assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            value = connection.execute(
                "SELECT value FROM app_settings WHERE key = 'sample'"
            ).fetchone()[0]
        assert value == "1"
        assert AuditLog.query.filter_by(
            entity_type="DatabaseSafety",
            action="backup_created",
        ).count() == 1


def test_sqlite_backup_retention_keeps_configured_latest_files(tmp_path):
    app = make_file_database_app(tmp_path)
    with app.app_context():
        db.create_all()
        db.session.commit()

        for second in range(3):
            create_sqlite_backup(now=datetime(2026, 9, 2, 12, 0, second))

        backups = sorted(Path(app.config["DATABASE_BACKUP_DIR"]).glob("actions-*.sqlite3"))
        assert [path.name for path in backups] == [
            "actions-20260902-120001.sqlite3",
            "actions-20260902-120002.sqlite3",
        ]


def test_database_commands_fail_safely_for_in_memory_sqlite_database(tmp_path):
    class TestConfig:
        SECRET_KEY = "test"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = str(tmp_path / "uploads")
        TENANT_BASE_DOMAIN = "volkaportal.com"

    app = create_app(TestConfig)

    result = app.test_cli_runner().invoke(args=["db-check"])

    assert result.exit_code != 0
    assert "sadece dosya tabanli SQLite" in result.output


def test_database_helpers_reject_non_sqlite_uri(tmp_path):
    app = make_file_database_app(tmp_path)
    with app.app_context():
        assert sqlite_database_path("postgresql://user:pass@example.test/volkaportal") is None
        with pytest.raises(DatabaseOperationError):
            sqlite_health_check("postgresql://user:pass@example.test/volkaportal")


def test_runtime_schema_marks_sales_readiness_sqlite_done(tmp_path):
    app = make_file_database_app(tmp_path)
    with app.app_context():
        db.create_all()
        AppSetting.query.delete()
        db.session.commit()

        ensure_runtime_schema()

        setting = db.session.get(AppSetting, "sales_readiness:month1_sqlite")
        assert setting is not None
        assert setting.value == "1"
