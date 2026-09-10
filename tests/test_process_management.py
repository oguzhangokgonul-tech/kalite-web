from datetime import date, timedelta

from app.extensions import db
from app.models import (
    Action,
    AppSetting,
    AuditLog,
    CompanyModule,
    Document,
    PROCESS_CATEGORY_CORE,
    PROCESS_CATEGORY_SUPPORT,
    PROCESS_RELATION_INPUT,
    PROCESS_STATUS_ARCHIVED,
    PROCESS_STATUS_DRAFT,
    PROCESS_STATUS_PUBLISHED,
    PROCESS_STATUS_REVIEW,
    ProcessRecord,
    ProcessRelation,
    ProcessStep,
    RiskRecord,
)
from app.seed import ensure_runtime_schema

from .helpers import assert_xlsx_response, create_company, create_user, login, make_document, sheet_values


def process_payload(**overrides):
    data = {
        "title": "Sevkiyat Sureci",
        "category": PROCESS_CATEGORY_CORE,
        "owner_user_id": "",
        "department": "Kalite",
        "purpose": "Siparislerin zamaninda sevki.",
        "scope": "Sevkiyat operasyonlari",
        "inputs": "Sevkiyat plani",
        "outputs": "Teslim tutanagi",
        "suppliers": "Uretim",
        "customers": "Musteri",
        "kpi": "Zamaninda sevk orani",
        "review_frequency": "Yilda 1",
        "next_review_date": (date.today() + timedelta(days=5)).isoformat(),
        "related_document_id": "",
        "risk_id": "",
        "action_id": "",
        "status": PROCESS_STATUS_REVIEW,
    }
    data.update(overrides)
    return data


def test_process_dashboard_requires_permission(client):
    company = create_company("981")
    user = create_user("plain-process-user", company=company)
    login(client, user)

    response = client.get("/surec-yonetimi")

    assert response.status_code == 403


def test_process_full_flow_marks_checklist_audits_steps_and_relations(app, client):
    company = create_company("982")
    manager = create_user(
        "process-manager",
        company=company,
        permissions=(
            "process.view",
            "process.create",
            "process.manage",
            "process.delete",
            "reports.view",
            "reports.export",
            "process.export",
            "actions.view_all",
            "risk.view",
            "documents.view",
        ),
        full_name="Yonetim Temsilcisi",
    )
    owner = create_user(
        "process-owner",
        company=company,
        permissions=("process.view",),
        full_name="Surec Sahibi",
    )
    document = make_document(
        app,
        company,
        uploader=manager,
        document_code="PRS.01",
        title="Sevkiyat Prosesi",
    )
    risk = RiskRecord(
        company_id=company.id,
        risk_no="RSK-2026-0101",
        title="Sevkiyat gecikme riski",
        process="Sevkiyat",
        likelihood=3,
        severity=4,
    )
    action = Action(
        company_id=company.id,
        action_number=981,
        title="Sevkiyat kontrol listesi",
        responsible_owner="Surec Sahibi",
        responsible_user_id=owner.id,
        department="Kalite",
        termin_date=date.today() + timedelta(days=7),
    )
    db.session.add_all([risk, action])
    db.session.commit()
    login(client, manager)

    create_response = client.post(
        "/surec-yonetimi/yeni",
        data=process_payload(
            owner_user_id=str(owner.id),
            related_document_id=str(document.id),
            risk_id=str(risk.id),
            action_id=str(action.id),
        ),
        follow_redirects=True,
    )

    assert create_response.status_code == 200
    assert "Sevkiyat Sureci" in create_response.get_data(as_text=True)
    process_record = ProcessRecord.query.one()
    assert process_record.process_no.startswith(f"PRC-{date.today().year}-")
    assert process_record.owner_user_id == owner.id
    assert process_record.related_document_id == document.id
    assert process_record.risk_id == risk.id
    assert process_record.action_id == action.id
    assert (
        AuditLog.query.filter_by(
            entity_type="ProcessRecord",
            action="process_created",
        ).count()
        == 1
    )
    assert db.session.get(AppSetting, "sales_readiness:competitor_process_bpm").value == "1"

    login(client, owner)
    assigned_response = client.get("/uzerime-atananlar?module=process")
    assert assigned_response.status_code == 200
    assert "Sevkiyat Sureci" in assigned_response.get_data(as_text=True)

    login(client, manager)
    target_process = ProcessRecord(
        company_id=company.id,
        process_no="PRC-2026-0099",
        title="Uretim Sureci",
        category=PROCESS_CATEGORY_SUPPORT,
        status=PROCESS_STATUS_PUBLISHED,
    )
    db.session.add(target_process)
    db.session.commit()

    step_response = client.post(
        f"/surec-yonetimi/{process_record.id}/adim-ekle",
        data={
            "step_order": "2",
            "title": "Yukleme kontrolu",
            "responsible_user_id": str(owner.id),
            "description": "Sevk oncesi kontrol yapilir.",
            "input_note": "Sevkiyat listesi",
            "output_note": "Kontrol kaydi",
            "control_point": "Cift imza",
            "document_id": str(document.id),
        },
        follow_redirects=True,
    )
    assert step_response.status_code == 200
    assert ProcessStep.query.filter_by(process_id=process_record.id).count() == 1
    assert AuditLog.query.filter_by(action="process_step_created").count() == 1

    relation_response = client.post(
        f"/surec-yonetimi/{process_record.id}/baglanti-ekle",
        data={
            "target_process_id": str(target_process.id),
            "relation_type": PROCESS_RELATION_INPUT,
            "description": "Uretimden sevke girdi aktarilir.",
        },
        follow_redirects=True,
    )
    assert relation_response.status_code == 200
    assert ProcessRelation.query.filter_by(source_process_id=process_record.id).count() == 1
    assert AuditLog.query.filter_by(action="process_relation_created").count() == 1

    map_response = client.get("/surec-yonetimi/harita")
    assert map_response.status_code == 200
    map_body = map_response.get_data(as_text=True)
    assert "Sevkiyat Sureci" in map_body
    assert "Uretim Sureci" in map_body

    archive_response = client.post(
        f"/surec-yonetimi/{process_record.id}/arsivle",
        follow_redirects=True,
    )
    assert archive_response.status_code == 200
    db.session.refresh(process_record)
    assert process_record.status == PROCESS_STATUS_ARCHIVED
    assert process_record.archived_at is not None
    assert AuditLog.query.filter_by(action="process_archived").count() == 1


def test_process_report_is_company_scoped_and_requires_process_export(client):
    company_a = create_company("983")
    company_b = create_company("984")
    report_only_user = create_user(
        "process-report-only",
        company=company_a,
        permissions=("reports.view", "reports.export"),
    )
    reporter = create_user(
        "process-reporter",
        company=company_a,
        permissions=("reports.view", "reports.export", "process.view", "process.export"),
    )
    db.session.add_all(
        [
            ProcessRecord(
                company_id=company_a.id,
                process_no="PRC-2026-0001",
                title="Gorunen surec",
                category=PROCESS_CATEGORY_CORE,
                status=PROCESS_STATUS_PUBLISHED,
            ),
            ProcessRecord(
                company_id=company_b.id,
                process_no="PRC-2026-0002",
                title="Gorunmeyen surec",
                category=PROCESS_CATEGORY_CORE,
                status=PROCESS_STATUS_PUBLISHED,
            ),
        ]
    )
    db.session.commit()

    login(client, report_only_user)
    blocked_dashboard = client.get("/rapor-merkezi")
    blocked_export = client.get("/rapor-merkezi/processes/excel")
    assert blocked_dashboard.status_code == 200
    assert "/rapor-merkezi/processes/excel" not in blocked_dashboard.get_data(as_text=True)
    assert blocked_export.status_code == 404

    login(client, reporter)
    response = client.get("/rapor-merkezi/processes/excel")

    assert_xlsx_response(response)
    rows = sheet_values(response.data)
    flattened = "\n".join("\t".join(row) for row in rows)
    assert "Gorunen surec" in flattened
    assert "Gorunmeyen surec" not in flattened


def test_process_rejects_cross_company_links(app, client):
    company_a = create_company("985")
    company_b = create_company("986")
    manager = create_user(
        "process-cross-company-manager",
        company=company_a,
        permissions=("process.view", "process.create", "process.manage", "documents.view"),
    )
    other_document = make_document(
        app,
        company_b,
        document_code="PRS.99",
        title="Baska Firma Dokumani",
    )
    login(client, manager)

    response = client.post(
        "/surec-yonetimi/yeni",
        data=process_payload(related_document_id=str(other_document.id)),
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert ProcessRecord.query.count() == 0


def test_disabled_process_module_blocks_direct_route(client):
    company = create_company("987", module_keys=("actions",))
    user = create_user(
        "disabled-process-user",
        company=company,
        permissions=("process.view", "process.create"),
    )
    module = CompanyModule.query.filter_by(
        company_id=company.id,
        module_key="process_management",
    ).one()
    assert module.is_enabled is False
    login(client, user)

    response = client.get("/surec-yonetimi")

    assert response.status_code == 403


def test_archived_process_is_read_only_for_manager(client):
    company = create_company("988")
    manager = create_user(
        "archived-process-manager",
        company=company,
        permissions=("process.view", "process.manage", "process.delete"),
    )
    archived_process = ProcessRecord(
        company_id=company.id,
        process_no="PRC-2026-0201",
        title="Arsiv Sureci",
        category=PROCESS_CATEGORY_CORE,
        status=PROCESS_STATUS_ARCHIVED,
    )
    target_process = ProcessRecord(
        company_id=company.id,
        process_no="PRC-2026-0202",
        title="Hedef Surec",
        category=PROCESS_CATEGORY_SUPPORT,
        status=PROCESS_STATUS_PUBLISHED,
    )
    db.session.add_all([archived_process, target_process])
    db.session.flush()
    step = ProcessStep(
        company_id=company.id,
        process_id=archived_process.id,
        step_order=1,
        title="Korunan adim",
    )
    relation = ProcessRelation(
        company_id=company.id,
        source_process_id=archived_process.id,
        target_process_id=target_process.id,
        relation_type=PROCESS_RELATION_INPUT,
    )
    db.session.add_all([step, relation])
    db.session.commit()
    login(client, manager)

    assert client.get(f"/surec-yonetimi/{archived_process.id}/duzenle").status_code == 403
    assert (
        client.post(
            f"/surec-yonetimi/{archived_process.id}/adim-ekle",
            data={"title": "Yeni adim"},
        ).status_code
        == 404
    )
    assert client.post(f"/surec-yonetimi/adim/{step.id}/sil").status_code == 403
    assert client.post(f"/surec-yonetimi/baglanti/{relation.id}/sil").status_code == 403
    assert ProcessStep.query.filter_by(id=step.id).count() == 1
    assert ProcessRelation.query.filter_by(id=relation.id).count() == 1


def test_department_manager_is_scoped_and_cannot_publish_process(client):
    company = create_company("989")
    manager = create_user(
        "department-process-manager",
        company=company,
        role_key="department_manager",
        title="Kalite Muduru",
    )
    own_department_process = ProcessRecord(
        company_id=company.id,
        process_no="PRC-2026-0301",
        title="Kalite Sureci",
        category=PROCESS_CATEGORY_CORE,
        department="Kalite",
        status=PROCESS_STATUS_DRAFT,
    )
    other_department_process = ProcessRecord(
        company_id=company.id,
        process_no="PRC-2026-0302",
        title="Sevkiyat Sureci",
        category=PROCESS_CATEGORY_CORE,
        department="Sevkiyat",
        status=PROCESS_STATUS_DRAFT,
    )
    db.session.add_all([own_department_process, other_department_process])
    db.session.commit()
    login(client, manager)

    assert client.get(f"/surec-yonetimi/{own_department_process.id}/duzenle").status_code == 200
    assert client.get(f"/surec-yonetimi/{other_department_process.id}/duzenle").status_code == 403

    response = client.post(
        f"/surec-yonetimi/{own_department_process.id}/duzenle",
        data=process_payload(title="Yayinlanamaz", status=PROCESS_STATUS_PUBLISHED),
        follow_redirects=True,
    )

    assert response.status_code == 200
    db.session.refresh(own_department_process)
    assert own_department_process.status == PROCESS_STATUS_DRAFT


def test_process_owner_can_complete_review_task(client):
    company = create_company("990")
    owner = create_user(
        "owned-process-user",
        company=company,
        permissions=("process.view",),
    )
    process_record = ProcessRecord(
        company_id=company.id,
        process_no="PRC-2026-0401",
        title="Sahipli Surec",
        category=PROCESS_CATEGORY_CORE,
        owner_user_id=owner.id,
        status=PROCESS_STATUS_DRAFT,
    )
    db.session.add(process_record)
    db.session.commit()
    login(client, owner)

    assert client.get(f"/surec-yonetimi/{process_record.id}/duzenle").status_code == 200
    response = client.post(
        f"/surec-yonetimi/{process_record.id}/duzenle",
        data=process_payload(title="Gozden Gecirilen Surec", status=PROCESS_STATUS_REVIEW),
        follow_redirects=True,
    )

    assert response.status_code == 200
    db.session.refresh(process_record)
    assert process_record.status == PROCESS_STATUS_REVIEW


def test_process_action_options_and_validation_follow_manager_scope(client):
    company = create_company("991")
    manager = create_user(
        "scoped-action-process-manager",
        company=company,
        role_key="department_manager",
        title="Kalite Muduru",
    )
    allowed_action = Action(
        company_id=company.id,
        action_number=991,
        title="Kalite aksiyonu",
        responsible_owner="Kalite",
        department="Kalite",
        termin_date=date.today() + timedelta(days=5),
    )
    hidden_action = Action(
        company_id=company.id,
        action_number=992,
        title="Sevkiyat gizli aksiyonu",
        responsible_owner="Sevkiyat",
        department="Sevkiyat",
        termin_date=date.today() + timedelta(days=5),
    )
    db.session.add_all([allowed_action, hidden_action])
    db.session.commit()
    login(client, manager)

    form_response = client.get("/surec-yonetimi/yeni")
    form_body = form_response.get_data(as_text=True)
    assert form_response.status_code == 200
    assert "Kalite aksiyonu" in form_body
    assert "Sevkiyat gizli aksiyonu" not in form_body

    create_response = client.post(
        "/surec-yonetimi/yeni",
        data=process_payload(action_id=str(hidden_action.id)),
        follow_redirects=True,
    )
    assert create_response.status_code == 200
    assert ProcessRecord.query.count() == 0


def test_runtime_schema_marks_sales_readiness_process_done(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:competitor_process_bpm")
    assert setting is not None
    assert setting.value == "1"
