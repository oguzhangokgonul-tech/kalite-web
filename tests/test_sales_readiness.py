from html.parser import HTMLParser
from pathlib import Path
import json

import pytest

from app import create_app
from app.extensions import db
from app.models import AppSetting, AuditLog, Company, User, UserPermission
from app.routes import (
    SALES_READINESS_DEFERRED,
    SALES_READINESS_SECTIONS,
    SALES_READINESS_SETTING_PREFIX,
    sales_readiness_active_item_ids,
    sales_readiness_completed_ids,
    sales_readiness_context,
    sales_readiness_item_ids,
    save_sales_readiness_state,
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
    assert "Rakip Analizi - ISO 9001 / QDMS Modülleri" in body
    assert "Değişiklik yönetimi modülü" in body
    assert "Mobil uyumlu PWA / QR ile hızlı bildirim" in body
    assert "Yeni Modül Havuzu - Strateji, Toplantı ve Planlama" in body
    assert "Toplantı notları ve karar takip modülü" in body
    assert "Proje yönetimi / planlama modülü" in body
    assert "SWOT analizi modülü" in body
    assert "Riskler ve fırsatlar portföyü" in body
    assert "Yeni Modül Havuzu - Fabrika Operasyon ve Üretim" in body
    assert "Yeni Modül Havuzu - İleri Kalite Araçları" in body


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
    assert f"2 / {len(sales_readiness_active_item_ids())} madde" in body


def test_runtime_schema_marks_sales_readiness_tenant_tests_done(app):
    from app.seed import ensure_runtime_schema

    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:month4_tenant_tests")
    assert setting is not None
    assert setting.value == "1"


class ChecklistParser(HTMLParser):
    def __init__(self, body):
        super().__init__()
        self.form_id = None
        self.checkboxes = []
        self.categories = []
        self.links = []
        self.feed(body)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.form_id = attrs.get("id")
        elif tag == "input" and attrs.get("name") == "completed_items":
            self.checkboxes.append((self.form_id, attrs))
        elif tag == "details" and attrs.get("class") == "readiness-category":
            self.categories.append(attrs)
        elif tag == "a":
            self.links.append(attrs)

    def handle_endtag(self, tag):
        if tag == "form":
            self.form_id = None


def test_sales_readiness_catalog_and_deferred_metadata():
    assert set(SALES_READINESS_DEFERRED) == {
        "competitor_esignature", "competitor_sso_mfa",
    }
    catalog_ids = [
        item_id for section in SALES_READINESS_SECTIONS
        for item_id, _label in section["items"]
    ]
    assert len(catalog_ids) == len(set(catalog_ids)) == 142
    assert len(sales_readiness_active_item_ids()) == 140
    assert set(SALES_READINESS_DEFERRED) <= sales_readiness_item_ids()
    assert SALES_READINESS_DEFERRED["competitor_esignature"]["scope"] == "E-imza entegrasyonu"
    assert SALES_READINESS_DEFERRED["competitor_sso_mfa"]["scope"] == "SSO/MFA"
    for metadata in SALES_READINESS_DEFERRED.values():
        assert metadata["date"] == "2026-09-29"
        assert "Lider kararı" in metadata["reason"]
    assert "Mevcut elektronik onay korunur" in SALES_READINESS_DEFERRED["competitor_esignature"]["reason"]


@pytest.mark.parametrize("stored_value", [None, "0", "1", "legacy"])
@pytest.mark.parametrize("submit_deferred", [False, True])
def test_sales_readiness_post_preserves_deferred(app, client, stored_value, submit_deferred):
    login(client, create_user("superadmin"))
    if stored_value is not None:
        for item_id in SALES_READINESS_DEFERRED:
            db.session.add(AppSetting(key=f"{SALES_READINESS_SETTING_PREFIX}{item_id}", value=stored_value))
        db.session.commit()

    selected = list(SALES_READINESS_DEFERRED) if submit_deferred else []
    response = client.post("/satisa-hazirlik", data={"completed_items": selected})

    assert response.status_code == 302
    for item_id in SALES_READINESS_DEFERRED:
        setting = db.session.get(AppSetting, f"{SALES_READINESS_SETTING_PREFIX}{item_id}")
        if stored_value is None:
            assert setting is None
        else:
            assert setting is not None
            assert setting.value == stored_value
    assert not sales_readiness_completed_ids() & SALES_READINESS_DEFERRED.keys()


def test_sales_readiness_post_ignores_unknown_ids_and_preserves_settings(app, client):
    login(client, create_user("superadmin"))
    preserved = {
        f"{SALES_READINESS_SETTING_PREFIX}retired_item": "1",
        "unrelated_setting": "untouched",
    }
    for key, value in preserved.items():
        db.session.add(AppSetting(key=key, value=value))
    db.session.commit()

    response = client.post("/satisa-hazirlik", data={
        "completed_items": ["audit_log", "unknown_item", "retired_item", "unrelated_setting"],
    })

    assert response.status_code == 302
    assert db.session.get(AppSetting, f"{SALES_READINESS_SETTING_PREFIX}unknown_item") is None
    assert sales_readiness_completed_ids() == {"audit_log"}
    for key, value in preserved.items():
        assert db.session.get(AppSetting, key).value == value


def test_sales_readiness_post_writes_explicit_zero_without_bulk_creation(app, client):
    from app.seed import ensure_runtime_schema

    login(client, create_user("superadmin"))
    client.get("/satisa-hazirlik")
    db.session.add(AppSetting(key=f"{SALES_READINESS_SETTING_PREFIX}audit_log", value="1"))
    db.session.add(AppSetting(key=f"{SALES_READINESS_SETTING_PREFIX}risk_module", value="0"))
    db.session.commit()
    keys_before = {setting.key for setting in AppSetting.query.all()}

    response = client.post("/satisa-hazirlik", data={})

    assert response.status_code == 302
    assert {setting.key for setting in AppSetting.query.all()} == keys_before
    for item_id in ("audit_log", "risk_module"):
        assert db.session.get(AppSetting, f"{SALES_READINESS_SETTING_PREFIX}{item_id}").value == "0"
    assert db.session.get(AppSetting, f"{SALES_READINESS_SETTING_PREFIX}competitor_ai_assistants") is None

    ensure_runtime_schema()

    for item_id in ("audit_log", "risk_module"):
        assert db.session.get(AppSetting, f"{SALES_READINESS_SETTING_PREFIX}{item_id}").value == "0"
        assert item_id not in sales_readiness_completed_ids()


@pytest.mark.parametrize("completed_count", [0, 2, 140])
def test_sales_readiness_active_counters_exclude_deferred(app, completed_count):
    active_ids = sales_readiness_active_item_ids()
    selected = set(sorted(active_ids)[:completed_count])
    save_sales_readiness_state(selected)
    for item_id in SALES_READINESS_DEFERRED:
        db.session.add(AppSetting(key=f"{SALES_READINESS_SETTING_PREFIX}{item_id}", value="1"))
    db.session.commit()

    context = sales_readiness_context()

    assert context["total_count"] == len(active_ids)
    assert context["catalog_total_count"] == len(sales_readiness_item_ids())
    assert context["deferred_count"] == 2
    assert context["completed_count"] == completed_count
    assert context["remaining_count"] == len(active_ids) - completed_count
    assert context["progress"] == round(completed_count / len(active_ids) * 100)
    assert sum(section["total_count"] for section in context["sections"]) == len(active_ids)
    assert sum(section["completed_count"] for section in context["sections"]) == completed_count
    assert all("is_done" not in item for item in context["deferred_items"])
    for section in context["sections"]:
        assert section["remaining_count"] == section["total_count"] - section["completed_count"]
        assert section["progress"] == round(section["completed_count"] / section["total_count"] * 100)
    if completed_count == len(active_ids):
        assert context["next_item"] is None
    else:
        expected_next = next(
            item_id for section in SALES_READINESS_SECTIONS
            for item_id, _label in section["items"]
            if item_id in active_ids - selected
        )
        assert context["next_item"]["id"] == expected_next


def test_sales_readiness_live_scenario_next_is_ai_without_marking_done(app, client):
    from app.seed import ensure_runtime_schema

    login(client, create_user("superadmin"))
    ensure_runtime_schema()
    # The live integration slice is complete; the local AI slice is not.
    save_sales_readiness_state(sales_readiness_completed_ids() | {"competitor_api_webhooks"})
    context = sales_readiness_context()
    assert context["completed_count"] == 67
    assert context["next_item"]["id"] == "competitor_ai_assistants"
    assert "competitor_ai_assistants" not in sales_readiness_completed_ids()

    response = client.get("/satisa-hazirlik")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    parsed = ChecklistParser(body)
    assert len(parsed.checkboxes) == len(sales_readiness_active_item_ids())
    assert {attrs["value"] for _form, attrs in parsed.checkboxes} == sales_readiness_active_item_ids()
    assert all(form == "sales-readiness-form" for form, _attrs in parsed.checkboxes)
    assert all(attrs["type"] == "checkbox" and "disabled" not in attrs for _form, attrs in parsed.checkboxes)
    checked_ids = {attrs["value"] for _form, attrs in parsed.checkboxes if "checked" in attrs}
    assert checked_ids == sales_readiness_completed_ids()
    assert len(parsed.categories) == len(SALES_READINESS_SECTIONS)
    assert sum("open" in category for category in parsed.categories) == 1
    assert any(link.get("href") == "#readiness-competitor_ai_assistants" for link in parsed.links)
    assert "67 / 140 madde" in body
    assert "2026-09-29" in body
    assert "Mevcut elektronik onay korunur" in body
    assert "E-imza entegrasyonu" in body and "SSO/MFA" in body

    response = client.post("/satisa-hazirlik", data={"completed_items": list(checked_ids)})
    assert response.status_code == 302
    assert sales_readiness_completed_ids() == checked_ids
    assert db.session.get(AppSetting, f"{SALES_READINESS_SETTING_PREFIX}competitor_ai_assistants") is None


def test_sales_readiness_all_active_done_has_no_next_link(app, client):
    login(client, create_user("superadmin"))
    save_sales_readiness_state(sales_readiness_active_item_ids())

    response = client.get("/satisa-hazirlik")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Aktif maddeler tamamlandı." in body
    assert 'id="readiness-next-link"' not in body
    assert "Ertelenenler" in body
    parsed = ChecklistParser(body)
    assert len(parsed.checkboxes) == len(sales_readiness_active_item_ids())
    assert all("checked" in attrs for _form, attrs in parsed.checkboxes)
    assert all("open" not in category for category in parsed.categories)


@pytest.mark.parametrize("username,permission", [("viewer", None), ("manager", "users.manage")])
def test_sales_readiness_unauthorized_post_does_not_change_settings(app, client, username, permission):
    login(client, create_user(username, permission))
    client.get("/")
    before = {s.key: s.value for s in AppSetting.query.all()}
    assert client.post("/satisa-hazirlik", data={"completed_items": ["audit_log"]}).status_code == 403
    assert {s.key: s.value for s in AppSetting.query.all()} == before


def test_tenant_account_named_superadmin_cannot_manage_checklist(app, client):
    company = Company(code="101", name="Firma", slug="firma")
    db.session.add(company)
    db.session.commit()
    user = create_user("superadmin")
    user.company_id = company.id
    db.session.commit()
    login(client, user)
    assert client.get("/satisa-hazirlik").status_code == 403
    assert client.post("/satisa-hazirlik", data={"completed_items": ["audit_log"]}).status_code == 403


def test_sales_readiness_csrf_and_audit(app, client):
    import re
    app.config["WTF_CSRF_ENABLED"] = True
    user = create_user("superadmin")
    login(client, user)
    response = client.get("/satisa-hazirlik")
    token = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True)).group(1)
    before = {s.key: s.value for s in AppSetting.query.all()}
    for bad_token in (None, "invalid"):
        data = {"completed_items": ["audit_log"]}
        if bad_token:
            data["csrf_token"] = bad_token
        response = client.post("/satisa-hazirlik", data=data, headers={"Accept": "application/json"})
        assert response.status_code == 400
        assert {s.key: s.value for s in AppSetting.query.all()} == before
    response = client.post("/satisa-hazirlik", data={"csrf_token": token, "completed_items": ["audit_log"]})
    assert response.status_code == 302
    assert db.session.get(AppSetting, "sales_readiness:audit_log").value == "1"
    audit = AuditLog.query.filter_by(
        entity_type="AppSetting", entity_id="sales_readiness:audit_log", user_id=user.id,
        action="created",
    ).one()
    assert json.loads(audit.new_values)["value"] == "1"
