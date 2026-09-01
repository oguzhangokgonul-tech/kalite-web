from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.models import AppSetting, User, UserPermission
from app.routes import SALES_READINESS_SETTING_PREFIX


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


def test_sales_readiness_requires_superadmin_account(app, client):
    user = create_user("viewer")
    login(client, user)

    response = client.get("/satisa-hazirlik")

    assert response.status_code == 403


def test_sales_readiness_rejects_other_management_users(app, client):
    user = create_user("manager", "users.manage")
    login(client, user)

    response = client.get("/satisa-hazirlik")

    assert response.status_code == 403


def test_sales_readiness_page_renders_checklist(app, client):
    user = create_user("superadmin")
    login(client, user)

    response = client.get("/satisa-hazirlik")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Satışa Hazırlık" in body
    assert "ISO 9001 KYS Çekirdek" in body
    assert "audit_log" in body


def test_sales_readiness_sidebar_link_only_for_superadmin_account(app, client):
    manager = create_user("manager", "users.manage")
    login(client, manager)

    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/satisa-hazirlik"' not in response.get_data(as_text=True)

    superadmin = create_user("superadmin")
    login(client, superadmin)

    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/satisa-hazirlik"' in response.get_data(as_text=True)


def test_sales_readiness_persists_completed_items(app, client):
    user = create_user("superadmin")
    login(client, user)

    response = client.post(
        "/satisa-hazirlik",
        data={"completed_items": ["audit_log", "risk_module"]},
        follow_redirects=True,
    )

    assert response.status_code == 200
    settings = {
        setting.key: setting.value
        for setting in AppSetting.query.filter(
            AppSetting.key.like(f"{SALES_READINESS_SETTING_PREFIX}%")
        ).all()
    }
    assert settings[f"{SALES_READINESS_SETTING_PREFIX}audit_log"] == "1"
    assert settings[f"{SALES_READINESS_SETTING_PREFIX}risk_module"] == "1"
    assert f"{SALES_READINESS_SETTING_PREFIX}training_module" not in settings
    body = response.get_data(as_text=True)
    assert "2 / 45 madde" in body
