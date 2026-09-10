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
    Company,
    CompanyModule,
    Document,
    DocumentCategory,
    DocumentRevisionRequest,
    Dof,
    InternalAudit,
    ManagementReview,
    User,
    UserPermission,
)
from app.routes import DOCUMENT_REVISION_PENDING_STATUS
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
    user.extra_permissions.extend(
        [
            UserPermission(permission_key="roles.manage"),
            UserPermission(permission_key="iso_dashboard.view"),
            UserPermission(permission_key="management_due_dashboard.view"),
            UserPermission(permission_key="internal_audit.manage"),
            UserPermission(permission_key="complaints.view"),
            UserPermission(permission_key="management_review.view"),
        ]
    )
    db.session.add(user)
    db.session.commit()
    return user


def test_dashboard_panels_are_moved_to_permission_gated_modules(app, client):
    user = User(
        username="personnel",
        full_name="Personel Kullanıcı",
        password_hash="not-used",
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    login(client, user)

    dashboard_response = client.get("/")
    iso_response = client.get("/iso-9001-yonetici-ozeti")
    due_response = client.get("/yonetici-termin-paneli")

    assert dashboard_response.status_code == 200
    dashboard_body = dashboard_response.get_data(as_text=True)
    assert '<h2 class="h5 mb-1">ISO 9001 Yönetici Özeti</h2>' not in dashboard_body
    assert '<h3 class="h6 mb-1">Yönetici Termin Paneli</h3>' not in dashboard_body
    assert "ISO 9001 Yönetici Özeti" not in dashboard_body
    assert "Yönetici Termin Paneli" not in dashboard_body
    assert iso_response.status_code == 403
    assert due_response.status_code == 403


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
            Action(
                action_number=2,
                title="Tamamlanan aksiyon termin panelinde olmamalı",
                responsible_owner=manager.full_name,
                responsible_user_id=manager.id,
                department="Kalite",
                termin_date=today - timedelta(days=40),
                is_completed=True,
            ),
            Action(
                action_number=3,
                title="Daha eski gecikme",
                responsible_owner=manager.full_name,
                responsible_user_id=manager.id,
                department="Kalite",
                termin_date=today - timedelta(days=12),
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
            ManagementReview(
                review_no="YGG-2026-0001",
                title="Yıllık yönetimin gözden geçirmesi",
                meeting_date=today + timedelta(days=10),
                status="Planlandı",
                review_period="2026",
                created_by_user_id=manager.id,
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

    dashboard_response = client.get("/")
    iso_response = client.get("/iso-9001-yonetici-ozeti")
    due_response = client.get("/yonetici-termin-paneli")

    assert dashboard_response.status_code == 200
    dashboard_body = dashboard_response.get_data(as_text=True)
    assert "Kalite yönetim sistemindeki kritik kayıtları" not in dashboard_body
    assert "Geciken ve 30 gün içinde yaklaşan işleri" not in dashboard_body

    assert iso_response.status_code == 200
    iso_body = iso_response.get_data(as_text=True)
    assert "ISO 9001 Yönetici Özeti" in iso_body
    assert "Açık IF/DÖF" in iso_body
    assert "Geciken Aksiyon" in iso_body
    assert "Revizyon Bekleyen Doküman" in iso_body
    assert "Açık Şikayet" in iso_body
    assert "Yaklaşan İç Denetim" in iso_body
    assert "YGG Takibi" in iso_body
    assert "Kalibrasyon Riski" in iso_body
    assert "Yönetim Prosedürü" in iso_body
    assert "Yönetici Termin Paneli" in iso_body

    assert due_response.status_code == 200
    due_body = due_response.get_data(as_text=True)
    assert "Yönetici Termin Paneli" in due_body
    assert "4 gün geçti" in due_body
    assert "12 gün geçti" in due_body
    assert "40 gün geçti" not in due_body
    assert due_body.index("Daha eski gecikme") < due_body.index("Geciken aksiyon")
    assert "Geciken aksiyon" in due_body
    assert "Açık uygunsuzluk" in due_body
    assert "Geciken müşteri şikayeti" in due_body
    assert "Yıllık yönetimin gözden geçirmesi" in due_body
    assert "Yaklaşan denetim" in due_body
    assert "Elek" in due_body


def test_dashboard_module_role_matrix(app, client):
    roles = ensure_default_roles()
    users = {}
    for role_key in (
        "super_admin",
        "management_representative",
        "management",
        "department_manager",
        "department_staff",
        "viewer",
    ):
        user = User(
            username=f"dashboard-{role_key}",
            full_name=role_key,
            password_hash="not-used",
            is_active=True,
        )
        user.roles.append(roles[role_key])
        db.session.add(user)
        users[role_key] = user
    db.session.commit()

    expected_statuses = {
        "super_admin": (200, 200),
        "management_representative": (200, 200),
        "management": (200, 200),
        "department_manager": (403, 200),
        "department_staff": (403, 403),
        "viewer": (403, 403),
    }
    for role_key, user in users.items():
        login(client, user)
        expected_iso, expected_due = expected_statuses[role_key]
        assert client.get("/iso-9001-yonetici-ozeti").status_code == expected_iso
        assert client.get("/yonetici-termin-paneli").status_code == expected_due


def test_disabled_dashboard_modules_are_hidden_and_forbidden(app, client):
    company = Company(
        code="901",
        name="Modül Test Firması",
        slug="modul-test-firmasi",
        package_key="custom",
        is_active=True,
    )
    db.session.add(company)
    db.session.flush()
    db.session.add_all(
        [
            CompanyModule(
                company_id=company.id,
                module_key="iso_executive_summary",
                is_enabled=False,
            ),
            CompanyModule(
                company_id=company.id,
                module_key="management_due_dashboard",
                is_enabled=False,
            ),
        ]
    )
    user = User(
        company_id=company.id,
        username="module-manager",
        full_name="Modül Yöneticisi",
        password_hash="not-used",
        is_active=True,
    )
    user.extra_permissions.extend(
        [
            UserPermission(permission_key="iso_dashboard.view"),
            UserPermission(permission_key="management_due_dashboard.view"),
        ]
    )
    db.session.add(user)
    db.session.commit()
    login(client, user)

    dashboard_response = client.get("/")
    assert dashboard_response.status_code == 200
    dashboard_body = dashboard_response.get_data(as_text=True)
    assert "ISO 9001 Yönetici Özeti" not in dashboard_body
    assert "Yönetici Termin Paneli" not in dashboard_body
    assert client.get("/iso-9001-yonetici-ozeti").status_code == 403
    assert client.get("/yonetici-termin-paneli").status_code == 403


def test_department_manager_due_panel_respects_module_permissions(app, client):
    roles = ensure_default_roles()
    manager = User(
        username="department-due-manager",
        full_name="Departman Yöneticisi",
        password_hash="not-used",
        is_active=True,
    )
    manager.roles.append(roles["department_manager"])
    db.session.add(manager)
    db.session.flush()
    today = date.today()
    db.session.add_all(
        [
            Action(
                action_number=10,
                title="Yöneticinin kendi aksiyonu",
                responsible_owner=manager.full_name,
                responsible_user_id=manager.id,
                department="Üretim",
                termin_date=today + timedelta(days=2),
            ),
            InternalAudit(
                audit_no="ID-GIZLI",
                title="Yetkisiz iç denetim kaydı",
                planned_date=today + timedelta(days=3),
                status="Planlandı",
            ),
            ComplaintRecord(
                complaint_no="SIK-GIZLI",
                customer_name="Gizli Müşteri",
                subject="Yetkili şikayet kaydı",
                due_date=today + timedelta(days=4),
                status="Açık",
                priority="Orta",
            ),
        ]
    )
    db.session.commit()
    login(client, manager)

    response = client.get("/yonetici-termin-paneli")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Yöneticinin kendi aksiyonu" in body
    assert "Yetkisiz iç denetim kaydı" not in body
    assert "Yetkili şikayet kaydı" in body


def test_runtime_schema_marks_sales_readiness_iso_dashboard_done(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:iso_dashboard")
    assert setting is not None
    assert setting.value == "1"


def test_runtime_schema_marks_sales_readiness_management_dashboard_done(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:month2_management_dashboard")
    assert setting is not None
    assert setting.value == "1"
