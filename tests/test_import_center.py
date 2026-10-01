from io import BytesIO
from pathlib import Path

from app.extensions import db
from app.models import (
    AppSetting,
    AuditLog,
    CompanyDepartment,
    DataImportBatch,
    PersonnelContact,
    CalibrationRecord,
    SupplierRecord,
)
from app.routes import build_simple_xlsx

from .helpers import assert_xlsx_response, create_company, create_user, login


def _xlsx(headers, rows):
    return build_simple_xlsx(headers, rows, sheet_name="Aktarım").getvalue()


def _upload(client, company, module_key, content, filename="aktarim.xlsx"):
    return client.post(
        "/veri-ice-aktarma/onizle",
        data={
            "company_id": str(company.id),
            "module_key": module_key,
            "source_file": (BytesIO(content), filename),
        },
        content_type="multipart/form-data",
    )


def test_import_center_is_superadmin_only_and_language_buttons_are_hidden(app, client):
    company = create_company("741")
    manager = create_user("import-manager", company=company, role_key="management_representative")
    login(client, manager, company)
    assert client.get("/veri-ice-aktarma").status_code == 403

    superadmin = create_user("superadmin", role_key="super_admin")
    login(client, superadmin)
    page = client.get("/veri-ice-aktarma")
    assert page.status_code == 200
    assert "Veri İçe Aktarma" in page.get_data(as_text=True)
    assert "locale-switcher-sidebar" not in page.get_data(as_text=True)
    with client.session_transaction() as session:
        session.clear()
    assert "locale-switcher-login" not in client.get("/login").get_data(as_text=True)


def test_personnel_preview_apply_duplicate_protection_audit_and_rollback(app, client):
    company = create_company("742")
    other_company = create_company("743")
    superadmin = create_user("superadmin", role_key="super_admin")
    login(client, superadmin)
    workbook = _xlsx(
        ("İsim Soyisim", "Telefon No", "Görev/Ünvan", "E-posta"),
        (
            ("Ayşe Yılmaz", "+90 555 111 22 33", "Kalite Uzmanı", "ayse@example.com"),
            ("Mehmet Demir", "", "Üretim Müdürü", "mehmet@example.com"),
        ),
    )
    response = _upload(client, company, "personnel", workbook)
    assert response.status_code == 302
    batch = DataImportBatch.query.one()
    assert batch.status == "validated"
    assert (batch.total_count, batch.valid_count, batch.warning_count, batch.error_count) == (2, 2, 0, 0)
    assert PersonnelContact.query.filter_by(company_id=company.id).count() == 0
    assert Path(app.config["UPLOAD_FOLDER"], batch.stored_file_path).is_file()

    detail = client.get(response.location)
    assert detail.status_code == 200
    assert "Veriler henüz sisteme yazılmadı" in detail.get_data(as_text=True)
    superadmin.preferred_locale = "en"
    db.session.commit()
    assert client.get("/veri-ice-aktarma").status_code == 200
    applied = client.post(f"/veri-ice-aktarma/{batch.id}/uygula", data={"confirm": "yes"})
    assert applied.status_code == 302
    assert PersonnelContact.query.filter_by(company_id=company.id).count() == 2
    assert PersonnelContact.query.filter_by(company_id=other_company.id).count() == 0
    db.session.refresh(batch)
    assert batch.status == "applied" and batch.created_count == 2
    assert db.session.get(AppSetting, "sales_readiness:competitor_import_center").value == "1"
    assert AuditLog.query.filter_by(
        company_id=company.id, entity_type="DataImportBatch", action="applied"
    ).count() >= 1
    audit_payload = " ".join(
        value
        for row in AuditLog.query.filter_by(entity_type="DataImportBatch").all()
        for value in (row.old_values or "", row.new_values or "")
        if value
    )
    assert "Ayşe Yılmaz" not in audit_payload
    assert "ayse@example.com" not in audit_payload

    rolled_back = client.post(f"/veri-ice-aktarma/{batch.id}/geri-al", data={"confirm": "yes"})
    assert rolled_back.status_code == 302
    assert PersonnelContact.query.filter_by(company_id=company.id).count() == 0
    db.session.refresh(batch)
    assert batch.status == "rolled_back"

    duplicate = _upload(client, company, "personnel", workbook)
    assert duplicate.status_code == 302
    assert duplicate.location.endswith(f"/veri-ice-aktarma/{batch.id}")
    assert DataImportBatch.query.count() == 1


def test_errors_block_apply_and_error_report_is_valid_xlsx(app, client):
    company = create_company("744")
    superadmin = create_user("superadmin", role_key="super_admin")
    login(client, superadmin)
    workbook = _xlsx(
        ("Departman Adı", "Sıralama"),
        (("Kalite", "1"), ("", "iki"), ("Kalite", "3")),
    )
    response = _upload(client, company, "departments", workbook)
    batch = DataImportBatch.query.one()
    assert (batch.valid_count, batch.warning_count, batch.error_count) == (1, 1, 1)
    assert CompanyDepartment.query.filter_by(company_id=company.id).count() == 0
    blocked = client.post(f"/veri-ice-aktarma/{batch.id}/uygula", data={"confirm": "yes"})
    assert blocked.status_code == 409
    assert CompanyDepartment.query.filter_by(company_id=company.id).count() == 0
    assert_xlsx_response(client.get(f"/veri-ice-aktarma/{batch.id}/hata-raporu.xlsx"))


def test_templates_and_unsafe_files(app, client):
    company = create_company("745")
    superadmin = create_user("superadmin", role_key="super_admin")
    login(client, superadmin)
    for module_key in ("departments", "personnel", "calibrations", "suppliers"):
        assert_xlsx_response(client.get(f"/veri-ice-aktarma/sablon/{module_key}.xlsx"))
    invalid = _upload(client, company, "personnel", b"not excel", "bad.exe")
    assert invalid.status_code == 302
    assert DataImportBatch.query.count() == 0


def test_csv_calibration_and_supplier_imports_are_tenant_scoped(app, client):
    company = create_company("746")
    other_company = create_company("747")
    superadmin = create_user("superadmin", role_key="super_admin")
    login(client, superadmin)

    calibration_csv = (
        "Cihaz Kodu;Cihaz / Ekipman;Son Kalibrasyon;Gelecek Kalibrasyon;Durum\n"
        "CK-01;Kumpas;01.09.2026;01.09.2027;UYGUN\n"
    ).encode("utf-8-sig")
    response = _upload(client, company, "calibrations", calibration_csv, "kalibrasyon.csv")
    batch = DataImportBatch.query.order_by(DataImportBatch.id.desc()).first()
    assert response.status_code == 302 and batch.valid_count == 1
    assert client.post(f"/veri-ice-aktarma/{batch.id}/uygula", data={"confirm": "yes"}).status_code == 302
    calibration = CalibrationRecord.query.filter_by(company_id=company.id).one()
    assert calibration.device_code == "CK-01" and calibration.next_calibration_date.isoformat() == "2027-09-01"
    assert CalibrationRecord.query.filter_by(company_id=other_company.id).count() == 0

    supplier_csv = (
        "Tedarikçi No,Tedarikçi Adı,Ürün Grubu,E-posta\n"
        "TED-01,Kalite Metal,Hammadde,tedarik@example.com\n"
    ).encode("utf-8-sig")
    response = _upload(client, other_company, "suppliers", supplier_csv, "tedarikci.csv")
    supplier_batch = DataImportBatch.query.order_by(DataImportBatch.id.desc()).first()
    assert response.status_code == 302 and supplier_batch.company_id == other_company.id
    assert client.post(f"/veri-ice-aktarma/{supplier_batch.id}/uygula", data={"confirm": "yes"}).status_code == 302
    assert SupplierRecord.query.filter_by(company_id=company.id).count() == 0
    assert SupplierRecord.query.filter_by(company_id=other_company.id, supplier_no="TED-01").count() == 1


def test_formula_xlsx_and_unconfirmed_apply_are_rejected(app, client):
    company = create_company("748")
    superadmin = create_user("superadmin", role_key="super_admin")
    login(client, superadmin)
    safe = _xlsx(("Departman Adı", "Sıralama"), (("Kalite", "1"),))
    response = _upload(client, company, "departments", safe)
    batch = DataImportBatch.query.one()
    assert response.status_code == 302
    assert client.post(f"/veri-ice-aktarma/{batch.id}/uygula", data={}).status_code == 400
    assert CompanyDepartment.query.filter_by(company_id=company.id).count() == 0

    import zipfile
    source = BytesIO(safe)
    output = BytesIO()
    with zipfile.ZipFile(source) as archive, zipfile.ZipFile(output, "w") as rewritten:
        for name in archive.namelist():
            content = archive.read(name)
            if name == "xl/worksheets/sheet1.xml":
                content = content.replace(b"<is><t>Kalite</t></is>", b"<f>1+1</f><v>2</v>")
            rewritten.writestr(name, content)
    rejected = _upload(client, company, "departments", output.getvalue(), "formul.xlsx")
    assert rejected.status_code == 302
    assert DataImportBatch.query.count() == 1


def test_rollback_stops_when_an_imported_record_was_changed(app, client):
    company = create_company("749")
    superadmin = create_user("superadmin", role_key="super_admin")
    login(client, superadmin)
    workbook = _xlsx(
        ("İsim Soyisim", "Telefon No", "Görev/Ünvan", "E-posta"),
        (("Güvenli Geri Alma", "555 000 00 00", "Kalite Uzmanı", "geri@example.com"),),
    )
    _upload(client, company, "personnel", workbook)
    batch = DataImportBatch.query.one()
    assert client.post(f"/veri-ice-aktarma/{batch.id}/uygula", data={"confirm": "yes"}).status_code == 302

    contact = PersonnelContact.query.filter_by(company_id=company.id).one()
    contact.title = "Kalite Yöneticisi"
    db.session.commit()

    blocked = client.post(f"/veri-ice-aktarma/{batch.id}/geri-al", data={"confirm": "yes"})
    assert blocked.status_code == 409
    assert PersonnelContact.query.filter_by(company_id=company.id).one().title == "Kalite Yöneticisi"
    db.session.refresh(batch)
    assert batch.status == "applied"
