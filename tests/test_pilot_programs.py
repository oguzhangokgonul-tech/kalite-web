import json

from app.extensions import db
from app.models import AppSetting, AuditLog, PilotProgram
from tests.helpers import create_company, create_user, login


def test_pilot_programs_superadmin_account_only(app, client):
    company = create_company("801")
    viewer = create_user("pilot-viewer", company=company)
    manager = create_user(
        "pilot-manager",
        company=company,
        permissions=("users.manage",),
    )
    role_superadmin = create_user("pilot-role-superadmin", role_key="super_admin")

    login(client, viewer, company)
    assert client.get("/pilot-programi").status_code == 403

    login(client, manager, company)
    assert client.get("/pilot-programi").status_code == 403

    login(client, role_superadmin)
    assert client.get("/pilot-programi").status_code == 403

    superadmin = create_user("superadmin")
    login(client, superadmin)
    assert client.get("/pilot-programi").status_code == 200


def test_pilot_program_sidebar_link_only_for_superadmin_account(app, client):
    company = create_company("802")
    manager = create_user(
        "pilot-sidebar-manager",
        company=company,
        permissions=("users.manage",),
    )
    login(client, manager, company)

    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/pilot-programi"' not in response.get_data(as_text=True)

    superadmin = create_user("superadmin")
    login(client, superadmin)

    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/pilot-programi"' in response.get_data(as_text=True)


def test_superadmin_can_create_update_and_archive_pilot_program(app, client):
    company = create_company("803", name="Pilot Firma")
    superadmin = create_user("superadmin")
    login(client, superadmin)

    response = client.post(
        "/pilot-programi/yeni",
        data={
            "company_id": str(company.id),
            "status": "planned",
            "contact_name": "Ayse Pilot",
            "contact_phone": "0555 111 22 33",
            "contact_email": "ayse@example.com",
            "start_date": "2026-09-08",
            "end_date": "2026-10-08",
            "next_follow_up_date": "2026-09-15",
            "target_modules": ["documents", "if_management"],
            "success_criteria": "Dokuman ve IF akislarini denesin.",
            "feedback_summary": "Ilk gorusme olumlu.",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    program = PilotProgram.query.one()
    assert program.company_id == company.id
    assert json.loads(program.target_modules) == ["documents", "if_management"]
    created_log = AuditLog.query.filter_by(
        entity_type="PilotProgram",
        action="pilot_created",
    ).one()
    assert created_log.company_id == company.id

    response = client.post(
        f"/pilot-programi/{program.id}/duzenle",
        data={
            "company_id": str(company.id),
            "status": "active",
            "contact_name": "Ayse Pilot",
            "sales_blocker": "on",
            "sales_blocker_note": "Fiyat netlesmeli.",
            "result": "Pilot devam ediyor",
            "target_modules": ["documents"],
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    program = db.session.get(PilotProgram, program.id)
    assert program.status == "active"
    assert program.sales_blocker is True
    assert program.sales_blocker_note == "Fiyat netlesmeli."
    assert AuditLog.query.filter_by(
        entity_type="PilotProgram",
        action="pilot_updated",
    ).count() == 1

    response = client.post(
        f"/pilot-programi/{program.id}/arsivle",
        follow_redirects=True,
    )

    assert response.status_code == 200
    program = db.session.get(PilotProgram, program.id)
    assert program.status == "archived"
    assert AuditLog.query.filter_by(
        entity_type="PilotProgram",
        action="pilot_archived",
    ).count() == 1


def test_two_qualified_pilots_mark_sales_readiness(app, client):
    company_a = create_company("804")
    company_b = create_company("805")
    superadmin = create_user("superadmin")
    login(client, superadmin)

    client.post(
        "/pilot-programi/yeni",
        data={"company_id": str(company_a.id), "status": "active"},
    )
    assert db.session.get(AppSetting, "sales_readiness:month5_pilots") is None

    client.post(
        "/pilot-programi/yeni",
        data={"company_id": str(company_b.id), "status": "completed"},
    )

    setting = db.session.get(AppSetting, "sales_readiness:month5_pilots")
    assert setting is not None
    assert setting.value == "1"
