from datetime import date
from pathlib import Path
import json

import pytest

from app import create_app
from app.audit import TRACKED_MODEL_NAMES, record_audit_event
from app.extensions import db
from app.models import Action, AppSetting, AuditLog, User, UserPermission
from app.seed import ensure_runtime_schema
from .helpers import (
    create_company as helper_create_company,
    create_user as helper_create_user,
    make_document,
)


@pytest.fixture()
def app(tmp_path):
    class TestConfig:
        SECRET_KEY = "test"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = str(Path(tmp_path) / "uploads")
        TENANT_BASE_DOMAIN = "volkaportal.com"

    test_app = create_app(TestConfig)
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, user):
    with client.session_transaction() as session:
        session["user_id"] = user.id


def create_user(username, permission_key=None):
    user = User(
        username=username,
        full_name=username.title(),
        password_hash="not-used",
        is_active=True,
    )
    if permission_key:
        user.extra_permissions.append(UserPermission(permission_key=permission_key))
    db.session.add(user)
    db.session.commit()
    return user


def test_audit_log_records_create_update_and_delete(app):
    user = create_user("manager", "users.manage")

    with app.test_request_context("/", headers={"User-Agent": "pytest"}):
        from flask import g

        g.current_user = user
        g.current_company = None
        g.current_user_is_super_admin = True
        action = Action(
            title="Audit Deneme",
            responsible_owner="Kalite",
            department="Kalite",
            description="İlk açıklama",
            termin_date=date(2026, 9, 1),
        )
        db.session.add(action)
        db.session.commit()

        assert action.title == "Audit Deneme"
        action.title = "Audit Deneme Güncel"
        db.session.commit()

        db.session.delete(action)
        db.session.commit()

    logs = AuditLog.query.filter_by(entity_type="Action").order_by(AuditLog.id.asc()).all()

    assert [log.action for log in logs] == ["created", "updated", "deleted"]
    assert logs[0].user_id == user.id
    assert logs[0].entity_id
    assert logs[0].new_values is not None
    assert json.loads(logs[1].old_values)["title"] == "Audit Deneme"
    assert json.loads(logs[1].new_values)["title"] == "Audit Deneme Güncel"
    assert json.loads(logs[2].old_values)["title"] == "Audit Deneme Güncel"


def test_audit_log_does_not_store_sensitive_password_hash(app):
    user = create_user("supervisor", "users.manage")

    with app.test_request_context("/"):
        from flask import g

        g.current_user = user
        g.current_company = None
        g.current_user_is_super_admin = True
        user.password_hash = "new-secret-hash"
        db.session.commit()

    logs = AuditLog.query.filter_by(entity_type="User").all()

    assert logs
    for log in logs:
        payload = f"{log.old_values or ''} {log.new_values or ''}"
        assert "password_hash" not in payload
        assert "new-secret-hash" not in payload


def test_audit_log_tracks_critical_supporting_models(app):
    assert {
        "ActionClosureFile",
        "ActionComment",
        "ActionHistory",
        "AppSetting",
        "DocumentRevisionRequestFile",
        "DofComment",
        "DofFile",
        "LoginAttempt",
        "SuggestionScore",
    }.issubset(TRACKED_MODEL_NAMES)
    assert "Notification" not in TRACKED_MODEL_NAMES


def test_manual_audit_event_records_request_context(app):
    user = create_user("audit-event-user", "roles.manage")

    with app.test_request_context(
        "/download",
        headers={"User-Agent": "pytest-agent", "X-Forwarded-For": "10.0.0.1"},
    ):
        from flask import g

        g.current_user = user
        g.current_company = None
        record_audit_event(
            "Document",
            "downloaded",
            "PR.01 dokumani indirildi",
            entity_id=7,
            details={"file_name": "dokuman.pdf", "downloaded_at": date(2026, 9, 3)},
        )

    log = AuditLog.query.filter_by(
        entity_type="Document",
        entity_id="7",
        action="downloaded",
    ).one()
    assert log.user_id == user.id
    assert log.ip_address == "10.0.0.1"
    assert log.user_agent == "pytest-agent"
    assert json.loads(log.new_values)["downloaded_at"] == "2026-09-03"


def test_document_download_writes_audit_log(app, client):
    company = helper_create_company("371")
    user = helper_create_user(
        "document-audit-user",
        company=company,
        permissions=("documents.view",),
    )
    document = make_document(app, company, uploader=user, document_code="PR.77")
    login(client, user)
    with client.session_transaction() as session:
        session["company_id"] = company.id

    response = client.get(f"/documents/{document.id}/download")

    assert response.status_code == 200
    log = AuditLog.query.filter_by(
        entity_type="Document",
        entity_id=str(document.id),
        action="downloaded",
    ).one()
    assert "PR.77" in log.summary
    assert json.loads(log.new_values)["document_code"] == "PR.77"


def test_audit_log_page_requires_management_permission(app, client):
    user = create_user("viewer")
    login(client, user)

    response = client.get("/denetim-logu")

    assert response.status_code == 403


def test_audit_log_page_renders_for_manager(app, client):
    user = create_user("manager", "roles.manage")
    db.session.add(
        AuditLog(
            user_id=user.id,
            entity_type="Action",
            entity_id="1",
            action="updated",
            summary="Audit Deneme",
        )
    )
    db.session.commit()
    login(client, user)

    response = client.get("/denetim-logu")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Denetim Logu" in body
    assert "Audit Deneme" in body
    assert "Güncellendi" in body


def test_audit_log_hides_database_safety_entries_from_non_superadmin(app, client):
    user = create_user("manager", "roles.manage")
    db.session.add_all(
        [
            AuditLog(
                user_id=user.id,
                entity_type="Action",
                entity_id="1",
                action="updated",
                summary="Normal kayit",
            ),
            AuditLog(
                entity_type="DatabaseSafety",
                action="backup_created",
                summary="SQLite veritabani yedegi olusturuldu",
                new_values='{"backup_path": "/var/www/aksiyon-takip/instance/backups/actions.sqlite3"}',
            ),
        ]
    )
    db.session.commit()
    login(client, user)

    response = client.get("/denetim-logu")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Normal kayit" in body
    assert "DatabaseSafety" not in body
    assert "/var/www/aksiyon-takip" not in body


def test_audit_log_shows_database_safety_entries_to_superadmin_account(app, client):
    user = create_user("superadmin", "roles.manage")
    db.session.add(
        AuditLog(
            entity_type="DatabaseSafety",
            action="backup_created",
            summary="SQLite veritabani yedegi olusturuldu",
        )
    )
    db.session.commit()
    login(client, user)

    response = client.get("/denetim-logu")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "DatabaseSafety" in body
    assert "SQLite veritabani yedegi olusturuldu" in body


def test_runtime_schema_marks_sales_readiness_audit_log_done(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:audit_log")
    assert setting is not None
    assert setting.value == "1"

    month2_setting = db.session.get(AppSetting, "sales_readiness:month2_audit_log")
    assert month2_setting is not None
    assert month2_setting.value == "1"
