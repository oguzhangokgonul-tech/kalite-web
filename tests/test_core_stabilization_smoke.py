from app.extensions import db
from app.models import AppSetting, COMPANY_MODULE_KEYS
from app.seed import ensure_runtime_schema

from .helpers import assert_xlsx_response, create_company, create_user, login


def test_superadmin_core_pages_render_without_errors(client):
    company = create_company("301")
    superadmin = create_user("superadmin", role_key="super_admin")
    login(client, superadmin, company)

    urls = [
        "/",
        "/uzerime-atananlar",
        "/organization",
        "/dofs",
        "/ic-denetim",
        "/documents",
        "/documents/list",
        "/oneri-sikayet/oneri",
        "/oneri-sikayet/sikayet",
        "/kalibrasyon",
        "/insan-kaynaklari/personel-listesi",
        "/bakim",
        "/arac-yonetimi",
        "/kalite-deneyleri/beton-deneyi",
        "/risk-yonetimi",
        "/egitim-yeterlilik",
        "/yonetimin-gozden-gecirmesi",
        "/tedarikci-degerlendirme",
        "/rapor-merkezi",
        "/users",
        "/roles",
        "/companies",
        "/kurulum-sihirbazi",
        "/satisa-hazirlik",
    ]

    for url in urls:
        response = client.get(url)
        assert response.status_code == 200, url


def test_plain_user_cannot_open_admin_or_create_pages(client):
    company = create_company("302")
    user = create_user("plain-user", company=company)
    login(client, user)

    forbidden_urls = [
        "/companies",
        "/kurulum-sihirbazi",
        "/roles",
        "/satisa-hazirlik",
        "/actions/new",
        "/users/new",
        "/documents/upload",
        "/ic-denetim/olustur",
        "/risk-yonetimi/yeni",
        "/egitim-yeterlilik/yeni",
        "/yonetimin-gozden-gecirmesi/yeni",
        "/tedarikci-degerlendirme/yeni",
        "/kalibrasyon/yeni",
        "/bakim/makine/yeni",
        "/arac-yonetimi/arac/yeni",
        "/kalite-deneyleri/beton-deneyi/yeni",
    ]

    for url in forbidden_urls:
        response = client.get(url)
        assert response.status_code == 403, url

    assert client.get("/bakim/ariza/yeni").status_code == 200


def test_report_center_exports_key_reports_as_xlsx(client):
    company = create_company("303")
    reporter = create_user(
        "reporter",
        company=company,
        permissions=("reports.view", "reports.export"),
    )
    login(client, reporter)

    for report_key in [
        "actions_overdue",
        "dofs_status",
        "documents_master",
        "calibration",
        "personnel_contacts",
    ]:
        assert_xlsx_response(client.get(f"/rapor-merkezi/{report_key}/excel"))


def test_runtime_schema_marks_month1_tests_done(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:month1_tests")
    assert setting is not None
    assert setting.value == "1"


def test_disabled_module_blocks_direct_route_even_with_permission(client):
    enabled_modules = set(COMPANY_MODULE_KEYS) - {"documents"}
    company = create_company("304", module_keys=enabled_modules, package_key="custom")
    user = create_user(
        "document-manager",
        company=company,
        permissions=("documents.view", "documents.manage"),
    )
    login(client, user)

    assert client.get("/documents").status_code == 403
    assert client.get("/documents/upload").status_code == 403
