from datetime import date, timedelta
from io import BytesIO

from app.extensions import db
from app.models import (
    Action,
    AppSetting,
    AuditLog,
    CompanyDepartment,
    OhsRiskAssessment,
    OhsRiskEvaluation,
    RiskRecord,
)
from app.reminders import generate_due_reminders
from app.seed import ensure_runtime_schema
from .helpers import assert_xlsx_response, create_company, create_user, login


ALL_PERMISSIONS = (
    "risk.view", "risk.manage", "risk.view_all", "risk.approve", "risk.archive",
    "risk.export", "risk.ohs_view", "risk.ohs_create", "risk.ohs_manage",
    "risk.ohs_approve", "risk.ohs_archive", "risk.ohs_export", "actions.create",
    "reports.view", "reports.export",
)


def department(company, name="Üretim", order=1):
    row = CompanyDepartment(company_id=company.id, name=name, sort_order=order, is_active=True)
    db.session.add(row)
    db.session.commit()
    return row


def assessment_payload(dept, responsible, reviewer, *, likelihood="4", severity="5"):
    return {
        "department_id": str(dept.id),
        "activity": "Pres hattında parça basımı",
        "location": "Üretim holü",
        "hazard": "Koruyucusuz hareketli parça",
        "risk_description": "El sıkışması ve uzuv yaralanması",
        "exposed_people": "Pres operatörleri",
        "existing_controls": "Günlük operatör kontrolü",
        "initial_likelihood": likelihood,
        "initial_severity": severity,
        "control_hierarchy": "Mühendislik Kontrolü",
        "planned_controls": "Fotosel ve sabit muhafaza kurulması",
        "responsible_user_id": str(responsible.id),
        "reviewer_user_id": str(reviewer.id),
        "due_date": (date.today() + timedelta(days=14)).isoformat(),
        "review_date": (date.today() + timedelta(days=30)).isoformat(),
    }


def create_people(company, dept_name="Üretim"):
    manager = create_user(
        f"ohs-manager-{company.code}", company=company, permissions=ALL_PERMISSIONS,
        title="Kalite Müdürü",
    )
    responsible = create_user(
        f"ohs-owner-{company.code}", company=company,
        permissions=("risk.ohs_view", "risk.ohs_create", "actions.create"),
        title=f"{dept_name} Personeli",
    )
    reviewer = create_user(
        f"ohs-reviewer-{company.code}", company=company,
        permissions=("risk.ohs_view", "risk.ohs_approve", "risk.approve"),
        title="Yönetim Temsilcisi",
    )
    return manager, responsible, reviewer


def create_assessment(client, company, dept, responsible, reviewer, creator):
    login(client, creator)
    response = client.post(
        "/risk-yonetimi/isg/yeni",
        data=assessment_payload(dept, responsible, reviewer),
        follow_redirects=True,
    )
    assert response.status_code == 200
    return OhsRiskAssessment.query.one()


def test_ohs_risk_full_workflow_is_versioned_audited_and_archived(app, client):
    company = create_company("931")
    dept = department(company)
    manager, responsible, reviewer = create_people(company)
    row = create_assessment(client, company, dept, responsible, reviewer, manager)

    assert row.assessment_no.startswith("ISG-")
    assert row.initial_score == 20 and row.initial_level == "Çok Yüksek"
    assert row.risk_record.company_id == company.id

    login(client, responsible)
    assert client.post(f"/risk-yonetimi/isg/{row.id}/onaya-gonder").status_code == 302
    login(client, reviewer)
    response = client.post(
        f"/risk-yonetimi/isg/{row.id}/ilk-degerlendirme",
        data={"decision": "approve", "note": "Risk ve kontroller incelendi."},
        follow_redirects=True,
    )
    assert "azaltma aksiyonuna" in response.get_data(as_text=True)
    db.session.refresh(row)
    assert row.status == "Onay Bekliyor"

    action = Action(
        company_id=company.id,
        action_number=91,
        title="Pres koruyucusu kurulumu",
        responsible_owner=responsible.full_name,
        responsible_user_id=responsible.id,
        department=dept.name,
        termin_date=date.today() + timedelta(days=7),
    )
    db.session.add(action)
    db.session.flush()
    row.risk_record.action_id = action.id
    db.session.commit()

    login(client, reviewer)
    assert client.post(
        f"/risk-yonetimi/isg/{row.id}/ilk-degerlendirme",
        data={"decision": "approve", "note": "Aksiyon bağlantısı uygun."},
    ).status_code == 302
    db.session.refresh(row)
    assert row.status == "Aktif"
    assert OhsRiskEvaluation.query.filter_by(assessment_id=row.id).count() == 1

    login(client, responsible)
    blocked = client.post(
        f"/risk-yonetimi/isg/{row.id}/artik-risk",
        data={
            "residual_likelihood": "1", "residual_severity": "3",
            "completion_note": "Kontroller uygulandı.",
            "evidence": (BytesIO(b"%PDF-1.4 evidence"), "kontrol.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "aksiyonu tamamlanmadan" in blocked.get_data(as_text=True)

    action.mark_completed()
    db.session.commit()
    submitted = client.post(
        f"/risk-yonetimi/isg/{row.id}/artik-risk",
        data={
            "residual_likelihood": "1", "residual_severity": "3",
            "completion_note": "Fotosel devreye alındı ve fonksiyon testi yapıldı.",
            "evidence": (BytesIO(b"%PDF-1.4 evidence-v2"), "kontrol.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert submitted.status_code == 302
    db.session.refresh(row)
    assert row.status == "Kapanış Onayı" and row.evidence_hash

    login(client, reviewer)
    assert client.post(
        f"/risk-yonetimi/isg/{row.id}/kapanis-degerlendirme",
        data={"decision": "approve", "note": "Kalıntı risk kabul edilebilir."},
    ).status_code == 302
    db.session.refresh(row)
    assert row.status == "Tamamlandı" and row.residual_score == 3
    assert row.risk_record.status == "Kapandı"
    assert row.risk_record.likelihood == 1 and row.risk_record.severity == 3
    assert OhsRiskEvaluation.query.filter_by(assessment_id=row.id).count() == 2

    evaluation = OhsRiskEvaluation.query.filter_by(assessment_id=row.id, phase="Artık Risk").one()
    assert client.get(f"/risk-yonetimi/isg/kanit/{evaluation.id}").status_code == 200

    login(client, manager)
    assert client.post(f"/risk-yonetimi/isg/{row.id}/arsivle").status_code == 302
    db.session.refresh(row)
    assert row.status == "Arşiv" and row.archived_at is not None
    assert row.risk_record.status == "Arşiv" and row.risk_record.archived_at is not None
    assert AuditLog.query.filter(AuditLog.entity_type.in_(("OhsRiskAssessment", "OhsRiskEvaluation"))).count() > 0


def test_ohs_risk_enforces_independent_approval_department_and_tenant_scope(app, client):
    company = create_company("932")
    other_company = create_company("933")
    production = department(company, "Üretim")
    logistics = department(company, "Lojistik", 2)
    manager, responsible, reviewer = create_people(company)
    wrong_owner = create_user(
        "ohs-logistics-owner", company=company,
        permissions=("risk.ohs_view", "risk.ohs_create"), title="Lojistik Personeli",
    )
    outsider = create_user("ohs-outsider", company=other_company, permissions=ALL_PERMISSIONS)

    login(client, manager)
    mismatch = assessment_payload(production, wrong_owner, reviewer)
    response = client.post("/risk-yonetimi/isg/yeni", data=mismatch, follow_redirects=True)
    assert response.status_code == 200
    assert "seçilen departmanda" in response.get_data(as_text=True)
    assert OhsRiskAssessment.query.count() == 0

    self_review = assessment_payload(production, responsible, manager)
    response = client.post("/risk-yonetimi/isg/yeni", data=self_review, follow_redirects=True)
    assert "bağımsız onaylayan" in response.get_data(as_text=True)
    assert OhsRiskAssessment.query.count() == 0

    row = create_assessment(client, company, production, responsible, reviewer, manager)
    login(client, manager)
    client.post(f"/risk-yonetimi/isg/{row.id}/onaya-gonder")
    assert client.post(
        f"/risk-yonetimi/isg/{row.id}/ilk-degerlendirme",
        data={"decision": "reject", "note": "Kendi kaydını onaylayamaz."},
    ).status_code == 403

    login(client, outsider)
    assert client.get(f"/risk-yonetimi/isg/{row.id}").status_code == 404
    assert client.get("/risk-yonetimi/isg").status_code == 200
    assert row.assessment_no not in client.get("/risk-yonetimi/isg").get_data(as_text=True)
    assert logistics.id != production.id


def test_ohs_risk_export_tasks_reminders_module_guard_and_checklist(app, client):
    company = create_company("934")
    dept = department(company)
    manager, responsible, reviewer = create_people(company)
    row = create_assessment(client, company, dept, responsible, reviewer, manager)
    row.due_date = date.today() - timedelta(days=1)
    db.session.commit()

    login(client, manager)
    assert_xlsx_response(client.get("/risk-yonetimi/isg/rapor.xlsx"))
    assert_xlsx_response(client.get("/rapor-merkezi/ohs_risks/excel"))
    login(client, responsible)
    task_page = client.get("/uzerime-atananlar?module=ohs_risk").get_data(as_text=True)
    assert row.assessment_no in task_page

    stats = generate_due_reminders(company_id=company.id, run_date=date.today())
    assert stats["notifications"] >= 1

    setting_key = "sales_readiness:competitor_ohs_risk_matrix"
    AppSetting.query.filter_by(key=setting_key).delete()
    db.session.commit()
    ensure_runtime_schema()
    assert db.session.get(AppSetting, setting_key).value == "1"

    disabled_company = create_company("935", module_keys=())
    disabled_user = create_user("ohs-disabled", company=disabled_company, permissions=ALL_PERMISSIONS)
    login(client, disabled_user)
    assert client.get("/risk-yonetimi/isg").status_code in {403, 404}


def test_generic_risk_delete_preserves_record_as_archive(app, client):
    company = create_company("936")
    user = create_user(
        "risk-archive-manager", company=company,
        permissions=("risk.view", "risk.manage", "risk.delete"),
    )
    risk = RiskRecord(
        company_id=company.id, risk_no="RSK-2026-0099", title="Arşiv testi",
        likelihood=2, severity=2, status="Açık", created_by_user_id=user.id,
    )
    db.session.add(risk)
    db.session.commit()
    login(client, user)
    assert client.post(f"/risk-yonetimi/{risk.id}/sil").status_code == 302
    db.session.refresh(risk)
    assert risk.status == "Arşiv" and risk.archived_at is not None
    assert RiskRecord.query.count() == 1
