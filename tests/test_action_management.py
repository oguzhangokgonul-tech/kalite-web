from datetime import date, timedelta

from app.extensions import db
from app.models import Action, ActionComment, ActionHistory, ActionSubTask, DEPARTMENTS

from .helpers import create_company, create_user, login, upload_tuple


def action_payload(responsible, **overrides):
    data = {
        "title": "Satisa hazirlik aksiyonu",
        "responsible_user_id": str(responsible.id),
        "related_user_1_id": "",
        "related_user_2_id": "",
        "department": "Kalite" if "Kalite" in DEPARTMENTS else DEPARTMENTS[0],
        "description": "Aksiyon aciklamasi",
        "termin_date": (date.today() + timedelta(days=7)).isoformat(),
        "sub_action_indexes": "",
    }
    data.update(overrides)
    return data


def make_action(company, responsible, **overrides):
    action = Action(
        company_id=company.id,
        action_number=overrides.pop("action_number", 1),
        title=overrides.pop("title", "Atanan aksiyon"),
        responsible_owner=responsible.full_name,
        responsible_user_id=responsible.id,
        department=overrides.pop("department", "Kalite"),
        termin_date=overrides.pop("termin_date", date.today() + timedelta(days=7)),
        **overrides,
    )
    db.session.add(action)
    db.session.commit()
    return action


def test_action_create_file_comment_subtask_and_closure_flow(client):
    company = create_company("331")
    responsible = create_user(
        "action-owner",
        company=company,
        permissions=(
            "actions.create",
            "actions.comment_assigned",
            "actions.request_close_assigned",
        ),
    )
    approver = create_user(
        "action-approver",
        company=company,
        role_key="management_representative",
    )

    login(client, responsible)
    response = client.post(
        "/actions/new",
        data={
            **action_payload(responsible),
            "action_file": upload_tuple(b"action-file", "aksiyon.pdf"),
        },
    )

    assert response.status_code == 302
    action = Action.query.one()
    assert action.action_number == 1
    assert action.file_original_name == "aksiyon.pdf"
    assert client.get(f"/actions/{action.id}/download").data == b"action-file"

    response = client.post(
        f"/actions/{action.id}/comments",
        data={"comment": "Durum notu eklendi"},
    )

    assert response.status_code == 302
    assert ActionComment.query.filter_by(action_id=action.id).count() == 1

    response = client.post(
        f"/actions/{action.id}/sub-actions/create",
        data={
            "title": "Alt aksiyon",
            "description": "",
            "responsible_id": str(responsible.id),
            "related_user_1_id": "",
            "related_user_2_id": "",
            "due_date": (date.today() + timedelta(days=3)).isoformat(),
            "priority": "Orta",
            "status": "Beklemede",
        },
    )

    assert response.status_code == 302
    sub_action = ActionSubTask.query.one()

    response = client.post(
        f"/sub-actions/{sub_action.id}/complete",
        data={"closing_note": "Tamamlandi"},
    )

    assert response.status_code == 302
    db.session.refresh(sub_action)
    assert sub_action.completed_by_user_id == responsible.id

    response = client.post(
        f"/actions/{action.id}/request-closure",
        data={"closure_evidence_note": "Kapanis kaniti tamam"},
    )

    assert response.status_code == 302
    db.session.refresh(action)
    assert action.closure_approval_requested is True

    login(client, approver)
    response = client.post(f"/actions/{action.id}/complete")

    assert response.status_code == 302
    db.session.refresh(action)
    assert action.is_completed is True
    assert ActionHistory.query.filter_by(action_id=action.id, event_type="completed").count() == 1


def test_assigned_tasks_only_lists_relevant_actions(client):
    company = create_company("332")
    owner = create_user("assigned-owner", company=company)
    other = create_user("other-owner", company=company)
    make_action(company, owner, title="Gorunen aksiyon", action_number=1)
    make_action(company, other, title="Gorunmeyen aksiyon", action_number=2)

    login(client, owner)
    response = client.get("/uzerime-atananlar?tab=actions")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Gorunen aksiyon" in body
    assert "Gorunmeyen aksiyon" not in body


def test_action_detail_is_not_visible_across_companies(client):
    company_a = create_company("333")
    company_b = create_company("334")
    user_a = create_user("tenant-action-user", company=company_a)
    user_b = create_user("tenant-action-owner", company=company_b)
    foreign_action = make_action(company_b, user_b)

    login(client, user_a)

    assert client.get(f"/actions/{foreign_action.id}").status_code == 404


def test_action_effectiveness_review_becomes_assigned_task(client):
    company = create_company("335")
    responsible = create_user(
        "action-effect-owner",
        company=company,
        permissions=("actions.comment_assigned", "actions.request_close_assigned"),
    )
    reviewer = create_user("action-effect-reviewer", company=company)
    approver = create_user(
        "action-effect-approver",
        company=company,
        role_key="management_representative",
    )
    action = make_action(
        company,
        responsible,
        effectiveness_required=True,
        effectiveness_owner_user_id=reviewer.id,
        effectiveness_due_date=date.today(),
        effectiveness_result="Bekliyor",
    )

    login(client, responsible)
    assert client.post(
        f"/actions/{action.id}/request-closure",
        data={"closure_evidence_note": "Kapanis kaniti"},
    ).status_code == 302

    login(client, approver)
    assert client.post(f"/actions/{action.id}/complete").status_code == 302

    login(client, reviewer)
    tasks_response = client.get("/uzerime-atananlar?module=action")

    assert tasks_response.status_code == 200
    assert "Etkinlik Kontrolü" in tasks_response.get_data(as_text=True)

    response = client.post(
        f"/actions/{action.id}/effectiveness",
        data={"effectiveness_result": "Etkin", "effectiveness_note": "Uygun"},
    )

    assert response.status_code == 302
    db.session.refresh(action)
    assert action.effectiveness_result == "Etkin"
    assert action.effectiveness_checked_by_user_id == reviewer.id


def test_action_effectiveness_rejected_reopens_action(client):
    company = create_company("336")
    responsible = create_user(
        "action-effect-reopen-owner",
        company=company,
        permissions=("actions.comment_assigned", "actions.request_close_assigned"),
    )
    reviewer = create_user("action-effect-reopen-reviewer", company=company)
    approver = create_user(
        "action-effect-reopen-approver",
        company=company,
        role_key="management_representative",
    )
    action = make_action(
        company,
        responsible,
        effectiveness_required=True,
        effectiveness_owner_user_id=reviewer.id,
        effectiveness_due_date=date.today(),
        effectiveness_result="Bekliyor",
    )

    login(client, responsible)
    assert client.post(
        f"/actions/{action.id}/request-closure",
        data={"closure_evidence_note": "Kapanis kaniti"},
    ).status_code == 302

    login(client, approver)
    assert client.post(f"/actions/{action.id}/complete").status_code == 302

    login(client, reviewer)
    response = client.post(
        f"/actions/{action.id}/effectiveness",
        data={"effectiveness_result": "Etkin Değil", "effectiveness_note": "Yetersiz"},
    )

    assert response.status_code == 302
    db.session.refresh(action)
    assert action.effectiveness_result == "Etkin Değil"
    assert action.is_completed is False
    assert action.completed_at is None
    assert action.closure_approval_requested is False
    assert action.closure_rejection_reason == "Yetersiz"

    login(client, responsible)
    tasks_response = client.get("/uzerime-atananlar?module=action")

    assert tasks_response.status_code == 200
    assert "Etkin Değil" in tasks_response.get_data(as_text=True)

    response = client.post(
        f"/actions/{action.id}/request-closure",
        data={"closure_evidence_note": "Yeni kapanis kaniti"},
    )
    assert response.status_code == 302

    login(client, approver)
    response = client.post(f"/actions/{action.id}/complete")

    assert response.status_code == 302
    db.session.refresh(action)
    assert action.is_completed is True
    assert action.effectiveness_result == "Bekliyor"
    assert action.effectiveness_note is None
