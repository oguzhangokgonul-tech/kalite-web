from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.extensions import db
from app.models import Action, ActionEvidenceManifest, AuditLog, CompanyModule, Notification
from app.notification_models import NotificationEmailEvent
from app.notification_policy import dispatch_collection, reminder_timezone
from app.ohs_notes_models import OhsNote, OhsNoteImage
from .helpers import create_company, create_user, login
from .test_action_management import action_payload, write_action_evidence


@pytest.fixture()
def setup(app):
    company = create_company("871")
    owner = create_user("note-owner", company=company)
    other = create_user("note-other", company=company)
    manager = create_user("note-manager", company=company, role_key="management_representative")
    note = OhsNote(company_id=company.id, author_id=owner.id, title="Kaygan zemin",
                   description="Üretim girişinde su birikiyor.", location="Üretim")
    db.session.add(note)
    db.session.commit()
    return SimpleNamespace(company=company, owner=owner, other=other, manager=manager, note=note)


def image_upload(name, color):
    stream = BytesIO()
    Image.new("RGB", (24, 24), color).save(stream, format="PNG")
    stream.seek(0)
    return stream, name


def test_multiple_images_create_view_edit_and_remove(app, client, setup):
    login(client, setup.owner)
    form = client.get("/isg-notlari/yeni").get_data(as_text=True)
    assert 'name="images"' in form and "multiple" in form
    response = client.post("/isg-notlari/yeni", data={
        "title": "Iki fotograflı not", "description": "Sahadaki gözlem",
        "images": [image_upload("ilk.png", "red"), image_upload("ikinci.png", "blue")],
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    note = OhsNote.query.filter_by(title="Iki fotograflı not").one()
    images = OhsNoteImage.query.filter_by(note_id=note.id, deleted_at=None).order_by(OhsNoteImage.id).all()
    assert len(images) == 2
    assert {image.company_id for image in images} == {setup.company.id}
    assert {image.uploaded_by_user_id for image in images} == {setup.owner.id}
    assert len({image.stored_path for image in images}) == 2
    assert "ilk.png" in client.get(f"/isg-notlari/{note.id}").get_data(as_text=True)

    image_url = f"/isg-notlari/{note.id}/gorseller/{images[0].id}"
    login(client, setup.other)
    downloaded = client.get(image_url)
    assert downloaded.status_code == 200
    assert downloaded.mimetype == "image/png"
    assert {part.strip() for part in downloaded.headers["Cache-Control"].split(",")} == {
        "private", "no-store"
    }
    assert downloaded.headers["X-Content-Type-Options"] == "nosniff"
    assert Image.open(BytesIO(downloaded.data)).getexif() == {}
    assert client.get(f"/isg-notlari/{note.id}/duzenle").status_code == 403

    login(client, setup.owner)
    stored = Path(app.config["UPLOAD_FOLDER"]) / images[0].stored_path
    response = client.post(f"/isg-notlari/{note.id}/duzenle", data={
        "version_id": note.version_id, "title": note.title,
        "description": note.description, "location": "",
        "remove_image_ids": str(images[0].id),
        "images": [image_upload("ucuncu.png", "green")],
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    db.session.refresh(note)
    assert note.version_id > 1
    assert OhsNoteImage.query.filter_by(note_id=note.id, deleted_at=None).count() == 2
    assert client.get(image_url).status_code == 404
    assert not stored.exists()
    assert AuditLog.query.filter_by(entity_type="OhsNoteImage", action="created").count() == 3
    assert AuditLog.query.filter_by(entity_type="OhsNoteImage", action="deleted").count() == 1

    foreign_company = create_company("874")
    foreign = create_user("note-image-foreign", company=foreign_company)
    login(client, foreign)
    assert client.get(f"/isg-notlari/{note.id}/gorseller/{images[1].id}").status_code == 404
    login(client, setup.owner)
    CompanyModule.query.filter_by(company_id=setup.company.id, module_key="ohs_actions").one().is_enabled = False
    db.session.commit()
    assert client.get(f"/isg-notlari/{note.id}/gorseller/{images[1].id}").status_code == 403


def test_image_validation_and_rollback_leave_no_files(app, client, setup, monkeypatch):
    login(client, setup.owner)
    bad = client.post("/isg-notlari/yeni", data={
        "title": "Yanlış dosya", "description": "İçerik denemesi",
        "images": [(BytesIO(b"not a png"), "fake.png")],
    }, content_type="multipart/form-data")
    assert bad.status_code == 200
    assert OhsNote.query.count() == 1
    assert OhsNoteImage.query.count() == 0

    large = client.post("/isg-notlari/yeni", data={
        "title": "Büyük dosya", "description": "Boyut denemesi",
        "images": [(BytesIO(b"x" * (8 * 1024 * 1024 + 1)), "large.png")],
    }, content_type="multipart/form-data")
    assert large.status_code == 200
    assert OhsNoteImage.query.count() == 0

    import app.ohs_notes as ohs_notes
    monkeypatch.setattr(ohs_notes, "record_audit_event", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("audit unavailable")))
    failed = client.post("/isg-notlari/yeni", data={
        "title": "Geri alınan", "description": "Rollback",
        "images": [image_upload("rollback.png", "yellow")],
    }, content_type="multipart/form-data")
    assert failed.status_code == 500
    assert OhsNote.query.count() == 1
    assert OhsNoteImage.query.count() == 0
    assert not list((Path(app.config["UPLOAD_FOLDER"]) /
                     f"company-{setup.company.id:03d}" / "ohs-notes").rglob("*.png"))


def test_full_storage_quota_allows_text_edit_removal_and_replacement(app, client, setup):
    login(client, setup.owner)
    note = setup.note
    setup.company.storage_quota_mb = 1
    db.session.commit()
    response = client.post(f"/isg-notlari/{note.id}/duzenle", data={
        "version_id": note.version_id, "title": note.title,
        "description": note.description, "images": [image_upload("before.png", "red")],
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    db.session.refresh(note)
    original = OhsNoteImage.query.filter_by(note_id=note.id, deleted_at=None).one()
    company_dir = Path(app.config["UPLOAD_FOLDER"]) / f"company-{setup.company.id:03d}"
    (company_dir / "quota-filler.bin").write_bytes(b"x" * (1024 * 1024 - original.size_bytes))

    response = client.post(f"/isg-notlari/{note.id}/duzenle", data={
        "version_id": note.version_id, "title": note.title,
        "description": "Kota doluyken metin değişti",
    })
    assert response.status_code == 302
    db.session.refresh(note)

    response = client.post(f"/isg-notlari/{note.id}/duzenle", data={
        "version_id": note.version_id, "title": note.title,
        "description": note.description, "remove_image_ids": str(original.id),
        "images": [image_upload("after.png", "red")],
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    db.session.refresh(note)
    active = OhsNoteImage.query.filter_by(note_id=note.id, deleted_at=None).one()
    assert active.id != original.id

    response = client.post(f"/isg-notlari/{note.id}/duzenle", data={
        "version_id": note.version_id, "title": note.title,
        "description": note.description, "remove_image_ids": str(active.id),
    })
    assert response.status_code == 302
    assert OhsNoteImage.query.filter_by(note_id=note.id, deleted_at=None).count() == 0


def test_image_metadata_exif_and_note_ownership(client, setup):
    login(client, setup.owner)
    exif = Image.Exif()
    exif[315] = "camera-owner"
    raw = BytesIO()
    Image.new("RGB", (24, 24), "red").save(raw, format="JPEG", exif=exif)
    raw.seek(0)
    response = client.post("/isg-notlari/yeni", data={
        "title": "Fotoğraf kanıtı", "description": "Saha notu",
        "images": [(raw, "kamera.jpg")],
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    note = OhsNote.query.filter_by(title="Fotoğraf kanıtı").one()
    image = OhsNoteImage.query.filter_by(note_id=note.id).one()
    image_url = f"/isg-notlari/{note.id}/gorseller/{image.id}"
    with Image.open(BytesIO(client.get(image_url).data)) as clean:
        assert clean.getexif() == {}

    other_note = setup.note
    other_url = f"/isg-notlari/{other_note.id}/gorseller/{image.id}"
    assert client.get(other_url).status_code == 404
    assert client.post(f"/isg-notlari/{other_note.id}/duzenle", data={
        "version_id": other_note.version_id, "title": other_note.title,
        "description": other_note.description, "remove_image_ids": str(image.id),
    }).status_code == 200
    assert client.get(image_url).status_code == 200

    image.stored_path = image.stored_path.replace(
        f"ohs-notes/{note.id}/", f"ohs-notes/{other_note.id}/"
    )
    db.session.commit()
    assert client.get(image_url).status_code == 404


def test_personnel_create_mobile_and_pool(client, setup):
    s = setup
    login(client, s.owner)
    mobile = client.get("/mobil").get_data(as_text=True)
    assert "/isg-notlari/yeni" in mobile
    assert "İSG Notu Oluştur" in mobile
    assert "/isg-aksiyonlari/yeni" not in mobile
    response = client.post("/isg-notlari/yeni", data={
        "title": "Gözlem", "description": "Türkçe gözlem", "company_id": 999, "author_id": s.other.id})
    assert response.status_code == 302
    note = OhsNote.query.filter_by(title="Gözlem").one()
    assert note.author_id == s.owner.id and note.company_id == s.company.id
    login(client, s.other)
    assert "Gözlem" in client.get("/isg-notlari").get_data(as_text=True)
    assert client.get(f"/isg-notlari/{note.id}").status_code == 200


@pytest.mark.parametrize("role,allowed", [(None, False), ("company_admin", True),
    ("management_representative", True), ("department_manager", False), ("viewer", False)])
def test_edit_delete_roles(client, setup, role, allowed):
    user = create_user("role-editor", company=setup.company, role_key=role)
    login(client, user)
    note = setup.note
    assert client.get(f"/isg-notlari/{note.id}/duzenle").status_code == (200 if allowed else 403)
    response = client.post(f"/isg-notlari/{note.id}/sil", data={"version_id": note.version_id})
    assert response.status_code == (302 if allowed else 403)


def test_owner_edit_version_delete_and_xss(client, setup):
    note = setup.note
    login(client, setup.owner)
    original_version = note.version_id
    assert client.post(f"/isg-notlari/{note.id}/duzenle", data={
        "version_id": original_version, "title": "<script>alert(1)</script>", "description": "Güncel"
    }).status_code == 302
    db.session.refresh(note)
    assert note.version_id > original_version
    assert "<script>alert(1)</script>" not in client.get(f"/isg-notlari/{note.id}").get_data(as_text=True)
    assert client.post(f"/isg-notlari/{note.id}/sil", data={"version_id": original_version}).status_code == 409
    assert client.post(f"/isg-notlari/{note.id}/sil", data={"version_id": note.version_id}).status_code == 302
    assert client.get(f"/isg-notlari/{note.id}").status_code == 404
    assert db.session.get(OhsNote, note.id).deleted_at is not None


def test_tenant_and_disabled_module(client, setup):
    foreign_company = create_company("872")
    foreign = create_user("foreign", company=foreign_company, role_key="management_representative")
    login(client, foreign)
    for suffix in ("", "/duzenle"):
        assert client.get(f"/isg-notlari/{setup.note.id}{suffix}").status_code == 404
    assert client.post(f"/isg-notlari/{setup.note.id}/sil").status_code == 404
    assert client.get(f"/isg-aksiyonlari/yeni?ohs_note_id={setup.note.id}").status_code == 404
    login(client, setup.owner)
    CompanyModule.query.filter_by(company_id=setup.company.id, module_key="ohs_actions").one().is_enabled = False
    db.session.commit()
    assert client.get("/isg-notlari").status_code == 403
    assert client.post("/isg-notlari/yeni", data={"title": "X", "description": "Y"}).status_code == 403


def test_action_conversion_duplicate_and_note_delete_preserves_action(client, setup):
    s = setup
    login(client, s.manager)
    assert "Aksiyon Oluştur" in client.get(f"/isg-notlari/{s.note.id}").get_data(as_text=True)
    response = client.get(f"/isg-aksiyonlari/yeni?ohs_note_id={s.note.id}")
    assert response.status_code == 200
    assert "Kaygan zemin" in response.get_data(as_text=True)
    data = action_payload(s.owner, ohs_note_id=str(s.note.id), ohs_note_version=str(s.note.version_id))
    response = client.post("/isg-aksiyonlari/yeni", data=data)
    assert response.status_code == 302
    db.session.refresh(s.note)
    action = Action.query.one()
    assert action.action_category == "ohs" and action.company_id == s.company.id
    assert s.note.action_id == action.id and s.note.converted_at
    assert f'/isg-notlari/{s.note.id}' in client.get(f'/actions/{action.id}').get_data(as_text=True)
    event = AuditLog.query.filter_by(entity_type='OhsNote', action='action_created').one()
    assert event.company_id == s.company.id and event.user_id == s.manager.id
    assert client.post("/isg-aksiyonlari/yeni", data=data).status_code == 409
    assert Action.query.count() == 1
    assert client.post(f"/isg-notlari/{s.note.id}/sil", data={"version_id": s.note.version_id}).status_code == 302
    assert Action.query.count() == 1
    assert client.post(f"/actions/{action.id}/delete").status_code == 302
    db.session.refresh(s.note)
    assert s.note.action_id is None
    assert s.note.converted_at is not None
    assert s.note.deleted_at is not None
    assert AuditLog.query.filter_by(entity_type="OhsNote", action="action_deleted").count() == 1


def test_linked_ohs_action_delete_preserves_note_and_audits_unlink(app, client, setup):
    s = setup
    login(client, s.manager)
    response = client.post("/isg-aksiyonlari/yeni", data=action_payload(
        s.owner, ohs_note_id=str(s.note.id), ohs_note_version=str(s.note.version_id)))
    assert response.status_code == 302
    action = Action.query.one()
    action_id = action.id
    stored_name = f"company-{s.company.id:03d}/actions/files/{action_id}/proof.png"
    physical_file = write_action_evidence(
        app, stored_name, b"proof", company_id=s.company.id,
        action_id=action_id, folder="files",
    )
    action.file_stored_name = stored_name
    action.file_original_name = "proof.png"
    db.session.commit()

    login(client, s.owner)
    assert client.get(f"/actions/{action_id}/delete").status_code == 403
    assert client.post(f"/actions/{action_id}/delete").status_code == 403

    foreign_company = create_company("875")
    foreign = create_user("note-delete-foreign", company=foreign_company,
                          role_key="management_representative")
    login(client, foreign)
    assert client.get(f"/actions/{action_id}/delete").status_code == 404
    assert client.post(f"/actions/{action_id}/delete").status_code == 404

    login(client, s.manager)
    confirmation = client.get(f"/actions/{action_id}/delete")
    assert confirmation.status_code == 200
    assert "Kaynak İSG notu ve denetim kayıtları korunacak" in confirmation.get_data(as_text=True)
    assert 'href="/isg-aksiyonlari"' in confirmation.get_data(as_text=True)
    db.session.refresh(s.note)
    assert s.note.action_id == action_id
    assert client.post(f"/actions/{action_id}/delete").status_code == 302
    assert db.session.get(Action, action_id) is None
    manifest = ActionEvidenceManifest.query.filter_by(stored_name=stored_name).one()
    assert manifest.deleted_at is not None and manifest.cleaned_at is not None
    assert not physical_file.exists()
    db.session.refresh(s.note)
    assert s.note.action_id is None
    assert s.note.converted_at is not None
    note_page = client.get(f"/isg-notlari/{s.note.id}")
    assert note_page.status_code == 200
    assert "Bağlı aksiyon silindi" in note_page.get_data(as_text=True)
    assert client.get(f"/isg-aksiyonlari/yeni?ohs_note_id={s.note.id}").status_code == 409
    note_event = AuditLog.query.filter_by(entity_type="OhsNote", action="action_deleted").one()
    assert note_event.company_id == s.company.id and note_event.user_id == s.manager.id
    assert AuditLog.query.filter_by(entity_type="Action", entity_id=action_id, action="deleted").count() == 1


@pytest.mark.parametrize("assign_to_actor", [False, True])
def test_note_conversion_notifies_assignee(client, setup, assign_to_actor):
    s = setup
    assignee = s.manager if assign_to_actor else s.owner
    login(client, s.manager)
    response = client.post("/isg-aksiyonlari/yeni", data=action_payload(
        assignee, ohs_note_id=str(s.note.id), ohs_note_version=str(s.note.version_id)))
    assert response.status_code == 302
    action = Action.query.one()
    notifications = Notification.query.filter_by(action_id=action.id).all()
    assert len(notifications) == 1
    assert notifications[0].user_id == assignee.id
    assert notifications[0].company_id == s.company.id
    assert notifications[0].target_url == f"/actions/{action.id}"
    event = NotificationEmailEvent.query.one()
    assert (event.user_id, event.company_id, event.kind, event.record_id) == (
        assignee.id, s.company.id, "action", action.id)
    assert event.phase.startswith("event:assignment:")
    assert event.status == "pending"
    login(client, assignee)
    assert client.get("/notifications/count").get_json()["count"] == 1
    assert client.get(f"/notifications/{notifications[0].id}/open").status_code == 302


def test_note_assignment_digest_is_delivered_without_close_permission(app, client, setup, monkeypatch):
    s = setup
    s.owner.email = "note-owner@example.test"
    db.session.commit()
    assert not s.owner.has_permission("actions.request_close_assigned")
    sent = []
    app.config.update(MAIL_ENABLED=True, MAIL_SERVER="smtp.example.test",
                      MAIL_DEFAULT_SENDER="notify@example.test", MAIL_SUPPRESS_SEND=False)
    monkeypatch.setattr("app.mail.send_mail_now", lambda *args: sent.append(args) or True)
    login(client, s.manager)
    assert client.post("/isg-aksiyonlari/yeni", data=action_payload(
        s.owner, ohs_note_id=str(s.note.id), ohs_note_version=str(s.note.version_id))).status_code == 302
    run_date = date.today()
    now = datetime.combine(run_date, datetime.min.time()).replace(
        hour=8, minute=30, tzinfo=reminder_timezone())
    assert dispatch_collection({"company_id": s.company.id, "run_date": run_date, "items": {}}, now=now) == 1
    assert len(sent) == 1 and sent[0][1] == [s.owner.email]
    assert NotificationEmailEvent.query.one().status == "accepted"


def test_invalid_action_does_not_claim_note(client, setup):
    login(client, setup.manager)
    response = client.post("/isg-aksiyonlari/yeni", data={
        "ohs_note_id": setup.note.id, "ohs_note_version": setup.note.version_id})
    assert response.status_code == 200
    db.session.refresh(setup.note)
    assert setup.note.action_id is None and setup.note.converted_at is None
    assert Action.query.count() == 0


def test_conversion_permission_and_wrong_category(client, setup):
    login(client, setup.owner)
    assert client.get(f"/isg-aksiyonlari/yeni?ohs_note_id={setup.note.id}").status_code == 403
    login(client, setup.manager)
    assert client.get(f"/actions/new?ohs_note_id={setup.note.id}").status_code == 400
    assert client.post("/isg-aksiyonlari/yeni", data=action_payload(
        setup.owner, ohs_note_id=setup.note.id, ohs_note_version=999)).status_code == 409


def test_csrf_and_required_fields(app, client, setup):
    login(client, setup.owner)
    assert client.post("/isg-notlari/yeni", data={"title": "", "description": " "}).status_code == 200
    assert OhsNote.query.count() == 1
    app.config["WTF_CSRF_ENABLED"] = True
    assert client.post(f"/isg-notlari/{setup.note.id}/sil", data={"version_id": setup.note.version_id}).status_code == 302
    db.session.refresh(setup.note)
    assert setup.note.deleted_at is None


def test_viewer_can_create_notes_but_not_convert(client, setup):
    viewer = create_user("note-viewer", company=setup.company, role_key="viewer")
    login(client, viewer)
    assert client.post("/isg-notlari/yeni", data={"title": "Gözlem", "description": "Not"}).status_code == 302
    assert client.get("/isg-notlari").status_code == 200
    assert client.post("/isg-aksiyonlari/yeni", data=action_payload(
        setup.owner, ohs_note_id=setup.note.id, ohs_note_version=setup.note.version_id)).status_code == 403


def test_foreign_post_and_deleted_conversion(client, setup):
    other_company = create_company("873")
    user = create_user("tenant-editor", company=other_company, role_key="management_representative")
    login(client, user)
    data = {"version_id": setup.note.version_id, "title": "Forged", "description": "Forged"}
    assert client.post(f"/isg-notlari/{setup.note.id}/duzenle", data=data).status_code == 404
    assert client.post("/isg-aksiyonlari/yeni", data=action_payload(
        user, ohs_note_id=setup.note.id, ohs_note_version=setup.note.version_id)).status_code == 404
    login(client, setup.manager)
    assert client.post(f"/isg-notlari/{setup.note.id}/sil", data=data).status_code == 302
    assert client.post("/isg-aksiyonlari/yeni", data=action_payload(
        setup.owner, ohs_note_id=setup.note.id, ohs_note_version=setup.note.version_id)).status_code == 404


def test_integrity_conflict_rolls_back_conversion(client, setup, monkeypatch):
    from sqlalchemy.exc import IntegrityError
    from app import routes
    def conflict(*args, **kwargs):
        raise IntegrityError("simulated unique number conflict", {}, Exception("duplicate"))
    login(client, setup.manager)
    monkeypatch.setattr(routes, "reserve_action_number", conflict)
    response = client.post("/isg-aksiyonlari/yeni", data=action_payload(
        setup.owner, ohs_note_id=setup.note.id, ohs_note_version=setup.note.version_id))
    assert response.status_code == 409
    db.session.refresh(setup.note)
    assert setup.note.converted_at is None and Action.query.count() == 0


def test_validation_retry_retains_original_note_version(client, setup, monkeypatch):
    from sqlalchemy import text
    from app import routes
    login(client, setup.manager)
    original_version = setup.note.version_id
    real_parse = routes.parse_action_form
    def concurrent_edit(**kwargs):
        with db.engine.begin() as conn:
            conn.execute(text('UPDATE ohs_notes SET title=:title, version_id=version_id+1 WHERE id=:id'),
                         {'title': 'Concurrent update', 'id': setup.note.id})
        raise ValueError('required_fields')
    monkeypatch.setattr(routes, 'parse_action_form', concurrent_edit)
    payload = action_payload(setup.owner, ohs_note_id=setup.note.id, ohs_note_version=original_version)
    response = client.post('/isg-aksiyonlari/yeni', data=payload)
    assert response.status_code == 200
    assert f'name="ohs_note_version" value="{original_version}"' in response.get_data(as_text=True)
    monkeypatch.setattr(routes, 'parse_action_form', real_parse)
    assert client.post('/isg-aksiyonlari/yeni', data=payload).status_code == 409
    assert Action.query.count() == 0


@pytest.mark.parametrize("change", ["edit", "delete", "convert"])
def test_independent_sessions_reject_stale_claim(app, setup, change):
    from datetime import datetime
    from sqlalchemy.orm import Session
    from sqlalchemy.orm.exc import StaleDataError
    with Session(db.engine) as first, Session(db.engine) as second:
        stale = first.get(OhsNote, setup.note.id)
        fresh = second.get(OhsNote, setup.note.id)
        if change == "edit":
            fresh.title = "Changed"
        elif change == "delete":
            fresh.deleted_at = datetime(2026, 10, 20)
        else:
            fresh.converted_at = datetime(2026, 10, 20)
        second.commit()
        stale.converted_at = datetime(2026, 10, 21)
        with pytest.raises(StaleDataError):
            first.commit()
        first.rollback()
