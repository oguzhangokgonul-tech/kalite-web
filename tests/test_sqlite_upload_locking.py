from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
import sqlite3

from sqlalchemy.exc import OperationalError

from app import create_app
from app import routes
from app.extensions import db
from app.models import Document
from app.seed import ensure_default_roles

from .helpers import create_company, create_user, first_document_category, login, upload_tuple
from .test_documents_management import document_payload


def file_database_app(tmp_path):
    database = tmp_path / "actions.db"

    class TestConfig:
        APP_ENV = "testing"
        SECRET_KEY = "test"
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database.as_posix()}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SQLITE_BUSY_TIMEOUT_SECONDS = 15
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = str(tmp_path / "uploads")
        TENANT_BASE_DOMAIN = "volkaportal.com"
        MAIL_ENABLED = False

    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        ensure_default_roles()
        company = create_company("LOCK1")
        manager = create_user("sqlite-upload-manager", company=company, role_key="management_representative")
        category_id = first_document_category(company).id
        login_user = SimpleNamespace(
            id=manager.id, session_version=manager.session_version, company_id=manager.company_id,
        )
        db.session.remove()
    return app, database, login_user, category_id


def test_preview_work_does_not_hold_sqlite_write_lock(tmp_path, monkeypatch):
    app, database, manager, category_id = file_database_app(tmp_path)
    entered = Event()
    release = Event()
    original_preview = routes.generate_document_preview

    def pause_preview(document):
        entered.set()
        assert release.wait(15)
        return original_preview(document)

    monkeypatch.setattr(routes, "generate_document_preview", pause_preview)
    client = app.test_client()
    login(client, manager)
    with app.app_context():
        category = db.session.get(routes.DocumentCategory, category_id)
        payload = document_payload(category)
        db.session.remove()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            client.post, "/documents/upload",
            data={**payload, "document_file": upload_tuple(b"%PDF-1.4\nlock test\n", "lock.pdf")},
        )
        try:
            assert entered.wait(15)
            with sqlite3.connect(database, timeout=0.5) as connection:
                connection.execute(
                    "INSERT INTO app_settings (key, value) VALUES (?, ?)",
                    ("concurrent-upload-write", "ok"),
                )
            release.set()
            assert future.result(timeout=20).status_code == 302
        finally:
            release.set()
    with app.app_context():
        assert Document.query.filter_by(company_id=manager.company_id).count() == 1
        db.session.remove()
        db.engine.dispose()


def test_locked_upload_cleans_files_and_returns_retry_message(tmp_path, monkeypatch):
    app, database, manager, category_id = file_database_app(tmp_path)
    client = app.test_client()
    login(client, manager)
    with app.app_context():
        category = db.session.get(routes.DocumentCategory, category_id)
        payload = document_payload(category)
        real_commit = db.session.commit

        def fail_document_commit():
            if any(isinstance(item, Document) for item in db.session.new):
                raise OperationalError(
                    "INSERT INTO documents", (), sqlite3.OperationalError("database is locked")
                )
            return real_commit()

        monkeypatch.setattr(db.session, "commit", fail_document_commit)
        response = client.post(
            "/documents/upload",
            data={**payload, "document_file": upload_tuple(b"%PDF-1.4\nlock test\n", "lock.pdf")},
        )
        assert response.status_code == 503
        assert "lütfen tekrar deneyin" in response.get_data(as_text=True)
        assert Document.query.count() == 0
        assert not list((tmp_path / "uploads").rglob("document-*"))
        db.session.remove()
        db.engine.dispose()
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_sqlite_connections_receive_bounded_busy_timeout(tmp_path):
    app, _, _, _ = file_database_app(tmp_path)
    with app.app_context():
        with db.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 15000
        db.session.remove()
        db.engine.dispose()
