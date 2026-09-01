from datetime import date, timedelta
from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.models import Action, AppSetting, AuditLog, ComplaintRecord, Dof, User, UserPermission
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


def create_user(username, *permission_keys):
    user = User(
        username=username,
        full_name=username.title(),
        password_hash="not-used",
        is_active=True,
    )
    for permission_key in permission_keys:
        user.extra_permissions.append(UserPermission(permission_key=permission_key))
    db.session.add(user)
    db.session.commit()
    return user


def test_complaint_dashboard_requires_permission(app, client):
    user = create_user("viewer")
    login(client, user)

    response = client.get("/oneri-sikayet/sikayet")

    assert response.status_code == 403


def test_complaint_create_edit_delete_flow(app, client):
    today = date.today()
    user = create_user(
        "manager",
        "complaints.view",
        "complaints.manage",
        "complaints.delete",
    )
    action = Action(
        action_number=1,
        title="Şikayet aksiyonu",
        responsible_owner=user.full_name,
        responsible_user_id=user.id,
        department="Kalite",
        termin_date=today + timedelta(days=7),
    )
    dof = Dof(
        dof_no="IF-0001",
        title="Şikayet IF bağlantısı",
        department="Kalite",
        responsible_id=user.id,
        created_by_user_id=user.id,
        opening_date=today,
        due_date=today + timedelta(days=10),
        status="Onay Akışı Bekleniyor",
        approval_step="management_representative",
    )
    db.session.add_all([action, dof])
    db.session.commit()
    login(client, user)

    form_response = client.get("/oneri-sikayet/sikayet/yeni")
    assert form_response.status_code == 200
    assert "Yeni Şikayet Kaydı" in form_response.get_data(as_text=True)

    response = client.post(
        "/oneri-sikayet/sikayet/yeni",
        data={
            "customer_name": "Bergama Plastik",
            "contact_name": "Müşteri Yetkilisi",
            "contact_phone": "555 000 00 00",
            "department": "Kalite",
            "subject": "Yüzey hatası bildirimi",
            "description": "Üründe yüzey kusuru bildirildi.",
            "received_date": today.isoformat(),
            "due_date": (today - timedelta(days=2)).isoformat(),
            "status": "İncelemede",
            "priority": "Kritik",
            "responsible_user_id": str(user.id),
            "action_id": str(action.id),
            "dof_id": str(dof.id),
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Bergama Plastik" in body
    assert "Yüzey hatası bildirimi" in body
    assert "2 gün geçti" in body
    complaint = ComplaintRecord.query.one()
    assert complaint.complaint_no.startswith("SIK-")
    assert complaint.priority == "Kritik"
    assert complaint.action_id == action.id
    assert complaint.dof_id == dof.id

    edit_response = client.get(f"/oneri-sikayet/sikayet/{complaint.id}/duzenle")
    assert edit_response.status_code == 200
    assert "Yüzey hatası bildirimi" in edit_response.get_data(as_text=True)

    response = client.post(
        f"/oneri-sikayet/sikayet/{complaint.id}/duzenle",
        data={
            "customer_name": "Bergama Plastik",
            "department": "Kalite",
            "subject": "Yüzey hatası kapandı",
            "root_cause": "Kalıp yüzeyi kontrol edilmedi.",
            "corrective_action": "Kontrol sıklığı artırıldı.",
            "closing_note": "Müşteri bilgilendirildi.",
            "received_date": today.isoformat(),
            "due_date": today.isoformat(),
            "status": "Kapandı",
            "priority": "Orta",
            "responsible_user_id": str(user.id),
            "action_id": "",
            "dof_id": "",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    complaint = db.session.get(ComplaintRecord, complaint.id)
    assert complaint.status == "Kapandı"
    assert complaint.closed_at is not None
    assert complaint.action_id is None
    assert complaint.dof_id is None

    response = client.post(f"/oneri-sikayet/sikayet/{complaint.id}/sil", follow_redirects=True)

    assert response.status_code == 200
    assert ComplaintRecord.query.count() == 0
    assert AuditLog.query.filter_by(entity_type="ComplaintRecord").count() >= 3


def test_complaints_sort_delayed_open_before_closed(app, client):
    today = date.today()
    user = create_user("manager", "complaints.view", "complaints.manage")
    db.session.add_all(
        [
            ComplaintRecord(
                complaint_no="SIK-2026-0001",
                customer_name="Kapalı Müşteri",
                subject="Kapalı kayıt",
                due_date=today - timedelta(days=12),
                status="Kapandı",
                priority="Kritik",
                created_by_user_id=user.id,
            ),
            ComplaintRecord(
                complaint_no="SIK-2026-0002",
                customer_name="Az Geciken",
                subject="Az geciken kayıt",
                due_date=today - timedelta(days=2),
                status="Açık",
                priority="Orta",
                created_by_user_id=user.id,
            ),
            ComplaintRecord(
                complaint_no="SIK-2026-0003",
                customer_name="Çok Geciken",
                subject="Çok geciken kayıt",
                due_date=today - timedelta(days=8),
                status="Açık",
                priority="Yüksek",
                created_by_user_id=user.id,
            ),
        ]
    )
    db.session.commit()
    login(client, user)

    response = client.get("/oneri-sikayet/sikayet")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert body.find("Çok Geciken") < body.find("Az Geciken")
    assert body.find("Az Geciken") < body.find("Kapalı Müşteri")


def test_runtime_schema_marks_sales_readiness_complaint_module_done(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:complaint_module")
    assert setting is not None
    assert setting.value == "1"
    roadmap_setting = db.session.get(AppSetting, "sales_readiness:month3_complaints")
    assert roadmap_setting is not None
    assert roadmap_setting.value == "1"
