from datetime import datetime, timedelta
from io import BytesIO
import json
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from flask import url_for
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.extensions import db
from app.models import AuditLog, CompanyDepartment, CompanyModule, Notification
from app.shift_handover_models import ShiftHandover, handover_today
from tests.helpers import create_company, create_user, login, assert_xlsx_response, sheet_values


BASE = "/vardiya-devir-teslimi"
VIEW = ("shift_handover.view",)
CREATE = (*VIEW, "shift_handover.create")
OPERATOR = (*CREATE, "shift_handover.receive", "shift_handover.export")


@pytest.fixture()
def people(app):
    company = create_company("shift")
    foreign_company = create_company("foreign-shift")
    users = {
        "sender": create_user("shift-sender", company=company, permissions=OPERATOR),
        "receiver": create_user("shift-receiver", company=company, permissions=OPERATOR),
        "stranger": create_user("shift-stranger", company=company, permissions=OPERATOR),
        "manager": create_user("shift-manager", company=company, role_key="management_representative"),
        "reader": create_user("shift-reader", company=company, permissions=("shift_handover.view_all",)),
        "foreign": create_user("shift-foreign", company=foreign_company, role_key="management_representative"),
    }
    department = CompanyDepartment(company_id=company.id, name="Production", is_active=True)
    foreign_department = CompanyDepartment(company_id=foreign_company.id, name="Foreign production", is_active=True)
    db.session.add_all([department, foreign_department])
    db.session.commit()
    return dict(users, company=company, foreign_company=foreign_company,
                department=department, foreign_department=foreign_department)


def endpoint(client, name, record=None):
    with client.application.test_request_context():
        return url_for("shift_handover." + name, **({"record_id": record.id} if record else {}))


def form_data(people, **overrides):
    data = dict(handover_date=handover_today().isoformat(), shift_name="Morning",
                department_id=str(people["department"].id), area="Line 1",
                title="Shift inspection", summary="PRIVATE-SUMMARY",
                pending_work="PRIVATE-PENDING", safety_notes="PRIVATE-SAFETY",
                quality_notes="PRIVATE-QUALITY", equipment_notes="PRIVATE-EQUIPMENT",
                receiver_user_id=str(people["receiver"].id), request_token=str(uuid4()), version_id="1")
    data.update(overrides)
    return data


def seed_record(people, **overrides):
    values = form_data(people)
    values.update(company_id=people["company"].id, sender_user_id=people["sender"].id,
                  department_id=people["department"].id, receiver_user_id=people["receiver"].id,
                  handover_date=handover_today())
    values.update(overrides)
    values["version_id"] = int(values["version_id"])
    record = ShiftHandover(**values)
    db.session.add(record)
    db.session.commit()
    return record


def snapshot(record):
    db.session.refresh(record)
    return {column.name: getattr(record, column.name) for column in record.__table__.columns}


def create_record(client, people, **overrides):
    login(client, people["sender"])
    data = form_data(people, **overrides)
    response = client.post(endpoint(client, "create"), data=data)
    assert response.status_code == 302
    record = ShiftHandover.query.filter_by(request_token=data["request_token"]).one()
    assert response.location.endswith(endpoint(client, "detail", record))
    return record


def transition(client, record, name, **overrides):
    data = dict(version_id=str(record.version_id))
    data.update(overrides)
    return client.post(endpoint(client, name, record), data=data)


def counts():
    return (ShiftHandover.query.count(), AuditLog.query.filter_by(entity_type="ShiftHandover").count(),
            Notification.query.count())


def test_registered_endpoints_are_company_module_gated(client, people):
    from app.models import COMPANY_MODULE_KEYS
    from app.routes import MODULE_ENDPOINTS

    assert "shift_handover" in COMPANY_MODULE_KEYS
    record = seed_record(people)
    names = ("dashboard", "create", "detail", "edit", "send", "receive", "archive", "cancel", "export_excel")
    for name in names:
        assert MODULE_ENDPOINTS["shift_handover." + name] == "shift_handover"
        assert endpoint(client, name, record if name in {"detail", "edit", "send", "receive", "archive", "cancel"} else None).startswith(BASE)
    login(client, people["manager"])
    assert client.get(BASE).status_code == 200
    assert client.get(endpoint(client, "create")).status_code == 200
    CompanyModule.query.filter_by(company_id=people["company"].id, module_key="shift_handover").one().is_enabled = False
    db.session.commit()
    before = counts()
    for name in names:
        target = record if name in {"detail", "edit", "send", "receive", "archive", "cancel"} else None
        url = endpoint(client, name, target)
        response = client.post(url, data=form_data(people)) if name in {"send", "receive", "archive", "cancel"} else client.get(url)
        assert response.status_code == 403, name
    assert counts() == before


def test_full_lifecycle_audit_private_notification_and_report(client, people):
    record = create_record(client, people)
    assert record.sender_user_id == people["sender"].id
    assert record.company_id == people["company"].id
    assert record.status == "draft" and record.version_id == 1
    assert record.sent_at is record.received_at is record.archived_at is None
    assert Notification.query.count() == 0
    assert client.get(endpoint(client, "detail", record)).status_code == 200
    assert client.post(endpoint(client, "edit", record), data=form_data(
        people, version_id=record.version_id, title="Updated handover",
    )).status_code == 302
    assert record.title == "Updated handover" and record.version_id == 2
    assert transition(client, record, "send").status_code == 302
    assert record.status == "sent" and record.sent_by_user_id == people["sender"].id
    assert record.sent_at is not None and record.version_id == 3
    notice = Notification.query.one()
    assert notice.company_id == record.company_id and notice.user_id == people["receiver"].id
    assert notice.target_url == endpoint(client, "detail", record)
    for field in ("summary", "pending_work", "safety_notes", "quality_notes", "equipment_notes"):
        assert getattr(record, field) not in notice.message
    login(client, people["receiver"])
    assert transition(client, record, "receive").status_code == 302
    assert record.status == "received" and record.version_id == 4
    assert record.received_by_user_id == people["receiver"].id
    assert record.received_at >= record.sent_at
    report = client.get(endpoint(client, "export_excel"), query_string={"status": "received"})
    assert_xlsx_response(report)
    rows = sheet_values(report.data)
    assert any(record.title in row and record.summary in row for row in rows)
    login(client, people["manager"])
    assert transition(client, record, "archive").status_code == 302
    assert record.archived_at is not None and record.archived_by_user_id == people["manager"].id
    assert record.title not in client.get(BASE).get_data(as_text=True)
    assert record.title in client.get(BASE, query_string={"archive": "archived"}).get_data(as_text=True)
    events = AuditLog.query.filter_by(entity_type="ShiftHandover", entity_id=str(record.id)).order_by(AuditLog.id).all()
    assert [event.action for event in events] == ["created", "updated", "sent", "received", "archived"]
    assert [event.user_id for event in events] == [people["sender"].id] * 3 + [people["receiver"].id, people["manager"].id]
    assert all(event.company_id == record.company_id for event in events)
    assert json.loads(events[2].old_values)["status"] == "draft"
    assert json.loads(events[2].new_values)["status"] == "sent"
    assert AuditLog.query.filter_by(entity_type="ShiftHandover", action="exported", company_id=record.company_id).count() == 1


def test_own_visibility_and_tenant_idor_on_every_record_endpoint(client, people):
    record = create_record(client, people, title="PRIVATE-RECORD-TITLE")
    before = snapshot(record), counts()
    for actor, visible in (("sender", True), ("receiver", True), ("manager", True),
                           ("reader", True), ("stranger", False), ("foreign", False)):
        login(client, people[actor])
        assert client.get(endpoint(client, "detail", record)).status_code == (200 if visible else 404), actor
        html = client.get(BASE).get_data(as_text=True)
        assert (record.title in html) is visible, actor
        if not visible:
            for name in ("edit", "send", "receive", "cancel"):
                assert client.post(endpoint(client, name, record), data=form_data(
                    people, version_id=record.version_id,
                )).status_code == 404, (actor, name)
    login(client, people["foreign"])
    assert transition(client, record, "archive").status_code == 404
    assert (snapshot(record), counts()) == before


def test_sender_identity_lifecycle_and_company_cannot_be_forged(client, people):
    record = create_record(client, people, company_id=people["foreign_company"].id,
                           sender_user_id=people["foreign"].id, status="received",
                           sent_by_user_id=people["foreign"].id, received_by_user_id=people["foreign"].id,
                           sent_at="2026-10-12T08:00:00", received_at="2026-10-12T09:00:00",
                           archived_at="2026-10-12T10:00:00", archived_by_user_id=people["foreign"].id)
    assert record.company_id == people["company"].id
    assert record.sender_user_id == people["sender"].id
    assert record.status == "draft" and record.sent_at is record.received_at is record.archived_at is None
    login(client, people["manager"])
    token = record.request_token
    assert client.post(endpoint(client, "edit", record), data=form_data(
        people, version_id=record.version_id, company_id=people["foreign_company"].id,
        sender_user_id=people["manager"].id, status="sent",
    )).status_code == 302
    assert record.company_id == people["company"].id and record.sender_user_id == people["sender"].id
    assert record.status == "draft" and record.request_token == token
    assert transition(client, record, "send", sent_by_user_id=people["sender"].id).status_code == 302
    assert record.sent_by_user_id == people["manager"].id
    before = snapshot(record), counts()
    assert transition(client, record, "receive", receiver_user_id=people["manager"].id,
                      received_by_user_id=people["receiver"].id).status_code == 403
    assert (snapshot(record), counts()) == before
    login(client, people["receiver"])
    assert transition(client, record, "receive", received_by_user_id=people["manager"].id).status_code == 302
    assert record.received_by_user_id == people["receiver"].id


def test_draft_edit_send_and_archive_restrictions(client, people):
    record = create_record(client, people)
    for actor, code in (("receiver", 403), ("reader", 403), ("stranger", 404)):
        login(client, people[actor])
        before = snapshot(record), counts()
        assert client.get(endpoint(client, "edit", record)).status_code == code
        assert client.post(endpoint(client, "edit", record), data=form_data(people)).status_code == code
        assert transition(client, record, "send").status_code == code
        assert (snapshot(record), counts()) == before
    login(client, people["sender"])
    assert transition(client, record, "archive").status_code == 403
    login(client, people["receiver"])
    assert transition(client, record, "receive").status_code == 409
    login(client, people["sender"])
    assert transition(client, record, "send").status_code == 302
    for actor in ("sender", "manager"):
        login(client, people[actor])
        before = snapshot(record), counts()
        assert client.get(endpoint(client, "edit", record)).status_code == 409
        assert client.post(endpoint(client, "edit", record), data=form_data(people, version_id=record.version_id)).status_code == 409
        assert transition(client, record, "send").status_code == 409
        assert (snapshot(record), counts()) == before


def test_received_and_archived_records_are_immutable(client, people):
    record = create_record(client, people)
    assert transition(client, record, "send").status_code == 302
    login(client, people["receiver"])
    assert transition(client, record, "receive").status_code == 302
    before = snapshot(record), counts()
    assert transition(client, record, "receive").status_code == 409
    login(client, people["manager"])
    assert client.post(endpoint(client, "edit", record), data=form_data(people, version_id=record.version_id)).status_code == 409
    assert transition(client, record, "send").status_code == 409
    assert (snapshot(record), counts()) == before
    assert transition(client, record, "archive").status_code == 302
    before = snapshot(record), counts()
    assert transition(client, record, "archive").status_code == 409
    assert client.post(endpoint(client, "edit", record), data=form_data(people, version_id=record.version_id)).status_code == 409
    login(client, people["receiver"])
    assert transition(client, record, "receive").status_code == 409
    assert (snapshot(record), counts()) == before


def test_idempotent_create_does_not_leak_another_senders_record(client, people):
    login(client, people["sender"])
    data = form_data(people)
    original = client.post(endpoint(client, "create"), data=data)
    assert original.status_code == 302
    before = counts()
    assert client.post(endpoint(client, "create"), data=data).location == original.location
    assert counts() == before
    login(client, people["stranger"])
    replay = client.post(endpoint(client, "create"), data=data)
    assert replay.status_code == 409 and "Location" not in replay.headers
    assert counts() == before


@pytest.mark.parametrize("name", ["create", "edit", "send", "receive", "archive", "cancel"])
def test_all_posts_require_current_version(client, people, name):
    record = create_record(client, people)
    if name == "receive":
        assert transition(client, record, "send").status_code == 302
        login(client, people["receiver"])
    elif name == "archive":
        login(client, people["manager"])
    before = snapshot(record), counts()
    for invalid in (None, "", "not-a-version", "0", "-1", str(2**100)):
        data = form_data(people, version_id=invalid)
        if invalid is None:
            data.pop("version_id")
        response = client.post(endpoint(client, name, None if name == "create" else record), data=data)
        assert response.status_code == 409, (name, invalid)
        assert (snapshot(record), counts()) == before


def test_old_browser_versions_cannot_repeat_lifecycle_mutations(client, people):
    record = create_record(client, people)
    old_version = record.version_id
    data = form_data(people, version_id=old_version, title="Newer edit")
    assert client.post(endpoint(client, "edit", record), data=data).status_code == 302
    before = snapshot(record), counts()
    assert client.post(endpoint(client, "edit", record), data=data).status_code == 409
    assert transition(client, record, "send", version_id=old_version).status_code == 409
    assert (snapshot(record), counts()) == before
    sent_version = record.version_id
    assert transition(client, record, "send").status_code == 302
    before = snapshot(record), counts()
    assert transition(client, record, "send", version_id=sent_version).status_code == 409
    login(client, people["receiver"])
    assert transition(client, record, "receive", version_id=sent_version).status_code == 409
    assert (snapshot(record), counts()) == before
    receive_version = record.version_id
    assert transition(client, record, "receive").status_code == 302
    before = snapshot(record), counts()
    assert transition(client, record, "receive", version_id=receive_version).status_code == 409
    login(client, people["manager"])
    assert transition(client, record, "archive", version_id=receive_version).status_code == 409
    assert (snapshot(record), counts()) == before


def test_all_write_endpoints_require_csrf_and_have_no_get_side_effects(app, client, people):
    draft = create_record(client, people)
    sent = create_record(client, people)
    assert transition(client, sent, "send").status_code == 302
    app.config["WTF_CSRF_ENABLED"] = True
    cases = (("create", None, "sender"), ("edit", draft, "sender"), ("send", draft, "sender"),
             ("receive", sent, "receiver"), ("archive", sent, "manager"), ("cancel", draft, "sender"))
    for name, record, actor in cases:
        login(client, people[actor])
        before = snapshot(draft), snapshot(sent), counts()
        data = form_data(people, version_id=record.version_id if record else 1)
        url = endpoint(client, name, record)
        for token in (None, "forged-csrf-token"):
            if token:
                data["csrf_token"] = token
            response = client.post(url, data=data, headers={"Accept": "application/json"})
            assert response.status_code == 400, name
        if name in {"send", "receive", "archive", "cancel"}:
            assert client.get(url).status_code == 405
        assert (snapshot(draft), snapshot(sent), counts()) == before


def test_invalid_fields_are_rejected_without_partial_record_or_audit(client, people):
    login(client, people["sender"])
    invalid_fields = [
        {"handover_date": ""}, {"handover_date": "not-a-date"}, {"handover_date": "2026-02-30"},
        {"handover_date": "2026-13-01"}, {"handover_date": "2026-10-12T12:00:00"},
        {"shift_name": " "}, {"shift_name": "a" * 81}, {"title": " "}, {"title": "a" * 181},
        {"summary": " "}, {"summary": "a" * 5001}, {"summary": "bad\x00text"}, {"area": "a" * 121},
        {"request_token": "invalid"}, {"request_token": ""},
    ]
    invalid_fields += [{name: "a" * 5001} for name in ("pending_work", "safety_notes", "quality_notes", "equipment_notes")]
    invalid_fields += [{name: value} for name in ("department_id", "receiver_user_id")
                       for value in ("", "bad", "0", "-1", str(2**100), "9999999")]
    before = counts()
    for overrides in invalid_fields:
        assert client.post(endpoint(client, "create"), data=form_data(people, **overrides)).status_code == 400, tuple(overrides)
        assert counts() == before


def test_forged_foreign_inactive_and_unprivileged_assignments(client, people):
    inactive_user = create_user("inactive-receiver", company=people["company"], permissions=OPERATOR)
    inactive_user.is_active = False
    unprivileged = create_user("unprivileged-receiver", company=people["company"])
    inactive_department = CompanyDepartment(company_id=people["company"].id, name="Inactive", is_active=False)
    db.session.add(inactive_department)
    db.session.commit()
    login(client, people["sender"])
    before = counts()
    for overrides in (
        dict(receiver_user_id=people["foreign"].id), dict(department_id=people["foreign_department"].id),
        dict(receiver_user_id=inactive_user.id), dict(receiver_user_id=unprivileged.id),
        dict(department_id=inactive_department.id),
    ):
        assert client.post(endpoint(client, "create"), data=form_data(people, **overrides)).status_code == 400
        assert counts() == before


@pytest.mark.parametrize("change", ["inactive", "lost_view", "lost_receive"])
def test_send_revalidates_receiver_after_assignment(client, people, change):
    record = create_record(client, people)
    receiver = people["receiver"]
    if change == "inactive":
        receiver.is_active = False
    else:
        permission = "shift_handover.view" if change == "lost_view" else "shift_handover.receive"
        receiver.extra_permissions = [item for item in receiver.extra_permissions if item.permission_key != permission]
    db.session.commit()
    before = snapshot(record), counts()
    assert transition(client, record, "send").status_code == 400
    assert (snapshot(record), counts()) == before


def test_receive_permission_is_separate_and_viewer_cannot_receive(client, people):
    from app.models import Role

    record = create_record(client, people)
    assert transition(client, record, "send").status_code == 302
    receiver = people["receiver"]
    receiver.extra_permissions = [item for item in receiver.extra_permissions if item.permission_key != "shift_handover.receive"]
    db.session.commit()
    login(client, receiver)
    before = snapshot(record), counts()
    assert client.get(endpoint(client, "detail", record)).status_code == 200
    assert transition(client, record, "receive").status_code == 403
    receiver.roles = [Role.query.filter_by(key="viewer").one()]
    receiver.extra_permissions = []
    db.session.commit()
    assert transition(client, record, "receive").status_code == 403
    from app.models import UserPermission
    receiver.extra_permissions.append(UserPermission(permission_key="shift_handover.receive"))
    db.session.commit()
    assert transition(client, record, "receive").status_code == 403
    assert (snapshot(record), counts()) == before


def test_export_requires_permission_and_never_expands_own_scope(client, people):
    record = create_record(client, people, title='=HYPERLINK("https://example.invalid")')
    seed_record(people, sender_user_id=people["stranger"].id, receiver_user_id=people["stranger"].id,
                title="SAME-COMPANY-HIDDEN")
    seed_record(people, company_id=people["foreign_company"].id, department_id=people["foreign_department"].id,
                sender_user_id=people["foreign"].id, receiver_user_id=people["foreign"].id, title="FOREIGN-HIDDEN")
    report = client.get(endpoint(client, "export_excel"), query_string={"archive": "all", "status": "all"})
    assert_xlsx_response(report)
    rows = sheet_values(report.data)
    assert any(record.title in row for row in rows)
    assert "SAME-COMPANY-HIDDEN" not in str(rows) and "FOREIGN-HIDDEN" not in str(rows)
    with ZipFile(BytesIO(report.data)) as archive:
        for name in archive.namelist():
            if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                root = ET.fromstring(archive.read(name))
                assert not root.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}f")
    login(client, people["reader"])
    before = counts()
    assert client.get(endpoint(client, "export_excel")).status_code == 403
    assert counts() == before


def test_audit_or_notification_failure_rolls_back_entire_send(client, people, monkeypatch):
    from app import shift_handover

    record = create_record(client, people)
    before = snapshot(record), counts()
    def unavailable(*args, **kwargs):
        raise RuntimeError("injected persistence failure")
    for hook in ("record_audit_event", "add_user_notification"):
        with monkeypatch.context() as patch:
            patch.setattr(shift_handover, hook, unavailable)
            assert transition(client, record, "send").status_code == 500
        assert (snapshot(record), counts()) == before


def test_anonymous_and_unscoped_super_admin_cannot_read_or_write(client, people):
    record = seed_record(people)
    anonymous = client.application.test_client()
    before = snapshot(record), counts()
    assert anonymous.get(endpoint(client, "detail", record)).status_code == 302
    assert anonymous.post(endpoint(client, "send", record), data={"version_id": 1}).status_code == 302
    admin = create_user("shift-unscoped-admin", role_key="super_admin")
    login(client, admin)
    assert client.get(BASE).status_code == 403
    assert transition(client, record, "archive").status_code == 403
    assert (snapshot(record), counts()) == before


def test_two_sessions_cannot_overwrite_a_newer_draft(people):
    record = seed_record(people)
    with Session(db.engine) as first, Session(db.engine) as second:
        current = first.get(ShiftHandover, record.id)
        stale = second.get(ShiftHandover, record.id)
        current.title = "First committed edit"
        first.commit()
        stale.title = "Lost update must be rejected"
        with pytest.raises(StaleDataError):
            second.commit()
        second.rollback()
    db.session.refresh(record)
    assert record.title == "First committed edit"
    assert record.version_id == 2


@pytest.mark.parametrize("field", ["receiver_user_id", "sender_user_id", "department_id"])
def test_database_rejects_cross_tenant_links(people, field):
    value = people["foreign_department"].id if field == "department_id" else people["foreign"].id
    with pytest.raises(IntegrityError):
        seed_record(people, **{field: value})
    db.session.rollback()
    assert ShiftHandover.query.count() == 0


def test_request_token_is_unique_per_company_not_globally(people):
    original = seed_record(people)
    token = original.request_token
    with pytest.raises(IntegrityError):
        seed_record(people, request_token=token)
    db.session.rollback()
    foreign = seed_record(people, company_id=people["foreign_company"].id,
                          department_id=people["foreign_department"].id,
                          sender_user_id=people["foreign"].id, receiver_user_id=people["foreign"].id,
                          request_token=token)
    assert foreign.company_id != original.company_id
    assert ShiftHandover.query.count() == 2


def test_database_receipt_requires_an_identified_receiver(people):
    record = seed_record(people)
    sender_id = people["sender"].id
    record.status = "sent"
    record.sent_at = datetime(2026, 10, 12, 8)
    record.sent_by_user_id = sender_id
    db.session.commit()
    record.status = "received"
    record.received_at = datetime(2026, 10, 12, 9)
    record.received_by_user_id = None
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    assert record.status == "sent"


@pytest.mark.parametrize("name", ["edit", "send", "cancel"])
def test_revoked_create_permission_prevents_sender_mutations(client, people, name):
    record = create_record(client, people)
    sender = people["sender"]
    sender.extra_permissions = [item for item in sender.extra_permissions
                                if item.permission_key != "shift_handover.create"]
    db.session.commit()
    before = snapshot(record), counts()
    assert client.get(endpoint(client, "detail", record)).status_code == 200
    response = client.post(endpoint(client, name, record), data=form_data(
        people, version_id=record.version_id, title="Unauthorized edit", cancel_reason="Unauthorized cancel",
    ))
    assert response.status_code == 403
    assert (snapshot(record), counts()) == before


@pytest.mark.parametrize("role,permissions", [
    ("super_admin", {"view", "view_all", "create", "receive", "manage", "export"}),
    ("management_representative", {"view", "view_all", "create", "receive", "manage", "export"}),
    ("management", {"view", "view_all", "export"}),
    ("department_manager", {"view", "create", "receive", "export"}),
    ("department_staff", {"view", "create", "receive"}),
    ("viewer", {"view"}),
])
def test_six_default_roles_permission_scope_and_controls(client, people, role, permissions):
    from app.seed import PERMISSION_CATALOG

    all_permissions = {"view", "view_all", "create", "receive", "manage", "export"}
    assert {item["key"] for item in PERMISSION_CATALOG if item["key"].startswith("shift_handover.")} == {
        "shift_handover." + item for item in all_permissions
    }
    actor = create_user("role-" + role, company=None if role == "super_admin" else people["company"], role_key=role)
    assert {item for item in all_permissions if actor.has_permission("shift_handover." + item)} == permissions
    record = seed_record(people, title="ROLE-SCOPED-RECORD")
    login(client, actor, company=people["company"] if role == "super_admin" else None)
    visible = bool(permissions & {"view_all", "manage"})
    response = client.get(BASE)
    assert response.status_code == 200
    assert (record.title in response.get_data(as_text=True)) is visible
    assert client.get(endpoint(client, "detail", record)).status_code == (200 if visible else 404)
    assert client.get(endpoint(client, "create")).status_code == (200 if "create" in permissions else 403)
    before = snapshot(record)
    assert transition(client, record, "receive").status_code == (403 if visible else 404)
    assert snapshot(record) == before
    report = client.get(endpoint(client, "export_excel"))
    assert report.status_code == (200 if "export" in permissions else 403)
    if report.status_code == 200:
        assert (record.title in str(sheet_values(report.data))) is visible


def test_cancel_reason_actor_state_and_archive(client, people):
    record = create_record(client, people)
    before = snapshot(record), counts()
    for reason in ("", " ", "a" * 1001, "bad\x00reason"):
        assert transition(client, record, "cancel", cancel_reason=reason).status_code == 400
        assert (snapshot(record), counts()) == before
    login(client, people["receiver"])
    assert transition(client, record, "cancel", cancel_reason="Not sender").status_code == 403
    login(client, people["sender"])
    assert transition(client, record, "send").status_code == 302
    assert transition(client, record, "cancel", cancel_reason="Already sent").status_code == 403
    login(client, people["manager"])
    assert transition(client, record, "cancel", cancel_reason="  Superseded shift  ",
                      cancelled_by_user_id=people["foreign"].id).status_code == 302
    assert record.status == "cancelled" and record.cancel_reason == "Superseded shift"
    assert record.cancelled_by_user_id == people["manager"].id and record.cancelled_at is not None
    before = snapshot(record), counts()
    assert transition(client, record, "cancel", cancel_reason="Retry").status_code == 409
    assert transition(client, record, "send").status_code == 409
    login(client, people["receiver"])
    assert transition(client, record, "receive").status_code == 409
    assert (snapshot(record), counts()) == before
    login(client, people["manager"])
    assert transition(client, record, "archive").status_code == 302
    event = AuditLog.query.filter_by(entity_type="ShiftHandover", entity_id=str(record.id), action="cancelled").one()
    assert event.user_id == people["manager"].id
    assert json.loads(event.new_values)["cancel_reason"] == "Superseded shift"


@pytest.mark.parametrize("name", ["create", "edit", "receive", "cancel", "archive", "export_excel"])
def test_audit_failure_rolls_back_each_operation(client, people, monkeypatch, name):
    from app import shift_handover

    record = create_record(client, people)
    if name in {"receive", "archive"}:
        assert transition(client, record, "send").status_code == 302
        login(client, people["receiver"])
        if name == "archive":
            assert transition(client, record, "receive").status_code == 302
            login(client, people["manager"])
    before = snapshot(record), counts()

    def unavailable(*args, **kwargs):
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(shift_handover, "record_audit_event", unavailable)
    target = None if name in {"create", "export_excel"} else record
    if name == "export_excel":
        response = client.get(endpoint(client, name, target))
    else:
        response = client.post(endpoint(client, name, target), data=form_data(
            people, version_id=record.version_id, title="Must roll back", cancel_reason="Must roll back",
        ))
    assert response.status_code == 500
    assert (snapshot(record), counts()) == before


def test_period_filters_and_literal_search_match_excel(client, people):
    today = handover_today()
    included = seed_record(people, handover_date=today, title="Literal 50%_ complete")
    excluded = seed_record(people, handover_date=today.replace(day=1) - timedelta(days=1), title="PREVIOUS-MONTH")
    seed_record(people, handover_date=today, title="Literal 50000 complete")
    login(client, people["sender"])
    filters = {"period": "month", "anchor": today.isoformat(), "q": "50%_"}
    html = client.get(BASE, query_string=filters)
    assert html.status_code == 200 and included.title in html.get_data(as_text=True)
    report = client.get(endpoint(client, "export_excel"), query_string=filters)
    assert_xlsx_response(report)
    rows = str(sheet_values(report.data))
    assert included.title in rows and excluded.title not in rows and "Literal 50000 complete" not in rows
    for invalid in ({"status": "invalid"}, {"archive": "invalid"}, {"period": "invalid"},
                    {"period": "month", "anchor": "bad"},
                    {"period": "month", "anchor": (today + timedelta(days=1)).isoformat()}):
        assert client.get(BASE, query_string=invalid).status_code == 400
        assert client.get(endpoint(client, "export_excel"), query_string=invalid).status_code == 400


def test_report_center_preserves_own_scope_export_permission_and_module_gate(client, people):
    from app.models import UserPermission

    owned = seed_record(people, title="REPORT-OWNED")
    hidden = seed_record(people, sender_user_id=people["stranger"].id,
                         receiver_user_id=people["stranger"].id, title="REPORT-HIDDEN")
    foreign = seed_record(people, company_id=people["foreign_company"].id,
                          department_id=people["foreign_department"].id,
                          sender_user_id=people["foreign"].id, receiver_user_id=people["foreign"].id,
                          title="REPORT-FOREIGN")
    sender = people["sender"]
    sender.extra_permissions.extend(UserPermission(permission_key=key) for key in ("reports.view", "reports.export"))
    db.session.commit()
    login(client, sender)
    url = "/rapor-merkezi/shift_handover/excel"
    response = client.get(url)
    assert_xlsx_response(response)
    rows = str(sheet_values(response.data))
    assert owned.title in rows and hidden.title not in rows and foreign.title not in rows
    sender.extra_permissions = [item for item in sender.extra_permissions if item.permission_key != "shift_handover.export"]
    db.session.commit()
    assert client.get(url).status_code == 404
    login(client, people["manager"])
    CompanyModule.query.filter_by(company_id=people["company"].id, module_key="shift_handover").one().is_enabled = False
    db.session.commit()
    assert client.get(url).status_code == 404


def test_assigned_tasks_only_show_pending_receiver_and_remove_after_receipt(client, people):
    record = create_record(client, people, title="TASK-RECEIVER-ONLY")
    assert transition(client, record, "send").status_code == 302
    url = "/uzerime-atananlar?module=shift_handover"
    for actor in ("receiver", "sender", "stranger", "manager", "foreign"):
        login(client, people[actor])
        response = client.get(url)
        assert response.status_code == 200, actor
        assert (record.title in response.get_data(as_text=True)) is (actor == "receiver"), actor
    login(client, people["receiver"])
    assert transition(client, record, "receive").status_code == 302
    response = client.get(url)
    assert response.status_code == 200 and record.title not in response.get_data(as_text=True)
