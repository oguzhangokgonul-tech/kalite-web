from datetime import date
from io import BytesIO
from pathlib import Path
import json
import zipfile
from xml.etree import ElementTree as ET

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    COMPANY_MODULE_KEYS,
    Action,
    AuditLog,
    Company,
    User,
    UserPermission,
)
from app.reporting import resolve_report_period
from app.routes import MODULE_ACTIVITY_ENTITY_TYPES, REPORT_CENTER_REPORTS, REPORT_PERIOD_POLICIES


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


def sheet_values(xlsx_bytes, sheet_name="xl/worksheets/sheet1.xml"):
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(BytesIO(xlsx_bytes)) as archive:
        sheet = ET.fromstring(archive.read(sheet_name))
    values = []
    for row in sheet.findall(".//m:row", namespace):
        values.append(
            [
                (cell.find("m:is/m:t", namespace).text or "")
                if cell.find("m:is/m:t", namespace) is not None
                else ""
                for cell in row.findall("m:c", namespace)
            ]
        )
    return values


@pytest.mark.parametrize(
    ("period_key", "expected_start", "expected_end", "expected_code"),
    (
        ("month", date(2024, 2, 1), date(2024, 2, 29), "2024-M02"),
        ("quarter", date(2026, 7, 1), date(2026, 9, 30), "2026-Q3"),
        ("half_year", date(2026, 7, 1), date(2026, 12, 31), "2026-H2"),
        ("year", date(2026, 1, 1), date(2026, 12, 31), "2026-Y"),
    ),
)
def test_report_period_calendar_boundaries(period_key, expected_start, expected_end, expected_code):
    anchor = expected_start.replace(day=min(15, expected_start.day))
    period = resolve_report_period(period_key, anchor.isoformat(), today=date(2027, 1, 1))

    assert period.start_date == expected_start
    assert period.end_date == expected_end
    assert period.code == expected_code


def test_every_company_module_has_an_activity_report_mapping():
    assert set(MODULE_ACTIVITY_ENTITY_TYPES) == set(COMPANY_MODULE_KEYS)
    assert set(REPORT_PERIOD_POLICIES) == {
        definition["key"] for definition in REPORT_CENTER_REPORTS
    }


def test_report_period_rejects_invalid_or_future_values():
    with pytest.raises(ValueError):
        resolve_report_period("weekly", "2026-09-01", today=date(2026, 9, 28))
    with pytest.raises(ValueError):
        resolve_report_period("month", "2026-10-01", today=date(2026, 9, 28))


def test_periodic_excel_filters_rows_adds_metadata_and_audits_scope(app, client):
    company = Company(code="501", name="Dönem Firması", slug="donem-firmasi")
    db.session.add(company)
    db.session.flush()
    user = User(
        username="period-reporter",
        full_name="Dönem Raporcusu",
        password_hash="not-used",
        company_id=company.id,
        is_active=True,
    )
    user.extra_permissions.extend(
        [
            UserPermission(permission_key="reports.view"),
            UserPermission(permission_key="reports.export"),
        ]
    )
    db.session.add_all(
        [
            user,
            Action(
                company_id=company.id,
                action_number=1,
                title="Eylül aksiyonu",
                responsible_owner="Kalite",
                department="Kalite",
                termin_date=date(2026, 9, 10),
            ),
            Action(
                company_id=company.id,
                action_number=2,
                title="Ağustos aksiyonu",
                responsible_owner="Kalite",
                department="Kalite",
                termin_date=date(2026, 8, 10),
            ),
        ]
    )
    db.session.commit()
    login(client, user)

    response = client.get(
        "/rapor-merkezi/actions_master/excel?period=month&anchor=2026-09-15"
    )

    assert response.status_code == 200
    rows = sheet_values(response.data)
    flattened = "\n".join("\t".join(row) for row in rows)
    assert "Eylül aksiyonu" in flattened
    assert "Ağustos aksiyonu" not in flattened
    metadata = sheet_values(response.data, "xl/worksheets/sheet2.xml")
    metadata_text = "\n".join("\t".join(row) for row in metadata)
    assert "2026-M09" in metadata_text
    assert "01.09.2026 - 28.09.2026" in metadata_text
    log = AuditLog.query.filter_by(entity_type="ReportCenter", action="exported").one()
    details = json.loads(log.new_values)
    assert details["period_code"] == "2026-M09"
    assert details["row_count"] == 1


def test_module_activity_report_is_periodic_and_tenant_scoped(app, client):
    company_a = Company(code="601", name="A Firması", slug="a-firmasi")
    company_b = Company(code="602", name="B Firması", slug="b-firmasi")
    db.session.add_all([company_a, company_b])
    db.session.flush()
    user = User(
        username="activity-reporter",
        full_name="Activity Reporter",
        password_hash="not-used",
        company_id=company_a.id,
        is_active=True,
    )
    user.extra_permissions.append(UserPermission(permission_key="reports.export"))
    db.session.add(user)
    db.session.flush()
    db.session.add_all(
        [
            AuditLog(
                company_id=company_a.id,
                user_id=user.id,
                entity_type="MaintenanceFault",
                entity_id="10",
                action="created",
                summary="A firması arızası",
                created_at=date(2026, 9, 5),
            ),
            AuditLog(
                company_id=company_b.id,
                entity_type="MaintenanceFault",
                entity_id="11",
                action="created",
                summary="B firması arızası",
                created_at=date(2026, 9, 6),
            ),
        ]
    )
    db.session.commit()
    login(client, user)

    response = client.get(
        "/rapor-merkezi/modul-hareket/excel?module=maintenance&period=month&anchor=2026-09-15"
    )

    assert response.status_code == 200
    flattened = "\n".join("\t".join(row) for row in sheet_values(response.data))
    assert "A firması arızası" in flattened
    assert "B firması arızası" not in flattened
