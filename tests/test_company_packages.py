from pathlib import Path

import pytest

from app import create_app
from app.company_packages import (
    ISO_CORE_MODULE_KEYS,
    PRODUCTION_MODULE_KEYS,
    PRODUCTION_PLUS_MODULE_KEYS,
)
from app.extensions import db
from app.models import AppSetting, Company, CompanyModule, Role, User
from app.routes import SALES_READINESS_SETTING_PREFIX
from app.seed import ensure_default_roles, ensure_runtime_schema


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
        user.roles.append(Role.query.filter_by(key=role_key).one())
    db.session.add(user)
    db.session.commit()
    return user


def company_payload(code, package_key, module_keys, is_demo=False):
    data = {
        "code": code,
        "name": f"Firma {code}",
        "slug": f"firma-{code}",
        "primary_domain": "",
        "custom_domain": "",
        "package_key": package_key,
        "is_active": "on",
        "enabled_modules": list(module_keys),
    }
    if is_demo:
        data["is_demo"] = "on"
    return data


def module_state(company):
    return {
        item.module_key: item.is_enabled
        for item in CompanyModule.query.filter_by(company_id=company.id).all()
    }


def test_iso_core_package_disables_production_modules_and_marks_demo(app, client):
    superadmin = create_user("superadmin", "super_admin")
    login(client, superadmin)

    response = client.post(
        "/companies/new",
        data=company_payload(
            "210",
            "iso_core",
            ISO_CORE_MODULE_KEYS,
            is_demo=True,
        ),
    )

    assert response.status_code == 302
    company = Company.query.filter_by(code="210").one()
    assert company.package_key == "iso_core"
    assert company.is_demo is True
    state = module_state(company)
    assert state["documents"] is True
    assert state["suggestions"] is True
    assert all(state[key] is False for key in PRODUCTION_MODULE_KEYS)


def test_production_plus_package_enables_production_modules(app, client):
    superadmin = create_user("superadmin", "super_admin")
    login(client, superadmin)

    response = client.post(
        "/companies/new",
        data=company_payload("211", "production_plus", PRODUCTION_PLUS_MODULE_KEYS),
    )

    assert response.status_code == 302
    company = Company.query.filter_by(code="211").one()
    assert company.package_key == "production_plus"
    state = module_state(company)
    assert state["maintenance"] is True
    assert state["vehicles"] is True
    assert state["quality_tests"] is True
    assert state["quality_test_concrete"] is True


def test_manual_module_change_marks_company_as_custom_package(app, client):
    superadmin = create_user("superadmin", "super_admin")
    login(client, superadmin)

    response = client.post(
        "/companies/new",
        data=company_payload("212", "iso_core", {"documents", "if_management"}),
    )

    assert response.status_code == 302
    company = Company.query.filter_by(code="212").one()
    assert company.package_key == "custom"


def test_disabled_package_modules_hide_menu_and_block_direct_urls(app, client):
    company = Company(
        code="213",
        name="Cekirdek Firma",
        slug="cekirdek-firma",
        package_key="iso_core",
        is_active=True,
    )
    db.session.add(company)
    db.session.flush()
    for module_key in PRODUCTION_PLUS_MODULE_KEYS:
        db.session.add(
            CompanyModule(
                company_id=company.id,
                module_key=module_key,
                is_enabled=module_key in ISO_CORE_MODULE_KEYS,
            )
        )
    user = create_user("cekirdek-user", company=company)
    login(client, user)

    dashboard = client.get("/")

    assert dashboard.status_code == 200
    body = dashboard.get_data(as_text=True)
    assert 'href="/bakim"' not in body
    assert 'href="/arac-yonetimi"' not in body
    assert 'href="/kalite-deneyleri/beton-deneyi"' not in body
    assert client.get("/bakim").status_code == 403
    assert client.get("/arac-yonetimi").status_code == 403
    assert client.get("/kalite-deneyleri/beton-deneyi").status_code == 403


def test_runtime_schema_marks_packaging_readiness_items_done(app):
    ensure_runtime_schema()

    completed = {
        setting.key
        for setting in AppSetting.query.filter(
            AppSetting.key.like(f"{SALES_READINESS_SETTING_PREFIX}%"),
            AppSetting.value == "1",
        ).all()
    }
    assert f"{SALES_READINESS_SETTING_PREFIX}core_package" in completed
    assert f"{SALES_READINESS_SETTING_PREFIX}optional_production_modules" in completed
    assert f"{SALES_READINESS_SETTING_PREFIX}suggestion_core" in completed
    assert f"{SALES_READINESS_SETTING_PREFIX}module_based_menu" in completed
    assert f"{SALES_READINESS_SETTING_PREFIX}demo_data_split" in completed
