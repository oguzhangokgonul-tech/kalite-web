from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter

from flask import g

from app.extensions import db
from app.models import AuditLog, COMPANY_MODULE_KEYS, CalibrationCertificate, CalibrationRecord
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
    assert client.get("/mobil/kalibrasyon").status_code == 403
    assert client.get("/kalibrasyon/1/pdf").status_code == 403
    assert client.get("/kalibrasyon/1/pdf/1/indir").status_code == 403


def pdf_file():
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(output)
    output.seek(0)
    return output


def image_file(color):
    output = BytesIO()
    Image.new("RGB", (120, 160), color).save(output, "JPEG")
    output.seek(0)
    return output


def test_calibration_pdf_upload_download_history_and_scan(client, app):
    company = create_company("344")
    manager = create_user("cal-pdf-manager", company=company, permissions=("calibration.manage",))
    record = CalibrationRecord(company_id=company.id, device_code="CK99", device_name="Ölçüm cihazı")
    db.session.add(record)
    db.session.commit()
    login(client, manager)

    hub = client.get("/mobil")
    assert b"/mobil/kalibrasyon" in hub.data
    mobile = client.get("/mobil/kalibrasyon")
    assert mobile.status_code == 200
    assert "PDF Tara" in mobile.get_data(as_text=True)
    assert "PDF Ekle" in client.get("/kalibrasyon").get_data(as_text=True)

    response = client.post(
        f"/kalibrasyon/{record.id}/pdf",
        data={"mode": "upload", "pdf": (pdf_file(), "sertifika.pdf")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    certificate = CalibrationCertificate.query.one()
    assert certificate.company_id == company.id
    assert certificate.sha256
    assert AuditLog.query.filter_by(entity_type="CalibrationCertificate", action="uploaded").count() == 1

    download = client.get(f"/kalibrasyon/{record.id}/pdf/{certificate.id}/indir")
    assert download.status_code == 200
    assert len(PdfReader(BytesIO(download.data)).pages) == 1
    assert "no-store" in download.headers["Cache-Control"]

    response = client.post(
        f"/kalibrasyon/{record.id}/pdf",
        data={"mode": "scan", "pages": [
            (image_file("red"), "bir.jpg"), (image_file("blue"), "iki.jpg")
        ]},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    assert CalibrationCertificate.query.count() == 2
    scanned = CalibrationCertificate.query.filter(CalibrationCertificate.id != certificate.id).one()
    scanned_file = client.get(f"/kalibrasyon/{record.id}/pdf/{scanned.id}/indir")
    assert len(PdfReader(BytesIO(scanned_file.data)).pages) == 2
    db.session.refresh(record)
    assert record.status == "UYGUN"
    assert record.next_calibration_date is None
    assert client.post(f"/kalibrasyon/{record.id}/sil").status_code == 302
    assert db.session.get(CalibrationRecord, record.id) is not None


def test_calibration_pdf_validation_permissions_and_tenant(client, app):
    company_a = create_company("345")
    company_b = create_company("346")
    manager_a = create_user("cal-a", company=company_a, permissions=("calibration.manage",))
    manager_b = create_user("cal-b", company=company_b, permissions=("calibration.manage",))
    viewer = create_user("cal-view", company=company_a)
    record = CalibrationRecord(company_id=company_a.id, device_code="CK45", device_name="Terazi")
    db.session.add(record)
    db.session.commit()

    login(client, manager_a)
    invalid = client.post(
        f"/kalibrasyon/{record.id}/pdf",
        data={"mode": "upload", "pdf": (BytesIO(b"not-a-pdf"), "bad.pdf")},
        content_type="multipart/form-data",
    )
    assert invalid.status_code == 400
    assert CalibrationCertificate.query.count() == 0
    assert not list(Path(app.config["UPLOAD_FOLDER"]).rglob("*.pdf"))

    uploaded = client.post(
        f"/kalibrasyon/{record.id}/pdf",
        data={"mode": "upload", "pdf": (pdf_file(), "good.pdf")},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 302
    certificate = CalibrationCertificate.query.one()

    login(client, viewer)
    assert client.get(f"/kalibrasyon/{record.id}/pdf/{certificate.id}/indir").status_code == 200
    assert client.get(f"/kalibrasyon/{record.id}/pdf").status_code == 200
    assert client.post(f"/kalibrasyon/{record.id}/pdf", data={"mode": "upload"}).status_code == 403

    login(client, manager_b)
    assert client.get(f"/kalibrasyon/{record.id}/pdf/{certificate.id}/indir").status_code == 404
    assert client.post(f"/kalibrasyon/{record.id}/pdf", data={"mode": "upload"}).status_code == 404

    inconsistent = CalibrationCertificate(
        company_id=company_b.id,
        calibration_record_id=record.id,
        original_name="foreign.pdf",
        stored_path=f"company-{company_b.id:03d}/calibration/{record.id}/foreign.pdf",
        size_bytes=1,
        sha256="0" * 64,
        uploaded_by_user_id=manager_b.id,
    )
    db.session.add(inconsistent)
    db.session.commit()
    db.session.expire_all()
    login(client, viewer)
    assert "foreign.pdf" not in client.get(f"/kalibrasyon/{record.id}/pdf").get_data(as_text=True)
    assert client.get(f"/kalibrasyon/{record.id}/pdf/{inconsistent.id}/indir").status_code == 404


def test_calibration_pdf_rejects_bad_scan_quota_and_missing_csrf(client, app):
    company = create_company("347")
    manager = create_user("cal-secure", company=company, permissions=("calibration.manage",))
    record = CalibrationRecord(company_id=company.id, device_code="CK47", device_name="Kumpas")
    db.session.add(record)
    db.session.commit()
    login(client, manager)

    bad_scan = client.post(
        f"/kalibrasyon/{record.id}/pdf",
        data={"mode": "scan", "pages": (BytesIO(b"fake-image"), "page.jpg")},
        content_type="multipart/form-data",
    )
    assert bad_scan.status_code == 400
    assert CalibrationCertificate.query.count() == 0

    company.storage_quota_mb = 1
    db.session.commit()
    company_folder = Path(app.config["UPLOAD_FOLDER"]) / f"company-{company.id:03d}"
    company_folder.mkdir(parents=True)
    (company_folder / "existing.bin").write_bytes(b"x" * (1024 * 1024))
    quota_response = client.post(
        f"/kalibrasyon/{record.id}/pdf",
        data={"mode": "upload", "pdf": (pdf_file(), "good.pdf")},
        content_type="multipart/form-data",
    )
    assert quota_response.status_code == 400
    assert CalibrationCertificate.query.count() == 0
    assert not list(company_folder.rglob("*.pdf"))

    app.config["WTF_CSRF_ENABLED"] = True
    try:
        csrf_response = client.post(
            f"/kalibrasyon/{record.id}/pdf",
            data={"mode": "upload", "pdf": (pdf_file(), "good.pdf")},
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )
        assert csrf_response.status_code == 400
        assert CalibrationCertificate.query.count() == 0
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_calibration_scan_limits_total_decoded_pixels(client):
    company = create_company("348")
    manager = create_user("cal-pixels", company=company, permissions=("calibration.manage",))
    record = CalibrationRecord(company_id=company.id, device_code="CK48", device_name="Sayaç")
    db.session.add(record)
    db.session.commit()
    login(client, manager)
    pages = []
    for index in range(6):
        output = BytesIO()
        Image.new("RGB", (2400, 2400), "white").save(output, "JPEG")
        output.seek(0)
        pages.append((output, f"{index}.jpg"))
    response = client.post(
        f"/kalibrasyon/{record.id}/pdf",
        data={"mode": "scan", "pages": pages},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert CalibrationCertificate.query.count() == 0
