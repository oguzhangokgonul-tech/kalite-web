from pathlib import Path
import sqlite3
import zipfile

from app import create_app
from app.database_ops import (
    FULL_BACKUP_CONFIRMATION_TEXT,
    create_full_backup,
    restore_full_backup_apply,
    restore_full_backup_dry_run,
    validate_backup_package,
)
from app.extensions import db
from app.models import AppSetting, AuditLog, User
from app.seed import ensure_runtime_schema


def make_file_database_app(tmp_path, restore_enabled=False):
    database_path = tmp_path / "actions.db"
    upload_root = tmp_path / "uploads"
    backup_dir = tmp_path / "backups"
    full_backup_dir = backup_dir / "full"

    class TestConfig:
        SECRET_KEY = "test"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path.as_posix()}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = str(upload_root)
        DATA_DIR = str(tmp_path)
        DATABASE_BACKUP_DIR = str(backup_dir)
        DATABASE_BACKUP_KEEP_LAST = 2
        FULL_BACKUP_DIR = str(full_backup_dir)
        FULL_BACKUP_KEEP_LAST = 2
        BACKUP_INCLUDE_UPLOADS = True
        RESTORE_ENABLED = restore_enabled
        TENANT_BASE_DOMAIN = "volkaportal.com"

    return create_app(TestConfig)


def login(client, user):
    with client.session_transaction() as session:
        session["user_id"] = user.id


def create_superadmin():
    user = User(
        username="superadmin",
        full_name="Super Admin",
        password_hash="not-used",
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


def read_setting(database_path, key):
    with sqlite3.connect(database_path) as connection:
        return connection.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            (key,),
        ).fetchone()[0]


def test_full_backup_contains_database_uploads_manifest_and_checksums(tmp_path):
    app = make_file_database_app(tmp_path)
    with app.app_context():
        db.create_all()
        db.session.add(AppSetting(key="sample", value="1"))
        db.session.commit()
        upload_file = Path(app.config["UPLOAD_FOLDER"]) / "company-001" / "doc.txt"
        upload_file.parent.mkdir(parents=True)
        upload_file.write_text("dosya", encoding="utf-8")

        result = create_full_backup()

        assert result.backup_path.exists()
        assert result.upload_file_count == 1
        with zipfile.ZipFile(result.backup_path) as archive:
            names = set(archive.namelist())
            assert "manifest.json" in names
            assert "checksums.json" in names
            assert "database/actions.db" in names
            assert "uploads/company-001/doc.txt" in names

        validation = validate_backup_package(result.backup_path)
        assert validation.is_ok
        assert validation.quick_check == "ok"
        assert validation.integrity_check == "ok"


def test_restore_dry_run_does_not_change_database_or_uploads(tmp_path):
    app = make_file_database_app(tmp_path)
    database_path = tmp_path / "actions.db"
    upload_file = tmp_path / "uploads" / "company-001" / "doc.txt"
    with app.app_context():
        db.create_all()
        db.session.add(AppSetting(key="sample", value="original"))
        db.session.commit()
        upload_file.parent.mkdir(parents=True)
        upload_file.write_text("original", encoding="utf-8")
        backup = create_full_backup().backup_path

        db.session.get(AppSetting, "sample").value = "changed"
        db.session.commit()
        upload_file.write_text("changed", encoding="utf-8")

        result = restore_full_backup_dry_run(backup)

        assert result.dry_run is True
        assert result.applied is False
        assert not result.issues
        assert read_setting(database_path, "sample") == "changed"
        assert upload_file.read_text(encoding="utf-8") == "changed"


def test_restore_apply_requires_enabled_flag_and_confirmation(tmp_path):
    app = make_file_database_app(tmp_path)
    with app.app_context():
        db.create_all()
        db.session.add(AppSetting(key="sample", value="original"))
        db.session.commit()
        backup = create_full_backup().backup_path

        try:
            restore_full_backup_apply(backup, confirm=FULL_BACKUP_CONFIRMATION_TEXT)
        except Exception as error:
            assert "RESTORE_ENABLED" in str(error)
        else:
            raise AssertionError("restore should require RESTORE_ENABLED")

    app = make_file_database_app(tmp_path, restore_enabled=True)
    with app.app_context():
        try:
            restore_full_backup_apply(backup, confirm="wrong")
        except Exception as error:
            assert FULL_BACKUP_CONFIRMATION_TEXT in str(error)
        else:
            raise AssertionError("restore should require the confirmation text")


def test_restore_apply_restores_database_and_upload_folder(tmp_path):
    app = make_file_database_app(tmp_path, restore_enabled=True)
    database_path = tmp_path / "actions.db"
    upload_file = tmp_path / "uploads" / "company-001" / "doc.txt"
    with app.app_context():
        db.create_all()
        db.session.add(AppSetting(key="sample", value="original"))
        db.session.commit()
        upload_file.parent.mkdir(parents=True)
        upload_file.write_text("original", encoding="utf-8")
        backup = create_full_backup().backup_path

        db.session.get(AppSetting, "sample").value = "changed"
        db.session.commit()
        upload_file.write_text("changed", encoding="utf-8")

        result = restore_full_backup_apply(
            backup,
            confirm=FULL_BACKUP_CONFIRMATION_TEXT,
        )

        assert result.applied is True
        assert result.pre_restore_backup_path is not None
        assert result.pre_restore_backup_path.exists()
        assert read_setting(database_path, "sample") == "original"
        assert upload_file.read_text(encoding="utf-8") == "original"


def test_corrupt_backup_package_is_not_valid(tmp_path):
    app = make_file_database_app(tmp_path)
    with app.app_context():
        db.create_all()
        db.session.commit()
        backup = create_full_backup().backup_path
        broken_backup = tmp_path / "broken.zip"
        broken_backup.write_bytes(backup.read_bytes()[:50])

        result = validate_backup_package(broken_backup)

        assert result.is_ok is False
        assert result.issues


def test_system_backup_page_is_superadmin_only_and_can_create_backup(tmp_path):
    app = make_file_database_app(tmp_path)
    client = app.test_client()
    with app.app_context():
        db.create_all()
        viewer = User(
            username="viewer",
            full_name="Viewer",
            password_hash="not-used",
            is_active=True,
        )
        db.session.add(viewer)
        db.session.commit()

        login(client, viewer)
        assert client.get("/sistem/yedekler").status_code == 403

        superadmin = create_superadmin()
        login(client, superadmin)
        response = client.post("/sistem/yedekler/olustur", follow_redirects=True)

        assert response.status_code == 200
        assert "Sistem Yedekleri" in response.get_data(as_text=True)
        assert list(Path(app.config["FULL_BACKUP_DIR"]).glob("volkaportal-backup-*.zip"))
        assert AuditLog.query.filter_by(action="full_backup_created").count() == 1


def test_runtime_schema_marks_sales_readiness_backup_done(tmp_path):
    app = make_file_database_app(tmp_path)
    with app.app_context():
        db.create_all()
        AppSetting.query.delete()
        db.session.commit()

        ensure_runtime_schema()

        setting = db.session.get(AppSetting, "sales_readiness:month4_backup")
        assert setting is not None
        assert setting.value == "1"
