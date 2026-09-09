from datetime import date, timedelta

from app.extensions import db
from app.models import (
    Action,
    AppSetting,
    AuditLog,
    CompanyModule,
    DeviationFile,
    DeviationRecord,
)

from .helpers import assert_xlsx_response, create_company, create_user, login, sheet_values, upload_tuple


def test_deviation_dashboard_requires_permission(client):
    company = create_company("901")
    user = create_user("plain-deviation-user", company=company)
    login(client, user)

    response = client.get("/sapma-uygunsuz-urun")

    assert response.status_code == 403


def test_deviation_full_flow_marks_checklist_and_audits(app, client):
    company = create_company("902")
    manager = create_user(
        "deviation-manager",
        company=company,
        permissions=(
            "deviation.view",
            "deviation.create",
            "deviation.manage",
            "deviation.approve",
            "deviation.delete",
            "reports.view",
            "reports.export",
            "deviation.export",
        ),
        full_name="Yonetim Temsilcisi",
    )
    responsible = create_user(
        "deviation-responsible",
        company=company,
        permissions=("deviation.view", "deviation.create"),
        full_name="Aksiyon Sorumlusu",
    )
    login(client, manager)

    create_response = client.post(
        "/sapma-uygunsuz-urun/yeni",
        data={
            "title": "Beton numunesi etiket sapmasi",
            "record_type": "Uygunsuz \u00dcr\u00fcn",
            "source_type": "\u00dcretim",
            "department": "Kalite",
            "process_name": "Beton deneyi",
            "product_name": "C30 beton numunesi",
            "batch_no": "LOT-42",
            "quantity": "2 adet",
            "severity": "Y\u00fcksek",
            "detected_date": date.today().isoformat(),
            "containment_action": "Numuneler ayrildi.",
            "quarantine_location": "Karantina raf 1",
            "responsible_user_id": str(responsible.id),
            "approver_user_id": str(manager.id),
            "due_date": (date.today() + timedelta(days=5)).isoformat(),
            "description": "Etiket ile kayit bilgisi eslesmiyor.",
            "deviation_files": upload_tuple(b"tespit", "tespit.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert create_response.status_code == 200
    assert "Beton numunesi etiket sapmasi" in create_response.get_data(as_text=True)
    deviation = DeviationRecord.query.one()
    assert deviation.deviation_no.startswith(f"SAP-{date.today().year}-")
    assert deviation.status == "Karar Bekliyor"
    assert deviation.created_by_user_id == manager.id
    assert deviation.responsible_user_id == responsible.id
    assert DeviationFile.query.count() == 1
    assert AuditLog.query.filter_by(
        entity_type="DeviationRecord",
        action="deviation_created",
    ).count() == 1

    dashboard_response = client.get("/sapma-uygunsuz-urun")
    assert dashboard_response.status_code == 200
    assert "Beton numunesi etiket sapmasi" in dashboard_response.get_data(as_text=True)

    task_response = client.get("/uzerime-atananlar?module=deviation")
    assert task_response.status_code == 200
    assert "Beton numunesi etiket sapmasi" in task_response.get_data(as_text=True)

    download_response = client.get(f"/sapma-uygunsuz-urun/dosya/{deviation.files[0].id}/indir")
    assert download_response.status_code == 200
    assert download_response.data == b"tespit"

    quarantine_response = client.post(
        f"/sapma-uygunsuz-urun/{deviation.id}/karantinaya-al",
        data={
            "containment_action": "Saha kullanimi durduruldu.",
            "quarantine_location": "Karantina alani",
            "quarantine_files": upload_tuple(b"karantina", "karantina.jpg"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert quarantine_response.status_code == 200
    db.session.refresh(deviation)
    assert deviation.status == "Karantinada"
    assert DeviationFile.query.count() == 2
    linked_action = Action(
        company_id=company.id,
        action_number=420,
        title="Etiket kontrol aksiyonu",
        responsible_owner="Aksiyon Sorumlusu",
        responsible_user_id=responsible.id,
        department="Kalite",
        termin_date=date.today() + timedelta(days=2),
    )
    db.session.add(linked_action)
    db.session.commit()

    decision_response = client.post(
        f"/sapma-uygunsuz-urun/{deviation.id}/karar-ver",
        data={
            "disposition": "Aksiyon A\u00e7\u0131ld\u0131",
            "responsible_user_id": str(responsible.id),
            "action_id": str(linked_action.id),
            "due_date": (date.today() + timedelta(days=2)).isoformat(),
            "disposition_note": "Yeni etiket kontrolu yapilacak.",
            "root_cause": "Etiketleme kontrol noktasi eksik.",
            "corrective_action": "Cift kontrol listesi eklenecek.",
            "decision_files": upload_tuple(b"karar", "karar.xlsx"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert decision_response.status_code == 200
    db.session.refresh(deviation)
    assert deviation.status == "Aksiyon Bekliyor"
    assert DeviationFile.query.count() == 3
    assert AuditLog.query.filter_by(
        entity_type="DeviationRecord",
        action="deviation_decision_recorded",
    ).count() == 1
    assert db.session.get(
        AppSetting,
        "sales_readiness:competitor_deviation_management",
    ).value == "1"

    login(client, responsible)
    completion_response = client.post(
        f"/sapma-uygunsuz-urun/{deviation.id}/aksiyon-tamamlandi",
        data={
            "completion_note": "Kontrol listesi devreye alindi.",
            "closing_files": upload_tuple(b"kapanis", "kapanis.png"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert completion_response.status_code == 200
    db.session.refresh(deviation)
    assert deviation.status == "Etkinlik Kontrol\u00fc"

    login(client, manager)
    close_response = client.post(
        f"/sapma-uygunsuz-urun/{deviation.id}/etkinlik-kapat",
        data={
            "effectiveness_note": "Tekrar eden hata gorulmedi.",
            "effectiveness_files": upload_tuple(b"etkinlik", "etkinlik.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert close_response.status_code == 200
    db.session.refresh(deviation)
    assert deviation.status == "Kapat\u0131ld\u0131"
    assert deviation.closed_at == date.today()

    archive_response = client.post(
        f"/sapma-uygunsuz-urun/{deviation.id}/arsivle",
        follow_redirects=True,
    )
    assert archive_response.status_code == 200
    db.session.refresh(deviation)
    assert deviation.status == "Ar\u015fiv"
    assert deviation.archived_at is not None


def test_deviation_action_requires_owner_and_due_date(client):
    company = create_company("903")
    approver = create_user(
        "deviation-approver",
        company=company,
        permissions=("deviation.view", "deviation.approve"),
    )
    deviation = DeviationRecord(
        company_id=company.id,
        deviation_no="SAP-2026-0099",
        title="Eksik sorumlu sapma",
        record_type="Sapma",
        severity="Orta",
        status="Karar Bekliyor",
        approver_user_id=approver.id,
        created_by_user_id=approver.id,
    )
    db.session.add(deviation)
    db.session.commit()
    login(client, approver)

    response = client.post(
        f"/sapma-uygunsuz-urun/{deviation.id}/karar-ver",
        data={"disposition": "Yeniden \u0130\u015flem"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    db.session.refresh(deviation)
    assert deviation.status == "Karar Bekliyor"
    assert "sorumlu ve termin" in response.get_data(as_text=True)


def test_deviation_action_decision_requires_linked_action(client):
    company = create_company("907")
    approver = create_user(
        "deviation-action-link-approver",
        company=company,
        permissions=("deviation.view", "deviation.approve"),
    )
    responsible = create_user(
        "deviation-action-link-owner",
        company=company,
        permissions=("deviation.view",),
    )
    deviation = DeviationRecord(
        company_id=company.id,
        deviation_no="SAP-2026-0100",
        title="Baglantisiz aksiyon karari",
        record_type="Sapma",
        severity="Orta",
        status="Karar Bekliyor",
        approver_user_id=approver.id,
        responsible_user_id=responsible.id,
        due_date=date.today() + timedelta(days=3),
        created_by_user_id=responsible.id,
    )
    db.session.add(deviation)
    db.session.commit()
    login(client, approver)

    response = client.post(
        f"/sapma-uygunsuz-urun/{deviation.id}/karar-ver",
        data={
            "disposition": "Aksiyon A\u00e7\u0131ld\u0131",
            "responsible_user_id": str(responsible.id),
            "due_date": (date.today() + timedelta(days=3)).isoformat(),
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    db.session.refresh(deviation)
    assert deviation.status == "Karar Bekliyor"
    assert "ba\u011flant\u0131l\u0131 aksiyon" in response.get_data(as_text=True)


def test_deviation_report_is_company_scoped(client):
    company_a = create_company("904")
    company_b = create_company("905")
    report_only_user = create_user(
        "deviation-report-only",
        company=company_a,
        permissions=("reports.view", "reports.export"),
    )
    reporter = create_user(
        "deviation-reporter",
        company=company_a,
        permissions=(
            "reports.view",
            "reports.export",
            "deviation.view",
            "deviation.export",
        ),
    )
    db.session.add_all(
        [
            DeviationRecord(
                company_id=company_a.id,
                deviation_no="SAP-2026-0001",
                title="Gorunen sapma",
                record_type="Sapma",
                severity="D\u00fc\u015f\u00fck",
                status="Karar Bekliyor",
            ),
            DeviationRecord(
                company_id=company_b.id,
                deviation_no="SAP-2026-0002",
                title="Gorunmeyen sapma",
                record_type="Sapma",
                severity="D\u00fc\u015f\u00fck",
                status="Karar Bekliyor",
            ),
        ]
    )
    db.session.commit()

    login(client, report_only_user)
    blocked_dashboard = client.get("/rapor-merkezi")
    blocked_export = client.get("/rapor-merkezi/deviations/excel")
    assert blocked_dashboard.status_code == 200
    assert "/rapor-merkezi/deviations/excel" not in blocked_dashboard.get_data(
        as_text=True
    )
    assert blocked_export.status_code == 404

    login(client, reporter)
    response = client.get("/rapor-merkezi/deviations/excel")

    assert_xlsx_response(response)
    rows = sheet_values(response.data)
    flattened = "\n".join("\t".join(row) for row in rows)
    assert "Gorunen sapma" in flattened
    assert "Gorunmeyen sapma" not in flattened


def test_disabled_deviation_module_blocks_direct_route(client):
    company = create_company("906", module_keys=("actions",))
    user = create_user(
        "disabled-deviation-user",
        company=company,
        permissions=("deviation.view", "deviation.create"),
    )
    module = CompanyModule.query.filter_by(
        company_id=company.id,
        module_key="deviation_management",
    ).one()
    assert module.is_enabled is False
    login(client, user)

    response = client.get("/sapma-uygunsuz-urun")

    assert response.status_code == 403
