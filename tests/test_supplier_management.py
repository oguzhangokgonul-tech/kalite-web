from datetime import date, timedelta
from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.models import AppSetting, AuditLog, Company, SupplierEvaluation, SupplierRecord, User, UserPermission
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


def create_user(username, *permission_keys, company=None):
    user = User(
        username=username,
        full_name=username.title(),
        password_hash="not-used",
        company_id=company.id if company else None,
        is_active=True,
    )
    for permission_key in permission_keys:
        user.extra_permissions.append(UserPermission(permission_key=permission_key))
    db.session.add(user)
    db.session.commit()
    return user


def supplier_payload(**overrides):
    payload = {
        "name": "Kalite Metal Ltd.",
        "product_group": "Çelik bağlantı elemanları",
        "department": "Satın alma",
        "contact_person": "Ayşe Yılmaz",
        "phone": "0232 000 00 00",
        "email": "kalite@example.com",
        "next_evaluation_date": (date.today() + timedelta(days=180)).isoformat(),
        "status": "Değerlendirme Bekliyor",
    }
    payload.update(overrides)
    return payload


def evaluation_payload(**overrides):
    payload = {
        "evaluation_date": date.today().isoformat(),
        "next_evaluation_date": (date.today() + timedelta(days=365)).isoformat(),
        "quality_score": "10",
        "delivery_score": "10",
        "cost_score": "10",
        "communication_score": "10",
        "documentation_score": "10",
        "nonconformity_score": "10",
        "notes": "Yıllık değerlendirme sonucu uygundur.",
    }
    payload.update(overrides)
    return payload


def test_supplier_dashboard_requires_permission(app, client):
    user = create_user("viewer")
    login(client, user)

    response = client.get("/tedarikci-degerlendirme")

    assert response.status_code == 403


def test_supplier_create_evaluate_edit_and_deactivate_flow(app, client):
    user = create_user(
        "manager",
        "suppliers.view",
        "suppliers.evaluate",
        "suppliers.manage",
        "suppliers.delete",
    )
    login(client, user)

    form_response = client.get("/tedarikci-degerlendirme/yeni")
    assert form_response.status_code == 200
    assert "Yeni Tedarikçi" in form_response.get_data(as_text=True)

    response = client.post(
        "/tedarikci-degerlendirme/yeni",
        data=supplier_payload(),
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Kalite Metal Ltd." in body
    supplier = SupplierRecord.query.one()
    assert supplier.supplier_no.startswith("TED-")
    assert supplier.status == "Değerlendirme Bekliyor"
    assert supplier.is_active

    response = client.post(
        f"/tedarikci-degerlendirme/{supplier.id}/degerlendir",
        data=evaluation_payload(),
        follow_redirects=True,
    )

    assert response.status_code == 200
    supplier = db.session.get(SupplierRecord, supplier.id)
    evaluation = SupplierEvaluation.query.one()
    assert evaluation.total_score == 100
    assert evaluation.result_status == "Onaylı"
    assert supplier.last_score == 100
    assert supplier.status == "Onaylı"

    response = client.post(
        f"/tedarikci-degerlendirme/{supplier.id}/duzenle",
        data=supplier_payload(name="Kalite Metal A.Ş.", status="Onaylı"),
        follow_redirects=True,
    )

    assert response.status_code == 200
    supplier = db.session.get(SupplierRecord, supplier.id)
    assert supplier.name == "Kalite Metal A.Ş."

    response = client.post(
        f"/tedarikci-degerlendirme/{supplier.id}/pasife-al",
        follow_redirects=True,
    )

    assert response.status_code == 200
    supplier = db.session.get(SupplierRecord, supplier.id)
    assert not supplier.is_active
    assert supplier.status == "Pasif"
    assert AuditLog.query.filter_by(entity_type="SupplierRecord").count() >= 3
    assert AuditLog.query.filter_by(entity_type="SupplierEvaluation").count() == 1


def test_supplier_evaluation_score_thresholds(app, client):
    user = create_user("evaluator", "suppliers.view", "suppliers.evaluate")
    supplier = SupplierRecord(
        supplier_no="TED-2026-0001",
        name="Düşük Puanlı Tedarikçi",
        status="Değerlendirme Bekliyor",
        is_active=True,
    )
    db.session.add(supplier)
    db.session.commit()
    login(client, user)

    response = client.post(
        f"/tedarikci-degerlendirme/{supplier.id}/degerlendir",
        data=evaluation_payload(
            quality_score="5",
            delivery_score="5",
            cost_score="5",
            communication_score="5",
            documentation_score="5",
            nonconformity_score="5",
        ),
        follow_redirects=True,
    )

    assert response.status_code == 200
    supplier = db.session.get(SupplierRecord, supplier.id)
    assert supplier.last_score == 50
    assert supplier.status == "Askıda"


def test_supplier_list_is_scoped_to_current_company(app, client):
    company_a = Company(code="101", name="A Firması", slug="a-firmasi")
    company_b = Company(code="102", name="B Firması", slug="b-firmasi")
    db.session.add_all([company_a, company_b])
    db.session.commit()
    user = create_user("company_manager", "suppliers.view", company=company_a)
    db.session.add_all(
        [
            SupplierRecord(
                company_id=company_a.id,
                supplier_no="TED-2026-0001",
                name="A Firması Tedarikçisi",
                status="Onaylı",
                is_active=True,
            ),
            SupplierRecord(
                company_id=company_b.id,
                supplier_no="TED-2026-0001",
                name="B Firması Tedarikçisi",
                status="Onaylı",
                is_active=True,
            ),
        ]
    )
    db.session.commit()
    login(client, user)

    response = client.get("/tedarikci-degerlendirme")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "A Firması Tedarikçisi" in body
    assert "B Firması Tedarikçisi" not in body


def test_runtime_schema_marks_sales_readiness_supplier_done(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:supplier_module")
    assert setting is not None
    assert setting.value == "1"
    roadmap_setting = db.session.get(AppSetting, "sales_readiness:month3_supplier")
    assert roadmap_setting is not None
    assert roadmap_setting.value == "1"
