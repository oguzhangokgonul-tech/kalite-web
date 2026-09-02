from datetime import date, timedelta

from app.extensions import db
from app.models import DEPARTMENTS, DOF_PRIORITIES, DOF_SOURCES, Dof, DofFile

from .helpers import create_company, create_user, login, upload_tuple


def dof_payload(responsible, **overrides):
    data = {
        "save_mode": "open",
        "title": "Uygunsuzluk basligi",
        "department": "Kalite" if "Kalite" in DEPARTMENTS else DEPARTMENTS[0],
        "responsible_id": str(responsible.id),
        "opening_date": date.today().isoformat(),
        "due_date": (date.today() + timedelta(days=7)).isoformat(),
        "priority": DOF_PRIORITIES[-1],
        "source": DOF_SOURCES[-1],
        "nonconformity_description": "Uygunsuzluk aciklamasi",
        "root_cause_analysis": "",
        "corrective_action": "",
        "preventive_action": "",
        "closing_evidence": "",
    }
    data.update(overrides)
    return data


def make_dof(company, responsible, **overrides):
    dof = Dof(
        company_id=company.id,
        dof_no=overrides.pop("dof_no", "IF-2026-0001"),
        title=overrides.pop("title", "IF basligi"),
        department=overrides.pop("department", "Kalite"),
        responsible_id=responsible.id,
        created_by_user_id=overrides.pop("created_by_user_id", responsible.id),
        opening_date=overrides.pop("opening_date", date.today()),
        due_date=overrides.pop("due_date", date.today() + timedelta(days=7)),
        priority=overrides.pop("priority", DOF_PRIORITIES[-1]),
        source=overrides.pop("source", DOF_SOURCES[-1]),
        nonconformity_description=overrides.pop(
            "nonconformity_description",
            "Uygunsuzluk aciklamasi",
        ),
        status=overrides.pop("status", "Onay Akisi Bekleniyor"),
        approval_step=overrides.pop("approval_step", "management_representative"),
        **overrides,
    )
    db.session.add(dof)
    db.session.commit()
    return dof


def test_dof_create_opening_file_download_and_approval_flow(client):
    company = create_company("321")
    owner = create_user("dof-owner", company=company)
    representative = create_user(
        "dof-representative",
        company=company,
        role_key="management_representative",
    )
    superadmin = create_user("superadmin", role_key="super_admin")

    login(client, owner)
    response = client.post(
        "/dofs/new",
        data={
            **dof_payload(owner),
            "opening_files": upload_tuple(b"finding-image", "bulgu.png"),
        },
    )

    assert response.status_code == 302
    dof = Dof.query.one()
    assert dof.company_id == company.id
    assert dof.dof_no.startswith("IF-")
    assert dof.approval_step == "management_representative"
    dof_file = DofFile.query.one()

    download_response = client.get(f"/dofs/{dof.id}/files/{dof_file.id}/download")
    assert download_response.status_code == 200
    assert download_response.data == b"finding-image"

    login(client, representative)
    response = client.post(f"/dofs/{dof.id}/approve-management")

    assert response.status_code == 302
    db.session.refresh(dof)
    assert dof.approval_step == "general_manager_deputy"
    assert dof.management_approved_by_user_id == representative.id

    login(client, superadmin, company)
    response = client.post(f"/dofs/{dof.id}/approve-deputy")

    assert response.status_code == 302
    db.session.refresh(dof)
    assert dof.approval_step == "completed"
    assert dof.deputy_approved_by_user_id == superadmin.id


def test_dof_reject_and_revision_returns_to_management_approval(client):
    company = create_company("322")
    owner = create_user("dof-revision-owner", company=company)
    representative = create_user(
        "revision-representative",
        company=company,
        role_key="management_representative",
    )
    dof = make_dof(company, owner)

    login(client, representative)
    response = client.post(
        f"/dofs/{dof.id}/reject",
        data={"rejection_reason": "Eksik kok neden"},
    )

    assert response.status_code == 302
    db.session.refresh(dof)
    assert dof.approval_step == "revision_requested"
    assert dof.rejection_reason == "Eksik kok neden"

    login(client, owner)
    response = client.post(
        f"/dofs/{dof.id}/revision",
        data=dof_payload(
            owner,
            root_cause_analysis="Kok neden tamamlandi",
            revision_note="Duzenlendi",
        ),
    )

    assert response.status_code == 302
    db.session.refresh(dof)
    assert dof.approval_step == "management_representative"
    assert dof.rejection_reason is None
    assert dof.root_cause_analysis == "Kok neden tamamlandi"


def test_dof_due_sort_puts_highest_delay_first_and_completed_last(client):
    company = create_company("323")
    representative = create_user(
        "sort-representative",
        company=company,
        role_key="management_representative",
    )
    make_dof(
        company,
        representative,
        dof_no="IF-2026-0001",
        due_date=date.today() - timedelta(days=45),
    )
    make_dof(
        company,
        representative,
        dof_no="IF-2026-0002",
        due_date=date.today() - timedelta(days=10),
    )
    make_dof(
        company,
        representative,
        dof_no="IF-2026-0003",
        due_date=date.today() - timedelta(days=60),
        status="Tamamlandi",
        approval_step="completed",
    )
    make_dof(
        company,
        representative,
        dof_no="IF-2026-0004",
        due_date=date.today() + timedelta(days=1),
    )

    login(client, representative)
    response = client.get("/dofs?sort=due_nearest")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert body.index("IF-0001") < body.index("IF-0002")
    assert body.index("IF-0002") < body.index("IF-0004")
    assert body.index("IF-0004") < body.index("IF-0003")


def test_dof_detail_is_not_visible_across_companies(client):
    company_a = create_company("324")
    company_b = create_company("325")
    user_a = create_user("tenant-dof-user", company=company_a)
    user_b = create_user("tenant-dof-owner", company=company_b)
    foreign_dof = make_dof(company_b, user_b)

    login(client, user_a)

    assert client.get(f"/dofs/{foreign_dof.id}").status_code == 404
