from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from app.extensions import db
from app.models import (
    AppSetting,
    AuditLog,
    CompanyDepartment,
    ComplianceObligation,
    EnvironmentalAspect,
    EnvironmentalAspectAssessment,
    EnvironmentalAspectFile,
    Notification,
    RiskRecord,
    WasteBatch,
    WasteMovement,
    WasteMovementFile,
    WasteStream,
)
from app.reminders import generate_due_reminders
from app.seed import ensure_runtime_schema
from .helpers import assert_xlsx_response, create_company, create_user, login


ALL_PERMISSIONS = (
    "environmental.view", "environmental.view_all", "environmental.create", "environmental.update",
    "environmental.assess", "environmental.approve", "environmental.waste_manage",
    "environmental.shipment", "environmental.archive", "environmental.export",
    "environmental.file_download", "environmental.manage",
)


def department(company, name="Üretim"):
    row = CompanyDepartment(company_id=company.id, name=name, sort_order=1, is_active=True)
    db.session.add(row); db.session.commit()
    return row


def aspect_payload(dept, responsible, reviewer, **overrides):
    values = {
        "department_id": str(dept.id), "process": "Metal İşleme", "activity": "Parça temizleme",
        "aspect": "Atık yağ oluşumu", "impact": "Toprak ve su kirliliği",
        "lifecycle_stage": "Üretim", "operating_condition": "Normal", "influence_type": "Doğrudan Kontrol",
        "existing_controls": "Sızdırmaz kap ve ikincil hazne", "emergency_response": "Döküntü kiti kullanılır.",
        "matrix_version": "V1", "significance_threshold": "40",
        "review_due_date": (date.today() + timedelta(days=90)).isoformat(),
        "responsible_user_id": str(responsible.id), "reviewer_user_id": str(reviewer.id),
        "severity": "5", "frequency": "4", "legal_score": "5", "stakeholder_score": "3",
        "control_effectiveness": "3", "assessment_rationale": "Yasal takip ve sızıntı riski nedeniyle.",
    }
    values.update(overrides)
    return values


def create_aspect(client, dept, responsible, reviewer, **overrides):
    data = aspect_payload(dept, responsible, reviewer, **overrides)
    data["evidence_file"] = (BytesIO(b"%PDF-1.4 aspect"), "etki-analizi.pdf")
    return client.post("/cevre-yonetimi/boyut/yeni", data=data, content_type="multipart/form-data", follow_redirects=True)


def test_environmental_aspect_versioned_workflow_audit_report_and_isolation(app, client):
    company = create_company("771"); other = create_company("772")
    dept = department(company)
    creator = create_user("env-creator", company=company, permissions=("environmental.view", "environmental.create", "environmental.file_download"))
    responsible = create_user("env-owner", company=company, permissions=("environmental.view", "environmental.update", "environmental.assess", "environmental.file_download"))
    reviewer = create_user("env-reviewer", company=company, permissions=("environmental.view", "environmental.approve", "environmental.file_download"))
    outsider = create_user("env-outsider", company=other, permissions=ALL_PERMISSIONS)
    manager = create_user("env-manager", company=company, permissions=ALL_PERMISSIONS)
    viewer = create_user("env-viewer", company=company, permissions=("environmental.view", "environmental.file_download"))
    risk = RiskRecord(
        company_id=company.id, risk_no="RSK-2026-0771", title="Atık yağ sızıntısı",
        department="Üretim", owner_user_id=responsible.id, likelihood=4, severity=5,
        due_date=date.today() + timedelta(days=60),
    )
    db.session.add(risk)
    db.session.flush()
    obligation = ComplianceObligation(
        company_id=company.id,
        obligation_no="MEV-2026-0771",
        title="Atik yaglarin yonetimi",
        category="Cevre",
        obligation_type="Yasal",
        department=dept.name,
        owner_user_id=responsible.id,
        criticality="high",
        next_review_date=date.today() + timedelta(days=180),
        status="active",
        created_by_user_id=creator.id,
    )
    db.session.add(obligation)
    db.session.commit()

    login(client, creator)
    assert client.get("/cevre-yonetimi/parametreler").status_code == 403
    invalid = create_aspect(client, dept, viewer, reviewer)
    assert "gerekli yetkilere sahip değil" in invalid.get_data(as_text=True)
    assert EnvironmentalAspect.query.count() == 0
    response = create_aspect(
        client,
        dept,
        responsible,
        reviewer,
        risk_id=str(risk.id),
        compliance_obligation_id=str(obligation.id),
    )
    assert response.status_code == 200 and "CEV-2026-0001" in response.get_data(as_text=True)
    row = EnvironmentalAspect.query.one(); first = EnvironmentalAspectAssessment.query.one()
    assert row.status == "Taslak" and first.inherent_score == 100 and first.residual_score == 60 and first.is_significant

    evidence = EnvironmentalAspectFile.query.one()
    login(client, viewer)
    assert client.get(f"/cevre-yonetimi/boyut/{row.id}").status_code == 404
    assert client.get(f"/cevre-yonetimi/boyut-dosya/{evidence.id}").status_code == 404

    login(client, outsider)
    assert client.get(f"/cevre-yonetimi/boyut/{row.id}").status_code == 404

    login(client, responsible)
    assert row.aspect_no in client.get("/uzerime-atananlar?module=environmental").get_data(as_text=True)
    assert client.post(f"/cevre-yonetimi/boyut/{row.id}/onaya-gonder").status_code == 302
    db.session.refresh(row); assert row.status == "Onay Bekliyor"

    login(client, reviewer)
    assert client.post(f"/cevre-yonetimi/boyut/{row.id}/degerlendir", data={"decision": "approve", "note": "Kontroller uygun."}).status_code == 302
    db.session.refresh(row); db.session.refresh(first)
    assert row.status == "Aktif" and first.review_status == "Onaylandı"
    assert first.reviewed_by_user_id == reviewer.id and first.reviewed_at is not None

    login(client, viewer)
    assert client.get(f"/cevre-yonetimi/boyut-dosya/{evidence.id}").status_code == 200
    assert AuditLog.query.filter_by(entity_type="EnvironmentalAspectFile", entity_id=str(evidence.id), action="downloaded").count() == 1

    login(client, manager)
    response = client.post("/cevre-yonetimi/parametreler", data={
        "matrix_version": "V2", "significance_threshold": "55",
    }, follow_redirects=True)
    assert response.status_code == 200 and "parametreleri güncellendi" in response.get_data(as_text=True)

    login(client, responsible)
    response = client.post(f"/cevre-yonetimi/boyut/{row.id}/yeniden-degerlendir", data={
        "severity": "4", "frequency": "2", "legal_score": "5", "stakeholder_score": "2",
        "control_effectiveness": "5", "assessment_rationale": "Yeni kapalı sistem devrede.",
        "review_due_date": (date.today() + timedelta(days=365)).isoformat(),
    })
    assert response.status_code == 302
    db.session.refresh(row)
    assert row.status == "Onay Bekliyor" and EnvironmentalAspectAssessment.query.count() == 2
    assert first.inherent_score == 100 and first.residual_score == 60
    assert row.current_assessment.review_status == "Bekliyor"
    assert row.current_assessment.matrix_version == "V2" and row.current_assessment.significance_threshold == 55

    login(client, manager)
    assert_xlsx_response(client.get("/cevre-yonetimi/rapor.xlsx"))
    assert AuditLog.query.filter_by(entity_type="EnvironmentalAspect", entity_id=row.id).count() >= 1
    assert AuditLog.query.filter_by(entity_type="EnvironmentalReport", action="exported").count() == 1


def test_waste_chain_requires_evidence_and_reconciles_quantity(app, client):
    company = create_company("773"); dept = department(company)
    manager = create_user("waste-manager", company=company, permissions=ALL_PERMISSIONS)
    reviewer = create_user("waste-reviewer", company=company, permissions=("environmental.view", "environmental.approve", "environmental.file_download"))
    login(client, manager)
    response = client.post("/cevre-yonetimi/atik-akisi/yeni", data={
        "waste_code": "13 02 05*", "name": "Atık motor yağı", "is_hazardous": "1",
        "department_id": str(dept.id), "source_process": "Bakım", "storage_location": "Atık Alanı A",
        "unit": "kg", "maximum_capacity": "100", "maximum_storage_days": "30",
        "responsible_user_id": str(manager.id),
    }, follow_redirects=True)
    assert response.status_code == 200 and "13 02 05*" in response.get_data(as_text=True)
    stream = WasteStream.query.one()
    response = client.post(f"/cevre-yonetimi/atik-akisi/{stream.id}/parti", data={
        "generated_date": date.today().isoformat(), "quantity": "25", "container_count": "2",
        "reviewer_user_id": str(reviewer.id), "note": "Sahadan teslim alındı.",
    }, follow_redirects=True)
    assert response.status_code == 200 and "ATK-2026-0001" in response.get_data(as_text=True)
    batch = WasteBatch.query.one(); assert batch.remaining_quantity == Decimal("25.000")
    assert WasteMovement.query.one().movement_type == "Oluşum"

    client.post(f"/cevre-yonetimi/atik/{batch.id}/sevke-hazirla")
    response = client.post(f"/cevre-yonetimi/atik/{batch.id}/teslim", data={
        "carrier_name": "Lisanslı Taşıma AŞ", "carrier_license_no": "T-123",
        "receiving_facility": "Geri Kazanım Tesisi", "facility_license_no": "G-456",
        "motat_reference": "MOTAT-2026-1", "quantity": "25",
    }, follow_redirects=True)
    assert "Kanıt dosyası zorunludur" in response.get_data(as_text=True)
    db.session.refresh(batch); assert batch.status == "Sevk Bekliyor" and batch.remaining_quantity == Decimal("25.000")

    response = client.post(f"/cevre-yonetimi/atik/{batch.id}/teslim", data={
        "carrier_name": "Lisanslı Taşıma AŞ", "carrier_license_no": "T-123",
        "receiving_facility": "Geri Kazanım Tesisi", "facility_license_no": "G-456",
        "motat_reference": "MOTAT-2026-1", "abs_declaration_no": "ABS-1", "quantity": "25",
        "evidence_file": (BytesIO(b"%PDF-1.4 transfer"), "motat.pdf"),
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    db.session.refresh(batch); assert batch.status == "Taşıyıcıya Teslim" and batch.remaining_quantity == 0

    login(client, reviewer)
    response = client.post(f"/cevre-yonetimi/atik/{batch.id}/tesis-kabulu", data={
        "accepted_quantity": "24.5", "note": "Tesis tartımı",
        "evidence_file": (BytesIO(b"%PDF-1.4 acceptance"), "kabul.pdf"),
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    db.session.refresh(batch); assert batch.status == "Mutabakat Bekliyor"
    response = client.post(f"/cevre-yonetimi/atik/{batch.id}/mutabakat", data={
        "note": "Nem kaybı tutanakla doğrulandı.",
        "evidence_file": (BytesIO(b"%PDF-1.4 reconciliation"), "mutabakat.pdf"),
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    db.session.refresh(batch)
    assert batch.status == "Tamamlandı" and batch.completed_at is not None
    assert WasteMovement.query.count() == 5 and WasteMovementFile.query.count() == 3


def test_waste_capacity_self_approval_and_company_scope_are_blocked(app, client):
    company = create_company("774"); other = create_company("775"); dept = department(company)
    manager = create_user("scope-manager", company=company, permissions=ALL_PERMISSIONS)
    reviewer = create_user("scope-reviewer", company=company, permissions=ALL_PERMISSIONS)
    outsider = create_user("scope-outsider", company=other, permissions=ALL_PERMISSIONS)
    stream = WasteStream(company_id=company.id, waste_code="15 01 10*", name="Kontamine ambalaj", is_hazardous=True, department_id=dept.id, source_process="Üretim", storage_location="Atık Alanı", unit="kg", maximum_capacity=Decimal("10"), maximum_storage_days=30, responsible_user_id=manager.id, created_by_user_id=manager.id)
    db.session.add(stream); db.session.commit()
    login(client, manager)
    response = client.post(f"/cevre-yonetimi/atik-akisi/{stream.id}/parti", data={"generated_date": date.today().isoformat(), "quantity": "5", "reviewer_user_id": str(manager.id)}, follow_redirects=True)
    assert "kendi" in response.get_data(as_text=True)
    client.post(f"/cevre-yonetimi/atik-akisi/{stream.id}/parti", data={"generated_date": date.today().isoformat(), "quantity": "8", "reviewer_user_id": str(reviewer.id)})
    response = client.post(f"/cevre-yonetimi/atik-akisi/{stream.id}/parti", data={"generated_date": date.today().isoformat(), "quantity": "3", "reviewer_user_id": str(reviewer.id)}, follow_redirects=True)
    assert "kapasitesini aşıyor" in response.get_data(as_text=True)
    batch = WasteBatch.query.one()
    response = client.post(f"/cevre-yonetimi/atik-akisi/{stream.id}/parti", data={"generated_date": (date.today() + timedelta(days=1)).isoformat(), "quantity": "1", "reviewer_user_id": str(reviewer.id)}, follow_redirects=True)
    assert "gelecekte olamaz" in response.get_data(as_text=True)
    response = client.post(f"/cevre-yonetimi/atik/{batch.id}/iptal", data={"reason": "Yanlış tartım kaydı."}, follow_redirects=True)
    db.session.refresh(batch)
    assert response.status_code == 200 and batch.status == "İptal"
    assert WasteMovement.query.filter_by(batch_id=batch.id, movement_type="İptal").one()
    login(client, outsider)
    assert client.get(f"/cevre-yonetimi/atik/{batch.id}").status_code == 404


def test_department_manager_cannot_access_another_departments_waste(app, client):
    company = create_company("777")
    own_department = department(company, "Üretim")
    other_department = department(company, "Lojistik")
    manager = create_user("department-env-manager", company=company, role_key="department_manager", title="Üretim Müdürü")
    approver = create_user("department-env-approver", company=company, permissions=("environmental.view", "environmental.approve"))
    stream = WasteStream(
        company_id=company.id, waste_code="20 01 01", name="Kağıt", is_hazardous=False,
        department_id=other_department.id, source_process="Sevkiyat", storage_location="Lojistik Deposu",
        unit="kg", maximum_storage_days=30, responsible_user_id=approver.id,
        created_by_user_id=approver.id,
    )
    db.session.add(stream); db.session.commit()

    login(client, manager)
    assert client.get(f"/cevre-yonetimi/atik-akisi/{stream.id}").status_code == 403
    assert client.post(f"/cevre-yonetimi/atik-akisi/{stream.id}/parti", data={
        "generated_date": date.today().isoformat(), "quantity": "1", "reviewer_user_id": str(approver.id),
    }).status_code == 403
    page = client.get("/cevre-yonetimi").get_data(as_text=True)
    assert "20 01 01" not in page and own_department.name in {row.name for row in CompanyDepartment.query.filter_by(company_id=company.id)}


def test_environmental_reminders_runtime_checklist_and_menu(app, client):
    company = create_company("776"); dept = department(company)
    owner = create_user("reminder-owner", company=company, permissions=ALL_PERMISSIONS)
    reviewer = create_user("reminder-reviewer", company=company, permissions=ALL_PERMISSIONS)
    aspect = EnvironmentalAspect(company_id=company.id, aspect_no="CEV-2026-0099", department_id=dept.id, process="Boya", activity="Boyama", aspect="VOC salımı", impact="Hava kirliliği", lifecycle_stage="Üretim", operating_condition="Normal", influence_type="Doğrudan Kontrol", existing_controls="Filtre", matrix_version="V1", significance_threshold=40, responsible_user_id=owner.id, reviewer_user_id=reviewer.id, created_by_user_id=owner.id, review_due_date=date.today(), status="Aktif")
    stream = WasteStream(company_id=company.id, waste_code="08 01 11*", name="Atık boya", is_hazardous=True, department_id=dept.id, source_process="Boya", storage_location="Atık Deposu", unit="kg", maximum_storage_days=1, responsible_user_id=owner.id, created_by_user_id=owner.id)
    db.session.add_all([aspect, stream]); db.session.flush()
    batch = WasteBatch(company_id=company.id, batch_no="ATK-2026-0099", stream=stream, generated_date=date.today() - timedelta(days=2), storage_due_date=date.today() - timedelta(days=1), initial_quantity=Decimal("2"), remaining_quantity=Decimal("2"), storage_location="Atık Deposu", responsible_user_id=owner.id, reviewer_user_id=reviewer.id, created_by_user_id=owner.id)
    db.session.add(batch); db.session.commit()
    stats = generate_due_reminders(company_id=company.id, run_date=date.today())
    assert stats["notifications"] >= 4
    assert Notification.query.filter(Notification.source_key.like("environmental-%")).count() >= 4

    AppSetting.query.filter_by(key="sales_readiness:competitor_environmental_aspects").delete(); db.session.commit()
    ensure_runtime_schema()
    assert db.session.get(AppSetting, "sales_readiness:competitor_environmental_aspects").value == "1"
    login(client, owner)
    page = client.get("/cevre-yonetimi")
    assert page.status_code == 200 and "Çevre ve Atık Yönetimi" in page.get_data(as_text=True)
