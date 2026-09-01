from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

import pytest

from app import create_app
from app.extensions import db
from app.models import Action, AppSetting, AuditLog, Company, User, UserPermission
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
    assert "Export Yetkisi Yok" in body

    export_response = client.get("/rapor-merkezi/actions_overdue/excel")

    assert export_response.status_code == 403


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
