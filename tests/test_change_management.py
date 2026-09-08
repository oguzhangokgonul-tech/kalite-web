from datetime import date, timedelta

from app.extensions import db
from app.models import AppSetting, AuditLog, ChangeRequest, ChangeRequestFile, CompanyModule

from .helpers import assert_xlsx_response, create_company, create_user, login, sheet_values, upload_tuple


def test_change_management_dashboard_requires_permission(client):
    company = create_company("701")
    user = create_user("plain-user", company=company)
    login(client, user)

    response = client.get("/degisiklik-yonetimi")

    assert response.status_code == 403


def test_change_request_full_flow_marks_checklist_and_audits(app, client):
    company = create_company("702")
    manager = create_user(
        "change-manager",
        company=company,
        permissions=(
            "change_management.view",
            "change_management.create",
            "change_management.manage",
            "change_management.approve",
            "change_management.delete",
        ),
        full_name="Yonetim Temsilcisi",
    )
    responsible = create_user(
        "change-responsible",
        company=company,
        permissions=("change_management.view", "change_management.create"),
        full_name="Uygulama Sorumlusu",
    )
    login(client, manager)

    create_response = client.post(
        "/degisiklik-yonetimi/yeni",
        data={
            "title": "Hat ayar standardi degisikligi",
            "change_type": "Proses",
            "department": "Kalite",
            "process_name": "Uretim kontrol",
            "risk_level": "Y\u00fcksek",
            "planned_date": date.today().isoformat(),
            "due_date": (date.today() + timedelta(days=7)).isoformat(),
            "responsible_user_id": str(responsible.id),
            "approver_user_id": str(manager.id),
            "description": "Yeni kontrol noktasi eklenecek.",
            "reason": "Tekrar eden uygunsuzluk",
            "scope": "Uretim ve kalite kontrol",
            "change_files": upload_tuple(b"kanit", "kanit.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert create_response.status_code == 200
    assert "Hat ayar standardi degisikligi" in create_response.get_data(as_text=True)
    change = ChangeRequest.query.one()
    assert change.change_no.startswith(f"DGY-{date.today().year}-")
    assert change.status == "Onay Bekliyor"
    assert change.requester_user_id == manager.id
    assert change.responsible_user_id == responsible.id
    assert ChangeRequestFile.query.count() == 1
    assert AuditLog.query.filter_by(
        entity_type="ChangeRequest",
        action="change_created",
    ).count() == 1

    download_response = client.get(
        f"/degisiklik-yonetimi/dosya/{change.files[0].id}/indir"
    )
    assert download_response.status_code == 200
    assert download_response.data == b"kanit"

    approve_response = client.post(
        f"/degisiklik-yonetimi/{change.id}/onayla",
        data={"approval_note": "Uygundur."},
        follow_redirects=True,
    )

    assert approve_response.status_code == 200
    db.session.refresh(change)
    assert change.status == "Onayland\u0131"
    assert AuditLog.query.filter_by(
        entity_type="ChangeRequest",
        action="change_approved",
    ).count() == 1
    assert db.session.get(
        AppSetting,
        "sales_readiness:competitor_change_management",
    ).value == "1"

    login(client, responsible)
    implement_response = client.post(
        f"/degisiklik-yonetimi/{change.id}/uygulandi",
        data={
            "effective_date": date.today().isoformat(),
            "implementation_note": "Saha uygulamasi tamamlandi.",
            "implementation_files": upload_tuple(b"uygulama", "uygulama.xlsx"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert implement_response.status_code == 200
    db.session.refresh(change)
    assert change.status == "Etkinlik Kontrol\u00fc"
    assert ChangeRequestFile.query.count() == 2

    login(client, manager)
    close_response = client.post(
        f"/degisiklik-yonetimi/{change.id}/etkinlik-kapat",
        data={
            "effectiveness_note": "Etkinlik dogrulandi.",
            "effectiveness_files": upload_tuple(b"etkinlik", "etkinlik.png"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert close_response.status_code == 200
    db.session.refresh(change)
    assert change.status == "Kapand\u0131"
    assert ChangeRequestFile.query.count() == 3

    archive_response = client.post(
        f"/degisiklik-yonetimi/{change.id}/arsivle",
        follow_redirects=True,
    )

    assert archive_response.status_code == 200
    db.session.refresh(change)
    assert change.status == "Ar\u015fiv"
    assert change.archived_at is not None


def test_change_request_approval_requires_owner_and_due_date(client):
    company = create_company("703")
    approver = create_user(
        "change-approval-only",
        company=company,
        permissions=("change_management.view", "change_management.approve"),
    )
    change = ChangeRequest(
        company_id=company.id,
        change_no="DGY-2026-0099",
        title="Eksik sorumlu talep",
        change_type="Proses",
        risk_level="Orta",
        status="Onay Bekliyor",
        approver_user_id=approver.id,
        created_by_user_id=approver.id,
    )
    db.session.add(change)
    db.session.commit()
    login(client, approver)

    response = client.post(
        f"/degisiklik-yonetimi/{change.id}/onayla",
        follow_redirects=True,
    )

    assert response.status_code == 200
    db.session.refresh(change)
    assert change.status == "Onay Bekliyor"
    assert "Onaydan" in response.get_data(as_text=True)


def test_change_request_rejection_keeps_rejection_note(client):
    company = create_company("704")
    approver = create_user(
        "change-rejecter",
        company=company,
        permissions=("change_management.view", "change_management.approve"),
    )
    change = ChangeRequest(
        company_id=company.id,
        change_no="DGY-2026-0100",
        title="Reddedilecek degisiklik",
        change_type="Proses",
        risk_level="Orta",
        status="Onay Bekliyor",
        approver_user_id=approver.id,
        created_by_user_id=approver.id,
    )
    db.session.add(change)
    db.session.commit()
    login(client, approver)

    response = client.post(
        f"/degisiklik-yonetimi/{change.id}/reddet",
        data={"approval_note": "Kapsam netlestirilmeli."},
        follow_redirects=True,
    )

    assert response.status_code == 200
    db.session.refresh(change)
    assert change.status == "Reddedildi"
    assert change.approval_note == "Kapsam netlestirilmeli."


def test_change_management_tasks_follow_current_status(client):
    company = create_company("705")
    approver = create_user(
        "change-approver",
        company=company,
        permissions=("change_management.view", "change_management.approve"),
    )
    responsible = create_user(
        "change-owner",
        company=company,
        permissions=("change_management.view",),
    )
    change = ChangeRequest(
        company_id=company.id,
        change_no="DGY-2026-0001",
        title="Bekleyen degisiklik gorevi",
        change_type="Dok\u00fcman",
        risk_level="Orta",
        status="Onay Bekliyor",
        due_date=date.today() + timedelta(days=5),
        approver_user_id=approver.id,
        responsible_user_id=responsible.id,
        created_by_user_id=responsible.id,
    )
    db.session.add(change)
    db.session.commit()

    login(client, approver)
    pending_response = client.get("/uzerime-atananlar?module=change_management")

    assert pending_response.status_code == 200
    assert "Bekleyen degisiklik gorevi" in pending_response.get_data(as_text=True)

    change.status = "Onayland\u0131"
    db.session.commit()
    login(client, responsible)
    implementation_response = client.get(
        "/uzerime-atananlar?module=change_management"
    )

    assert implementation_response.status_code == 200
    assert "Bekleyen degisiklik gorevi" in implementation_response.get_data(as_text=True)

    change.status = "Kapand\u0131"
    db.session.commit()
    closed_response = client.get("/uzerime-atananlar?module=change_management")

    assert closed_response.status_code == 200
    assert "Bekleyen degisiklik gorevi" not in closed_response.get_data(as_text=True)


def test_change_request_report_is_company_scoped(client):
    company_a = create_company("706")
    company_b = create_company("707")
    report_only_user = create_user(
        "change-report-only",
        company=company_a,
        permissions=("reports.view", "reports.export"),
    )
    reporter = create_user(
        "change-reporter",
        company=company_a,
        permissions=(
            "reports.view",
            "reports.export",
            "change_management.view",
            "change_management.export",
        ),
    )
    db.session.add_all(
        [
            ChangeRequest(
                company_id=company_a.id,
                change_no="DGY-2026-0001",
                title="Gorunen degisiklik",
                change_type="Proses",
                risk_level="D\u00fc\u015f\u00fck",
                status="Onay Bekliyor",
            ),
            ChangeRequest(
                company_id=company_b.id,
                change_no="DGY-2026-0002",
                title="Gorunmeyen degisiklik",
                change_type="Proses",
                risk_level="D\u00fc\u015f\u00fck",
                status="Onay Bekliyor",
            ),
        ]
    )
    db.session.commit()

    login(client, report_only_user)
    blocked_dashboard = client.get("/rapor-merkezi")
    blocked_export = client.get("/rapor-merkezi/change_requests/excel")

    assert blocked_dashboard.status_code == 200
    assert "/rapor-merkezi/change_requests/excel" not in blocked_dashboard.get_data(
        as_text=True
    )
    assert blocked_export.status_code == 404

    login(client, reporter)

    response = client.get("/rapor-merkezi/change_requests/excel")

    assert_xlsx_response(response)
    rows = sheet_values(response.data)
    flattened = "\n".join("\t".join(row) for row in rows)
    assert "Gorunen degisiklik" in flattened
    assert "Gorunmeyen degisiklik" not in flattened


def test_disabled_change_module_blocks_direct_route(client):
    company = create_company("708", module_keys=("actions",))
    user = create_user(
        "disabled-change-user",
        company=company,
        permissions=("change_management.view", "change_management.create"),
    )
    module = CompanyModule.query.filter_by(
        company_id=company.id,
        module_key="change_management",
    ).one()
    assert module.is_enabled is False
    login(client, user)

    response = client.get("/degisiklik-yonetimi")

    assert response.status_code == 403
