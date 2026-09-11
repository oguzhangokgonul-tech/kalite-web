from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    AppSetting,
    AuditLog,
    COMPANY_MODULE_KEYS,
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
        "package_key": "iso_core",
        "is_active": "on",
        "enabled_modules": [
            "iso_executive_summary",
            "management_due_dashboard",
            "organization",
            "calibration",
            "human_resources",
            "suggestions",
            "if_management",
            "risk_management",
            "fmea_management",
            "process_management",
            "quality_objectives",
            "change_management",
            "deviation_management",
            "incident_near_miss",
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


def test_company_onboarding_wizard_rejects_non_account_super_admin(app, client):
    user = create_user("role-super-admin", "super_admin")
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
    assert company.package_key == "iso_core"
    assert company.is_demo is False

    modules = {
        module.module_key: module.is_enabled
        for module in CompanyModule.query.filter_by(company_id=company.id).all()
    }
    assert modules["documents"] is True
    assert modules["iso_executive_summary"] is True
    assert modules["management_due_dashboard"] is True
    assert modules["if_management"] is True
    assert modules["fmea_management"] is True
    assert modules["process_management"] is True
    assert modules["quality_objectives"] is True
    assert modules["change_management"] is True
    assert modules["deviation_management"] is True
    assert modules["incident_near_miss"] is True
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


def company_edit_payload(company, **overrides):
    data = {
        "code": company.code,
        "name": company.name,
        "slug": company.slug,
        "primary_domain": "",
        "custom_domain": "",
        "package_key": "production_plus",
        "is_active": "on",
        "enabled_modules": list(COMPANY_MODULE_KEYS),
        "departments": ["Kalite"],
        "custom_departments": "Ar-Ge\nLojistik",
    }
    data.update(overrides)
    return data


def test_company_edit_manages_departments_per_company_without_deleting_history(app, client):
    superadmin = create_user("superadmin", "super_admin")
    company_a = Company(code="334", name="A Firma", slug="a-firma", is_active=True)
    company_b = Company(code="335", name="B Firma", slug="b-firma", is_active=True)
    db.session.add_all([company_a, company_b])
    db.session.flush()
    production = CompanyDepartment(
        company_id=company_a.id,
        name="Üretim",
        sort_order=1,
        is_active=True,
    )
    db.session.add_all(
        [
            production,
            CompanyDepartment(
                company_id=company_a.id,
                name="Kalite",
                sort_order=2,
                is_active=True,
            ),
            CompanyDepartment(
                company_id=company_a.id,
                name="Ar-Ge",
                sort_order=3,
                is_active=True,
            ),
            CompanyDepartment(
                company_id=company_b.id,
                name="Yalnız B Departmanı",
                sort_order=1,
                is_active=True,
            ),
        ]
    )
    db.session.commit()
    production_id = production.id
    login(client, superadmin)

    form_response = client.get(f"/companies/{company_a.id}/edit")

    assert form_response.status_code == 200
    body = form_response.get_data(as_text=True)
    assert "3. Departmanlar" in body
    assert "Ar-Ge" in body
    assert "Yalnız B Departmanı" not in body

    update_response = client.post(
        f"/companies/{company_a.id}/edit",
        data=company_edit_payload(company_a),
    )

    assert update_response.status_code == 302
    active_a = {
        item.name
        for item in CompanyDepartment.query.filter_by(
            company_id=company_a.id,
            is_active=True,
        ).all()
    }
    assert active_a == {"Kalite", "Ar-Ge", "Lojistik"}
    assert db.session.get(CompanyDepartment, production_id).is_active is False
    assert {
        item.name
        for item in CompanyDepartment.query.filter_by(
            company_id=company_b.id,
            is_active=True,
        ).all()
    } == {"Yalnız B Departmanı"}

    with client.session_transaction() as session:
        session["company_id"] = company_a.id
    risk_form_response = client.get("/risk-yonetimi/yeni")
    assert risk_form_response.status_code == 200
    risk_form_body = risk_form_response.get_data(as_text=True)
    assert 'value="Lojistik"' in risk_form_body
    assert "Yalnız B Departmanı" not in risk_form_body

    reactivate_response = client.post(
        f"/companies/{company_a.id}/edit",
        data=company_edit_payload(
            company_a,
            departments=["Kalite", "Üretim"],
        ),
    )

    assert reactivate_response.status_code == 302
    assert db.session.get(CompanyDepartment, production_id).is_active is True
    assert CompanyDepartment.query.filter_by(
        company_id=company_a.id,
        name="Üretim",
    ).count() == 1
    assert AuditLog.query.filter_by(
        company_id=company_a.id,
        entity_type="CompanyDepartmentCatalogue",
        action="updated",
    ).count() == 2


def test_company_edit_requires_at_least_one_active_department(app, client):
    superadmin = create_user("superadmin", "super_admin")
    company = Company(code="336", name="Bos Firma", slug="bos-firma", is_active=True)
    db.session.add(company)
    db.session.flush()
    db.session.add(
        CompanyDepartment(
            company_id=company.id,
            name="Kalite",
            sort_order=1,
            is_active=True,
        )
    )
    db.session.commit()
    login(client, superadmin)

    response = client.post(
        f"/companies/{company.id}/edit",
        data=company_edit_payload(
            company,
            departments=[],
            custom_departments="",
        ),
    )

    assert response.status_code == 200
    assert "en az bir aktif departman" in response.get_data(as_text=True)
    assert CompanyDepartment.query.filter_by(
        company_id=company.id,
        name="Kalite",
        is_active=True,
    ).count() == 1


def test_company_department_management_rejects_non_super_admin(app, client):
    company = Company(code="337", name="Yetki Firma", slug="yetki-firma", is_active=True)
    db.session.add(company)
    db.session.commit()
    manager = create_user("company-manager", "management_representative", company)
    login(client, manager)

    response = client.get(f"/companies/{company.id}/edit")

    assert response.status_code == 403
