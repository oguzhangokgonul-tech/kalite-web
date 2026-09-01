from datetime import date, timedelta
from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    Action,
    AppSetting,
    CalibrationRecord,
    ComplaintRecord,
    Document,
    DocumentCategory,
    DocumentRevisionRequest,
    Dof,
    InternalAudit,
    User,
    UserPermission,
)
from app.routes import DOCUMENT_REVISION_PENDING_STATUS
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


def create_manager():
    user = User(
        username="manager",
        full_name="Yönetici Kullanıcı",
        password_hash="not-used",
        is_active=True,
    )
    user.extra_permissions.append(UserPermission(permission_key="roles.manage"))
    db.session.add(user)
    db.session.commit()
    return user


def test_iso_dashboard_renders_cross_module_risk_summary(app, client):
    today = date.today()
    manager = create_manager()
    category = DocumentCategory(
        code="03",
        name="Prosedürler",
        slug="prosedurler",
        sort_order=3,
    )
    document = Document(
        category=category,
        document_code="PR.01",
        title="Yönetim Prosedürü",
        revision_no="1",
        status="Yayında",
        file_name="pr01.pdf",
        original_file_name="PR.01.pdf",
        file_path="documents/pr01.pdf",
    )
    db.session.add_all(
        [
            Action(
                action_number=1,
                title="Geciken aksiyon",
                responsible_owner=manager.full_name,
                responsible_user_id=manager.id,
                department="Kalite",
                termin_date=today - timedelta(days=4),
            ),
            Dof(
                dof_no="IF-0001",
                title="Açık uygunsuzluk",
                department="Kalite",
                responsible_id=manager.id,
                created_by_user_id=manager.id,
                opening_date=today - timedelta(days=8),
                due_date=today - timedelta(days=2),
                status="Onay Akışı Bekleniyor",
                approval_step="management_representative",
            ),
            category,
            document,
            DocumentRevisionRequest(
                document=document,
                requested_by_user_id=manager.id,
                status=DOCUMENT_REVISION_PENDING_STATUS,
                explanation="Revizyon talebi",
            ),
            InternalAudit(
                audit_no="ID-0001",
                title="Yaklaşan denetim",
                auditor_id=manager.id,
                planned_date=today + timedelta(days=7),
                status="Planlandı",
            ),
            CalibrationRecord(
                device_code="CK01",
                device_name="Elek",
                next_calibration_date=today - timedelta(days=3),
                status="UYGUN",
                is_active=True,
            ),
            ComplaintRecord(
                complaint_no="SIK-2026-0001",
                customer_name="Bergama Plastik",
                subject="Geciken müşteri şikayeti",
                due_date=today - timedelta(days=2),
                status="Açık",
                priority="Kritik",
                created_by_user_id=manager.id,
            ),
        ]
    )
    db.session.commit()
    login(client, manager)

    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "ISO 9001 Yönetici Özeti" in body
    assert "Açık IF/DÖF" in body
    assert "Geciken Aksiyon" in body
    assert "Revizyon Bekleyen Doküman" in body
    assert "Açık Şikayet" in body
    assert "Yaklaşan İç Denetim" in body
    assert "Kalibrasyon Riski" in body
    assert "Geciken aksiyon" in body
    assert "Açık uygunsuzluk" in body
    assert "Yönetim Prosedürü" in body
    assert "Geciken müşteri şikayeti" in body
    assert "Yaklaşan denetim" in body
    assert "Elek" in body


def test_runtime_schema_marks_sales_readiness_iso_dashboard_done(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:iso_dashboard")
    assert setting is not None
    assert setting.value == "1"
