from types import SimpleNamespace

import pytest

from app.extensions import db
from app.models import Action, AuditLog, CompanyModule
from app.ohs_notes_models import OhsNote
from .helpers import create_company, create_user, login
from .test_action_management import action_payload


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


def test_action_conversion_duplicate_and_delete_preserves_action(client, setup):
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
    assert client.post(f"/actions/{action.id}/delete").status_code == 409
    assert client.post(f"/isg-notlari/{s.note.id}/sil", data={"version_id": s.note.version_id}).status_code == 302
    assert Action.query.count() == 1
    assert client.post(f"/actions/{action.id}/delete").status_code == 409


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
