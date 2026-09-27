from datetime import date
from io import BytesIO
import json
from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

import pytest

from app import create_app
from app.extensions import db
from app.models import Action, AppSetting, AuditLog, Company, ReportDefinition, Role, User, UserPermission
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


def create_user(username, company, *permissions):
    user = User(
        username=username,
        full_name=username.title(),
        password_hash="not-used",
        company_id=company.id,
        is_active=True,
    )
    for permission in permissions:
        user.extra_permissions.append(UserPermission(permission_key=permission))
    db.session.add(user)
    db.session.commit()
    return user


def designer_payload(**overrides):
    payload = {
        "name": "Kalite Aksiyon Özeti",
        "description": "Kalite departmanı açık aksiyonları",
        "source_key": "actions_master",
        "visibility": "private",
        "columns": ["Aksiyon No", "Başlık", "Departman", "Durum"],
        "filter_column": ["Departman", "Durum", ""],
        "filter_operator": ["equals", "contains", "contains"],
        "filter_value": ["Kalite", "Açık", ""],
        "sort_column": ["Başlık", "", ""],
        "sort_direction": ["desc", "asc", "asc"],
        "metrics": ["row_count", "column_count", "group_count"],
        "group_by": "Durum",
    }
    payload.update(overrides)
    return payload


def add_actions(company, user):
    db.session.add_all(
        [
            Action(
                company_id=company.id,
                action_number=1,
                title="Alfa açık aksiyon",
                department="Kalite",
                responsible_owner=user.full_name,
                responsible_user_id=user.id,
                termin_date=date(2026, 10, 1),
            ),
            Action(
                company_id=company.id,
                action_number=2,
                title="Zeta açık aksiyon",
                department="Kalite",
                responsible_owner=user.full_name,
                responsible_user_id=user.id,
                termin_date=date(2026, 10, 2),
            ),
            Action(
                company_id=company.id,
                action_number=3,
                title="Bakım aksiyonu",
                department="Bakım",
                responsible_owner=user.full_name,
                responsible_user_id=user.id,
                termin_date=date(2026, 10, 3),
            ),
        ]
    )
    db.session.commit()


def sheet_values(content):
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(BytesIO(content)) as archive:
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    return [
        [
            (cell.find("m:is/m:t", namespace).text or "")
            if cell.find("m:is/m:t", namespace) is not None
            else ""
            for cell in row.findall("m:c", namespace)
        ]
        for row in sheet.findall(".//m:row", namespace)
    ]


def test_report_designer_requires_design_permission(app, client):
    company = Company(code="RD-1", name="Rapor Firması", slug="rapor-firmasi")
    db.session.add(company)
    db.session.commit()
    viewer = create_user("viewer", company, "reports.view")
    login(client, viewer)

    assert client.get("/rapor-merkezi/tasarim/yeni").status_code == 403
    assert client.post("/rapor-merkezi/tasarim/yeni", data=designer_payload()).status_code == 403
    assert client.post("/rapor-merkezi/tasarim/onizleme", data=designer_payload()).status_code == 403


def test_owner_can_create_filter_sort_view_and_export_private_report(app, client):
    company = Company(code="RD-2", name="Tasarım Firması", slug="tasarim-firmasi")
    db.session.add(company)
    db.session.commit()
    designer = create_user(
        "designer",
        company,
        "reports.view",
        "reports.export",
        "reports.design",
        "actions.view_all",
    )
    add_actions(company, designer)
    login(client, designer)

    designer_page = client.get("/rapor-merkezi/tasarim/yeni")
    assert designer_page.status_code == 200
    assert "Rapor Tasarla" in designer_page.get_data(as_text=True)

    preview = client.post("/rapor-merkezi/tasarim/onizleme", data=designer_payload())
    assert preview.status_code == 200
    assert "Bu bir önizlemedir" in preview.get_data(as_text=True)
    assert "Bakım aksiyonu" not in preview.get_data(as_text=True)
    assert ReportDefinition.query.count() == 0

    response = client.post("/rapor-merkezi/tasarim/yeni", data=designer_payload())

    report = ReportDefinition.query.one()
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/rapor-merkezi/tasarim/{report.id}")
    assert report.company_id == company.id
    assert report.created_by_user_id == designer.id
    assert report.visibility == "private"
    configuration = json.loads(report.configuration_json)
    assert configuration["columns"] == ["Aksiyon No", "Başlık", "Departman", "Durum"]
    assert len(report.configuration_hash) == 64

    detail = client.get(response.headers["Location"])
    body = detail.get_data(as_text=True)
    assert detail.status_code == 200
    assert "Zeta açık aksiyon" in body
    assert "Alfa açık aksiyon" in body
    assert body.index("Zeta açık aksiyon") < body.index("Alfa açık aksiyon")
    assert "Bakım aksiyonu" not in body
    assert "2 eşleşme" in body
    assert "Durum Dağılımı" in body

    export = client.get(f"/rapor-merkezi/tasarim/{report.id}/excel")
    assert export.status_code == 200
    rows = sheet_values(export.data)
    assert rows[0] == ["Aksiyon No", "Başlık", "Departman", "Durum"]
    flattened = "\n".join("\t".join(row) for row in rows)
    assert "Zeta açık aksiyon" in flattened
    assert "Bakım aksiyonu" not in flattened
    assert AuditLog.query.filter_by(
        entity_type="ReportDefinition", action="viewed", entity_id=str(report.id)
    ).count() == 1
    assert AuditLog.query.filter_by(
        entity_type="ReportCenter", action="exported", entity_id=f"custom-report-{report.id}"
    ).count() == 1


def test_private_company_and_tenant_access_rules(app, client):
    company_a = Company(code="RD-3", name="A Firması", slug="a-rapor")
    company_b = Company(code="RD-4", name="B Firması", slug="b-rapor")
    db.session.add_all([company_a, company_b])
    db.session.commit()
    owner = create_user("owner", company_a, "reports.view", "reports.design", "actions.create")
    colleague = create_user("colleague", company_a, "reports.view", "actions.create")
    no_report_access = create_user("no-report-access", company_a)
    manager = create_user("manager", company_a, "reports.view", "reports.design", "reports.manage", "actions.view_all")
    outsider = create_user("outsider", company_b, "reports.view", "reports.manage")
    login(client, owner)
    client.post("/rapor-merkezi/tasarim/yeni", data=designer_payload())
    private_report = ReportDefinition.query.one()

    login(client, colleague)
    assert client.get(f"/rapor-merkezi/tasarim/{private_report.id}").status_code == 404

    login(client, manager)
    assert client.get(f"/rapor-merkezi/tasarim/{private_report.id}").status_code == 200
    response = client.post(
        "/rapor-merkezi/tasarim/yeni",
        data=designer_payload(name="Şirket Raporu", visibility="company"),
    )
    shared_report = ReportDefinition.query.filter_by(name="Şirket Raporu").one()
    assert response.status_code == 302
    assert shared_report.visibility == "company"

    login(client, no_report_access)
    assert client.get(f"/rapor-merkezi/tasarim/{shared_report.id}").status_code == 403

    login(client, colleague)
    assert client.get(f"/rapor-merkezi/tasarim/{shared_report.id}").status_code == 200
    assert client.get(f"/rapor-merkezi/tasarim/{shared_report.id}/duzenle").status_code == 403

    login(client, outsider)
    assert client.get(f"/rapor-merkezi/tasarim/{shared_report.id}").status_code == 404


def test_tampered_columns_are_rejected_and_non_manager_cannot_share(app, client):
    company = Company(code="RD-5", name="Güvenli Firma", slug="guvenli-firma")
    db.session.add(company)
    db.session.commit()
    designer = create_user("limited", company, "reports.view", "reports.design", "actions.create")
    login(client, designer)

    source_page = client.get("/rapor-merkezi/tasarim/yeni").get_data(as_text=True)
    assert "Personel İletişim Raporu" not in source_page

    forbidden_source = client.post(
        "/rapor-merkezi/tasarim/yeni",
        data=designer_payload(source_key="dynamic_forms", columns=["Form"]),
    )
    assert forbidden_source.status_code == 200
    assert ReportDefinition.query.count() == 0

    invalid = client.post(
        "/rapor-merkezi/tasarim/yeni",
        data=designer_payload(columns=["Başlık", "password_hash"]),
    )
    assert invalid.status_code == 200
    assert ReportDefinition.query.count() == 0

    valid = client.post(
        "/rapor-merkezi/tasarim/yeni",
        data=designer_payload(name="Kişisel Rapor", visibility="company"),
    )
    assert valid.status_code == 302
    assert ReportDefinition.query.one().visibility == "private"


def test_optimistic_lock_archive_and_runtime_checklist(app, client):
    company = Company(code="RD-6", name="Revizyon Firması", slug="revizyon-firmasi")
    db.session.add(company)
    db.session.commit()
    manager = create_user(
        "report-manager",
        company,
        "reports.view",
        "reports.design",
        "reports.manage",
        "actions.view_all",
    )
    login(client, manager)
    client.post("/rapor-merkezi/tasarim/yeni", data=designer_payload())
    report = ReportDefinition.query.one()

    stale = client.post(
        f"/rapor-merkezi/tasarim/{report.id}/duzenle",
        data=designer_payload(name="Ezilmemeli", lock_version="0"),
    )
    assert stale.status_code == 302
    db.session.refresh(report)
    assert report.name == "Kalite Aksiyon Özeti"

    archived = client.post(
        f"/rapor-merkezi/tasarim/{report.id}/arsivle",
        data={"lock_version": str(report.lock_version)},
    )
    assert archived.status_code == 302
    db.session.refresh(report)
    assert report.status == "archived"
    assert client.get(f"/rapor-merkezi/tasarim/{report.id}").status_code == 404

    ensure_runtime_schema()
    assert db.session.get(
        AppSetting, "sales_readiness:competitor_report_designer"
    ).value == "1"


def test_department_manager_custom_report_is_scoped_to_own_department(app, client):
    company = Company(code="RD-7", name="Departman Firması", slug="departman-firmasi")
    role = Role(
        key="department_manager",
        name="Departman Yöneticisi",
        hierarchy_level=30,
    )
    db.session.add_all([company, role])
    db.session.commit()
    manager = create_user("quality-manager", company, "reports.view", "reports.design", "actions.create")
    manager.title = "Kalite"
    manager.roles.append(role)
    other = create_user("maintenance-owner", company)
    db.session.add_all(
        [
            Action(
                company_id=company.id,
                action_number=11,
                title="Kalite görünür",
                department="Kalite",
                responsible_owner=other.full_name,
                responsible_user_id=other.id,
                termin_date=date(2026, 10, 1),
            ),
            Action(
                company_id=company.id,
                action_number=12,
                title="Bakım gizli",
                department="Bakım",
                responsible_owner=other.full_name,
                responsible_user_id=other.id,
                termin_date=date(2026, 10, 1),
            ),
        ]
    )
    db.session.commit()
    login(client, manager)

    response = client.post(
        "/rapor-merkezi/tasarim/yeni",
        data=designer_payload(
            name="Departman Raporu",
            filter_column=["", "", ""],
            filter_operator=["contains", "contains", "contains"],
            filter_value=["", "", ""],
        ),
    )
    report = ReportDefinition.query.one()
    detail = client.get(response.headers["Location"])
    body = detail.get_data(as_text=True)
    assert "Kalite görünür" in body
    assert "Bakım gizli" not in body
