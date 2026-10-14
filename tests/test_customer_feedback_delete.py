from datetime import date, datetime, timedelta
import hashlib
from html.parser import HTMLParser
import json

import pytest
from sqlalchemy import String, cast
from sqlalchemy.orm import Query
from flask import template_rendered

from app import customer_portal
from app.extensions import db
from app.models import (
    Action,
    AuditLog,
    CompanyModule,
    ComplaintFile,
    ComplaintMessage,
    ComplaintRecord,
    ComplaintStatusHistory,
    CustomerPortalToken,
    Dof,
)

from .helpers import create_user
from .test_customer_feedback_internal import (
    BASE,
    CLOSED_STATUS,
    FeedbackCells,
    HEADERS,
    PUBLIC_SOURCE,
    app,
    client,
    company,
    create_record,
    image_upload,
    login,
    staff,
    stored_files,
)


class DeleteControls(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.links = set()
        self.inputs = {}
        self.cell = None
        self.cell_classes = {}
        self.feed(response.get_data(as_text=True))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "td":
            self.cell = attrs.get("data-label")
        if self.cell:
            self.cell_classes.setdefault(self.cell, set()).update(attrs.get("class", "").split())
        if tag == "a":
            self.links.add(attrs.get("href"))
        if tag == "input" and attrs.get("name"):
            self.inputs[attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "td":
            self.cell = None


def delete_url(record):
    return f"{BASE}/{record.id}/sil"


def delete_data(record, **overrides):
    values = {
        "reason": "Duplicate feedback entered in error",
        "confirm_delete": "yes",
        "updated_at": record.updated_at.isoformat(),
    }
    values.update(overrides)
    return values


def snapshot(model):
    return [
        {column.name: getattr(row, column.name) for column in model.__table__.columns}
        for row in model.query.order_by(model.id).all()
    ]


def retained_state(app):
    db.session.expire_all()
    return {
        "rows": {
            model.__name__: snapshot(model)
            for model in (
                ComplaintRecord, ComplaintFile, ComplaintMessage,
                ComplaintStatusHistory, CustomerPortalToken, Action, Dof, AuditLog,
            )
        },
        "files": stored_files(app),
    }


def add_token(record, purpose):
    raw = f"delete-test-{record.id}-{purpose}"
    token = CustomerPortalToken(
        company_id=record.company_id,
        complaint_id=record.id,
        purpose=purpose,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=datetime.now() + timedelta(days=1),
    )
    db.session.add(token)
    db.session.commit()
    return token, raw


@pytest.fixture()
def feedback(client, staff):
    record = create_record(
        client, staff,
        before_images=[image_upload("before.png")],
        after_images=[image_upload("after.png")],
    )
    message = ComplaintMessage(
        company_id=record.company_id, complaint_id=record.id,
        sender_type="user", sender_user_id=staff["owner"].id,
        body="Retain this investigation note", visibility="internal",
    )
    action = Action(
        company_id=record.company_id, title="Retain corrective action",
        responsible_owner="Internal Quality", termin_date=date.today(),
    )
    dof = Dof(company_id=record.company_id, dof_no="DELETE-QA-001", title="Retain DOF")
    db.session.add_all([message, action, dof])
    db.session.flush()
    record.action_id = action.id
    record.dof_id = dof.id
    action.dof_id = dof.id
    ComplaintFile.query.filter_by(complaint_id=record.id).first().message_id = message.id
    db.session.commit()
    add_token(record, "tracking")
    add_token(record, "verification")
    return record


@pytest.mark.parametrize("actor,visible", [("creator", True), ("owner", False)])
@pytest.mark.parametrize("closed", [False, True])
def test_delete_buttons_require_archive_permission(app, client, staff, feedback, actor, visible, closed):
    if closed:
        feedback.status = CLOSED_STATUS
        feedback.closed_at = datetime.now()
        db.session.commit()
    login(client, staff[actor])
    for url in (BASE, f"{BASE}/{feedback.id}"):
        response = client.get(url, headers=HEADERS)
        assert response.status_code == 200
        assert (delete_url(feedback) in DeleteControls(response).links) is visible


def test_confirmation_get_is_side_effect_free(app, client, staff, feedback):
    before = retained_state(app)
    response = client.get(delete_url(feedback), headers=HEADERS)
    assert response.status_code == 200
    controls = DeleteControls(response)
    assert controls.inputs["updated_at"] == feedback.updated_at.isoformat()
    assert controls.inputs["confirm_delete"] == "yes"
    assert controls.inputs["csrf_token"]
    assert retained_state(app) == before


def test_initial_server_default_timestamp_can_be_deleted_without_prior_update(app, client, staff):
    record = create_record(client, staff)
    raw_timestamp = db.session.query(cast(ComplaintRecord.updated_at, String)).filter_by(
        id=record.id,
    ).scalar()
    assert record.updated_at.microsecond == 0
    assert "." not in raw_timestamp
    assert record.updated_at == record.created_at
    response = client.get(delete_url(record), headers=HEADERS)
    assert response.status_code == 200
    controls = DeleteControls(response)
    response = client.post(delete_url(record), data=delete_data(
        record, updated_at=controls.inputs["updated_at"],
    ), headers=HEADERS)
    assert response.status_code == 302
    db.session.refresh(record)
    assert record.status == "Silindi"
    assert record.is_archived


@pytest.mark.parametrize("field,value", [
    ("reason", None), ("reason", ""), ("reason", " \t\n "),
    ("reason", "x" * 251), ("reason", "\u015f" * 251),
    ("confirm_delete", None), ("confirm_delete", ""),
    ("confirm_delete", "on"), ("confirm_delete", "true"),
])
def test_delete_requires_reason_and_explicit_confirmation(app, client, staff, feedback, field, value):
    data = delete_data(feedback)
    if value is None:
        data.pop(field)
    else:
        data[field] = value
    before = retained_state(app)
    response = client.post(delete_url(feedback), data=data, headers=HEADERS)
    assert response.status_code == 400
    assert retained_state(app) == before


@pytest.mark.parametrize("closed", [False, True])
def test_delete_preserves_evidence_links_and_resolution_state(app, client, staff, feedback, closed):
    if closed:
        feedback.status = CLOSED_STATUS
        feedback.closed_at = datetime.now() - timedelta(days=1)
        feedback.resolved_at = feedback.closed_at
        feedback.customer_solution_summary = "Previously resolved with the customer"
        db.session.commit()
    before = retained_state(app)
    original = before["rows"]["ComplaintRecord"][0]
    reason = "\u015f" * 250
    response = client.post(delete_url(feedback), data=delete_data(
        feedback, reason=f"  {reason}  ",
    ), headers=HEADERS)
    assert response.status_code == 302
    assert response.headers["Location"].endswith(BASE)
    after = retained_state(app)
    current = after["rows"]["ComplaintRecord"][0]
    assert len(after["rows"]["ComplaintRecord"]) == 1
    assert current["status"] == "Silindi"
    assert current["is_archived"] is True
    assert current["archived_at"] is not None
    assert current["archived_by_user_id"] == staff["creator"].id
    assert current["updated_at"] != original["updated_at"]
    changed_fields = {"status", "is_archived", "archived_at", "archived_by_user_id", "updated_at"}
    assert {k: v for k, v in current.items() if k not in changed_fields} == {
        k: v for k, v in original.items() if k not in changed_fields
    }
    for model in ("ComplaintFile", "ComplaintMessage", "Action", "Dof"):
        assert after["rows"][model] == before["rows"][model]
    assert after["files"] == before["files"]
    histories = after["rows"]["ComplaintStatusHistory"]
    assert histories[:-1] == before["rows"]["ComplaintStatusHistory"]
    assert histories[-1]["internal_status"] == "Silindi"
    assert histories[-1]["public_status"] == original["public_status"]
    assert histories[-1]["changed_by_user_id"] == staff["creator"].id
    assert histories[-1]["note"] == f"Silindi: {reason}"[:255]
    audit = AuditLog.query.filter_by(
        entity_type="CustomerFeedbackPortal", entity_id=str(feedback.id), action="deleted",
    ).one()
    assert audit.company_id == feedback.company_id
    assert audit.user_id == staff["creator"].id
    assert json.loads(audit.new_values) == {
        "soft_delete": True, "reason": reason,
        "previous_status": original["status"], "status": "Silindi",
    }
    active = client.get(BASE, headers=HEADERS)
    archive = client.get(BASE, query_string={"archived": "1"}, headers=HEADERS)
    detail = client.get(f"{BASE}/{feedback.id}", headers=HEADERS)
    assert active.status_code == archive.status_code == detail.status_code == 200
    assert feedback.complaint_no not in active.get_data(as_text=True)
    assert feedback.complaint_no in archive.get_data(as_text=True)
    assert "Silindi" in archive.get_data(as_text=True)
    cells = FeedbackCells(archive.get_data(as_text=True))
    assert cells.text("Kalan S\u00fcre") == "Takip d\u0131\u015f\u0131"
    assert cells.text("Sonu\u00e7") == "Silindi"
    if not closed:
        assert cells.text("Sonu\u00e7lanma") == "-"
    result_classes = DeleteControls(archive).cell_classes["Sonu\u00e7"]
    assert "bi-trash" in result_classes
    assert not {"text-bg-success", "bi-check-circle"} & result_classes
    for response in (archive, detail):
        assert delete_url(feedback) not in DeleteControls(response).links


def test_delete_revokes_only_target_tokens_and_blocks_public_access(app, client, staff, feedback):
    other = create_record(client, staff)
    for record in (feedback, other):
        record.source = PUBLIC_SOURCE
        record.email_verified_at = datetime.now()
    db.session.commit()
    other_token, other_raw = add_token(other, "tracking")
    before_other = snapshot(CustomerPortalToken)[-1]
    raw = f"delete-test-{feedback.id}-tracking"
    public = app.test_client()
    assert public.get(f"/musteri-portali/takip/{raw}", headers=HEADERS).status_code == 200
    response = client.post(delete_url(feedback), data=delete_data(feedback), headers=HEADERS)
    assert response.status_code == 302
    db.session.expire_all()
    tokens = CustomerPortalToken.query.filter_by(complaint_id=feedback.id).all()
    assert len(tokens) == 2
    assert all(token.revoked_at == feedback.archived_at for token in tokens)
    assert snapshot(CustomerPortalToken)[-1] == before_other
    assert other_token.revoked_at is None
    assert public.get(f"/musteri-portali/takip/{raw}", headers=HEADERS).status_code == 404
    assert public.get(
        f"/musteri-portali/dogrula/delete-test-{feedback.id}-verification", headers=HEADERS,
    ).status_code == 404
    assert public.get(f"/musteri-portali/takip/{other_raw}", headers=HEADERS).status_code == 200


@pytest.mark.parametrize("already_archived", [False, True])
def test_repeated_or_already_archived_deletion_conflicts(app, client, staff, feedback, already_archived):
    data = delete_data(feedback)
    if already_archived:
        feedback.is_archived = True
        feedback.status = "Ar\u015fiv"
        feedback.archived_at = datetime.now()
        db.session.commit()
    else:
        assert client.post(delete_url(feedback), data=data, headers=HEADERS).status_code == 302
    before = retained_state(app)
    for method in ("GET", "POST"):
        response = client.open(delete_url(feedback), method=method, data=data, headers=HEADERS)
        assert response.status_code == 409
        assert retained_state(app) == before


@pytest.mark.parametrize("version", ["stale", "stale_fraction", "missing", "malformed"])
def test_delete_rejects_invalid_record_version(app, client, staff, feedback, version):
    data = delete_data(feedback)
    if version in {"stale", "stale_fraction"}:
        feedback.subject = "Updated by another user"
        feedback.updated_at += timedelta(
            seconds=1 if version == "stale" else 0,
            microseconds=1 if version == "stale_fraction" else 0,
        )
        db.session.commit()
    elif version == "missing":
        data.pop("updated_at")
    else:
        data["updated_at"] = "not-a-timestamp"
    before = retained_state(app)
    response = client.post(delete_url(feedback), data=data, headers=HEADERS)
    assert response.status_code == 409
    assert retained_state(app) == before


def test_compare_and_swap_rejects_change_after_initial_version_check(app, client, staff, feedback, monkeypatch):
    data = delete_data(feedback)
    changed_at = feedback.updated_at + timedelta(seconds=1)
    original_update = Query.update
    observed = []

    def interleaved_update(query, values, *args, **kwargs):
        if values.get("is_archived") is True:
            # Commit a competing write after validation but before the guarded UPDATE.
            db.session.execute(ComplaintRecord.__table__.update().where(
                ComplaintRecord.id == feedback.id,
            ).values(subject="Concurrent edit", updated_at=changed_at))
            db.session.commit()
            observed.append(retained_state(app))
        return original_update(query, values, *args, **kwargs)

    monkeypatch.setattr(Query, "update", interleaved_update)
    response = client.post(delete_url(feedback), data=data, headers=HEADERS)
    assert response.status_code == 409
    assert len(observed) == 1
    assert retained_state(app) == observed[0]


@pytest.mark.parametrize("actor,status", [
    ("owner", 403), ("unrelated_archiver", 403), ("foreign_archiver", 404),
])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_delete_requires_permission_record_access_and_tenant(app, client, staff, feedback, actor, status, method):
    headers = HEADERS
    if actor == "owner":
        user = staff["owner"]
    else:
        user = create_user(actor, company=company("102" if actor == "foreign_archiver" else "101"),
                           permissions=("customer_portal.view", "customer_portal.archive"))
    isolated = app.test_client()
    if actor == "foreign_archiver":
        headers = {"Host": "diger-firma.volkaportal.com"}
        with isolated.session_transaction(base_url="https://diger-firma.volkaportal.com") as session:
            session["user_id"] = user.id
    else:
        login(isolated, user)
    before = retained_state(app)
    response = isolated.open(delete_url(feedback), method=method, data=delete_data(feedback), headers=headers)
    assert response.status_code == status
    assert retained_state(app) == before


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_anonymous_delete_redirects_without_mutation(app, client, staff, feedback, method):
    before = retained_state(app)
    response = app.test_client().open(delete_url(feedback), method=method, data=delete_data(feedback), headers=HEADERS)
    assert response.status_code == 302
    assert retained_state(app) == before


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_delete_is_disabled_with_module(app, client, staff, feedback, method):
    CompanyModule.query.filter_by(
        company_id=company().id, module_key="customer_feedback_portal",
    ).one().is_enabled = False
    db.session.commit()
    before = retained_state(app)
    response = client.open(delete_url(feedback), method=method, data=delete_data(feedback), headers=HEADERS)
    assert response.status_code in {403, 404}
    assert retained_state(app) == before


@pytest.mark.parametrize("csrf", [None, "forged-token"])
def test_delete_rejects_missing_or_invalid_csrf(app, client, staff, feedback, csrf):
    app.config["WTF_CSRF_ENABLED"] = True
    data = delete_data(feedback)
    if csrf is not None:
        data["csrf_token"] = csrf
    before = retained_state(app)
    response = client.post(delete_url(feedback), data=data, headers={**HEADERS, "Accept": "application/json"})
    assert response.status_code == 400
    assert response.json["ok"] is False
    assert retained_state(app) == before


def test_confirmation_form_submits_with_real_csrf(app, client, staff, feedback):
    app.config["WTF_CSRF_ENABLED"] = True
    response = client.get(delete_url(feedback), headers=HEADERS)
    assert response.status_code == 200
    controls = DeleteControls(response)
    response = client.post(delete_url(feedback), data=delete_data(
        feedback, csrf_token=controls.inputs["csrf_token"],
        updated_at=controls.inputs["updated_at"],
    ), headers={**HEADERS, "Referer": f"https://{HEADERS['Host']}{delete_url(feedback)}"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith(BASE)
    db.session.refresh(feedback)
    assert feedback.is_archived


def test_audit_failure_rolls_back_record_tokens_history_and_files(app, client, staff, feedback, monkeypatch):
    before = retained_state(app)
    real_audit = customer_portal._audit
    calls = []

    def fail_after_audit(record, action, details=None):
        calls.append(action)
        real_audit(record, action, details)
        db.session.flush()
        assert record.is_archived
        assert all(token.revoked_at is not None for token in record.portal_tokens)
        raise RuntimeError("Injected audit storage failure")

    monkeypatch.setattr(customer_portal, "_audit", fail_after_audit)
    with pytest.raises(RuntimeError, match="Injected audit storage failure"):
        client.post(delete_url(feedback), data=delete_data(feedback), headers=HEADERS)
    assert calls == ["deleted"]
    assert retained_state(app) == before


@pytest.mark.parametrize("status", ["Kapandı", "İncelemede"])
def test_deleted_feedback_is_excluded_from_iso_open_and_critical_counts(app, client, staff, feedback, status):
    manager = create_user("delete-iso-manager", company=company(), role_key="management_representative")
    db.session.add(CompanyModule(company_id=company().id, module_key="iso_executive_summary", is_enabled=True))
    feedback.status = status
    feedback.priority = "Kritik"
    db.session.commit()
    login(client, manager)
    captured = []

    def capture(sender, template, context, **extra):
        if "iso_dashboard" in context:
            captured.append(context["iso_dashboard"])

    with template_rendered.connected_to(capture, app):
        assert client.get("/iso-9001-yonetici-ozeti", headers=HEADERS).status_code == 200
        assert client.post(delete_url(feedback), data=delete_data(feedback), headers=HEADERS).status_code == 302
        assert client.get("/iso-9001-yonetici-ozeti", headers=HEADERS).status_code == 200
    before, after = [next(card for card in summary["cards"] if card["title"] == "Açık Şikayet") for summary in captured]
    assert before["value"] == (0 if status == "Kapandı" else 1)
    assert after["value"] == 0
    assert after["subtitle"] == "0 gecikmiş, 0 kritik"
    assert after["items"] == []
