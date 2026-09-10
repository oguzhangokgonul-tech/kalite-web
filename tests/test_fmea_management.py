from datetime import date, timedelta

from app.extensions import db
from app.models import (
    Action,
    AppSetting,
    AuditLog,
    CompanyModule,
    FmeaRecord,
    FMEA_STATUS_ACTION_PENDING,
    FMEA_STATUS_ARCHIVED,
    FMEA_STATUS_CLOSED,
    FMEA_STATUS_OPEN,
    RiskRecord,
)
from app.seed import ensure_runtime_schema

from .helpers import assert_xlsx_response, create_company, create_user, login, sheet_values


def test_fmea_dashboard_requires_permission(client):
    company = create_company("971")
    user = create_user("plain-fmea-user", company=company)
    login(client, user)

    response = client.get("/fmea")

    assert response.status_code == 403


def test_fmea_full_flow_marks_checklist_and_audits(client):
    company = create_company("972")
    manager = create_user(
        "fmea-manager",
        company=company,
        permissions=(
            "fmea.view",
            "fmea.create",
            "fmea.manage",
            "fmea.close",
            "fmea.delete",
            "reports.view",
            "reports.export",
            "fmea.export",
            "actions.view_all",
            "risk.view",
        ),
        full_name="Yonetim Temsilcisi",
    )
    responsible = create_user(
        "fmea-responsible",
        company=company,
        permissions=("fmea.view",),
        full_name="FMEA Sorumlusu",
    )
    risk = RiskRecord(
        company_id=company.id,
        risk_no="RSK-2026-0001",
        title="Sevkiyat proses riski",
        process="Sevkiyat",
        likelihood=4,
        severity=4,
    )
    action = Action(
        company_id=company.id,
        action_number=730,
        title="Etiket kontrol mastari",
        responsible_owner="FMEA Sorumlusu",
        responsible_user_id=responsible.id,
        department="Kalite",
        termin_date=date.today() + timedelta(days=5),
    )
    db.session.add_all([risk, action])
    db.session.commit()
    login(client, manager)

    create_response = client.post(
        "/fmea/yeni",
        data={
            "process_name": "Sevkiyat",
            "product_or_service": "Prefabrik panel",
            "operation_step": "Yukleme oncesi kontrol",
            "failure_mode": "Yanlis etiketli urun sevki",
            "failure_effect": "Musteriye hatali urun sevk edilir.",
            "failure_cause": "Etiket kontrol adimi atlanir.",
            "current_controls": "Sevkiyat listesi kontrolu.",
            "severity": "8",
            "occurrence": "4",
            "detection": "5",
            "recommended_action": "Etiket kontrol mastari zorunlu hale getirilecek.",
            "responsible_user_id": str(responsible.id),
            "due_date": (date.today() + timedelta(days=5)).isoformat(),
            "action_id": str(action.id),
            "risk_id": str(risk.id),
        },
        follow_redirects=True,
    )

    assert create_response.status_code == 200
    assert "Yanlis etiketli urun sevki" in create_response.get_data(as_text=True)
    fmea = FmeaRecord.query.one()
    assert fmea.fmea_no.startswith(f"FMEA-{date.today().year}-")
    assert fmea.rpn == 160
    assert fmea.level == "Yüksek"
    assert fmea.action_id == action.id
    assert fmea.risk_id == risk.id
    assert AuditLog.query.filter_by(
        entity_type="FmeaRecord",
        action="fmea_created",
    ).count() == 1
    assert db.session.get(AppSetting, "sales_readiness:competitor_fmea").value == "1"

    task_response = client.get("/uzerime-atananlar?module=fmea")
    assert task_response.status_code == 200
    assert "Yanlis etiketli urun sevki" not in task_response.get_data(as_text=True)

    login(client, responsible)
    assigned_response = client.get("/uzerime-atananlar?module=fmea")
    assert assigned_response.status_code == 200
    assert "Yanlis etiketli urun sevki" in assigned_response.get_data(as_text=True)

    login(client, manager)
    action_pending_response = client.post(
        f"/fmea/{fmea.id}/aksiyon-bekliyor",
        follow_redirects=True,
    )
    assert action_pending_response.status_code == 200
    db.session.refresh(fmea)
    assert fmea.status == FMEA_STATUS_ACTION_PENDING

    update_response = client.post(
        f"/fmea/{fmea.id}/duzenle",
        data={
            "process_name": "Sevkiyat",
            "product_or_service": "Prefabrik panel",
            "operation_step": "Yukleme oncesi kontrol",
            "failure_mode": "Yanlis etiketli urun sevki",
            "failure_effect": "Musteriye hatali urun sevk edilir.",
            "failure_cause": "Etiket kontrol adimi atlanir.",
            "current_controls": "Cift imzali kontrol.",
            "severity": "6",
            "occurrence": "3",
            "detection": "4",
            "recommended_action": "Etiket kontrolu tamamlandi.",
            "responsible_user_id": str(responsible.id),
            "due_date": (date.today() + timedelta(days=4)).isoformat(),
            "status": FMEA_STATUS_ACTION_PENDING,
            "action_id": str(action.id),
            "risk_id": str(risk.id),
        },
        follow_redirects=True,
    )
    assert update_response.status_code == 200
    db.session.refresh(fmea)
    assert fmea.rpn == 72
    assert fmea.level == "Orta"
    assert AuditLog.query.filter_by(
        entity_type="FmeaRecord",
        action="fmea_updated",
    ).count() == 1

    close_response = client.post(
        f"/fmea/{fmea.id}/kapat",
        data={"close_note": "Etkinlik kontrolu uygun."},
        follow_redirects=True,
    )
    assert close_response.status_code == 200
    db.session.refresh(fmea)
    assert fmea.status == FMEA_STATUS_CLOSED
    assert fmea.closed_at == date.today()

    login(client, responsible)
    completed_task_response = client.get("/uzerime-atananlar?module=fmea")
    assert "Yanlis etiketli urun sevki" not in completed_task_response.get_data(as_text=True)

    login(client, manager)
    archive_response = client.post(f"/fmea/{fmea.id}/arsivle", follow_redirects=True)
    assert archive_response.status_code == 200
    db.session.refresh(fmea)
    assert fmea.status == FMEA_STATUS_ARCHIVED
    assert fmea.archived_at is not None


def test_fmea_manage_permission_cannot_close_or_archive(client):
    company = create_company("979")
    manager_without_close = create_user(
        "fmea-manager-without-close",
        company=company,
        permissions=("fmea.view", "fmea.create", "fmea.manage"),
    )
    fmea = FmeaRecord(
        company_id=company.id,
        fmea_no="FMEA-2026-0099",
        process_name="Uretim",
        failure_mode="Kontrol kacagi",
        severity=5,
        occurrence=5,
        detection=5,
        status=FMEA_STATUS_OPEN,
    )
    db.session.add(fmea)
    db.session.commit()
    login(client, manager_without_close)

    close_response = client.post(f"/fmea/{fmea.id}/kapat")
    archive_response = client.post(f"/fmea/{fmea.id}/arsivle")
    edit_response = client.post(
        f"/fmea/{fmea.id}/duzenle",
        data={
            "process_name": "Uretim",
            "failure_mode": "Kontrol kacagi",
            "severity": "5",
            "occurrence": "5",
            "detection": "5",
            "status": FMEA_STATUS_CLOSED,
        },
        follow_redirects=True,
    )

    assert close_response.status_code == 403
    assert archive_response.status_code == 403
    assert edit_response.status_code == 200
    db.session.refresh(fmea)
    assert fmea.status == FMEA_STATUS_OPEN


def test_fmea_create_only_user_cannot_submit_closed_status(client):
    company = create_company("980")
    creator = create_user(
        "fmea-create-only",
        company=company,
        permissions=("fmea.view", "fmea.create"),
    )
    login(client, creator)

    response = client.post(
        "/fmea/yeni",
        data={
            "process_name": "Depo",
            "failure_mode": "Yanlis stok",
            "severity": "4",
            "occurrence": "4",
            "detection": "4",
            "status": FMEA_STATUS_CLOSED,
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert FmeaRecord.query.count() == 0


def test_fmea_orders_highest_rpn_first(client):
    company = create_company("973")
    user = create_user(
        "fmea-sort-user",
        company=company,
        permissions=("fmea.view", "fmea.create", "fmea.manage"),
    )
    db.session.add_all(
        [
            FmeaRecord(
                company_id=company.id,
                fmea_no="FMEA-2026-0001",
                process_name="Dusuk proses",
                failure_mode="Dusuk hata",
                severity=2,
                occurrence=2,
                detection=2,
            ),
            FmeaRecord(
                company_id=company.id,
                fmea_no="FMEA-2026-0002",
                process_name="Yuksek proses",
                failure_mode="Yuksek hata",
                severity=9,
                occurrence=8,
                detection=7,
            ),
        ]
    )
    db.session.commit()
    login(client, user)

    response = client.get("/fmea")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert body.index("Yuksek hata") < body.index("Dusuk hata")


def test_fmea_report_is_company_scoped(client):
    company_a = create_company("974")
    company_b = create_company("975")
    report_only_user = create_user(
        "fmea-report-only",
        company=company_a,
        permissions=("reports.view", "reports.export"),
    )
    reporter = create_user(
        "fmea-reporter",
        company=company_a,
        permissions=("reports.view", "reports.export", "fmea.view", "fmea.export"),
    )
    db.session.add_all(
        [
            FmeaRecord(
                company_id=company_a.id,
                fmea_no="FMEA-2026-0001",
                process_name="Gorunen proses",
                failure_mode="Gorunen FMEA",
                severity=8,
                occurrence=5,
                detection=5,
            ),
            FmeaRecord(
                company_id=company_b.id,
                fmea_no="FMEA-2026-0002",
                process_name="Gorunmeyen proses",
                failure_mode="Gorunmeyen FMEA",
                severity=9,
                occurrence=5,
                detection=5,
            ),
        ]
    )
    db.session.commit()

    login(client, report_only_user)
    blocked_dashboard = client.get("/rapor-merkezi")
    blocked_export = client.get("/rapor-merkezi/fmea/excel")
    assert blocked_dashboard.status_code == 200
    assert "/rapor-merkezi/fmea/excel" not in blocked_dashboard.get_data(as_text=True)
    assert blocked_export.status_code == 404

    login(client, reporter)
    response = client.get("/rapor-merkezi/fmea/excel")

    assert_xlsx_response(response)
    rows = sheet_values(response.data)
    flattened = "\n".join("\t".join(row) for row in rows)
    assert "Gorunen FMEA" in flattened
    assert "Gorunmeyen FMEA" not in flattened


def test_disabled_fmea_module_blocks_direct_route(client):
    company = create_company("976", module_keys=("actions",))
    user = create_user(
        "disabled-fmea-user",
        company=company,
        permissions=("fmea.view", "fmea.create"),
    )
    module = CompanyModule.query.filter_by(
        company_id=company.id,
        module_key="fmea_management",
    ).one()
    assert module.is_enabled is False
    login(client, user)

    response = client.get("/fmea")

    assert response.status_code == 403


def test_runtime_schema_marks_sales_readiness_fmea_done(app):
    AppSetting.query.delete()
    db.session.commit()

    ensure_runtime_schema()

    setting = db.session.get(AppSetting, "sales_readiness:competitor_fmea")
    assert setting is not None
    assert setting.value == "1"
