from datetime import date, timedelta

from flask import g

from app.extensions import db
from app.models import COMPANY_MODULE_KEYS, CalibrationRecord
from app.routes import calibration_dashboard_context

from .helpers import create_company, create_user, login


def calibration_payload(**overrides):
    data = {
        "device_code": "CK01",
        "device_name": "Metal tel orgulu elek",
        "manufacturer": "Kalite LTD",
        "brand_model": "125 um",
        "serial_no": "SN-001",
        "measurement_range": "125 um",
        "deviation_range": "+/- 12,4 um",
        "location": "Laboratuvar",
        "certificate_no": "0064K-1225-00223",
        "calibration_date": date.today().isoformat(),
        "calibration_interval": "12 ay",
        "next_calibration_date": (date.today() + timedelta(days=90)).isoformat(),
        "status": "UYGUN",
        "notes": "",
    }
    data.update(overrides)
    return data


def test_calibration_crud_duplicate_and_permissions(client):
    company = create_company("341")
    viewer = create_user("calibration-viewer", company=company)
    manager = create_user("calibration-manager", company=company, permissions=("calibration.manage",))

    login(client, viewer)
    assert client.get("/kalibrasyon").status_code == 200
    assert client.get("/kalibrasyon/yeni").status_code == 403

    login(client, manager)
    response = client.post("/kalibrasyon/yeni", data=calibration_payload())

    assert response.status_code == 302
    record = CalibrationRecord.query.one()
    assert record.device_code == "CK01"

    duplicate_response = client.post("/kalibrasyon/yeni", data=calibration_payload())
    assert duplicate_response.status_code == 200
    assert CalibrationRecord.query.count() == 1

    response = client.post(
        f"/kalibrasyon/{record.id}/duzenle",
        data=calibration_payload(device_name="Guncel elek", is_active="on"),
    )

    assert response.status_code == 302
    db.session.refresh(record)
    assert record.device_name == "Guncel elek"
    assert record.is_active is True

    response = client.post(f"/kalibrasyon/{record.id}/sil")

    assert response.status_code == 302
    assert CalibrationRecord.query.count() == 0


def test_calibration_dashboard_counters_separate_due_soon_and_overdue(app):
    company = create_company("342")
    user = create_user("calibration-counter", company=company, permissions=("calibration.manage",))
    db.session.add_all(
        [
            CalibrationRecord(
                company_id=company.id,
                device_code="OVER",
                device_name="Gecmis cihaz",
                next_calibration_date=date.today() - timedelta(days=1),
                status="UYGUN",
                is_active=True,
            ),
            CalibrationRecord(
                company_id=company.id,
                device_code="SOON",
                device_name="Yaklasan cihaz",
                next_calibration_date=date.today() + timedelta(days=30),
                status="UYGUN",
                is_active=True,
            ),
            CalibrationRecord(
                company_id=company.id,
                device_code="OK",
                device_name="Uygun cihaz",
                next_calibration_date=date.today() + timedelta(days=90),
                status="UYGUN",
                is_active=True,
            ),
        ]
    )
    db.session.commit()

    with app.test_request_context("/kalibrasyon"):
        g.current_user = user
        g.current_company = company
        g.current_user_is_super_admin = False
        g.enabled_company_modules = {key: True for key in COMPANY_MODULE_KEYS}
        context = calibration_dashboard_context()

    assert context["total_count"] == 3
    assert context["delayed_count"] == 1
    assert context["due_soon_count"] == 1
    assert context["suitable_count"] == 2


def test_disabled_calibration_module_blocks_direct_urls(client):
    enabled_modules = set(COMPANY_MODULE_KEYS) - {"calibration"}
    company = create_company("343", module_keys=enabled_modules, package_key="custom")
    manager = create_user("disabled-calibration-manager", company=company, permissions=("calibration.manage",))
    login(client, manager)

    assert client.get("/kalibrasyon").status_code == 403
    assert client.get("/kalibrasyon/yeni").status_code == 403
