from datetime import date, datetime, timedelta
from unittest.mock import Mock

import pytest
from flask import g

from app import customer_portal, mail, notification_policy
from app.extensions import db
from app.models import CompanyModule, ComplaintRecord, Notification
from app.notification_models import NotificationEmailEvent
from app.reminder_sources import customer_portal_recipients

from .helpers import create_user
from .test_customer_feedback_portal import (
    app, client, company, submit_and_extract_verification,
    verify_and_extract_tracking,
)


@pytest.fixture()
def workers(app):
    target = company()
    permissions = ("customer_portal.view", "customer_portal.triage")
    users = {
        "triage": create_user("triage", company=target, permissions=permissions),
        "owner": create_user("owner", company=target, permissions=(
            "customer_portal.view", "customer_portal.respond",
        )),
        "no_view": create_user("no-view", company=target, permissions=("customer_portal.assign",)),
        "foreign": create_user("foreign", company=company("102"), permissions=permissions),
        "inactive": create_user("inactive", company=target, permissions=permissions),
        "platform": create_user("platform", role_key="super_admin"),
        "viewer": create_user("viewer", company=target, role_key="viewer", permissions=permissions),
        "department": create_user("department", company=target, role_key="department_manager", title="Quality"),
        "other_department": create_user("other-department", company=target, role_key="department_manager", title="Sales"),
    }
    users["inactive"].is_active = False
    db.session.commit()
    return users


@pytest.fixture()
def record(workers):
    row = ComplaintRecord(
        company_id=company().id, complaint_no="PORTAL-1", customer_name="External customer",
        contact_email="external@example.test", subject="Feedback", department="Quality",
        source="M\u00fc\u015fteri Portal\u0131", status="Yeni", email_verified_at=datetime.now(),
        due_date=date.today() + timedelta(days=3),
    )
    db.session.add(row)
    db.session.commit()
    return row


def notify(app, record, suffix="verified", event_type="approval"):
    with app.test_request_context():
        customer_portal._notify_internal(record, "Internal work pending", suffix, event_type=event_type)


def test_verified_intake_queues_only_authorized_internal_triage(app, workers, record, monkeypatch):
    smtp = Mock()
    generic = Mock()
    monkeypatch.setattr(mail, "send_mail_now", smtp)
    monkeypatch.setattr(mail, "send_generic_notification_email", generic)
    notify(app, record)

    expected = {workers[key].id for key in ("triage", "department")}
    notifications = Notification.query.all()
    events = NotificationEmailEvent.query.all()
    assert {row.user_id for row in notifications} == expected
    assert {row.user_id for row in events} == expected
    assert all(row.email_sent_at is None for row in notifications)
    assert all(row.company_id == record.company_id and row.kind == "customer-portal"
               and row.record_id == record.id and row.status == "pending"
               and row.phase == f"event:approval:{row.notification_id}"
               and row.target_url == f"/musteri-geri-bildirimleri/{record.id}"
               for row in events)
    smtp.assert_not_called()
    generic.assert_not_called()


def test_response_queues_current_owner_only_and_deduplicates(app, workers, record):
    record.responsible_user_id = workers["owner"].id
    notify(app, record, "customer-message:42", "rescheduled")
    notify(app, record, "customer-message:42", "rescheduled")
    notification = Notification.query.one()
    event = NotificationEmailEvent.query.one()
    assert event.user_id == workers["owner"].id
    assert event.record_id == record.id
    assert event.phase == f"event:rescheduled:{notification.id}"
    assert notification.source_key == f"customer-portal:{record.id}:customer-message:42"
    assert notification.email_sent_at is None


@pytest.mark.parametrize("owner", ["foreign", "inactive", "platform", "no_view", "viewer"])
def test_invalid_owner_does_not_fall_back_to_broad_triage(app, workers, record, owner):
    record.responsible_user_id = workers[owner].id
    notify(app, record, "customer-message:42", "rescheduled")
    assert Notification.query.count() == 0
    assert NotificationEmailEvent.query.count() == 0


@pytest.mark.parametrize("field,value", [
    ("email_verified_at", None), ("is_archived", True),
    ("closed_at", datetime(2026, 1, 1)), ("source", "Internal"),
])
def test_nonactionable_records_do_not_notify(app, record, field, value):
    setattr(record, field, value)
    notify(app, record)
    assert Notification.query.count() == 0
    assert NotificationEmailEvent.query.count() == 0


def test_disabled_portal_does_not_notify(app, record):
    CompanyModule.query.filter_by(company_id=record.company_id, module_key=customer_portal.MODULE_KEY).one().is_enabled = False
    notify(app, record)
    assert Notification.query.count() == 0
    assert NotificationEmailEvent.query.count() == 0


def test_notifications_and_events_roll_back_with_record(app, record):
    original = record.subject
    record.subject = "Uncommitted change"
    notify(app, record)
    assert Notification.query.count() == 2
    assert NotificationEmailEvent.query.count() == 2
    db.session.rollback()
    assert record.subject == original
    assert Notification.query.count() == 0
    assert NotificationEmailEvent.query.count() == 0


def test_queue_failure_can_roll_back_site_notification(app, record, monkeypatch):
    monkeypatch.setattr(notification_policy, "queue_notification_event", Mock(side_effect=RuntimeError("queue failed")))
    with pytest.raises(RuntimeError, match="queue failed"):
        notify(app, record)
    db.session.rollback()
    assert Notification.query.count() == 0
    assert NotificationEmailEvent.query.count() == 0


def test_access_requires_view_and_respects_department_and_assignment(app, workers, record):
    with app.test_request_context():
        g.current_user = workers["no_view"]
        assert not customer_portal._can_access(record)
        assert customer_portal._can_access(record, workers["triage"])
        assert customer_portal._can_access(record, workers["department"])
        assert not customer_portal._can_access(record, workers["other_department"])
        assert not customer_portal._can_access(record, workers["owner"])
        record.responsible_user_id = workers["owner"].id
        assert customer_portal._can_access(record, workers["owner"])


def test_stale_owner_event_is_rejected_before_delivery(app, workers, record):
    record.responsible_user_id = workers["owner"].id
    notify(app, record, "customer-message:42", "rescheduled")
    event = NotificationEmailEvent.query.one()
    collection = {"items": {}}
    assert notification_policy._event_current(event, collection, workers["owner"])
    record.responsible_user_id = workers["triage"].id
    assert not notification_policy._event_current(event, collection, workers["owner"])
    assert {user.id for user in customer_portal_recipients(record)} == {workers["triage"].id}


def test_public_verification_and_response_use_typed_events_preserving_transactional_mail(app, client, workers, monkeypatch):
    transactional = Mock(return_value=True)
    monkeypatch.setattr(customer_portal, "send_recipient_email", transactional)
    raw, row = submit_and_extract_verification(client)
    assert NotificationEmailEvent.query.count() == 0
    assert transactional.call_count == 1
    tracking = verify_and_extract_tracking(client, raw)
    approval_events = NotificationEmailEvent.query.all()
    assert len(approval_events) == 1
    assert all(event.record_id == row.id and event.kind == "customer-portal"
               and event.phase.startswith("event:approval:") for event in approval_events)
    assert transactional.call_count == 2
    assert all(call.args[0] == row.contact_email for call in transactional.call_args_list)

    row.responsible_user_id = workers["owner"].id
    db.session.commit()
    response = client.post(
        f"/musteri-portali/takip/{tracking}", data={"message": "More details"},
        headers={"Host": "portal-firma.volkaportal.com"},
    )
    assert response.status_code == 302
    event = NotificationEmailEvent.query.filter_by(user_id=workers["owner"].id).one()
    assert event.record_id == row.id and event.phase.startswith("event:rescheduled:")
    assert all(item.email_sent_at is None for item in Notification.query.all())
    assert transactional.call_count == 2
