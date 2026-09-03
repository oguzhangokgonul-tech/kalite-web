from datetime import date, timedelta

from app.extensions import db
from app.models import Action, DEPARTMENTS, DOF_PRIORITIES, DOF_SOURCES, Dof, DofFile

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
            **dof_payload(
                owner,
                root_cause_analysis="Kok neden bulundu",
                corrective_action="Duzeltici faaliyet yapildi",
                closing_evidence="Kapanis kaniti aciklamasi",
            ),
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


def test_dof_final_approval_requires_standard_capa_fields(client):
    company = create_company("326")
    owner = create_user("dof-capa-owner", company=company)
    representative = create_user(
        "dof-capa-representative",
        company=company,
        role_key="management_representative",
    )
    superadmin = create_user("dof-capa-superadmin", role_key="super_admin")
    dof = make_dof(
        company,
        owner,
        root_cause_analysis="",
        corrective_action="",
        closing_evidence="",
    )

    login(client, representative)
    assert client.post(f"/dofs/{dof.id}/approve-management").status_code == 302

    login(client, superadmin, company)
    response = client.post(f"/dofs/{dof.id}/approve-deputy")

    assert response.status_code == 302
    db.session.refresh(dof)
    assert dof.approval_step == "general_manager_deputy"
    assert dof.status != "Tamamlandı"


def test_dof_effectiveness_review_is_task_and_can_complete(client):
    company = create_company("327")
    owner = create_user("dof-effect-owner", company=company)
    effectiveness_owner = create_user("dof-effect-reviewer", company=company)
    representative = create_user(
        "dof-effect-representative",
        company=company,
        role_key="management_representative",
    )
    superadmin = create_user("dof-effect-superadmin", role_key="super_admin")
    dof = make_dof(
        company,
        owner,
        root_cause_analysis="Kok neden",
        corrective_action="Duzeltici faaliyet",
        closing_evidence="Kanıt tamam",
        effectiveness_required=True,
        effectiveness_owner_user_id=effectiveness_owner.id,
        effectiveness_due_date=date.today(),
        effectiveness_result="Bekliyor",
    )

    login(client, representative)
    assert client.post(f"/dofs/{dof.id}/approve-management").status_code == 302
    login(client, superadmin, company)
    assert client.post(f"/dofs/{dof.id}/approve-deputy").status_code == 302

    db.session.refresh(dof)
    assert dof.status == "Etkinlik Kontrolü Bekliyor"
    assert dof.approval_step == "effectiveness_review"

    login(client, effectiveness_owner)
    tasks_response = client.get("/uzerime-atananlar?module=dof")

    assert tasks_response.status_code == 200
    assert "Etkinlik Kontrolü" in tasks_response.get_data(as_text=True)

    response = client.post(
        f"/dofs/{dof.id}/effectiveness",
        data={"effectiveness_result": "Etkin", "effectiveness_note": "Uygun"},
    )

    assert response.status_code == 302
    db.session.refresh(dof)
    assert dof.status == "Tamamlandı"
    assert dof.approval_step == "completed"
    assert dof.effectiveness_checked_by_user_id == effectiveness_owner.id


def test_dof_effectiveness_task_is_not_duplicated_for_same_owner(client):
    company = create_company("329")
    owner = create_user("dof-effect-same-owner", company=company)
    representative = create_user(
        "dof-effect-same-representative",
        company=company,
        role_key="management_representative",
    )
    superadmin = create_user("dof-effect-same-superadmin", role_key="super_admin")
    dof = make_dof(
        company,
        owner,
        dof_no="IF-2026-0099",
        root_cause_analysis="Kok neden",
        corrective_action="Duzeltici faaliyet",
        closing_evidence="Kanit tamam",
        effectiveness_required=True,
        effectiveness_owner_user_id=owner.id,
        effectiveness_due_date=date.today(),
        effectiveness_result="Bekliyor",
    )

    login(client, representative)
    assert client.post(f"/dofs/{dof.id}/approve-management").status_code == 302
    login(client, superadmin, company)
    assert client.post(f"/dofs/{dof.id}/approve-deputy").status_code == 302

    login(client, owner)
    response = client.get("/uzerime-atananlar?module=dof")

    assert response.status_code == 200
    assert response.get_data(as_text=True).count(dof.dof_no) == 2


def test_dof_linked_action_can_be_created_from_detail(client):
    company = create_company("328")
    owner = create_user(
        "dof-action-owner",
        company=company,
        permissions=("actions.create",),
    )
    dof = make_dof(
        company,
        owner,
        title="Bagli aksiyon IF",
        root_cause_analysis="Kok neden",
        corrective_action="Duzeltici faaliyet",
    )

    login(client, owner)
    form_response = client.get(f"/actions/new?dof_id={dof.id}")
    assert form_response.status_code == 200
    assert "Bagli aksiyon IF" in form_response.get_data(as_text=True)

    response = client.post(
        "/actions/new",
        data={
            "title": "IF bagli aksiyon",
            "responsible_user_id": str(owner.id),
            "related_user_1_id": "",
            "related_user_2_id": "",
            "department": dof.department,
            "description": "Aksiyon aciklamasi",
            "termin_date": (date.today() + timedelta(days=5)).isoformat(),
            "dof_id": str(dof.id),
            "capa_type": "Düzeltici Faaliyet",
            "sub_action_indexes": "",
        },
    )

    assert response.status_code == 302
    action = Action.query.one()
    assert action.dof_id == dof.id
    assert action.company_id == company.id


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
