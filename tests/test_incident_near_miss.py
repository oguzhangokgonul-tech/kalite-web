from datetime import date, timedelta

from app.extensions import db
from app.models import (
    Action,
    AppSetting,
    AuditLog,
    CompanyModule,
    IncidentFile,
    IncidentReport,
    INCIDENT_STATUS_ACTION_PENDING,
    INCIDENT_STATUS_CLOSED,
    INCIDENT_STATUS_EFFECTIVENESS,
    INCIDENT_STATUS_REVIEW,
)

from .helpers import assert_xlsx_response, create_company, create_user, login, sheet_values, upload_tuple


def test_incident_dashboard_requires_permission(client):
    company = create_company("951")
    user = create_user("plain-incident-user", company=company)
    login(client, user)

    response = client.get("/olay-ramak-kala")

    assert response.status_code == 403


def test_incident_full_flow_marks_checklist_and_audits(app, client):
    company = create_company("952")
    manager = create_user(
        "incident-manager",
        company=company,
        permissions=(
            "incident.view",
            "incident.create",
            "incident.manage",
            "incident.review",
            "incident.delete",
            "reports.view",
            "reports.export",
            "incident.export",
            "actions.view_all",
        ),
        full_name="Yonetim Temsilcisi",
    )
    responsible = create_user(
        "incident-responsible",
        company=company,
        permissions=("incident.view", "incident.create"),
        full_name="Aksiyon Sorumlusu",
    )
    login(client, manager)

    create_response = client.post(
        "/olay-ramak-kala/yeni",
        data={
            "title": "Forklift yolu ramak kala bildirimi",
            "report_type": "Ramak Kala",
            "department": "Kalite",
            "location": "Sevkiyat alani",
            "process_name": "Yukleme",
            "severity": "Y\u00fcksek",
            "probability": "3",
            "incident_date": date.today().isoformat(),
            "incident_time": "09:30",
            "immediate_action": "Alan seritle ayrildi.",
            "description": "Yaya yolu ile forklift yolu kesisiyor.",
            "incident_files": upload_tuple(b"bildirim", "bildirim.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert create_response.status_code == 200
    assert "Forklift yolu ramak kala bildirimi" in create_response.get_data(as_text=True)
    incident = IncidentReport.query.one()
    assert incident.incident_no.startswith(f"OLY-{date.today().year}-")
    assert incident.status == "Yeni Bildirim"
    assert incident.reported_by_user_id == manager.id
    assert incident.risk_score == 9
    assert IncidentFile.query.count() == 1
    assert AuditLog.query.filter_by(
        entity_type="IncidentReport",
        action="incident_created",
    ).count() == 1

    dashboard_response = client.get("/olay-ramak-kala")
    assert dashboard_response.status_code == 200
    assert "Forklift yolu ramak kala bildirimi" in dashboard_response.get_data(as_text=True)

    task_response = client.get("/uzerime-atananlar?module=incident")
    assert task_response.status_code == 200
    assert "Forklift yolu ramak kala bildirimi" in task_response.get_data(as_text=True)

    download_response = client.get(f"/olay-ramak-kala/dosya/{incident.files[0].id}/indir")
    assert download_response.status_code == 200
    assert download_response.data == b"bildirim"

    review_response = client.post(
        f"/olay-ramak-kala/{incident.id}/incelemeye-al",
        data={
            "immediate_action": "Saha isaretlemesi yapildi.",
            "review_files": upload_tuple(b"inceleme", "inceleme.jpg"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert review_response.status_code == 200
    db.session.refresh(incident)
    assert incident.status == INCIDENT_STATUS_REVIEW
    assert incident.reviewer_user_id == manager.id
    assert IncidentFile.query.count() == 2

    linked_action = Action(
        company_id=company.id,
        action_number=520,
        title="Forklift yaya yolu ayirma",
        responsible_owner="Aksiyon Sorumlusu",
        responsible_user_id=responsible.id,
        department="Kalite",
        termin_date=date.today() + timedelta(days=2),
    )
    db.session.add(linked_action)
    db.session.commit()

    decision_response = client.post(
        f"/olay-ramak-kala/{incident.id}/karar-ver",
        data={
            "decision": "Aksiyon A\u00e7\u0131ld\u0131",
            "responsible_user_id": str(responsible.id),
            "action_id": str(linked_action.id),
            "due_date": (date.today() + timedelta(days=2)).isoformat(),
            "decision_note": "Kalici ayrim cizgileri uygulanacak.",
            "root_cause": "Yaya yolu saha uzerinde net ayrilmamis.",
            "corrective_action": "Boya ve bariyer uygulanacak.",
            "decision_files": upload_tuple(b"karar", "karar.xlsx"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert decision_response.status_code == 200
    db.session.refresh(incident)
    assert incident.status == INCIDENT_STATUS_ACTION_PENDING
    assert IncidentFile.query.count() == 3
    assert AuditLog.query.filter_by(
        entity_type="IncidentReport",
        action="incident_decision_recorded",
    ).count() == 1
    assert db.session.get(
        AppSetting,
        "sales_readiness:competitor_incident_near_miss",
    ).value == "1"

    login(client, responsible)
    completion_response = client.post(
        f"/olay-ramak-kala/{incident.id}/aksiyon-tamamlandi",
        data={
            "completion_note": "Yaya yolu bariyerle ayrildi.",
            "closing_files": upload_tuple(b"kapanis", "kapanis.png"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert completion_response.status_code == 200
    db.session.refresh(incident)
    assert incident.status == INCIDENT_STATUS_EFFECTIVENESS

    login(client, manager)
    close_response = client.post(
        f"/olay-ramak-kala/{incident.id}/etkinlik-kapat",
        data={
            "effectiveness_note": "Saha turunda tekrar risk gorulmedi.",
            "effectiveness_files": upload_tuple(b"etkinlik", "etkinlik.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert close_response.status_code == 200
    db.session.refresh(incident)
    assert incident.status == INCIDENT_STATUS_CLOSED
    assert incident.closed_at == date.today()

    archive_response = client.post(
        f"/olay-ramak-kala/{incident.id}/arsivle",
        follow_redirects=True,
    )
    assert archive_response.status_code == 200
    db.session.refresh(incident)
    assert incident.status == "Ar\u015fiv"
    assert incident.archived_at is not None


def test_incident_action_decision_requires_linked_action(client):
    company = create_company("953")
    reviewer = create_user(
        "incident-action-link-reviewer",
        company=company,
        permissions=("incident.view", "incident.review"),
    )
    responsible = create_user(
        "incident-action-link-owner",
        company=company,
        permissions=("incident.view",),
    )
    incident = IncidentReport(
        company_id=company.id,
        incident_no="OLY-2026-0100",
        title="Baglantisiz aksiyon karari",
        report_type="Olay",
        severity="Orta",
        status=INCIDENT_STATUS_REVIEW,
        reviewer_user_id=reviewer.id,
        responsible_user_id=responsible.id,
        due_date=date.today() + timedelta(days=3),
        reported_by_user_id=responsible.id,
    )
    db.session.add(incident)
    db.session.commit()
    login(client, reviewer)

    response = client.post(
        f"/olay-ramak-kala/{incident.id}/karar-ver",
        data={
            "decision": "Aksiyon A\u00e7\u0131ld\u0131",
            "responsible_user_id": str(responsible.id),
            "due_date": (date.today() + timedelta(days=3)).isoformat(),
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    db.session.refresh(incident)
    assert incident.status == INCIDENT_STATUS_REVIEW
    assert "ba\u011flant\u0131l\u0131 aksiyon" in response.get_data(as_text=True)


def test_incident_report_is_company_scoped(client):
    company_a = create_company("954")
    company_b = create_company("955")
    report_only_user = create_user(
        "incident-report-only",
        company=company_a,
        permissions=("reports.view", "reports.export"),
    )
    reporter = create_user(
        "incident-reporter",
        company=company_a,
        permissions=(
            "reports.view",
            "reports.export",
            "incident.view",
            "incident.export",
        ),
    )
    db.session.add_all(
        [
            IncidentReport(
                company_id=company_a.id,
                incident_no="OLY-2026-0001",
                title="Gorunen olay",
                report_type="Ramak Kala",
                severity="D\u00fc\u015f\u00fck",
                status=INCIDENT_STATUS_REVIEW,
            ),
            IncidentReport(
                company_id=company_b.id,
                incident_no="OLY-2026-0002",
                title="Gorunmeyen olay",
                report_type="Ramak Kala",
                severity="D\u00fc\u015f\u00fck",
                status=INCIDENT_STATUS_REVIEW,
            ),
        ]
    )
    db.session.commit()

    login(client, report_only_user)
    blocked_dashboard = client.get("/rapor-merkezi")
    blocked_export = client.get("/rapor-merkezi/incidents/excel")
    assert blocked_dashboard.status_code == 200
    assert "/rapor-merkezi/incidents/excel" not in blocked_dashboard.get_data(
        as_text=True
    )
    assert blocked_export.status_code == 404

    login(client, reporter)
    response = client.get("/rapor-merkezi/incidents/excel")

    assert_xlsx_response(response)
    rows = sheet_values(response.data)
    flattened = "\n".join("\t".join(row) for row in rows)
    assert "Gorunen olay" in flattened
    assert "Gorunmeyen olay" not in flattened


def test_disabled_incident_module_blocks_direct_route(client):
    company = create_company("956", module_keys=("actions",))
    user = create_user(
        "disabled-incident-user",
        company=company,
        permissions=("incident.view", "incident.create"),
    )
    module = CompanyModule.query.filter_by(
        company_id=company.id,
        module_key="incident_near_miss",
    ).one()
    assert module.is_enabled is False
    login(client, user)

    response = client.get("/olay-ramak-kala")

    assert response.status_code == 403
