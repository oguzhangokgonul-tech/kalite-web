import json

from sqlalchemy import inspect, text

from app.extensions import db
from app.models import AppSetting, AuditLog, Company, User
from app.seed import ensure_runtime_schema

from .helpers import create_company, create_user


def tenant_url(company):
    return f"https://{company.slug}.volkaportal.com"


def login_for_tenant(client, user, company):
    with client.session_transaction(base_url=tenant_url(company)) as session:
        session["user_id"] = user.id
        session["company_id"] = company.id


def test_company_default_locale_controls_anonymous_login_and_manifest(app, client):
    company = create_company("701", name="English Company")
    company.default_locale = "en"
    db.session.commit()

    login_page = client.get("/login", base_url=tenant_url(company)).get_data(as_text=True)
    manifest = json.loads(
        client.get("/manifest.webmanifest", base_url=tenant_url(company)).get_data(as_text=True)
    )

    assert '<html lang="en">' in login_page
    assert "Username" in login_page
    assert "Remember me" in login_page
    assert manifest["lang"] == "en"
    assert manifest["description"] == "Quality and corporate process management mobile hub"
    assert manifest["shortcuts"][1]["name"] == "My Tasks"


def test_anonymous_locale_choice_is_tenant_scoped(app, client):
    company_a = create_company("702", name="Türkçe Firma")
    company_b = create_company("703", name="Diğer Firma")

    response = client.post(
        "/dil",
        data={"locale": "en", "next": "/login"},
        base_url=tenant_url(company_a),
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")

    page_a = client.get("/login", base_url=tenant_url(company_a)).get_data(as_text=True)
    page_b = client.get("/login", base_url=tenant_url(company_b)).get_data(as_text=True)
    assert '<html lang="en">' in page_a
    assert '<html lang="tr">' in page_b


def test_login_language_choice_becomes_user_preference(app, client):
    app.config.update(
        LOGIN_MAX_FAILED_ATTEMPTS=5,
        LOGIN_IP_MAX_FAILED_ATTEMPTS=20,
        LOGIN_LOCKOUT_MINUTES=10,
        REMEMBER_ME_DAYS=30,
        LEGAL_ACCEPTANCE_REQUIRED=False,
    )
    company = create_company("708", name="Türkçe Firma")
    user = create_user("login-locale-user", company=company)
    user.set_password("test-password")
    db.session.commit()

    client.post(
        "/dil",
        data={"locale": "en", "next": "/login"},
        base_url=tenant_url(company),
    )
    response = client.post(
        "/login",
        data={"identity": user.username, "password": "test-password"},
        base_url=tenant_url(company),
        follow_redirects=True,
    )

    db.session.refresh(user)
    assert response.status_code == 200
    assert user.preferred_locale == "en"
    assert '<html lang="en">' in response.get_data(as_text=True)
    assert AuditLog.query.filter_by(
        entity_type="LocalePreference",
        entity_id=str(user.id),
        action="updated",
    ).count() == 1


def test_user_locale_overrides_company_and_is_audited(app, client):
    company = create_company("704", name="Türkçe Firma")
    user = create_user("locale-user", company=company)
    login_for_tenant(client, user, company)

    response = client.post(
        "/dil",
        data={"locale": "en", "next": "/mobil"},
        base_url=tenant_url(company),
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Language preference updated." in response.get_data(as_text=True)
    db.session.refresh(user)
    assert user.preferred_locale == "en"
    audit = AuditLog.query.filter_by(
        entity_type="LocalePreference",
        entity_id=str(user.id),
        action="updated",
    ).one()
    assert audit.company_id == company.id
    assert '"preferred_locale": null' in audit.old_values
    assert '"effective_locale": "tr"' in audit.old_values
    assert '"preferred_locale": "en"' in audit.new_values

    client.post(
        "/dil",
        data={"locale": "en", "next": "/mobil"},
        base_url=tenant_url(company),
    )
    assert AuditLog.query.filter_by(
        entity_type="LocalePreference",
        entity_id=str(user.id),
        action="updated",
    ).count() == 1

    page = client.get("/mobil", base_url=tenant_url(company)).get_data(as_text=True)
    assert '<html lang="en">' in page
    assert "Mobile Hub" in page
    assert "Quick Actions" in page


def test_language_endpoint_rejects_invalid_locale_and_external_redirect(app, client):
    company = create_company("705")

    invalid = client.post(
        "/dil",
        data={"locale": "../../etc/passwd", "next": "/login"},
        base_url=tenant_url(company),
    )
    assert invalid.status_code == 400
    assert client.post(
        "/dil",
        data={"locale": "en-US", "next": "/login"},
        base_url=tenant_url(company),
    ).status_code == 400

    response = client.post(
        "/dil",
        data={"locale": "en", "next": "https://attacker.example/path"},
        base_url=tenant_url(company),
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    backslash_response = client.post(
        "/dil",
        data={"locale": "en", "next": "/\\attacker.example"},
        base_url=tenant_url(company),
    )
    assert backslash_response.headers["Location"] == "/"


def test_company_and_user_forms_store_validated_locale_preferences(app, client):
    company = create_company("706")
    superadmin = create_user("superadmin", role_key="super_admin")
    login_for_tenant(client, superadmin, company)

    company_response = client.post(
        f"/companies/{company.id}/edit",
        data={
            "code": company.code,
            "name": company.name,
            "slug": company.slug,
            "primary_domain": f"{company.slug}.volkaportal.com",
            "custom_domain": "",
            "default_locale": "en",
            "package_key": company.package_key,
            "brand_primary_color": "#1e5bff",
            "brand_accent_color": "#00bbaa",
            "user_limit": "25",
            "storage_quota_mb": "1024",
            "is_active": "on",
        },
        base_url=tenant_url(company),
    )
    assert company_response.status_code == 302
    db.session.refresh(company)
    assert company.default_locale == "en"

    manager = create_user("locale-manager", company=company, permissions=("users.manage",))
    login_for_tenant(client, manager, company)
    user_response = client.post(
        "/users/new",
        data={
            "full_name": "English User",
            "username": "english-user",
            "password": "1234",
            "preferred_locale": "en",
            "is_active": "on",
        },
        base_url=tenant_url(company),
    )
    assert user_response.status_code == 302
    assert User.query.filter_by(username="english-user", company_id=company.id).one().preferred_locale == "en"


def test_pwa_cache_is_separated_by_tenant_and_locale(app, client):
    company = create_company("707")
    company.default_locale = "en"
    db.session.commit()

    script = client.get(
        "/service-worker.js", base_url=tenant_url(company)
    ).get_data(as_text=True)
    assert f"volkaportal-shell-1-{company.id}-en" in script


def test_runtime_schema_adds_locale_columns_and_marks_checklist(app):
    AppSetting.query.filter_by(key="sales_readiness:competitor_multilanguage").delete()
    db.session.execute(text("UPDATE companies SET default_locale = 'tr'"))
    db.session.commit()

    ensure_runtime_schema()

    inspector = inspect(db.engine)
    assert "default_locale" in {column["name"] for column in inspector.get_columns("companies")}
    assert "preferred_locale" in {column["name"] for column in inspector.get_columns("users")}
    setting = db.session.get(AppSetting, "sales_readiness:competitor_multilanguage")
    assert setting is not None
    assert setting.value == "1"
