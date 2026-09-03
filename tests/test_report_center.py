from datetime import date, timedelta
from io import BytesIO
import json
from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    Action,
    AppSetting,
    AuditLog,
    Company,
    Dof,
    Document,
    DocumentAcknowledgement,
    DocumentCategory,
    Role,
    TrainingParticipant,
    TrainingRecord,
    User,
    UserPermission,
)
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


def create_user(username, *permission_keys, company=None, full_name=None):
    user = User(
        username=username,
        full_name=full_name or username.title(),
        password_hash="not-used",
        company_id=company.id if company else None,
        is_active=True,
    )
    for permission_key in permission_keys:
        user.extra_permissions.append(UserPermission(permission_key=permission_key))
    db.session.add(user)
    db.session.commit()
    return user


def sheet_values(xlsx_bytes):
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(BytesIO(xlsx_bytes)) as archive:
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in sheet.findall(".//m:row", namespace):
        values = []
        for cell in row.findall("m:c", namespace):
            text = cell.find("m:is/m:t", namespace)
            values.append(text.text if text is not None and text.text is not None else "")
        rows.append(values)
    return rows


def test_report_center_requires_report_permission(app, client):
    user = create_user("viewer")
    login(client, user)

    response = client.get("/rapor-merkezi")

    assert response.status_code == 403


def test_report_center_view_permission_does_not_allow_export(app, client):
    user = create_user("department-manager", "reports.view")
    login(client, user)

    response = client.get("/rapor-merkezi")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Rapor Merkezi" in body
    assert "Çıktı Yetkisi Yok" in body

    export_response = client.get("/rapor-merkezi/actions_overdue/excel")

    assert export_response.status_code == 403
    pdf_response = client.get("/rapor-merkezi/actions_overdue/pdf")

    assert pdf_response.status_code == 403


def test_report_center_export_is_scoped_to_current_company_and_audited(app, client):
    company_a = Company(code="101", name="A Firması", slug="a-firmasi")
    company_b = Company(code="102", name="B Firması", slug="b-firmasi")
    db.session.add_all([company_a, company_b])
    db.session.commit()
    user = create_user("reporter", "reports.view", "reports.export", company=company_a)
    today = date.today()
    db.session.add_all(
        [
            Action(
                company_id=company_a.id,
                action_number=1,
                title="A firması geciken aksiyon",
                responsible_owner="Kalite Sorumlusu",
                responsible_user_id=user.id,
                department="Kalite",
                termin_date=today - timedelta(days=5),
            ),
            Action(
                company_id=company_b.id,
                action_number=2,
                title="B firması görünmeyen aksiyon",
                responsible_owner="Bakım Sorumlusu",
                department="Bakım",
                termin_date=today - timedelta(days=12),
            ),
        ]
    )
    db.session.commit()
    login(client, user)

    response = client.get("/rapor-merkezi/actions_overdue/excel")

    assert response.status_code == 200
    assert response.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert response.headers["Content-Disposition"].startswith(
        "attachment; filename=actions-overdue-"
    )
    rows = sheet_values(response.data)
    assert rows[0] == [
        "Aksiyon No",
        "Başlık",
        "Departman",
        "Sorumlu",
        "Termin",
        "Gecikme Günü",
        "Durum",
    ]
    flattened = "\n".join("\t".join(row) for row in rows)
    assert "A firması geciken aksiyon" in flattened
    assert "B firması görünmeyen aksiyon" not in flattened

    log = AuditLog.query.filter_by(entity_type="ReportCenter", action="exported").one()
    assert log.company_id == company_a.id
    assert log.user_id == user.id
    assert log.entity_id == "actions_overdue"
    assert json.loads(log.new_values)["format"] == "excel"


def test_report_center_pdf_view_is_scoped_and_audited(app, client):
    company_a = Company(code="103", name="A Firması", slug="a-firmasi-pdf")
    company_b = Company(code="104", name="B Firması", slug="b-firmasi-pdf")
    db.session.add_all([company_a, company_b])
    db.session.commit()
    user = create_user("pdf-reporter", "reports.view", "reports.export", company=company_a)
    today = date.today()
    db.session.add_all(
        [
            Action(
                company_id=company_a.id,
                action_number=1,
                title="A firması PDF aksiyonu",
                responsible_owner="Kalite Sorumlusu",
                responsible_user_id=user.id,
                department="Kalite",
                termin_date=today - timedelta(days=2),
            ),
            Action(
                company_id=company_b.id,
                action_number=2,
                title="B firması PDF görünmeyen aksiyon",
                responsible_owner="Bakım Sorumlusu",
                department="Bakım",
                termin_date=today - timedelta(days=4),
            ),
        ]
    )
    db.session.commit()
    login(client, user)

    response = client.get("/rapor-merkezi/actions_overdue/pdf")

    assert response.status_code == 200
    assert response.mimetype == "text/html"
    body = response.get_data(as_text=True)
    assert "Aksiyon Gecikme Raporu" in body
    assert "PDF Olarak Kaydet" in body
    assert "A firması PDF aksiyonu" in body
    assert "B firması PDF görünmeyen aksiyon" not in body

    log = AuditLog.query.filter_by(entity_type="ReportCenter", action="exported").one()
    assert log.company_id == company_a.id
    assert log.user_id == user.id
    assert log.entity_id == "actions_overdue"
    assert json.loads(log.new_values)["format"] == "pdf"


def test_report_center_exports_capa_and_document_acknowledgement_reports(app, client):
    company = Company(code="105", name="Rapor Firması", slug="rapor-firmasi")
    db.session.add(company)
    db.session.commit()
    reporter = create_user("full-reporter", "reports.view", "reports.export", company=company)
    reader = create_user("document-reader", company=company, full_name="Ayşe Çelik")
    pending_reader = create_user("pending-reader", company=company, full_name="Mehmet Yılmaz")
    category = DocumentCategory(
        company_id=company.id,
        code="03",
        name="Prosedürler",
        slug="prosedurler",
        sort_order=3,
        is_active=True,
    )
    document = Document(
        company_id=company.id,
        category=category,
        document_code="PR.70",
        title="Okuma Onayı Prosedürü",
        revision_no="2",
        publish_date=date.today(),
        status="Yayında",
        file_name="pr70.pdf",
        original_file_name="pr70.pdf",
        file_path="company-105/documents/pr70.pdf",
        file_type="pdf",
    )
    training = TrainingRecord(
        company_id=company.id,
        training_no="EGT-2026-0070",
        title="PR.70 Okuma Onayı",
        training_type="Doküman Okuma Onayı",
        document=document,
        created_by_user_id=reporter.id,
    )
    db.session.add_all(
        [
            category,
            document,
            DocumentAcknowledgement(
                company_id=company.id,
                document=document,
                user=reader,
                document_code_snapshot="PR.70",
                document_title_snapshot="Okuma Onayı Prosedürü",
                revision_no_snapshot="2",
            ),
            training,
            TrainingParticipant(
                company_id=company.id,
                training=training,
                user_id=pending_reader.id,
                status="Atandı",
            ),
            Dof(
                company_id=company.id,
                dof_no="IF-2026-0700",
                title="CAPA kayıt başlığı",
                department="Kalite",
                responsible_id=reader.id,
                opening_date=date.today(),
                due_date=date.today(),
                priority="Orta",
                source="İç Denetim",
                status="Etkinlik Kontrolü Bekliyor",
                approval_step="effectiveness_review",
                root_cause_method="5 Neden",
                containment_action="Geçici önlem",
                root_cause_analysis="Kök neden analizi",
                corrective_action="Düzeltici faaliyet",
                closing_evidence="Kapanış kanıtı",
                effectiveness_required=True,
                effectiveness_owner_user_id=reader.id,
                effectiveness_due_date=date.today(),
                effectiveness_result="Bekliyor",
            ),
        ]
    )
    db.session.commit()
    login(client, reporter)

    capa_response = client.get("/rapor-merkezi/dof_capa_effectiveness/excel")
    acknowledgement_response = client.get("/rapor-merkezi/document_acknowledgements/excel")

    assert capa_response.status_code == 200
    assert acknowledgement_response.status_code == 200
    capa_rows = sheet_values(capa_response.data)
    acknowledgement_rows = sheet_values(acknowledgement_response.data)
    capa_text = "\n".join("\t".join(row) for row in capa_rows)
    acknowledgement_text = "\n".join("\t".join(row) for row in acknowledgement_rows)
    assert "IF-2026-0700" in capa_text
    assert "Kök neden analizi" in capa_text
    assert "Okuma Onayı Prosedürü" in acknowledgement_text
    assert "Ayşe Çelik" in acknowledgement_text
    assert "Onaylandı" in acknowledgement_text
    assert "Mehmet Yılmaz" in acknowledgement_text
    assert "Bekliyor" in acknowledgement_text


def test_report_center_sidebar_link_follows_report_permission(app, client):
    viewer = create_user("plain-viewer")
    login(client, viewer)

    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/rapor-merkezi"' not in response.get_data(as_text=True)

    reporter = create_user("report-viewer", "reports.view")
    login(client, reporter)

    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/rapor-merkezi"' in response.get_data(as_text=True)


def test_default_roles_receive_report_permissions_idempotently(app):
    existing_role = Role(
        key="management_representative",
        name="Eski Yönetim Temsilcisi",
        hierarchy_level=10,
        is_system=True,
    )
    db.session.add(existing_role)
    db.session.commit()

    ensure_default_roles()
    ensure_default_roles()
    db.session.flush()
    db.session.expire_all()

    management_representative = Role.query.filter_by(key="management_representative").one()
    management = Role.query.filter_by(key="management").one()
    department_manager = Role.query.filter_by(key="department_manager").one()
    department_staff = Role.query.filter_by(key="department_staff").one()

    assert {"reports.view", "reports.export"}.issubset(
        management_representative.permission_keys
    )
    assert {"reports.view", "reports.export"}.issubset(management.permission_keys)
    assert "reports.view" in department_manager.permission_keys
    assert "reports.export" not in department_manager.permission_keys
    assert "reports.view" not in department_staff.permission_keys
    assert (
        len(
            [
                permission
                for permission in management_representative.permissions
                if permission.permission_key == "reports.view"
            ]
        )
        == 1
    )


def test_runtime_schema_marks_sales_readiness_report_center_done(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:report_center")
    assert setting is not None
    assert setting.value == "1"
    roadmap_setting = db.session.get(AppSetting, "sales_readiness:month2_reports")
    assert roadmap_setting is not None
    assert roadmap_setting.value == "1"
