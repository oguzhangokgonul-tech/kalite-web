from datetime import datetime, timedelta, timezone
import hashlib
import re

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    Action,
    AppSetting,
    AuditLog,
    Company,
    CompanyModule,
    ComplaintMessage,
    ComplaintRecord,
    CustomerPortalAttempt,
    CustomerPortalSetting,
    CustomerPortalToken,
    User,
    UserPermission,
)
from app.seed import ensure_default_roles, ensure_runtime_schema


@pytest.fixture()
def app(tmp_path):
    class TestConfig:
        TESTING = True
        SECRET_KEY = "portal-test-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = str(tmp_path / "uploads")
        TENANT_BASE_DOMAIN = "volkaportal.com"
        PREFERRED_URL_SCHEME = "https"
        MAIL_ENABLED = False

    test_app = create_app(TestConfig)
    with test_app.app_context():
        db.create_all()
        ensure_default_roles()
        company = Company(code="101", name="Portal Firma", slug="portal-firma", package_key="iso_core", is_active=True)
        other = Company(code="102", name="Diğer Firma", slug="diger-firma", package_key="iso_core", is_active=True)
        db.session.add_all([company, other])
        db.session.flush()
        db.session.add_all([
            CompanyModule(company_id=company.id, module_key="suggestions", is_enabled=True),
            CompanyModule(company_id=company.id, module_key="customer_feedback_portal", is_enabled=True),
            CompanyModule(company_id=company.id, module_key="management_due_dashboard", is_enabled=True),
            CompanyModule(company_id=other.id, module_key="suggestions", is_enabled=True),
            CompanyModule(company_id=other.id, module_key="customer_feedback_portal", is_enabled=True),
        ])
        db.session.commit()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def company(code="101"):
    return Company.query.filter_by(code=code).one()


def public_form_data(**overrides):
    data = {
        "record_type": "Şikayet",
        "customer_name": "Müşteri AŞ",
        "contact_name": "Ayşe Yılmaz",
        "contact_email": "ayse@example.test",
        "contact_phone": "0555 111 22 33",
        "customer_reference": "MUS-42",
        "product_reference": "SIP-2026-8 / PARTI-3",
        "subject": "Ürün yüzeyinde hata",
        "description": "Teslim edilen üründe yüzey hatası görüldü.",
        "consent": "on",
    }
    data.update(overrides)
    return data


def submit_and_extract_verification(client):
    response = client.post(
        "/musteri-portali",
        data=public_form_data(),
        headers={"Host": "portal-firma.volkaportal.com"},
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    match = re.search(r"/musteri-portali/dogrula/([^\"<]+)", body)
    assert match
    return match.group(1), ComplaintRecord.query.one()


def verify_and_extract_tracking(client, verification_token):
    response = client.get(
        f"/musteri-portali/dogrula/{verification_token}",
        headers={"Host": "portal-firma.volkaportal.com"},
    )
    assert response.status_code == 302
    match = re.search(r"/musteri-portali/takip/([^?]+)", response.headers["Location"])
    assert match
    return match.group(1)


def create_user(*permissions, role_key=None):
    target = company()
    user = User(company_id=target.id, username="portal-manager", full_name="Portal Yöneticisi", password_hash="x", is_active=True)
    user.extra_permissions.extend(UserPermission(permission_key=key) for key in permissions)
    if role_key:
        from app.models import Role
        user.roles.append(Role.query.filter_by(key=role_key).one())
    db.session.add(user)
    db.session.commit()
    return user


def login(client, user):
    with client.session_transaction(base_url="https://portal-firma.volkaportal.com") as session:
        session["user_id"] = user.id


def test_public_portal_requires_tenant_and_enabled_module(app, client):
    assert client.get("/musteri-portali", headers={"Host": "volkaportal.com"}).status_code == 404
    assert client.get("/musteri-portali", headers={"Host": "unknown.volkaportal.com"}).status_code == 404
    assert client.get("/musteri-portali", headers={"Host": "portal-firma.volkaportal.com"}).status_code == 200

    CompanyModule.query.filter_by(company_id=company().id, module_key="customer_feedback_portal").one().is_enabled = False
    db.session.commit()
    assert client.get("/musteri-portali", headers={"Host": "portal-firma.volkaportal.com"}).status_code == 404


def test_submit_verify_hash_and_tenant_isolation(app, client):
    verification_raw, record = submit_and_extract_verification(client)
    token = CustomerPortalToken.query.filter_by(purpose="verification").one()
    assert verification_raw not in token.token_hash
    assert token.token_hash == hashlib.sha256(verification_raw.encode()).hexdigest()
    assert record.email_verified_at is None
    assert record.status == "E-posta Doğrulaması Bekleniyor"
    assert CustomerPortalAttempt.query.one().ip_hash != "127.0.0.1"

    assert client.get(
        f"/musteri-portali/dogrula/{verification_raw}",
        headers={"Host": "diger-firma.volkaportal.com"},
    ).status_code == 404

    tracking_raw = verify_and_extract_tracking(client, verification_raw)
    db.session.refresh(record)
    assert record.email_verified_at is not None
    assert record.first_response_due_at is not None
    assert record.resolution_due_at > record.first_response_due_at
    assert client.get(
        f"/musteri-portali/dogrula/{verification_raw}",
        headers={"Host": "portal-firma.volkaportal.com"},
    ).status_code == 404
    assert client.get(
        f"/musteri-portali/takip/{tracking_raw}",
        headers={"Host": "diger-firma.volkaportal.com"},
    ).status_code == 404


def test_tracking_hides_internal_notes_and_rejects_expired_token(app, client):
    verification_raw, record = submit_and_extract_verification(client)
    tracking_raw = verify_and_extract_tracking(client, verification_raw)
    db.session.add(ComplaintMessage(company_id=record.company_id, complaint_id=record.id, sender_type="user", sender_name="Kalite", body="Gizli kök neden", visibility="internal"))
    db.session.commit()

    response = client.get(f"/musteri-portali/takip/{tracking_raw}", headers={"Host": "portal-firma.volkaportal.com"})
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Gizli kök neden" not in body

    token = CustomerPortalToken.query.filter_by(purpose="tracking", token_hash=hashlib.sha256(tracking_raw.encode()).hexdigest()).one()
    token.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    db.session.commit()
    assert client.get(f"/musteri-portali/takip/{tracking_raw}", headers={"Host": "portal-firma.volkaportal.com"}).status_code == 404


def test_honeypot_and_rate_limit(app, client):
    response = client.post("/musteri-portali", data=public_form_data(website="spam"), headers={"Host": "portal-firma.volkaportal.com"})
    assert response.status_code == 400
    setting = CustomerPortalSetting.query.filter_by(company_id=company().id).one()
    setting.submission_limit_hour = 1
    db.session.commit()
    submit_and_extract_verification(client)
    response = client.post("/musteri-portali", data=public_form_data(contact_email="ikinci@example.test"), headers={"Host": "portal-firma.volkaportal.com"})
    assert response.status_code == 429


def test_rate_limit_also_follows_email_across_ip_addresses(app, client):
    client.get("/musteri-portali", headers={"Host": "portal-firma.volkaportal.com"})
    setting = CustomerPortalSetting.query.filter_by(company_id=company().id).one()
    setting.submission_limit_hour = 1
    db.session.commit()

    first_headers = {
        "Host": "portal-firma.volkaportal.com",
        "X-Forwarded-For": "10.0.0.1",
    }
    second_headers = {
        "Host": "portal-firma.volkaportal.com",
        "X-Forwarded-For": "10.0.0.2",
    }
    assert client.post(
        "/musteri-portali",
        data=public_form_data(),
        headers=first_headers,
    ).status_code == 200
    assert client.post(
        "/musteri-portali",
        data=public_form_data(),
        headers=second_headers,
    ).status_code == 429


def test_internal_permissions_response_closure_guard_and_archive(app, client):
    verification_raw, record = submit_and_extract_verification(client)
    tracking_raw = verify_and_extract_tracking(client, verification_raw)
    user = create_user(
        "customer_portal.view", "customer_portal.triage", "customer_portal.assign",
        "customer_portal.respond", "customer_portal.close", "customer_portal.archive",
        "customer_portal.file_download", "customer_portal.export",
    )
    action = Action(company_id=company().id, action_number=99, title="Müşteri aksiyonu", responsible_owner=user.full_name, responsible_user_id=user.id, department="Kalite", termin_date=datetime.now().date() + timedelta(days=3))
    db.session.add(action)
    db.session.commit()
    login(client, user)
    headers = {"Host": "portal-firma.volkaportal.com"}

    assert client.get("/musteri-geri-bildirimleri", headers=headers).status_code == 200
    response = client.post(
        f"/musteri-geri-bildirimleri/{record.id}/mesaj",
        data={"message": "İnceleme başlatıldı.", "visibility": "public"},
        headers=headers,
        follow_redirects=True,
    )
    assert response.status_code == 200
    db.session.refresh(record)
    assert record.first_response_at is not None
    message_audits = AuditLog.query.filter_by(entity_type="ComplaintMessage").all()
    assert message_audits
    assert all(
        "İnceleme başlatıldı." not in (audit.new_values or "")
        for audit in message_audits
    )

    response = client.post(
        f"/musteri-geri-bildirimleri/{record.id}/guncelle",
        data={"status": "Kapatıldı", "priority": "Yüksek", "action_id": action.id, "customer_solution_summary": "Çözüm uygulandı."},
        headers=headers,
        follow_redirects=True,
    )
    assert "Bağlı aksiyon tamamlanmadan" in response.get_data(as_text=True)
    db.session.refresh(record)
    assert record.status != "Kapatıldı"

    action.is_completed = True
    db.session.commit()
    response = client.post(
        f"/musteri-geri-bildirimleri/{record.id}/guncelle",
        data={"status": "Kapatıldı", "priority": "Yüksek", "action_id": action.id, "customer_solution_summary": "Çözüm uygulandı."},
        headers=headers,
    )
    assert response.status_code == 302
    db.session.refresh(record)
    assert record.status == "Kapatıldı"
    assert record.public_status == "Kapatıldı"

    with client.session_transaction(base_url="https://portal-firma.volkaportal.com") as session:
        session.clear()
    response = client.post(
        f"/musteri-portali/takip/{tracking_raw}/memnuniyet",
        data={"rating": "5", "comment": "Teşekkürler"},
        headers=headers,
    )
    assert response.status_code == 302
    db.session.refresh(record)
    assert record.customer_rating == 5

    login(client, user)
    response = client.post(f"/musteri-geri-bildirimleri/{record.id}/arsivle", headers=headers)
    assert response.status_code == 302
    db.session.refresh(record)
    assert record.is_archived is True
    assert ComplaintRecord.query.count() == 1
    assert AuditLog.query.filter_by(entity_type="CustomerFeedbackPortal").count() >= 4
    archive_page = client.get(
        "/musteri-geri-bildirimleri?archived=1",
        headers=headers,
    )
    assert archive_page.status_code == 200
    assert record.complaint_no in archive_page.get_data(as_text=True)


def test_close_only_assignee_can_finish_record(app, client):
    verification_raw, record = submit_and_extract_verification(client)
    verify_and_extract_tracking(client, verification_raw)
    closer = create_user("customer_portal.view", "customer_portal.close")
    record.responsible_user_id = closer.id
    db.session.commit()
    login(client, closer)
    headers = {"Host": "portal-firma.volkaportal.com"}

    detail_response = client.get(
        f"/musteri-geri-bildirimleri/{record.id}",
        headers=headers,
    )
    assert detail_response.status_code == 200
    assert "Süreci Kaydet" in detail_response.get_data(as_text=True)
    response = client.post(
        f"/musteri-geri-bildirimleri/{record.id}/guncelle",
        data={
            "status": "Kapatıldı",
            "customer_solution_summary": "Kontrol edildi ve çözüldü.",
        },
        headers=headers,
    )
    assert response.status_code == 302
    db.session.refresh(record)
    assert record.status == "Kapatıldı"


def test_triage_queue_is_in_assigned_tasks_and_due_dashboard(app, client):
    verification_raw, record = submit_and_extract_verification(client)
    verify_and_extract_tracking(client, verification_raw)
    triage_user = create_user(
        "customer_portal.view",
        "customer_portal.triage",
        "management_due_dashboard.view",
    )
    login(client, triage_user)
    headers = {"Host": "portal-firma.volkaportal.com"}

    tasks_response = client.get("/uzerime-atananlar", headers=headers)
    assert tasks_response.status_code == 200
    tasks_body = tasks_response.get_data(as_text=True)
    assert record.complaint_no in tasks_body
    assert "Ön İnceleme Bekliyor" in tasks_body

    due_response = client.get("/yonetici-termin-paneli", headers=headers)
    assert due_response.status_code == 200
    due_body = due_response.get_data(as_text=True)
    assert record.complaint_no in due_body
    assert "İlk Yanıt SLA" in due_body
    assert "Çözüm SLA" in due_body


def test_viewer_cannot_open_internal_portal_and_checklist_is_marked(app, client):
    viewer = create_user("complaints.view")
    login(client, viewer)
    assert client.get("/musteri-geri-bildirimleri", headers={"Host": "portal-firma.volkaportal.com"}).status_code == 403
    ensure_runtime_schema()
    setting = db.session.get(AppSetting, "sales_readiness:competitor_customer_request_portal")
    assert setting is not None and setting.value == "1"


def test_department_manager_does_not_match_department_by_substring(app, client):
    verification_raw, record = submit_and_extract_verification(client)
    verify_and_extract_tracking(client, verification_raw)
    record.department = "Kalite"
    manager = create_user("customer_portal.view", role_key="department_manager")
    manager.title = "IT Müdürü"
    db.session.commit()
    login(client, manager)

    response = client.get(
        f"/musteri-geri-bildirimleri/{record.id}",
        headers={"Host": "portal-firma.volkaportal.com"},
    )

    assert response.status_code == 403
