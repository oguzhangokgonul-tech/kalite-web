from datetime import date
from pathlib import Path
import json

import pytest

from app import create_app
from app.extensions import db
from app.models import Action, AppSetting, AuditLog, User, UserPermission
from app.seed import ensure_runtime_schema


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
