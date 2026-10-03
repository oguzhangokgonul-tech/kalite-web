import json
from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.models import AppSetting, Company, CompanyModule, User, UserPermission
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
        PREFERRED_URL_SCHEME = "https"
        SITE_NAME = "VolkaPortal"
        ASSET_VERSION = "pwa-test"
        MAIL_ENABLED = False

    test_app = create_app(TestConfig)
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def create_company(code, name, slug, color=None):
    company = Company(
        code=code,
        name=name,
        slug=slug,
        primary_domain=f"{slug}.volkaportal.com",
        brand_primary_color=color,
        is_active=True,
    )
    db.session.add(company)
    db.session.commit()
    return company


def create_user(company, *permissions):
    user = User(
        username=f"user-{company.code.lower()}",
        full_name="Mobil Kullanıcı",
        password_hash="not-used",
        company_id=company.id,
        is_active=True,
    )
    user.extra_permissions.extend(
        UserPermission(permission_key=permission) for permission in permissions
    )
    db.session.add(user)
    db.session.commit()
    return user


def login(client, user, base_url="http://localhost"):
    with client.session_transaction(base_url=base_url) as session:
        session["user_id"] = user.id


def test_manifest_is_tenant_specific_and_uses_relative_urls(app, client):
    company_a = create_company("PA1", "Er Prefabrik", "erprefabrik", "#1248aa")
    company_b = create_company("PB2", "Sağıroğlu Çelik", "sagiroglucelik", "#087a52")

    response_a = client.get(
        "/manifest.webmanifest", base_url=f"https://{company_a.primary_domain}"
    )
    response_b = client.get(
        "/manifest.webmanifest", base_url=f"https://{company_b.primary_domain}"
    )
    manifest_a = json.loads(response_a.get_data(as_text=True))
    manifest_b = json.loads(response_b.get_data(as_text=True))

    assert response_a.status_code == response_b.status_code == 200
    assert response_a.mimetype == "application/manifest+json"
    assert manifest_a["name"] == "Er Prefabrik | VolkaPortal"
    assert manifest_b["name"] == "Sağıroğlu Çelik | VolkaPortal"
    assert manifest_a["theme_color"] == "#1248aa"
    assert manifest_b["theme_color"] == "#087a52"
    assert manifest_a["start_url"] == "/mobil"
    assert manifest_a["scope"] == "/"
    assert {icon["sizes"] for icon in manifest_a["icons"]} == {"192x192", "512x512"}
    assert all(item["url"].startswith("/") for item in manifest_a["shortcuts"])


def test_service_worker_only_caches_allowlisted_shell_assets(client):
    response = client.get("/service-worker.js")
    script = response.get_data(as_text=True)

    assert response.status_code == 200
    assert response.headers["Service-Worker-Allowed"] == "/"
    assert "no-store" in response.headers["Cache-Control"]
    assert "request.method !== 'GET'" in script
    assert "request.mode === 'navigate'" in script
    assert "fetch(request).catch(() => caches.match(OFFLINE_URL))" in script
    assert "ALLOWED_PATHS.has(url.pathname)" in script
    assert "cache.put" not in script
    assert "/api" not in script
    assert "/uploads" not in script
    assert "/rapor-merkezi" not in script


def test_mobile_hub_and_qr_require_login(client):
    assert client.get("/mobil").status_code == 302
    assert client.get("/mobil/qr.svg").status_code == 302


def test_qr_uses_registered_tenant_domain_not_request_host(app, client):
    company = create_company("PQR", "Güvenli Firma", "guvenli-firma")
    user = create_user(company)
    hostile_url = "https://attacker.example"
    login(client, user, base_url=hostile_url)

    response = client.get("/mobil/qr.svg", base_url=hostile_url)

    assert response.status_code == 200
    assert response.mimetype == "image/svg+xml"
    assert response.headers["X-QR-Target"] == "https://guvenli-firma.volkaportal.com/mobil"
    assert "attacker.example" not in response.headers["X-QR-Target"]
    assert b"<svg" in response.data


def test_mobile_hub_lists_only_authorized_and_enabled_actions(app, client):
    company = create_company("PAC", "Mobil Firma", "mobil-firma")
    user = create_user(
        company,
        "actions.create",
        "complaints.manage",
        "helpdesk.create",
    )
    login(client, user, base_url=f"https://{company.primary_domain}")

    response = client.get("/mobil", base_url=f"https://{company.primary_domain}")
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Yeni Aksiyon" in page
    assert "Yeni İF / DÖF" in page
    assert "Yeni Öneri" in page
    assert "Yeni Şikayet" in page
    assert "Yeni İç Talep" in page
    assert 'href="/bakim/ariza/yeni"' in page
    assert "Bakım İşlemleri" in page
    assert client.get("/bakim/ariza/yeni", base_url=f"https://{company.primary_domain}").status_code == 200
    assert client.get("/bakim", base_url=f"https://{company.primary_domain}").status_code == 200

    db.session.add_all(
        [
            CompanyModule(company_id=company.id, module_key="suggestions", is_enabled=False),
            CompanyModule(company_id=company.id, module_key="help_desk", is_enabled=False),
            CompanyModule(company_id=company.id, module_key="maintenance", is_enabled=False),
        ]
    )
    db.session.commit()
    response = client.get("/mobil", base_url=f"https://{company.primary_domain}")
    page = response.get_data(as_text=True)
    assert "Yeni Aksiyon" in page
    assert "Yeni İF / DÖF" in page
    assert "Yeni Öneri" not in page
    assert "Yeni Şikayet" not in page
    assert "Yeni İç Talep" not in page
    assert 'href="/bakim/ariza/yeni"' not in page
    assert "Bakım İşlemleri" not in page
    assert client.get("/bakim/ariza/yeni", base_url=f"https://{company.primary_domain}").status_code == 403
    assert client.get("/bakim", base_url=f"https://{company.primary_domain}").status_code == 403


def test_runtime_schema_marks_mobile_pwa_checklist_done(app):
    AppSetting.query.filter_by(key="sales_readiness:competitor_mobile_pwa").delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:competitor_mobile_pwa")
    assert setting is not None
    assert setting.value == "1"


def test_default_employee_roles_can_create_helpdesk_requests(app, client):
    company = create_company("PHR", "Rol Firması", "rol-firmasi")
    roles = ensure_default_roles()
    db.session.commit()

    for index, role_key in enumerate(
        ("management_representative", "management", "department_manager", "department_staff"),
        start=1,
    ):
        user = User(
            username=f"pwa-role-{index}",
            full_name=role_key,
            password_hash="not-used",
            company_id=company.id,
            is_active=True,
        )
        user.roles.append(roles[role_key])
        db.session.add(user)
        db.session.commit()
        login(client, user, base_url=f"https://{company.primary_domain}")

        hub = client.get("/mobil", base_url=f"https://{company.primary_domain}")
        create_page = client.get(
            "/ic-talepler/yeni", base_url=f"https://{company.primary_domain}"
        )
        assert hub.status_code == 200
        assert "Yeni İç Talep" in hub.get_data(as_text=True)
        assert create_page.status_code == 200

    viewer = User(
        username="pwa-viewer",
        full_name="Sadece Görüntüleyici",
        password_hash="not-used",
        company_id=company.id,
        is_active=True,
    )
    viewer.roles.append(roles["viewer"])
    db.session.add(viewer)
    db.session.commit()
    login(client, viewer, base_url=f"https://{company.primary_domain}")

    hub = client.get("/mobil", base_url=f"https://{company.primary_domain}")
    create_page = client.get(
        "/ic-talepler/yeni", base_url=f"https://{company.primary_domain}"
    )
    assert hub.status_code == 200
    assert "Yeni İç Talep" not in hub.get_data(as_text=True)
    assert create_page.status_code == 403
