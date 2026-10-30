from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from unittest.mock import patch
from werkzeug.exceptions import NotFound
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models import Action, ActionClosureFile, ActionComment, ActionEvidenceManifest, ActionHistory, ActionSubTask, AuditLog, DEPARTMENTS, UserPermission
from app.routes import (
    send_action_upload, save_sub_action_evidence_file, save_closure_evidence_files,
    commit_action_upload_changes, register_action_upload, store_uploaded_file,
)

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


def write_action_evidence(app, stored_name, content, *, company_id, action_id, folder, record_id=None):
    file_path = write_stored_upload(app, stored_name, content)
    register_action_upload(
        stored_name, company_id=company_id, action_id=action_id,
        folder=folder, record_id=record_id,
    )
    return file_path


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
    manifest = ActionEvidenceManifest.query.filter_by(stored_name=action.file_stored_name).one()
    assert (manifest.company_id, manifest.action_id, manifest.kind) == (company.id, action.id, "files")
    assert manifest.deleted_at is None
    assert AuditLog.query.filter_by(entity_type="ActionEvidenceManifest", action="created").count() == 1

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


def test_personal_denial_blocks_manager_closure_approval(client):
    company = create_company("329")
    owner = create_user("closure-owner", company=company, permissions=("actions.create",))
    approver = create_user("closure-manager", company=company, role_key="management_representative")
    action = make_action(company, owner, closure_approval_requested=True)
    assert approver.has_permission("actions.approve_closure")
    approver.extra_permissions.append(UserPermission(
        permission_key="actions.approve_closure", is_allowed=False,
    ))
    db.session.commit()
    login(client, approver)
    assert client.post(f"/actions/{action.id}/complete").status_code == 403
    db.session.refresh(action)
    assert not action.is_completed


def test_sub_action_created_with_evidence_uses_its_record_directory(app, client):
    company = create_company("330")
    owner = create_user(
        "action-sub-upload-owner", company=company, permissions=("actions.create",)
    )
    action = make_action(company, owner)
    login(client, owner)
    response = client.post(
        f"/actions/{action.id}/sub-actions/create",
        data={"title": "İlk kanıt", "evidence_file": upload_tuple(b"proof", "proof.pdf")},
    )
    assert response.status_code == 302
    sub_action = ActionSubTask.query.one()
    assert sub_action.evidence_stored_name.startswith(
        f"company-{company.id:03d}/actions/sub-actions/{action.id}/{sub_action.id}/"
    )
    assert client.get(f"/sub-actions/{sub_action.id}/evidence/download").data == b"proof"


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
    ("foreign_company", "other_module", "other_action_folder", "legacy_root", "old_action_folder"),
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
            stored_name="pending",
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

    record_folder = (
        "legacy" if kind == "legacy_closure" else
        str(record.id) if kind in {"sub_action", "closure"} else None
    )
    valid_path = f"{valid_prefix}/{folder}/{action.id}"
    if record_folder is not None:
        valid_path += f"/{record_folder}"
    valid_path += "/evidence.pdf"
    setattr(record, field, valid_path)
    write_action_evidence(
        app, valid_path, b"own evidence", company_id=company.id,
        action_id=action.id, folder=folder, record_id=record_folder,
    )
    db.session.commit()
    login(client, owner)
    assert client.get(url, follow_redirects=True).data == b"own evidence"
    download_count = AuditLog.query.filter_by(action="downloaded").count()
    assert download_count == 1

    if path_scope == "foreign_company":
        borrowed_path = valid_path.replace(
            f"company-{company.id:03d}/", f"company-{foreign_company.id:03d}/"
        ).replace("evidence.pdf", "private.pdf")
    elif path_scope == "other_module":
        borrowed_path = f"company-{company.id:03d}/contracts/private.pdf"
    elif path_scope == "legacy_root":
        borrowed_path = "private.pdf"
    elif path_scope == "old_action_folder":
        borrowed_path = f"{valid_prefix}/{folder}/private.pdf"
    else:
        wrong_folder = "closure" if folder != "closure" else "files"
        borrowed_path = f"{valid_prefix}/{wrong_folder}/{action.id}/private.pdf"
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
    if kind == "main":
        hidden.file_original_name = visible.file_original_name = "other.pdf"
        other_record = hidden
        visible_record, stored_field = visible, "file_stored_name"
        url = f"/actions/{visible.id}/download"
    elif kind == "sub_action":
        other_record = ActionSubTask(
            company_id=company.id, parent_action_id=hidden.id,
            title="Diger kanit", responsible_id=other_owner.id,
            evidence_original_name="other.pdf",
        )
        db.session.add(other_record)
        sub = ActionSubTask(
            company_id=company.id, parent_action_id=visible.id,
            title="Gorunen kanit", responsible_id=viewer.id,
            evidence_original_name="other.pdf",
        )
        db.session.add(sub)
        db.session.flush()
        visible_record, stored_field = sub, "evidence_stored_name"
        url = f"/sub-actions/{sub.id}/evidence/download"
    elif kind == "closure":
        other_record = ActionClosureFile(
            company_id=company.id, action_id=hidden.id,
            stored_name="pending-other", original_name="other.pdf",
        )
        db.session.add(other_record)
        closure = ActionClosureFile(
            company_id=company.id, action_id=visible.id,
            stored_name="pending-visible", original_name="other.pdf",
        )
        db.session.add(closure)
        db.session.flush()
        visible_record, stored_field = closure, "stored_name"
        url = f"/actions/{visible.id}/closure-evidence/{closure.id}/download"
    else:
        hidden.closure_file_original_name = visible.closure_file_original_name = "other.pdf"
        other_record = hidden
        visible_record, stored_field = visible, "closure_file_stored_name"
        url = f"/actions/{visible.id}/closure-evidence/download"
    borrowed_path = f"company-{company.id:03d}/actions/{folder}/{hidden.id}"
    if kind in {"sub_action", "closure"}:
        borrowed_path += f"/{other_record.id}"
    elif kind == "legacy_closure":
        borrowed_path += "/legacy"
    borrowed_path += "/other.pdf"
    setattr(other_record, stored_field, borrowed_path)
    setattr(visible_record, stored_field, borrowed_path)
    write_stored_upload(app, borrowed_path, b"other action evidence")
    db.session.commit()

    login(client, viewer)
    assert client.get(f"/actions/{hidden.id}").status_code == 403
    before = AuditLog.query.filter_by(action="downloaded").count()
    response = client.get(url, follow_redirects=True)
    assert response.status_code == 404
    assert b"other action evidence" not in response.data
    assert AuditLog.query.filter_by(action="downloaded").count() == before

    setattr(visible_record, stored_field, borrowed_path)
    setattr(
        other_record, stored_field,
        f"company-{company.id:03d}/actions/{folder}/{hidden.id}/{other_record.id}/owner.pdf"
        if kind == "closure" else None,
    )
    db.session.commit()
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


def test_action_download_rejects_changed_file_content(app, client):
    company = create_company("355")
    owner = create_user("action-tamper-owner", company=company)
    action = make_action(company, owner)
    path = f"company-{company.id:03d}/actions/files/{action.id}/proof.pdf"
    physical_file = write_action_evidence(
        app, path, b"trusted", company_id=company.id,
        action_id=action.id, folder="files",
    )
    action.file_stored_name = path
    action.file_original_name = "proof.pdf"
    db.session.commit()

    login(client, owner)
    assert client.get(f"/actions/{action.id}/download").data == b"trusted"
    physical_file.write_bytes(b"changed")
    assert client.get(f"/actions/{action.id}/download").status_code == 404


def test_action_delete_keeps_tombstone_and_reconciles_failed_cleanup(app, client):
    company = create_company("356")
    manager = create_user(
        "action-tombstone-manager", company=company,
        permissions=("actions.delete",),
    )
    action = make_action(company, manager)
    action_id = action.id
    path = f"company-{company.id:03d}/actions/files/{action.id}/proof.pdf"
    physical_file = write_action_evidence(
        app, path, b"proof", company_id=company.id,
        action_id=action.id, folder="files",
    )
    action.file_stored_name = path
    db.session.commit()

    login(client, manager)
    with patch.object(Path, "unlink", side_effect=OSError("locked")):
        assert client.post(f"/actions/{action_id}/delete").status_code == 302
    manifest = ActionEvidenceManifest.query.filter_by(stored_name=path).one()
    assert db.session.get(Action, action_id) is None
    assert manifest.deleted_at is not None
    assert manifest.cleaned_at is None
    assert physical_file.exists()
    assert AuditLog.query.filter_by(entity_type="ActionEvidenceManifest", action="updated").count() >= 1

    runner = app.test_cli_runner()
    assert "Pending: 1" in runner.invoke(args=["reconcile-action-uploads"]).output
    assert physical_file.exists()
    physical_file.write_bytes(b"different")
    refused = runner.invoke(args=["reconcile-action-uploads", "--apply"])
    assert refused.exit_code == 0
    assert "mismatched: 1" in refused.output
    assert physical_file.read_bytes() == b"different"
    assert manifest.cleaned_at is None
    physical_file.write_bytes(b"proof")
    result = runner.invoke(args=["reconcile-action-uploads", "--apply"])
    assert result.exit_code == 0, result.output
    assert "cleaned: 1" in result.output
    assert not physical_file.exists()
    assert manifest.cleaned_at is not None

    physical_file.write_bytes(b"new content")
    with app.test_request_context():
        with pytest.raises(NotFound):
            send_action_upload(
                path, company_id=company.id, action_id=action_id,
                folder="files", download_name="proof.pdf",
            )


def test_action_download_rejects_noncanonical_metadata_path(app, client):
    company = create_company("343")
    owner = create_user("action-file-canonical-owner", company=company)
    action = make_action(company, owner)
    stored_name = f"company-{company.id:03d}/actions/files/{action.id}/evidence.pdf"
    write_stored_upload(app, stored_name, b"action evidence")
    action.file_stored_name = stored_name.replace("/files/", "/closure/../files/")
    action.file_original_name = "evidence.pdf"
    db.session.commit()

    login(client, owner)
    response = client.get(f"/actions/{action.id}/download")
    assert response.status_code == 404
    assert b"action evidence" not in response.data
    assert AuditLog.query.filter_by(action="downloaded").count() == 0


@pytest.mark.parametrize("kind", ("sub_action", "closure"))
def test_action_download_rejects_another_record_on_same_action(app, client, kind):
    company = create_company("344")
    owner = create_user("action-record-owner", company=company)
    action = make_action(company, owner)
    if kind == "sub_action":
        records = [ActionSubTask(
            company_id=company.id, parent_action_id=action.id,
            title=f"Kanit {index}", responsible_id=owner.id,
            evidence_original_name="proof.pdf",
        ) for index in range(2)]
        field = "evidence_stored_name"
        folder = "sub-actions"
        url = lambda record: f"/sub-actions/{record.id}/evidence/download"
    else:
        records = [ActionClosureFile(
            company_id=company.id, action_id=action.id,
            original_name="proof.pdf", stored_name=f"pending-{index}",
        ) for index in range(2)]
        field = "stored_name"
        folder = "closure"
        url = lambda record: f"/actions/{action.id}/closure-evidence/{record.id}/download"
    db.session.add_all(records)
    db.session.flush()
    borrowed_path = (
        f"company-{company.id:03d}/actions/{folder}/{action.id}/{records[0].id}/proof.pdf"
    )
    write_action_evidence(
        app, borrowed_path, b"first record only", company_id=company.id,
        action_id=action.id, folder=folder, record_id=records[0].id,
    )
    for record in records:
        setattr(record, field, borrowed_path)
    db.session.commit()

    login(client, owner)
    assert client.get(url(records[0])).data == b"first record only"
    before = AuditLog.query.filter_by(action="downloaded").count()
    assert client.get(url(records[1])).status_code == 404
    setattr(records[0], field, None if kind == "sub_action" else "pending-moved")
    db.session.commit()
    assert client.get(url(records[1])).status_code == 404
    assert AuditLog.query.filter_by(action="downloaded").count() == before


@pytest.mark.parametrize("kind", ("main", "sub_action", "closure", "legacy_closure"))
@pytest.mark.parametrize("foreign_company", (False, True))
def test_action_delete_cannot_remove_another_actions_file(app, client, kind, foreign_company):
    company = create_company("345")
    source_company = create_company("354") if foreign_company else company
    manager = create_user(
        "action-delete-manager", company=company, permissions=("actions.delete",)
    )
    owner = create_user("action-delete-owner", company=source_company)
    target = make_action(company, manager, action_number=1)
    other = make_action(
        source_company, owner, action_number=1 if foreign_company else 2
    )
    if kind == "main":
        folder, record_id = "files", None
        target_record = target
        source_record = other
        field = "file_stored_name"
    elif kind == "sub_action":
        folder = "sub-actions"
        source_record = ActionSubTask(
            company_id=source_company.id, parent_action_id=other.id,
            title="Kaynak kanıt", responsible_id=owner.id,
        )
        target_record = ActionSubTask(
            company_id=company.id, parent_action_id=target.id,
            title="Hedef kanıt", responsible_id=manager.id,
        )
        field = "evidence_stored_name"
        db.session.add_all([source_record, target_record])
        db.session.flush()
        record_id = source_record.id
    elif kind == "closure":
        folder = "closure"
        source_record = ActionClosureFile(
            company_id=source_company.id, action_id=other.id,
            original_name="proof.pdf", stored_name="pending-source",
        )
        target_record = ActionClosureFile(
            company_id=company.id, action_id=target.id,
            original_name="proof.pdf", stored_name="pending-target",
        )
        field = "stored_name"
        db.session.add_all([source_record, target_record])
        db.session.flush()
        record_id = source_record.id
    else:
        folder, record_id = "closure", "legacy"
        target_record = target
        source_record = other
        field = "closure_file_stored_name"
    borrowed_path = f"company-{source_company.id:03d}/actions/{folder}/{other.id}"
    if record_id is not None:
        borrowed_path += f"/{record_id}"
    borrowed_path += "/proof.pdf"
    physical_file = write_action_evidence(
        app, borrowed_path, b"other action proof", company_id=source_company.id,
        action_id=other.id, folder=folder, record_id=record_id,
    )
    setattr(source_record, field, borrowed_path)
    setattr(target_record, field, borrowed_path)
    db.session.commit()

    login(client, manager)
    assert client.post(f"/actions/{target.id}/delete").status_code == 409
    assert physical_file.read_bytes() == b"other action proof"
    assert getattr(source_record, field) == borrowed_path
    assert db.session.get(Action, target.id) is not None
    assert ActionEvidenceManifest.query.filter_by(stored_name=borrowed_path).one().deleted_at is None


def test_action_delete_handles_duplicate_legacy_closure_metadata(app, client):
    company = create_company("357")
    manager = create_user(
        "action-legacy-manager", company=company,
        permissions=("actions.delete",),
    )
    action = make_action(company, manager)
    path = f"company-{company.id:03d}/actions/closure/{action.id}/legacy/proof.pdf"
    physical_file = write_action_evidence(
        app, path, b"legacy", company_id=company.id,
        action_id=action.id, folder="closure", record_id="legacy",
    )
    action.closure_file_stored_name = path
    db.session.add(ActionClosureFile(
        company_id=company.id, action_id=action.id,
        stored_name=path, original_name="proof.pdf",
    ))
    db.session.commit()

    login(client, manager)
    assert client.post(f"/actions/{action.id}/delete").status_code == 302
    assert not physical_file.exists()
    manifest = ActionEvidenceManifest.query.filter_by(stored_name=path).one()
    assert manifest.deleted_at is not None
    assert manifest.cleaned_at is not None


def test_invalid_sub_action_replacement_preserves_original_file(app):
    company = create_company("346")
    owner = create_user("sub-replacement-owner", company=company)
    action = make_action(company, owner)
    sub_action = ActionSubTask(
        company_id=company.id, parent_action_id=action.id,
        title="Kanıt", responsible_id=owner.id,
    )
    db.session.add(sub_action)
    db.session.flush()
    stored_name = (
        f"company-{company.id:03d}/actions/sub-actions/"
        f"{action.id}/{sub_action.id}/original.pdf"
    )
    physical_file = write_action_evidence(
        app, stored_name, b"original proof", company_id=company.id,
        action_id=action.id, folder="sub-actions", record_id=sub_action.id,
    )
    sub_action.evidence_stored_name = stored_name
    db.session.commit()

    with app.test_request_context(
        "/", method="POST", data={"evidence_file": upload_tuple(b"bad", "bad.exe")}
    ):
        with pytest.raises(ValueError, match="invalid_file_type"):
            save_sub_action_evidence_file(sub_action)
    assert physical_file.read_bytes() == b"original proof"
    assert sub_action.evidence_stored_name == stored_name


def test_partial_action_upload_failure_removes_file(app):
    company = create_company("359")
    uploaded = FileStorage(stream=BytesIO(b"complete"), filename="proof.pdf")

    def partial_save(target):
        Path(target).write_bytes(b"partial")
        raise OSError("disk failure")

    with app.test_request_context():
        with patch.object(uploaded, "save", side_effect=partial_save):
            with pytest.raises(OSError, match="disk failure"):
                store_uploaded_file(
                    uploaded, folder="actions/files/1", company_id=company.id,
                )
    assert not list(Path(app.config["UPLOAD_FOLDER"]).rglob("*.pdf"))


def test_sub_action_replacement_only_deletes_old_file_after_commit(app):
    company = create_company("348")
    owner = create_user("sub-commit-owner", company=company)
    action = make_action(company, owner)
    sub_action = ActionSubTask(
        company_id=company.id, parent_action_id=action.id,
        title="Kanıt", responsible_id=owner.id,
    )
    db.session.add(sub_action)
    db.session.flush()
    stored_name = (
        f"company-{company.id:03d}/actions/sub-actions/"
        f"{action.id}/{sub_action.id}/original.pdf"
    )
    physical_file = write_action_evidence(
        app, stored_name, b"original proof", company_id=company.id,
        action_id=action.id, folder="sub-actions", record_id=sub_action.id,
    )
    sub_action.evidence_stored_name = stored_name
    db.session.commit()

    with app.test_request_context(
        "/", method="POST", data={"evidence_file": upload_tuple(b"new proof", "original.pdf")}
    ):
        save_sub_action_evidence_file(sub_action)
        new_path = sub_action.evidence_stored_name
        assert physical_file.read_bytes() == b"original proof"
        commit_action_upload_changes()
    assert not physical_file.exists()
    assert (Path(app.config["UPLOAD_FOLDER"]) / new_path).read_bytes() == b"new proof"


def test_nested_rollback_does_not_discard_outer_action_upload(app):
    company = create_company("352")
    owner = create_user("sub-savepoint-owner", company=company)
    action = make_action(company, owner)
    sub_action = ActionSubTask(
        company_id=company.id, parent_action_id=action.id,
        title="Kanıt", responsible_id=owner.id,
    )
    db.session.add(sub_action)
    db.session.flush()
    stored_name = (
        f"company-{company.id:03d}/actions/sub-actions/"
        f"{action.id}/{sub_action.id}/original.pdf"
    )
    old_file = write_action_evidence(
        app, stored_name, b"original proof", company_id=company.id,
        action_id=action.id, folder="sub-actions", record_id=sub_action.id,
    )
    sub_action.evidence_stored_name = stored_name
    db.session.commit()

    with app.test_request_context(
        "/", method="POST", data={"evidence_file": upload_tuple(b"new proof", "new.pdf")}
    ):
        save_sub_action_evidence_file(sub_action)
        new_file = Path(app.config["UPLOAD_FOLDER"]) / sub_action.evidence_stored_name
        nested = db.session.begin_nested()
        nested.rollback()
        assert new_file.read_bytes() == b"new proof"
        assert old_file.read_bytes() == b"original proof"
        commit_action_upload_changes()
    assert not old_file.exists()
    assert new_file.read_bytes() == b"new proof"


@pytest.mark.parametrize("failure", ("rollback", "commit_error"))
def test_failed_sub_action_commit_keeps_old_and_cleans_new_file(app, failure):
    company = create_company("350")
    owner = create_user("sub-rollback-owner", company=company)
    action = make_action(company, owner)
    sub_action = ActionSubTask(
        company_id=company.id, parent_action_id=action.id,
        title="Kanıt", responsible_id=owner.id,
    )
    db.session.add(sub_action)
    db.session.flush()
    stored_name = (
        f"company-{company.id:03d}/actions/sub-actions/"
        f"{action.id}/{sub_action.id}/original.pdf"
    )
    physical_file = write_action_evidence(
        app, stored_name, b"original proof", company_id=company.id,
        action_id=action.id, folder="sub-actions", record_id=sub_action.id,
    )
    sub_action.evidence_stored_name = stored_name
    db.session.commit()

    with app.test_request_context(
        "/", method="POST", data={"evidence_file": upload_tuple(b"new proof", "new.pdf")}
    ):
        save_sub_action_evidence_file(sub_action)
        new_file = Path(app.config["UPLOAD_FOLDER"]) / sub_action.evidence_stored_name
        assert new_file.is_file()
        if failure == "rollback":
            db.session.rollback()
        else:
            db.session.add(Action(
                company_id=company.id, action_number=action.action_number,
                title="Duplicate", responsible_owner=owner.full_name,
                responsible_user_id=owner.id, department="Kalite",
                termin_date=date.today() + timedelta(days=7),
            ))
            with pytest.raises(IntegrityError):
                commit_action_upload_changes()
        assert physical_file.read_bytes() == b"original proof"
        assert not new_file.exists()
        commit_action_upload_changes()

    assert physical_file.read_bytes() == b"original proof"
    assert db.session.get(ActionSubTask, sub_action.id).evidence_stored_name == stored_name


def test_required_sub_action_note_rejected_before_evidence_replacement(app, client):
    company = create_company("349")
    owner = create_user(
        "sub-required-note-owner", company=company,
        permissions=("actions.comment_assigned",),
    )
    action = make_action(company, owner)
    sub_action = ActionSubTask(
        company_id=company.id, parent_action_id=action.id,
        title="Kanıt", responsible_id=owner.id,
        evidence_required=True,
    )
    db.session.add(sub_action)
    db.session.flush()
    stored_name = (
        f"company-{company.id:03d}/actions/sub-actions/"
        f"{action.id}/{sub_action.id}/original.pdf"
    )
    physical_file = write_action_evidence(
        app, stored_name, b"original proof", company_id=company.id,
        action_id=action.id, folder="sub-actions", record_id=sub_action.id,
    )
    sub_action.evidence_stored_name = stored_name
    db.session.commit()

    login(client, owner)
    response = client.post(
        f"/sub-actions/{sub_action.id}/complete",
        data={"evidence_file": upload_tuple(b"replacement proof", "replacement.pdf")},
    )
    assert response.status_code == 302
    db.session.refresh(sub_action)
    assert sub_action.status != "Tamamlandı"
    assert sub_action.evidence_stored_name == stored_name
    assert physical_file.read_bytes() == b"original proof"


def test_failed_closure_replacement_preserves_original_file(app):
    company = create_company("347")
    owner = create_user("closure-replacement-owner", company=company)
    action = make_action(company, owner)
    closure = ActionClosureFile(
        company_id=company.id, action_id=action.id,
        original_name="old.pdf", stored_name="pending",
    )
    db.session.add(closure)
    db.session.flush()
    original_path = (
        f"company-{company.id:03d}/actions/closure/"
        f"{action.id}/{closure.id}/old.pdf"
    )
    physical_file = write_action_evidence(
        app, original_path, b"original evidence", company_id=company.id,
        action_id=action.id, folder="closure", record_id=closure.id,
    )
    closure.stored_name = original_path
    db.session.commit()

    with app.test_request_context(
        "/", method="POST",
        data={"closure_files": [
            upload_tuple(b"first", "first.pdf"),
            upload_tuple(b"second", "second.pdf"),
        ]},
    ):
        from app.routes import store_uploaded_file

        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError("file_too_large")
            return store_uploaded_file(*args, **kwargs)

        with patch("app.routes.store_uploaded_file", side_effect=fail_second):
            with pytest.raises(ValueError, match="file_too_large"):
                save_closure_evidence_files(action)
        db.session.rollback()

    assert physical_file.read_bytes() == b"original evidence"
    assert db.session.get(ActionClosureFile, closure.id).stored_name == original_path
    assert set(physical_file.parent.parent.rglob("*.pdf")) == {physical_file}


def test_note_only_closure_request_keeps_existing_evidence(app, client):
    company = create_company("358")
    owner = create_user(
        "closure-note-only-owner", company=company,
        permissions=("actions.request_close_assigned",),
    )
    action = make_action(company, owner)
    closure = ActionClosureFile(
        company_id=company.id, action_id=action.id,
        original_name="proof.pdf", stored_name="pending",
    )
    db.session.add(closure)
    db.session.flush()
    path = f"company-{company.id:03d}/actions/closure/{action.id}/{closure.id}/proof.pdf"
    physical_file = write_action_evidence(
        app, path, b"evidence", company_id=company.id,
        action_id=action.id, folder="closure", record_id=closure.id,
    )
    closure.stored_name = path
    db.session.commit()

    login(client, owner)
    response = client.post(
        f"/actions/{action.id}/request-closure",
        data={"closure_evidence_note": "Evidence remains valid"},
    )
    assert response.status_code == 302
    assert db.session.get(ActionClosureFile, closure.id).stored_name == path
    assert physical_file.read_bytes() == b"evidence"
    assert ActionEvidenceManifest.query.filter_by(stored_name=path).one().deleted_at is None


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
