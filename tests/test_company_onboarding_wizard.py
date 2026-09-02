from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    AppSetting,
    AuditLog,
    Company,
    CompanyDepartment,
    CompanyModule,
    DocumentCategory,
    DOCUMENT_CATEGORY_DEFAULTS,
    PersonnelContact,
    Role,
    User,
)
from app.routes import SALES_READINESS_SETTING_PREFIX
from app.seed import ensure_default_roles


@pytest.fixture()
def app(tmp_path):
    class TestConfig:
        SECRET_KEY = "test"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = str(Path(tmp_path) / "uploads")
        TENANT_BASE_DOMAIN = "volkaportal.com"
        PASSWORD_MIN_LENGTH = 4

    test_app = create_app(TestConfig)
    with test_app.app_context():
        db.create_all()
        ensure_default_roles()
        db.session.commit()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, user):
    with client.session_transaction() as session:
        session["user_id"] = user.id


def create_user(username, role_key=None, company=None):
    user = User(
        company_id=company.id if company else None,
        username=username,
        full_name=username.title(),
        password_hash="not-used",
        is_active=True,
    )
    if role_key:
        role = Role.query.filter_by(key=role_key).one()
        user.roles.append(role)
    db.session.add(user)
    db.session.commit()
    return user


def onboarding_payload(**overrides):
    data = {
        "code": "222",
        "name": "Pilot Firma",
        "slug": "pilot-firma",
        "primary_domain": "",
        "custom_domain": "",
        "is_active": "on",
        "enabled_modules": [
            "organization",
            "calibration",
            "human_resources",
            "suggestions",
            "if_management",
            "risk_management",
            "training",
            "internal_audit",
            "management_review",
            "supplier_management",
            "report_center",
            "documents",
        ],
        "departments": ["Kalite", "Uretim"],
        "custom_departments": "Ar-Ge\nSatis",
        "initial_full_name": "Ayse Kalite",
        "initial_username": "ayse",
        "initial_title": "Yonetim Temsilcisi",
        "initial_email": "ayse@example.test",
        "initial_password": "1234",
        "initial_role_keys": ["management_representative"],
        "create_document_categories": "on",
    }
    data.update(overrides)
    return data


def test_company_onboarding_wizard_requires_super_admin(app, client):
    user = create_user("viewer")
    login(client, user)

    response = client.get("/kurulum-sihirbazi")

    assert response.status_code == 403


def test_company_onboarding_wizard_renders_for_super_admin(app, client):
    user = create_user("superadmin", "super_admin")
    login(client, user)

    response = client.get("/kurulum-sihirbazi")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Kurulum Sihirbaz" in body
    assert "KYS" in body
    assert 'name="initial_full_name"' in body


def test_company_onboarding_wizard_creates_complete_company_workspace(app, client):
    user = create_user("superadmin", "super_admin")
    login(client, user)

    response = client.post("/kurulum-sihirbazi", data=onboarding_payload())

    assert response.status_code == 302
    company = Company.query.filter_by(code="222").one()
    assert response.headers["Location"].endswith(f"/companies/{company.id}/onboarding")
    status_response = client.get(f"/companies/{company.id}/onboarding")
    assert status_response.status_code == 200
    assert "Firma Kurulum" in status_response.get_data(as_text=True)
    assert company.slug == "pilot-firma"
    assert company.primary_domain == "pilot-firma.volkaportal.com"
    assert company.is_active

    modules = {
        module.module_key: module.is_enabled
        for module in CompanyModule.query.filter_by(company_id=company.id).all()
    }
    assert modules["documents"] is True
    assert modules["if_management"] is True
    assert modules["maintenance"] is False
    assert modules["quality_tests"] is False

    department_names = {
        item.name
        for item in CompanyDepartment.query.filter_by(
            company_id=company.id,
            is_active=True,
        ).all()
    }
    assert {"Kalite", "Uretim", "Ar-Ge", "Satis"}.issubset(department_names)
    assert DocumentCategory.query.filter_by(company_id=company.id).count() == len(
        DOCUMENT_CATEGORY_DEFAULTS
    )

    initial_user = User.query.filter_by(company_id=company.id, username="ayse").one()
    assert initial_user.full_name == "Ayse Kalite"
    assert initial_user.has_role("management_representative")
    assert initial_user.can_manage_users is True
    contact = PersonnelContact.query.filter_by(company_id=company.id).one()
    assert contact.full_name == "Ayse Kalite"
    assert contact.title == "Yonetim Temsilcisi"

    assert AppSetting.query.get(f"company:{company.id}:next_action_number").value == "1"
    assert (
        AppSetting.query.get(f"{SALES_READINESS_SETTING_PREFIX}onboarding_wizard").value
        == "1"
    )
    assert (
        AuditLog.query.filter_by(
            company_id=company.id,
            entity_type="CompanyOnboarding",
            action="completed",
        ).count()
        == 1
    )


def test_company_onboarding_repair_is_idempotent(app, client):
    user = create_user("superadmin", "super_admin")
    company = Company(code="333", name="Eksik Firma", slug="eksik-firma")
    db.session.add(company)
    db.session.commit()
    login(client, user)

    first = client.post(f"/companies/{company.id}/onboarding/repair")
    second = client.post(f"/companies/{company.id}/onboarding/repair")

    assert first.status_code == 302
    assert second.status_code == 302
    assert CompanyDepartment.query.filter_by(company_id=company.id).count() > 0
    assert DocumentCategory.query.filter_by(company_id=company.id).count() == len(
        DOCUMENT_CATEGORY_DEFAULTS
    )
    distinct_department_names = {
        item.name
        for item in CompanyDepartment.query.filter_by(company_id=company.id).all()
    }
    assert CompanyDepartment.query.filter_by(company_id=company.id).count() == len(
        distinct_department_names
    )
    assert (
        AuditLog.query.filter_by(
            company_id=company.id,
            entity_type="CompanyOnboarding",
            action="repaired",
        ).count()
        == 2
    )
