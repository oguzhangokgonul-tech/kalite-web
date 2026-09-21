from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from app.extensions import db
from app.models import (
    AppSetting,
    AuditLog,
    CompanyDepartment,
    EnergyMeter,
    EnergyReading,
    EnergySavingProject,
    EnergySavingVerification,
    EnergyTarget,
    Notification,
)
from app.reminders import generate_due_reminders
from app.seed import ensure_runtime_schema
from .helpers import assert_xlsx_response, create_company, create_user, login


ALL_PERMISSIONS = (
    "energy.view", "energy.view_all", "energy.create", "energy.meter_manage",
    "energy.project_manage", "energy.approve", "energy.archive", "energy.export",
    "energy.file_download", "energy.manage",
    "reports.view", "reports.export",
)


def department(company, name="Üretim"):
    row = CompanyDepartment(company_id=company.id, name=name, sort_order=1, is_active=True)
    db.session.add(row); db.session.commit()
    return row


def meter_payload(dept, owner, reviewer, code="ELK-01"):
    return {
        "meter_code": code, "name": "Ana Elektrik Sayacı", "energy_type": "Elektrik",
        "unit": "kWh", "department_id": str(dept.id), "location": "Ana Pano",
        "serial_no": "SN-100", "multiplier": "2", "emission_factor": "0.45",
        "reading_due_day": "5", "responsible_user_id": str(owner.id),
        "reviewer_user_id": str(reviewer.id),
    }


def test_energy_reading_is_calculated_approved_audited_and_isolated(app, client):
    company = create_company("881"); other = create_company("882"); dept = department(company)
    manager = create_user("energy-manager", company=company, permissions=ALL_PERMISSIONS)
    owner = create_user("energy-owner", company=company, permissions=("energy.view", "energy.create", "energy.project_manage", "energy.file_download"))
    reviewer = create_user("energy-reviewer", company=company, permissions=("energy.view", "energy.approve", "energy.file_download"))
    outsider = create_user("energy-outsider", company=other, permissions=ALL_PERMISSIONS)

    login(client, manager)
    response = client.post("/enerji-yonetimi/sayac/yeni", data=meter_payload(dept, owner, reviewer), follow_redirects=True)
    assert response.status_code == 200 and "ELK-01" in response.get_data(as_text=True)
    meter = EnergyMeter.query.one()

    login(client, owner)
    response = client.post(f"/enerji-yonetimi/sayac/{meter.id}/okuma/yeni", data={
        "period": date.today().replace(day=1).isoformat(), "previous_value": "100",
        "current_value": "150", "production_quantity": "10", "production_unit": "ton",
        "unit_cost": "3.5", "note": "Aylık fatura ile doğrulandı.",
        "evidence_file": (BytesIO(b"%PDF-1.4 energy"), "fatura.pdf"),
    }, content_type="multipart/form-data", follow_redirects=True)
    assert response.status_code == 200
    reading = EnergyReading.query.one()
    assert reading.consumption == Decimal("100.000")
    assert reading.normalized_consumption == Decimal("10.000000")
    assert reading.total_cost == Decimal("350.00")
    assert reading.emission_kg == Decimal("45.000")
    assert reading.multiplier_snapshot == Decimal("2.0000")

    self_review = client.post(f"/enerji-yonetimi/okuma/{reading.id}/degerlendir", data={"decision": "approve"})
    assert self_review.status_code == 403
    login(client, reviewer)
    assert client.post(f"/enerji-yonetimi/okuma/{reading.id}/degerlendir", data={"decision": "approve"}).status_code == 302
    db.session.refresh(reading); assert reading.status == "Onaylandı"
    assert client.get(f"/enerji-yonetimi/kanit/reading/{reading.id}").status_code == 200

    login(client, outsider)
    assert client.get(f"/enerji-yonetimi/sayac/{meter.id}").status_code == 404
    assert client.get(f"/enerji-yonetimi/okuma/{reading.id}").status_code == 404
    login(client, manager)
    assert_xlsx_response(client.get("/enerji-yonetimi/rapor.xlsx"))
    assert_xlsx_response(client.get("/rapor-merkezi/energy_consumption/excel"))
    assert AuditLog.query.filter_by(entity_type="EnergyReport", action="exported").count() == 1


def test_energy_prevents_duplicate_period_negative_consumption_and_self_approval(app, client):
    company = create_company("883"); dept = department(company)
    manager = create_user("energy-manager-2", company=company, permissions=ALL_PERMISSIONS)
    owner = create_user("energy-owner-2", company=company, permissions=("energy.view", "energy.create"))
    reviewer = create_user("energy-reviewer-2", company=company, permissions=("energy.view", "energy.approve"))
    login(client, manager)
    invalid = meter_payload(dept, owner, owner)
    response = client.post("/enerji-yonetimi/sayac/yeni", data=invalid, follow_redirects=True)
    assert response.status_code == 200
    assert EnergyMeter.query.count() == 0
    client.post("/enerji-yonetimi/sayac/yeni", data=meter_payload(dept, owner, reviewer))
    meter = EnergyMeter.query.one()
    login(client, owner)
    period = date.today().replace(day=1).isoformat()
    response = client.post(f"/enerji-yonetimi/sayac/{meter.id}/okuma/yeni", data={"period": period, "previous_value": "20", "current_value": "10"}, follow_redirects=True)
    assert "küçük olamaz" in response.get_data(as_text=True)
    client.post(f"/enerji-yonetimi/sayac/{meter.id}/okuma/yeni", data={"period": period, "previous_value": "10", "current_value": "20"})
    response = client.post(f"/enerji-yonetimi/sayac/{meter.id}/okuma/yeni", data={"period": period, "previous_value": "20", "current_value": "30"}, follow_redirects=True)
    assert "kayıt bulunuyor" in response.get_data(as_text=True) and EnergyReading.query.count() == 1
    reading = EnergyReading.query.one(); reading.status = "Reddedildi"; db.session.commit()
    client.post(f"/enerji-yonetimi/sayac/{meter.id}/okuma/yeni", data={"period": period, "previous_value": "20", "current_value": "35"})
    assert EnergyReading.query.count() == 2
    current = EnergyReading.query.filter_by(is_current=True).one()
    assert current.version_no == 2 and current.supersedes_id == reading.id
    db.session.refresh(reading); assert not reading.is_current


def test_energy_target_and_saving_project_independent_workflow(app, client):
    company = create_company("884"); dept = department(company)
    manager = create_user("energy-manager-3", company=company, permissions=ALL_PERMISSIONS)
    owner = create_user("energy-owner-3", company=company, permissions=("energy.view", "energy.create", "energy.project_manage", "energy.file_download"))
    reviewer = create_user("energy-reviewer-3", company=company, permissions=("energy.view", "energy.approve", "energy.file_download"))
    login(client, manager); client.post("/enerji-yonetimi/sayac/yeni", data=meter_payload(dept, owner, reviewer)); meter = EnergyMeter.query.one()
    response = client.post("/enerji-yonetimi/hedef/yeni", data={
        "title": "Elektrik yoğunluğunu azalt", "meter_id": str(meter.id), "baseline_year": str(date.today().year - 1),
        "baseline_consumption": "120000", "reduction_percent": "8", "target_date": (date.today() + timedelta(days=180)).isoformat(),
        "responsible_user_id": str(owner.id), "approver_user_id": str(reviewer.id),
    })
    assert response.status_code == 302
    target = EnergyTarget.query.one()
    login(client, owner); assert client.post(f"/enerji-yonetimi/hedef/{target.id}/onaya-gonder").status_code == 302
    login(client, manager); assert client.post(f"/enerji-yonetimi/hedef/{target.id}/arsivle").status_code == 409
    login(client, reviewer); client.post(f"/enerji-yonetimi/hedef/{target.id}/degerlendir", data={"decision": "approve"})
    db.session.refresh(target); assert target.status == "Aktif"
    login(client, owner); client.post(f"/enerji-yonetimi/hedef/{target.id}/tamamla", data={"actual_consumption": "108000", "completion_note": "Yıllık tüketim doğrulandı."})
    db.session.refresh(target); assert target.status == "Tamamlama Onayı"
    login(client, reviewer); client.post(f"/enerji-yonetimi/hedef/{target.id}/degerlendir", data={"decision": "approve", "review_note": "Hedef sağlandı."})
    db.session.refresh(target); assert target.status == "Tamamlandı" and target.completed_at is not None

    login(client, manager)
    client.post("/enerji-yonetimi/tasarruf/yeni", data={
        "title": "Kompresör kaçaklarını azalt", "description": "Hat kaçaklarının giderilmesi",
        "meter_id": str(meter.id), "planned_saving": "15000", "investment_cost": "25000",
        "start_date": date.today().isoformat(), "due_date": (date.today() + timedelta(days=30)).isoformat(),
        "responsible_user_id": str(owner.id), "approver_user_id": str(reviewer.id),
    })
    project = EnergySavingProject.query.one()
    login(client, owner); client.post(f"/enerji-yonetimi/tasarruf/{project.id}/baslat")
    client.post(f"/enerji-yonetimi/tasarruf/{project.id}/tamamla", data={
        "actual_saving": "14000", "completion_note": "Sayaç karşılaştırması tamamlandı.",
        "evidence_file": (BytesIO(b"%PDF-1.4 verify"), "dogrulama.pdf"),
    }, content_type="multipart/form-data")
    db.session.refresh(project); assert project.status == "Doğrulama Bekliyor"
    login(client, reviewer); client.post(f"/enerji-yonetimi/tasarruf/{project.id}/dogrula", data={"decision": "reject", "verification_note": "İkinci sayaç fotoğrafı gerekli."})
    db.session.refresh(project); assert project.status == "Devam Ediyor"
    first_verification = EnergySavingVerification.query.one()
    assert first_verification.decision == "Reddedildi" and first_verification.evidence_hash
    login(client, owner); client.post(f"/enerji-yonetimi/tasarruf/{project.id}/tamamla", data={
        "actual_saving": "14000", "completion_note": "Eksik sayaç fotoğrafı eklendi.",
        "evidence_file": (BytesIO(b"%PDF-1.4 verify-v2"), "dogrulama-v2.pdf"),
    }, content_type="multipart/form-data")
    login(client, reviewer); client.post(f"/enerji-yonetimi/tasarruf/{project.id}/dogrula", data={"decision": "approve", "verification_note": "Tasarruf doğrulandı.", "financial_saving": "42000"})
    db.session.refresh(project); assert project.status == "Tamamlandı"
    verification = EnergySavingVerification.query.filter_by(decision="Onaylandı").one()
    assert verification.actual_saving == Decimal("14000.000") and verification.version_no == 2
    assert verification.decision == "Onaylandı" and verification.evidence_hash
    assert EnergySavingVerification.query.count() == 2 and verification.version_no == 2


def test_energy_reminders_tasks_and_checklist(app, client):
    company = create_company("885"); dept = department(company)
    manager = create_user("energy-manager-4", company=company, permissions=ALL_PERMISSIONS)
    reviewer = create_user("energy-reviewer-4", company=company, permissions=ALL_PERMISSIONS)
    meter = EnergyMeter(company_id=company.id, meter_code="DG-01", name="Doğal Gaz", energy_type="Doğal Gaz", unit="m³", department_id=dept.id, location="Kazan Dairesi", multiplier=1, emission_factor=2, reading_due_day=1, responsible_user_id=manager.id, reviewer_user_id=reviewer.id, created_by_user_id=manager.id)
    db.session.add(meter); db.session.flush()
    project = EnergySavingProject(company_id=company.id, project_no="ENT-2026-0099", title="Kazan optimizasyonu", description="Yanma ayarı", meter_id=meter.id, planned_saving=100, start_date=date.today() - timedelta(days=30), due_date=date.today() - timedelta(days=1), responsible_user_id=manager.id, approver_user_id=reviewer.id, created_by_user_id=manager.id)
    db.session.add(project); db.session.commit()
    stats = generate_due_reminders(company_id=company.id, run_date=date.today())
    assert stats["notifications"] >= 2
    assert Notification.query.filter(Notification.source_key.like("energy-%")).count() >= 2
    login(client, manager)
    page = client.get("/uzerime-atananlar?module=energy").get_data(as_text=True)
    assert "ENT-2026-0099" in page and "DG-01" in page

    AppSetting.query.filter(AppSetting.key.in_(("sales_readiness:competitor_energy_management", "sales_readiness:module_energy_consumption_tracking"))).delete(synchronize_session=False)
    db.session.commit(); ensure_runtime_schema()
    assert db.session.get(AppSetting, "sales_readiness:competitor_energy_management").value == "1"
    assert db.session.get(AppSetting, "sales_readiness:module_energy_consumption_tracking").value == "1"


def test_department_scope_applies_to_assignments_records_and_dashboard_counts(app, client):
    company = create_company("886")
    production = department(company, "Üretim")
    logistics = department(company, "Lojistik")
    manager = create_user("energy-dept-manager", company=company, role_key="department_manager", title="Üretim Müdürü")
    own_owner = create_user("energy-production-owner", company=company, role_key="department_staff", title="Üretim Personeli")
    other_owner = create_user("energy-logistics-owner", company=company, role_key="department_staff", title="Lojistik Personeli")
    reviewer = create_user("energy-company-reviewer", company=company, role_key="management", title="Yönetim")
    other_meter = EnergyMeter(company_id=company.id, meter_code="LOJ-01", name="Lojistik Sayacı", energy_type="Elektrik", unit="kWh", department_id=logistics.id, location="Depo", multiplier=1, emission_factor=0, reading_due_day=5, responsible_user_id=other_owner.id, reviewer_user_id=reviewer.id, created_by_user_id=reviewer.id)
    db.session.add(other_meter); db.session.flush()
    db.session.add(EnergyReading(company_id=company.id, meter_id=other_meter.id, period=date.today().replace(day=1), previous_value=0, current_value=10, consumption=10, multiplier_snapshot=1, emission_factor_snapshot=0, emission_kg=0, entered_by_user_id=other_owner.id, status="Onay Bekliyor"))
    db.session.commit()

    login(client, manager)
    body = client.get("/enerji-yonetimi").get_data(as_text=True)
    assert "LOJ-01" not in body
    marker = body.index("Onay Bekleyen")
    assert ">0<" in body[marker:marker + 250]
    response = client.post("/enerji-yonetimi/sayac/yeni", data=meter_payload(production, other_owner, reviewer, "URE-01"), follow_redirects=True)
    assert response.status_code == 200 and EnergyMeter.query.filter_by(meter_code="URE-01").count() == 0
    response = client.post("/enerji-yonetimi/sayac/yeni", data=meter_payload(production, own_owner, reviewer, "URE-02"))
    assert response.status_code == 302 and EnergyMeter.query.filter_by(meter_code="URE-02").count() == 1
