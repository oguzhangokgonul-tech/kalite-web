from datetime import date, timedelta

import pytest
from werkzeug.exceptions import NotFound

from app.extensions import db
from app.models import Action, ActionClosureFile, ActionComment, ActionHistory, ActionSubTask, AuditLog, DEPARTMENTS
from app.routes import send_action_upload

from .helpers import create_company, create_user, login, upload_tuple, write_stored_upload


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


def test_assigned_viewer_cannot_change_action_or_create_sub_action(client):
    company = create_company("337")
    viewer = create_user("action-read-only", company=company, role_key="viewer")
    action = make_action(company, viewer)
    old_termin = action.termin_date
    sub_action = ActionSubTask(
        company_id=company.id,
        parent_action_id=action.id,
        title="Salt okunur alt aksiyon",
        responsible_id=viewer.id,
        created_by_user_id=viewer.id,
        due_date=old_termin,
    )
    db.session.add(sub_action)
    db.session.commit()

    login(client, viewer)
    assert client.get(f"/actions/{action.id}").status_code == 200
    assert client.post(
        f"/actions/{action.id}/revise-termin",
        data={"termin_date": (old_termin + timedelta(days=1)).isoformat()},
    ).status_code == 403
    assert client.post(
        f"/actions/{action.id}/sub-actions/create",
        data={
            "title": "Yetkisiz alt aksiyon",
            "responsible_id": str(viewer.id),
            "due_date": old_termin.isoformat(),
            "priority": "Orta",
            "status": "Beklemede",
        },
    ).status_code == 403
    assert client.get(f"/sub-actions/{sub_action.id}/edit").status_code == 403
    assert client.post(
        f"/sub-actions/{sub_action.id}/edit",
        data={"title": "Degistirildi"},
    ).status_code == 403
    assert client.post(
        f"/sub-actions/{sub_action.id}/complete",
        data={"closing_note": "Yetkisiz"},
    ).status_code == 403
    assert client.post(f"/sub-actions/{sub_action.id}/delete").status_code == 403
    db.session.refresh(action)
    db.session.refresh(sub_action)
    assert action.termin_date == old_termin
    assert sub_action.title == "Salt okunur alt aksiyon"
    assert sub_action.completed_at is None
    assert ActionSubTask.query.filter_by(parent_action_id=action.id).count() == 1


def test_foreign_action_mutations_and_downloads_are_not_found(client):
    company_a = create_company("338")
    company_b = create_company("339")
    manager = create_user(
        "action-foreign-manager", company=company_a, role_key="management_representative"
    )
    owner = create_user("action-foreign-owner", company=company_b)
    action = make_action(company_b, owner)
    sub_action = ActionSubTask(
        company_id=company_b.id,
        parent_action_id=action.id,
        title="Yabanci alt aksiyon",
        responsible_id=owner.id,
    )
    db.session.add(sub_action)
    db.session.commit()

    login(client, manager)
    for path in (
        f"/actions/{action.id}",
        f"/actions/{action.id}/edit",
        f"/actions/{action.id}/delete",
        f"/actions/{action.id}/download",
        f"/actions/{action.id}/closure-evidence/download",
        f"/sub-actions/{sub_action.id}",
        f"/sub-actions/{sub_action.id}/evidence/download",
    ):
        assert client.get(path).status_code == 404, path
    for path, data in (
        (f"/actions/{action.id}/revise-termin", {"termin_date": date.today().isoformat()}),
        (f"/actions/{action.id}/sub-actions/create", {"title": "Yetkisiz"}),
        (f"/actions/{action.id}/comments", {"comment": "Yetkisiz"}),
        (f"/actions/{action.id}/delete", {}),
        (f"/sub-actions/{sub_action.id}/complete", {}),
    ):
        assert client.post(path, data=data).status_code == 404, path
    db.session.refresh(action)
    db.session.refresh(sub_action)
    assert action.is_completed is False
    assert sub_action.completed_at is None
    assert ActionComment.query.filter_by(action_id=action.id).count() == 0


@pytest.mark.parametrize("kind", ("main", "sub_action", "closure", "legacy_closure"))
@pytest.mark.parametrize(
    "path_scope",
    ("foreign_company", "other_module", "other_action_folder", "legacy_root"),
)
def test_action_download_rejects_borrowed_metadata_path(app, client, kind, path_scope):
    company = create_company("340")
    foreign_company = create_company("341")
    owner = create_user("action-file-owner", company=company)
    action = make_action(company, owner)
    valid_prefix = f"company-{company.id:03d}/actions"
    if kind == "main":
        folder = "files"
        record = action
        field = "file_stored_name"
        action.file_original_name = "evidence.pdf"
        url = f"/actions/{action.id}/download"
    elif kind == "sub_action":
        folder = "sub-actions"
        record = ActionSubTask(
            company_id=company.id, parent_action_id=action.id,
            title="Kanit", responsible_id=owner.id,
            evidence_original_name="evidence.pdf",
        )
        field = "evidence_stored_name"
        db.session.add(record)
        db.session.flush()
        url = f"/sub-actions/{record.id}/evidence/download"
    elif kind == "closure":
        folder = "closure"
        record = ActionClosureFile(
            company_id=company.id, action_id=action.id,
            original_name="evidence.pdf",
            stored_name=f"{valid_prefix}/closure/evidence.pdf",
        )
        field = "stored_name"
        db.session.add(record)
        db.session.flush()
        url = f"/actions/{action.id}/closure-evidence/{record.id}/download"
    else:
        folder = "closure"
        record = action
        field = "closure_file_stored_name"
        action.closure_file_original_name = "evidence.pdf"
        url = f"/actions/{action.id}/closure-evidence/download"

    valid_path = f"{valid_prefix}/{folder}/evidence.pdf"
    setattr(record, field, valid_path)
    write_stored_upload(app, valid_path, b"own evidence")
    db.session.commit()
    login(client, owner)
    assert client.get(url, follow_redirects=True).data == b"own evidence"
    download_count = AuditLog.query.filter_by(action="downloaded").count()
    assert download_count == 1

    if path_scope == "foreign_company":
        borrowed_path = f"company-{foreign_company.id:03d}/actions/{folder}/private.pdf"
    elif path_scope == "other_module":
        borrowed_path = f"company-{company.id:03d}/contracts/private.pdf"
    elif path_scope == "legacy_root":
        borrowed_path = "private.pdf"
    else:
        wrong_folder = "closure" if folder != "closure" else "files"
        borrowed_path = f"{valid_prefix}/{wrong_folder}/private.pdf"
    write_stored_upload(app, borrowed_path, b"other company's private evidence")
    setattr(record, field, borrowed_path)
    db.session.commit()

    response = client.get(url, follow_redirects=True)
    assert response.status_code == 404
    assert b"private evidence" not in response.data
    assert AuditLog.query.filter_by(action="downloaded").count() == download_count


@pytest.mark.parametrize("kind", ("main", "sub_action", "closure", "legacy_closure"))
def test_action_download_rejects_another_actions_file(app, client, kind):
    company = create_company("342")
    viewer = create_user("action-file-viewer", company=company)
    other_owner = create_user("action-file-other-owner", company=company)
    visible = make_action(company, viewer, action_number=1)
    hidden = make_action(company, other_owner, action_number=2)
    folder = {
        "main": "files", "sub_action": "sub-actions",
        "closure": "closure", "legacy_closure": "closure",
    }[kind]
    borrowed_path = f"company-{company.id:03d}/actions/{folder}/other.pdf"
    write_stored_upload(app, borrowed_path, b"other action evidence")

    if kind == "main":
        hidden.file_stored_name = visible.file_stored_name = borrowed_path
        hidden.file_original_name = visible.file_original_name = "other.pdf"
        visible_record, stored_field = visible, "file_stored_name"
        url = f"/actions/{visible.id}/download"
    elif kind == "sub_action":
        db.session.add(ActionSubTask(
            company_id=company.id, parent_action_id=hidden.id,
            title="Diger kanit", responsible_id=other_owner.id,
            evidence_stored_name=borrowed_path, evidence_original_name="other.pdf",
        ))
        sub = ActionSubTask(
            company_id=company.id, parent_action_id=visible.id,
            title="Gorunen kanit", responsible_id=viewer.id,
            evidence_stored_name=borrowed_path, evidence_original_name="other.pdf",
        )
        db.session.add(sub)
        db.session.flush()
        visible_record, stored_field = sub, "evidence_stored_name"
        url = f"/sub-actions/{sub.id}/evidence/download"
    elif kind == "closure":
        db.session.add(ActionClosureFile(
            company_id=company.id, action_id=hidden.id,
            stored_name=borrowed_path, original_name="other.pdf",
        ))
        closure = ActionClosureFile(
            company_id=company.id, action_id=visible.id,
            stored_name=borrowed_path, original_name="other.pdf",
        )
        db.session.add(closure)
        db.session.flush()
        visible_record, stored_field = closure, "stored_name"
        url = f"/actions/{visible.id}/closure-evidence/{closure.id}/download"
    else:
        hidden.closure_file_stored_name = visible.closure_file_stored_name = borrowed_path
        hidden.closure_file_original_name = visible.closure_file_original_name = "other.pdf"
        visible_record, stored_field = visible, "closure_file_stored_name"
        url = f"/actions/{visible.id}/closure-evidence/download"
    db.session.commit()

    login(client, viewer)
    assert client.get(f"/actions/{hidden.id}").status_code == 403
    before = AuditLog.query.filter_by(action="downloaded").count()
    response = client.get(url, follow_redirects=True)
    assert response.status_code == 404
    assert b"other action evidence" not in response.data
    assert AuditLog.query.filter_by(action="downloaded").count() == before

    setattr(
        visible_record, stored_field,
        borrowed_path.replace(f"/{folder}/", f"/{folder}/../{folder}/"),
    )
    db.session.commit()
    response = client.get(url, follow_redirects=True)
    assert response.status_code == 404
    assert b"other action evidence" not in response.data
    assert AuditLog.query.filter_by(action="downloaded").count() == before


def test_action_download_rejects_record_without_company(app):
    with app.test_request_context():
        with pytest.raises(NotFound):
            send_action_upload(
                "private.pdf", company_id=None, action_id=1,
                folder="files", download_name="private.pdf"
            )


def test_action_download_rejects_noncanonical_metadata_path(app, client):
    company = create_company("343")
    owner = create_user("action-file-canonical-owner", company=company)
    action = make_action(company, owner)
    stored_name = f"company-{company.id:03d}/actions/files/evidence.pdf"
    write_stored_upload(app, stored_name, b"action evidence")
    action.file_stored_name = stored_name.replace("/files/", "/closure/../files/")
    action.file_original_name = "evidence.pdf"
    db.session.commit()

    login(client, owner)
    response = client.get(f"/actions/{action.id}/download")
    assert response.status_code == 404
    assert b"action evidence" not in response.data
    assert AuditLog.query.filter_by(action="downloaded").count() == 0


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
